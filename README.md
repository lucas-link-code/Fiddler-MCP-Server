# Fiddler MCP Bridge

Real-time web traffic analysis powered by Gemini. Connect Fiddler Classic to large language models via the Model Context Protocol.

## What This Does

This bridge streams captured HTTP/S sessions from Fiddler to Gemini through MCP tools. Ask natural language questions about your traffic:

- "Show me sessions from the last 5 minutes"
- "Are there any suspicious downloads?"
- "Analyze the JavaScript in session 147"
- "Find all POST requests to api.example.com"
- "Create EKFiddle rules for the malicious code in session 256"

The LLM receives raw session data (headers, bodies, metadata, EKFiddle comments) and performs the analysis itself. No black-box threat scoring; you see what the model sees.

## Architecture

```
Fiddler Classic          enhanced-bridge.py        5ire-bridge.py         gemini-fiddler-client.py
     |                         |                        |                      |
     |   POST /live-session    |                        |                      |
     |------------------------>|  REST API (8081)       |                      |
     |   (JSON session data)   |----------------------->|   MCP tools/list     |
     |                         |  /api/sessions/...     |   tools/call         |
     |                         |                        |--------------------->|
     |                         |                        |   stdin/stdout MCP   |
     |                         |                        |                      |
     |                         |                        |   FunctionDeclarations
     |                         |                        |   function_call /
     |                         |                        |   FunctionResponse
     |                         |                        |---------------------> Gemini API
```

1. **Fiddler** captures traffic and POSTs JSON via CustomRules.js
2. **enhanced-bridge.py** buffers sessions and exposes REST on port 8081
3. **5ire-bridge.py** exposes MCP tools that call that REST API
4. **gemini-fiddler-client.py** binds those tools as Gemini FunctionDeclarations, runs the chat loop, and executes every tool through `call_tool`
5. **gemini_native_tools.py** is a helper library used by the client (schema conversion, function_call extraction, FunctionResponse packing). It is not a server.

The model never talks to Fiddler or Python directly. The client is the middleman.

## Prerequisites

- Windows 10/11 (analysis VM) or macOS/Linux for development
- **Python 3.10 or later** (3.11 or 3.12 recommended)
- Fiddler Classic (must be installed and run at least once)
- Gemini API key (https://aistudio.google.com/apikey)

**Important:** The MCP package requires Python 3.10+.

## Quick Start

Run the one-click deployment script on Windows:

```batch
deploy-mcp.bat
```

Or start the client alone after copying the project folder. On startup it:

1. Checks and installs packages from `requirements-gemini.txt` if missing
2. Verifies `enhanced-bridge.py`, `5ire-bridge.py`, and `gemini_native_tools.py` are present
3. Starts `enhanced-bridge.py` if port 8081 is down
4. Starts `5ire-bridge.py` as the MCP child process
5. Enters interactive chat

After deployment:
1. In Fiddler, reload the script: Rules > Reload Script (Ctrl+R)
2. Browse the web to generate traffic
3. Ask questions in the Gemini Fiddler Client window

## How the model uses tools

Default mode is native Gemini function calling (`GEMINI_NATIVE_TOOLS=1`):

1. Client asks MCP `tools/list` and converts each tool schema via `gemini_native_tools.py`
2. Gemini may return a structured `function_call` (name + args)
3. Client runs `call_tool`:
   - fixes common bad tool names
   - sanitizes args (aliases, strip leading `*`, required key checks)
   - blocks duplicate `session_body` re-fetches in the same query
   - optional auto body fetch after narrow host searches
4. Result is returned as a `FunctionResponse` part (large bodies truncated)
5. Gemini continues or gives the final analyst answer

If the model sends wrong parameter shapes, `call_tool` repairs or rejects with a hint. The error is fed back to Gemini so it can retry. Native schemas reduce invented keys; sanitizer still catches bad values.

Legacy text JSON tool calls remain available with `GEMINI_NATIVE_TOOLS=0`.

## MCP Tools

Ten tools are exposed to the LLM:

| Tool | Purpose |
|------|---------|
| `fiddler_mcp__live_sessions` | List recent sessions with metadata and risk indicators |
| `fiddler_mcp__sessions_search` | Filter by host, URL, status, method, size, MIME type |
| `fiddler_mcp__session_headers` | Get request/response headers for a session |
| `fiddler_mcp__session_body` | Get request/response bodies |
| `fiddler_mcp__compare_sessions` | Fetch several session bodies for side-by-side analysis |
| `fiddler_mcp__live_stats` | Buffer depth, capture rate, uptime |
| `fiddler_mcp__sessions_timeline` | Aggregate by time, host, status, or content type |
| `fiddler_mcp__sessions_clear` | Clear buffers after exporting evidence |
| `fiddler_mcp__ekfiddle_sessions` | List sessions already flagged by EKFiddle |
| `fiddler_mcp__ekfiddle_threats` | High-risk EKFiddle hits for triage |

Tools return raw data. The LLM performs reasoning on headers, bodies, and EKFiddle comments.

## Example Session

```
You: Show me JavaScript files from the last 10 minutes

[Tool: fiddler_mcp__sessions_search]
Found 3 sessions matching content_type=javascript, since_minutes=10

You: Analyze session 175

[Tool: fiddler_mcp__session_body]
Session 175: 7.2KB JavaScript from cdn.example.com
Contains: obfuscated variable names, eval() call, base64 encoded string

The code appears to be a loader script. The eval() on line 47 executes
decoded content from the base64 payload. This pattern is common in
dropper scripts...
```

## File Structure

```
fiddler-mcp/
├── deploy-mcp.bat                   # One-click setup (run this first)
├── install-dependencies-manual.bat  # Manual dependency installer (if deploy fails)
├── diagnose-environment.bat         # Diagnostic tool for troubleshooting
├── enhanced-bridge.py               # HTTP server, session buffer (port 8081)
├── 5ire-bridge.py                   # MCP server (FastMCP over stdin/stdout)
├── gemini-fiddler-client.py         # Interactive Gemini chat client + bootstrap
├── gemini_native_tools.py           # Native FunctionDeclaration helpers
├── CustomRules.js                   # Fiddler script (auto-deployed)
├── requirements-gemini.txt          # Gemini client dependencies
├── requirements-mcp.txt             # MCP bridge dependencies
├── gemini-fiddler-config.json       # Generated config (API key, model)
├── NATIVE_TOOLS_SOAK_CHECKLIST.txt  # Manual validation after native tools deploy
├── TROUBLESHOOTING.txt              # Detailed troubleshooting guide
├── MCP_Data_Flow.md                 # Data flow walkthrough
├── MCP_Server_Guide.md              # Architecture overview
└── MCP_TOOL_CONTRACT.md             # Tool schemas and responses
```

## Manual Setup

If the one-click script fails, install manually:

```batch
:: Install dependencies
pip install -r requirements-gemini.txt

:: Copy CustomRules.js to Fiddler
copy CustomRules.js "%USERPROFILE%\Documents\Fiddler2\Scripts\"

:: Start the client (auto-starts bridges if needed)
python gemini-fiddler-client.py
```

The client prompts for your API key on first run.

Environment flags:
- `GEMINI_NATIVE_TOOLS=0` — legacy text JSON tool loop
- `GEMINI_SKIP_DEP_INSTALL=1` — skip automatic pip install
- `GEMINI_MAX_TOOL_CALLS` — max tool calls per query (default 20)

## Configuration

`gemini-fiddler-config.json` (created by deploy-mcp.bat or first client run):

```json
{
  "api_key": "your-api-key",
  "model": "gemini-3-flash-preview",
  "auto_save_full_bodies": false,
  "mcp_server_command": ["python", "5ire-bridge.py"],
  "bridge_url": "http://127.0.0.1:8081"
}
```

Available models:
- `gemini-3-flash-preview` (default)
- `gemini-3.1-flash-lite` (fast, cost efficient)
- `gemini-3.1-pro-preview` (most capable Gemini 3)
- `gemini-3.5-flash` (stable Gemini 3.5)
- `gemini-2.5-flash` / `gemini-2.5-pro` / `gemini-2.5-flash-lite`

## Troubleshooting

**Dependency installation failed**

Quick fix: Run the manual installer
```batch
install-dependencies-manual.bat
```

This installs each package individually. After completion, run deploy-mcp.bat again.

For diagnosis, run:
```batch
diagnose-environment.bat
```

This tests Python installation, pip availability, network connectivity to PyPI, package installation permissions, and antivirus interference.

See TROUBLESHOOTING.txt for detailed solutions.

**Port 8081 already in use**
```batch
netstat -ano | findstr :8081
taskkill /F /PID <pid>
```

**CustomRules.js not deploying**
- Close Fiddler before running deploy-mcp.bat
- Run as Administrator if permission denied
- Manually copy to `%USERPROFILE%\Documents\Fiddler2\Scripts\`

**No sessions appearing**
- Verify Fiddler is capturing traffic (check session list in Fiddler)
- Reload script in Fiddler: Rules > Reload Script
- Check bridge console for POST /live-session messages

**Bridge not responding**
```batch
curl http://127.0.0.1:8081/health
curl http://127.0.0.1:8081/api/stats
```

**Missing gemini_native_tools.py**
Keep `gemini_native_tools.py` in the same folder as `gemini-fiddler-client.py`. Native tool binding imports it at startup.

**Enable debug mode**
```batch
SET DEPLOY_DEBUG=1
deploy-mcp.bat
```

## How It Works

For every captured session:

1. Fiddler intercepts a request/response pair
2. CustomRules.js serializes the session to JSON and POSTs to `http://127.0.0.1:8081/live-session`
3. enhanced-bridge.py stores the session in a ring buffer
4. When the analyst asks a question, Gemini may emit a `function_call` for an MCP tool
5. gemini-fiddler-client.py executes that call through `call_tool` → 5ire-bridge → REST
6. The tool result is returned as a `FunctionResponse`; Gemini continues or answers

See `MCP_Data_Flow.md` for a detailed walkthrough with code snippets.
See `NATIVE_TOOLS_SOAK_CHECKLIST.txt` for post-deploy validation.

## Use Cases

- Malware traffic analysis (FakeUpdates, SocGholish, exploit kits, EtherHiding)
- EKFiddle CustomRegex drafting from live session bodies
- API debugging and inspection
- Session forensics and timeline reconstruction
- JavaScript deobfuscation assistance
- Header and cookie analysis
- Redirect chain investigation

## Acknowledgments

- EKFiddle for rule format inspiration
- Model Context Protocol specification
- Fiddler community
