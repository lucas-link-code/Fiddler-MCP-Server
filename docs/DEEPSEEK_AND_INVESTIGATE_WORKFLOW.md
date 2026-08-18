# DeepSeek Second Backend and Investigate Workflow

Documentation for DeepSeek second-backend delivery and the `/investigate` playbook.

OpenRouter was later added as a third OpenAI-compatible provider (`llm_providers/openrouter_provider.py`, `/model 14`–`18`, freeform `vendor/model`). Gemini remains default. Bare DeepSeek names stay on the direct DeepSeek API; slash IDs such as `deepseek/deepseek-v4-pro` route through OpenRouter. See README and `NATIVE_TOOLS_SOAK_CHECKLIST.txt` OpenRouter section O1–O7. Restore tag: `pre-openrouter-restore`.

Entry script remains `gemini-fiddler-client.py`. Gemini stays the default provider.

---

## Summary of what this thread delivered

DeepSeek was added as a second OpenAI-compatible LLM backend with native tool calling, sharing the same investigation prompts, MCP tool gate, `/investigate` playbook, and EKFiddle rule authoring path as Gemini.

| Area           | What changed                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------- |
| Providers      | Thin Gemini and DeepSeek adapters under `llm_providers/`                                                |
| Shared prompts | `llm_prompts.py` holds INVESTIGATE CAPTURE + EKFiddle HARD MODE text for both backends                  |
| Schema         | `llm_tool_schema.py` normalizes MCP JSON Schema; OpenAI tools array for DeepSeek                        |
| Client loop    | `_chat_native` is provider-driven (same sequential `call_tool`, refetch lock, budget synthesis, Ctrl+C) |
| Models         | `/model` lists Gemini 1–11 and DeepSeek 12–13 (`deepseek-v4-flash`, `deepseek-v4-pro`)                  |
| Config         | `provider`, `deepseek_api_key`, `deepseek_base_url`, `deepseek_ssl_verify`                              |
| UX             | Missing DeepSeek key prompts at `/model` switch and saves into config                                   |
| TLS            | FLARE/analysis VM cert failures addressed via certifi + optional verify bypass                          |
| Tests          | Hardening + native Gemini suites kept green; new `tests/test_deepseek_provider.py`                      |
| Docs           | README, `MCP_Data_Flow.md`, soak checklist DeepSeek cases                                               |
| Rollback       | Annotated tag `pre-deepseek-restore` at pre-DeepSeek commit `5bb18ab`                                   |

Restore point:

```bash
git fetch --tags
git checkout pre-deepseek-restore
```

Feature commit on `main` (example): DeepSeek second native-tools backend landing with shared prompts, SSL/config UX, and tests.

---

## Architecture after this work

```
Fiddler Classic
  -> CustomRules.js POST /live-session
  -> enhanced-bridge.py (HTTP :8081)
  -> 5ire-bridge.py (MCP stdio, 10 tools)
  -> gemini-fiddler-client.py
       -> call_tool gate (sanitize, refetch lock, auto-fetch)
       -> GeminiProvider  OR  DeepSeekProvider
       -> Gemini API  OR  https://api.deepseek.com
```

MCP path is provider-agnostic. Only the LLM turn format differs:

- Gemini: FunctionDeclarations / `function_call` / FunctionResponse
- DeepSeek: OpenAI `tools` / `tool_calls` / `role=tool`

Shared agent semantics:

- Sequential tool execution through `call_tool`
- Session body re-fetch lock per query
- Optional auto body fetch after narrow host search
- Tool budget then `tool_choice=none` synthesis
- Soft Ctrl+C on the current chain only
- EKFiddle extract/save via `maybe_persist_ekfiddle_rules`

---

## DeepSeek backend details

### Official API

| Setting       | Value                                                                    |
| ------------- | ------------------------------------------------------------------------ |
| Base URL      | `https://api.deepseek.com`                                               |
| Models        | `deepseek-v4-flash`, `deepseek-v4-pro`                                   |
| Protocol      | OpenAI-compatible `chat.completions` + tools                             |
| Thinking mode | Out of scope for v1; tool loops use non-thinking / stable agent behavior |

### Config keys

`gemini-fiddler-config.json` (gitignored; local only):

```json
{
  "api_key": "gemini-key-optional-if-using-deepseek-only",
  "deepseek_api_key": "sk-...",
  "provider": "deepseek",
  "model": "deepseek-v4-pro",
  "deepseek_base_url": "https://api.deepseek.com",
  "deepseek_ssl_verify": true,
  "auto_save_full_bodies": false,
  "mcp_server_command": ["python", "5ire-bridge.py"],
  "bridge_url": "http://127.0.0.1:8081"
}
```

Env overrides: `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `LLM_PROVIDER`, `GEMINI_MODEL`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_SSL_VERIFY`, `DEEPSEEK_SSL_CERT_FILE`.

### Analyst UX improvements in this thread

1. **`/model` lists both providers** and shows whether the DeepSeek key is configured.
2. **Missing key prompt**: selecting DeepSeek without a key asks for paste, merges into `gemini-fiddler-config.json`, then completes the switch.
3. **DeepSeek forces native tools**: `GEMINI_NATIVE_TOOLS=0` legacy text loop is Gemini-only; DeepSeek never falls into that path.
4. **Clear unbound-tools error** instead of crashing into Gemini `generate_content` with `model=None`.
5. **TLS diagnostics**: richer errors for `CERTIFICATE_VERIFY_FAILED`; optional lab bypass.

### TLS / FLARE VM note

`curl -I https://api.deepseek.com` returning `401` proves URL and network are fine. Python may still fail with `unable to get local issuer certificate` because the Windows Python trust store is incomplete.

Mitigations shipped:

- Prefer `certifi` CA bundle for the DeepSeek httpx client
- Config `deepseek_ssl_verify: false` or env `DEEPSEEK_SSL_VERIFY=0` for lab-only bypass
- Startup prints TLS verify mode so you can confirm the new provider code is loaded

---

## Slash commands still available on both providers

| Command               | Role                                         |
| --------------------- | -------------------------------------------- |
| `/help`               | Menu and examples                            |
| `/stats`              | Bridge stats via MCP                         |
| `/tools`              | List bound MCP tools                         |
| `/model`              | Show/switch Gemini or DeepSeek models        |
| `/history`            | Conversation history                         |
| `/clear`              | Clear live + suspicious bridge buffers       |
| `/clearchat`          | Clear chat history only                      |
| `/investigate`        | Malicious-traffic playbook on current buffer |
| `/investigate <host>` | Same playbook, prioritize a host             |
| `/quit`               | Exit                                         |

---

## `/investigate` and domain-focused workflow

### Important design fact

`/investigate <domain>` is **not** a separate hard-coded domain crawler. It injects a canned playbook prompt into the **normal native tool loop**, with an extra host-priority sentence. The LLM then drives MCP tools against whatever is **already in the Fiddler capture buffer**.

The agent does not live-browse the domain. It searches captured sessions for that host, reads bodies, then pivots to related hosts found in those bodies.

### Command entry

1. Analyst runs `/investigate` or `/investigate evil.example` (URL forms are reduced to hostname).
2. Client builds a user prompt via `build_investigate_prompt(host)`.
3. That prompt is passed to `chat()` like any natural-language question.
4. Native loop wraps it with system instruction from `llm_prompts.investigation_system_instruction` (INVESTIGATE CAPTURE + EKFiddle HARD MODE + IOC-FIRST / zero-hit rules).

### Prompt shape when a host is named

Base playbook text asks for:

- Triage with `live_stats` and `ekfiddle_threats` / `ekfiddle_sessions`
- Fetch a few highest-severity JS/HTML bodies
- Pivot on hosts found in those bodies
- Trace infection chain
- Structured summary: Infection chain, hosts/IOCs, verdict
- EKFiddle CustomRegexes only if malicious high-signal evidence exists
- No rules for confirmed FP / benign libraries

When a host is supplied, the client appends:

> Prioritize host `{host}`: search that host first, then follow any loader/C2/RPC pivots found in its bodies.

Standing system guidance also includes **IOC-FIRST**: named hosts should be searched with `host_pattern` before Low EKFiddle HTML noise.

### Intended analysis sequence

```
/investigate evil.example
        |
        v
+------------------+
| live_stats       |  buffer health
| ekfiddle_threats |  Critical/High first
| ekfiddle_sessions|
+--------+---------+
         |
         v
+------------------+
| sessions_search  |  host_pattern = evil.example
| (domain focus)   |
+--------+---------+
         |
         v
+------------------+
| session_body     |  few JS/HTML/JSON bodies
| (skip media)     |  prefer body over headers
+--------+---------+
         |
         v
+------------------+
| sessions_search  |  pivot hosts/URLs found in bodies
| (zero-hit budget)|  stop serial hunting after 1-2 misses
+--------+---------+
         |
         v
+------------------+
| Chain + verdict  |  landing -> loader -> C2/RPC -> payload/overlay
| Optional EKFiddle|  only if high-signal malicious evidence
+------------------+
```

Step detail:

1. **Triage** — `live_stats`, then `ekfiddle_threats` or `ekfiddle_sessions`, Critical/High first. Low External Script Monitor last unless IOCs demand it.
2. **Domain focus** — `sessions_search` with `host_pattern` for the named host so the model sees which buffer sessions belong to that domain.
3. **Deep dive** — fetch a small number of JS/HTML `session_body` results for highest-signal sessions. Skip image/video/audio. Prefer body over headers; treat headers 404 as non-fatal.
4. **Pivot** — from bodies extract loader/C2/RPC/overlay hosts and URLs; `sessions_search` those next. **Zero-hit budget**: after the first empty host search when chasing many IOCs, stop burning calls on absent hosts; report which hosts are missing and continue from bodies or prior findings.
5. **Chain reconstruction** — landing → loader → C2/RPC → payload/overlay from tool evidence only. Never invent domains, IPs, cookies, or function names absent from tool results or the user query.
6. **Close** — Infection chain, hosts/IOCs, verdict. Author EKFiddle CustomRegexes only when high-signal malicious evidence exists. Do not author FP monitors for confirmed benign libraries unless the analyst explicitly asks.

### What “domain in focus” means in practice

| Situation                 | Expected behavior                                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Domain present in buffer  | Search hits sessions; bodies inspected; pivots follow embedded hosts                                                      |
| Domain absent from buffer | Search returns empty; model reports absence; falls back to other Critical/High EKFiddle hits instead of inventing traffic |
| Many IOC hosts pasted     | At most 1–2 serial zero-hit host hunts, then stop and summarize                                                           |

### Client-side gates that shape the run

These apply to `/investigate` the same as any native chat turn:

| Gate             | Effect                                                                      |
| ---------------- | --------------------------------------------------------------------------- |
| Arg sanitizer    | Fixes common LLM mistakes (`id` → `session_id`, strip leading `*`, etc.)    |
| Refetch lock     | Blocks duplicate `session_body` for the same session ID in one query        |
| Auto-fetch       | May pull a body after a narrow host-filtered search                         |
| Tool budget      | Default ~20 calls (`GEMINI_MAX_TOOL_CALLS`); then force text-only synthesis |
| Soft Ctrl+C      | Stops current tool chain; keeps conversation; returns to prompt             |
| EKFiddle persist | Valid tab-separated rules may be appended to `generated_ekfiddle_rules.txt` |

### Status line: Waiting for DeepSeek LLM (native tools)

That message means the client is blocked on one HTTPS round trip to the LLM (`chat.completions` with tools attached). Local MCP/Fiddler are not queried during that wait. When the model returns `tool_calls`, breadcrumbs such as `-> session_body 42` appear while `call_tool` hits 5ire-bridge then enhanced-bridge. Results are appended and another Waiting turn may follow until the model answers without tools or the budget forces synthesis.

---

## New / touched files (this delivery)

| Path                                                               | Role                                                       |
| ------------------------------------------------------------------ | ---------------------------------------------------------- |
| `llm_prompts.py`                                                   | Shared investigation + EKFiddle system instruction         |
| `llm_tool_schema.py`                                               | Schema normalize + MCP → OpenAI tools                      |
| `llm_providers/base.py`                                            | Provider Protocol                                          |
| `llm_providers/gemini_provider.py`                                 | Gemini native adapter                                      |
| `llm_providers/deepseek_provider.py`                               | DeepSeek OpenAI-compatible adapter + TLS helpers           |
| `gemini-fiddler-client.py`                                         | Provider-driven loop, `/model`, config, investigate prompt |
| `gemini_native_tools.py`                                           | Re-exports / delegates shared prompt + schema              |
| `requirements-gemini.txt`                                          | Adds `openai`, `certifi`, `httpx`                          |
| `tests/test_deepseek_provider.py`                                  | DeepSeek unit + config + loop tests                        |
| `tests/test_native_tool_binding.py`                                | Updated for provider-driven loop                           |
| `README.md`, `MCP_Data_Flow.md`, `NATIVE_TOOLS_SOAK_CHECKLIST.txt` | Docs + soak cases                                          |
| `.gitignore`                                                       | `gemini-fiddler-config.json`, logs, generated rules        |

---

## What this thread deliberately did not change

- Fiddler `CustomRules.js` posting path
- MCP tool set / enhanced-bridge HTTP contracts beyond existing behavior
- Removal of Gemini native path or legacy `GEMINI_NATIVE_TOOLS=0` for Gemini
- DeepSeek thinking mode / strict beta tool schemas
- Renaming the public entry script away from `gemini-fiddler-client.py`

---

## Soak checklist (DeepSeek section)

Manual parity checks after deploy:

1. Gemini default still boots; `/investigate` completes with tool calls
2. `/model deepseek-v4-flash` then `/investigate` with tool calls
3. `/model deepseek-v4-pro` then create EKFiddle rules for a named session
4. Refetch lock, zero-hit, `/clear`, `/clearchat` under DeepSeek
5. Switch back to Gemini mid-session without restart
6. Missing DeepSeek key prompts and saves
7. Connection/TLS errors: confirm URL `https://api.deepseek.com`; treat cert failures as trust-store issues on the VM

Automated suites:

```bash
python3 tests/test_investigation_hardening.py -v
python3 tests/test_native_tool_binding.py -v
python3 tests/test_deepseek_provider.py -v
```

---

## Quick analyst reference

```text
Default provider: gemini / gemini-3-flash-preview
DeepSeek models:  /model 12  or  /model deepseek-v4-flash
                  /model 13  or  /model deepseek-v4-pro

Investigate whole buffer:   /investigate
Investigate with host focus: /investigate evil.example.com

Domain focus = search buffer for that host, read JS/HTML bodies,
then pivot on embedded loader/C2 hosts. Not a live crawl.
```

---

## Related docs in this repo

- `README.md` — setup, models, TLS troubleshooting
- `MCP_Data_Flow.md` — end-to-end capture → MCP → LLM loop
- `NATIVE_TOOLS_SOAK_CHECKLIST.txt` — Gemini + DeepSeek manual soak
- `EKFIDDLE_WORKFLOW_GUIDE.md` — EKFiddle analyst workflow (existing)
