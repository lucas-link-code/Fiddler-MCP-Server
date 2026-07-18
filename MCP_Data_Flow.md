# Connecting Fiddler to an LLM via MCP

This document walks one data path end to end: a captured session in Fiddler becomes tool evidence that Gemini or DeepSeek can reason over.

The header tool is used as the concrete example. Every other tool is the same pattern with a different REST path. There are currently **10 MCP tools** on 5ire-bridge.

## High level

1. **Fiddler** converts captured sessions to JSON and POSTs them to the local Flask bridge.
2. **enhanced-bridge.py** stores JSON in memory and exposes REST endpoints such as `/api/sessions/headers/<id>`.
3. **5ire-bridge.py** exposes MCP tools such as `fiddler_mcp__session_headers` that call those REST endpoints.
4. **gemini-fiddler-client.py** binds MCP schemas on the active provider (Gemini FunctionDeclarations or DeepSeek OpenAI tools), runs the native chat loop, executes tools through `call_tool`, and returns results to the model.
5. **gemini_native_tools.py**, **llm_prompts.py**, **llm_tool_schema.py**, and **llm_providers/** are helper libraries. They are not processes you start.

The model never executes Python and never talks to Fiddler directly. The client is the only component that calls tools.

```
Fiddler CustomRules
  -> enhanced-bridge POST /live-session
  -> 5ire-bridge MCP tools/list + tools/call
  -> gemini-fiddler-client + llm_providers (Gemini or DeepSeek)
  -> LLM native tool loop
```

<br>

## 1. Fiddler captures traffic and publishes JSON

Fiddler keeps sessions in memory. To make them accessible outside the UI we push each completed session to the local HTTP server. CustomRules does this after every response via `McpTryPost`.

```js
// CustomRules.js
static function McpTryPost(oSession: Session): void {
    try {
        // Skip tunnels or sessions with no HTTP response
        if ((oSession.oResponse == null) || (oSession.responseCode == 0)) return;

        var json: String = McpBuildSimpleJson(oSession);
        McpHttpPost(json);
    } catch (e) {
        FiddlerApplication.Log.LogString("MCP error: " + e.Message);
    }
}
```

*Key idea*: `McpBuildSimpleJson` condenses the session (request line, headers, body, EKFiddle flags) and `McpHttpPost` sends it to `http://127.0.0.1:8081/live-session`.

<br>

## 2. enhanced-bridge.py stages the data

The staging HTTP server buffers JSON in a ring buffer and exposes REST endpoints. For headers:

```python
# enhanced-bridge.py
@self.app.route('/api/sessions/headers/<session_id>', methods=['GET'])
def get_session_headers(session_id):
    """Get headers for specific session"""
    try:
        with self.session_lock:
            for session in reversed(self.live_sessions):
                if str(session.get('id', '')) == str(session_id):
                    return jsonify({
                        "success": True,
                        "session_id": session_id,
                        "request_headers": session.get('requestHeaders', {}),
                        "response_headers": session.get('responseHeaders', {}),
                        "found": True
                    })

        return jsonify({
            "success": False,
            "error": f"Session {session_id} not found",
            "found": False
        }), 404
```

*Key idea*: everything stays reachable through plain HTTP so curl, MCP, or a browser can fetch it like a normal API.

<br>

## 3. 5ire-bridge.py exposes MCP tools

The MCP bridge translates model tool invocations into REST calls.

```python
# 5ire-bridge.py (FiddlerBridgeClient helper)
def get_session_headers(self, *, session_id: str) -> Dict[str, Any]:
    try:
        data = self.request("GET", f"/api/sessions/headers/{session_id}")
    except BridgeConnectionError:
        return {
            "success": False,
            "error": "Cannot connect to real-time bridge",
            "bridge_status": "Disconnected",
        }
    ...
```

That helper is wired to the tool definition the LLM sees:

```python
# 5ire-bridge.py (MCP tool)
@mcp.tool()
def fiddler_mcp__session_headers(
    session_id: Annotated[str, Field(description="Session ID from live_sessions or sessions_search.")],
) -> Dict[str, Any]:
    """Fetch ONLY the HTTP headers (NOT the body content) for a captured session."""

    return client.get_session_headers(session_id=session_id)
```

*Key idea*: the tool name `fiddler_mcp__session_headers` is what appears in `tools/list`. Calling it hits the REST endpoint above.

Current MCP tools:
- `fiddler_mcp__live_sessions`
- `fiddler_mcp__sessions_search`
- `fiddler_mcp__session_headers`
- `fiddler_mcp__session_body`
- `fiddler_mcp__compare_sessions`
- `fiddler_mcp__live_stats`
- `fiddler_mcp__sessions_timeline`
- `fiddler_mcp__sessions_clear`
- `fiddler_mcp__ekfiddle_sessions`
- `fiddler_mcp__ekfiddle_threats`

<br>

## 4. gemini-fiddler-client.py runs the agent loop

### Startup

`gemini-fiddler-client.py` bootstraps the runtime:

1. Checks / installs packages from `requirements-gemini.txt` (includes `openai` for DeepSeek)
2. Verifies companion scripts exist, including `gemini_native_tools.py` and `llm_prompts.py`
3. Starts `enhanced-bridge.py` if port 8081 is unhealthy
4. Starts `5ire-bridge.py` as an MCP child over stdin/stdout
5. Calls MCP `tools/list` and binds tools on the active provider (Gemini default)

### Shared helpers

- `llm_prompts.py` — INVESTIGATE CAPTURE + EKFiddle HARD MODE system instruction shared by both backends
- `llm_tool_schema.py` — MCP JSON Schema normalization; OpenAI tools array conversion for DeepSeek
- `gemini_native_tools.py` — Gemini FunctionDeclaration / FunctionResponse helpers
- `llm_providers/gemini_provider.py` / `llm_providers/deepseek_provider.py` — provider adapters used by `_chat_native`

### Native tool loop (default)

```python
# Native path: GEMINI_NATIVE_TOOLS=1 (provider-driven)
calls = provider.extract_tool_calls(response)
for call in calls:
    result = self.call_tool(call["name"], call["args"])  # execution gate
provider.append_tool_results(conversation, executed, nudge)
```

Flow for one analyst question:

1. Client sends user text plus bound tools to the active LLM
2. Gemini may return `function_call` parts; DeepSeek may return `tool_calls`
3. Client executes each call **sequentially** through `call_tool`
4. Client appends model turn + tool results to the provider conversation
5. The model continues with more tools or returns the final answer
6. If the tool budget is exhausted, client forces a text-only synthesis turn (`tool_choice=none`)

`/investigate` builds a shared playbook prompt then enters the same chat loop, so both providers get investigation + EKFiddle parity.

### What call_tool does when args are wrong

The model chooses tool names and parameters. Python validates them before MCP:

- rename common hallucinated tool names
- reject unknown tools
- sanitize args: map `id` → `session_id`, `filter` → `host_pattern`, strip leading `*`
- drop unknown keys or return a structured error with a correction hint
- block re-fetch of an already analyzed `session_body` in the same query
- optionally auto-fetch a body after a narrow host-filtered search

If sanitize rejects the call, that error is returned as the tool result. The model sees it on the next turn and can retry with better args.

Native schemas reduce invented keys. They do not eliminate bad values. That is why `call_tool` stays in front of every execution.

### Legacy path

With `GEMINI_NATIVE_TOOLS=0`, the Gemini client scrapes tool JSON from free text instead of using `function_call` parts. Prefer the native path. DeepSeek uses native tools only.

<br>

## Mental model

| Component | Role |
|-----------|------|
| Fiddler + CustomRules.js | Capture and publish sessions |
| enhanced-bridge.py | In-memory HTTP API for session data |
| 5ire-bridge.py | MCP tool surface over that API |
| gemini-fiddler-client.py | Chat UI, bootstrap, agent loop, call_tool gate |
| llm_providers/* | Gemini / DeepSeek native tool adapters |
| Gemini or DeepSeek API | Chooses tools and writes the analyst answer |

Whatever the bridge returns (headers, bodies, stats, EKFiddle triage) becomes evidence for the next model turn. Different tools simply supply different JSON through the same gate.
