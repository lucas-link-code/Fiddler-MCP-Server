# Fiddler MCP Server

Created a GenAI assisted workflow that helps analysts examine HTTP traffic captured in Fiddler. Analysts can ask questions in natural language about redirects, scripts, downloads, headers and suspicious behaviour instead of reviewing each web session manually.

Implemented an MCP bridge as the interface between Fiddler and LLM clients, with support for Gemini, DeepSeek and OpenRouter. Developed 10 analysis tools which let the model search sessions, inspect headers and bodies, compare traffic, build timelines and review EKFiddle findings.

Built an agentic analysis workflow which triggers tools on demand to deliver comprehensive malicious website analysis in a report. The analyst can see the raw evidence behind each answer and remains responsible for the final decision.

## Quick Start

Windows analysis VM with Fiddler Classic and Python 3.10 or later.

1. Download these two files from the repo root into the same folder:
   - `Fiddler-MCP-Setup.bat`
   - `Fiddler-MCP-Bundle.zip`
2. Double-click `Fiddler-MCP-Setup.bat`
3. Setup extracts to `%USERPROFILE%\Fiddler_MCP`, installs dependencies, deploys `CustomRules.js`, and starts the bridge plus client
4. API keys are not required during setup. Enter them in the client window when prompted
5. In Fiddler: Rules > Reload Script (Ctrl+R)

Day-to-day restart from the install folder:

```batch
start-fiddler-mcp.bat
```

`5ire-bridge.py` runs inside the client as the MCP child. There is no third console window.

Guides: [QUICK_START_GUIDE.txt](docs/QUICK_START_GUIDE.txt), [Fiddler_MCP_Guide.pdf](docs/Fiddler_MCP_Guide.pdf)

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
     |                         |                        |   Native tool loop
     |                         |                        |---------------------> LLM API
```

1. Fiddler captures traffic and POSTs JSON via CustomRules.js
2. enhanced-bridge.py buffers sessions and exposes REST on port 8081
3. 5ire-bridge.py exposes MCP tools that call that REST API
4. gemini-fiddler-client.py binds those tools on the active LLM provider, runs the chat loop, and executes every tool through `call_tool`

The model never talks to Fiddler or Python directly. The client is the middleman.

## MCP Tools

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

Tools return raw data. The LLM reasons over headers, bodies, and EKFiddle comments.

Slash commands in the client: `/investigate`, `/investigate <host>`, `/clear`, `/clearchat`, `/model`, `/stats`, `/tools`, `/help`, `/quit`.

## Repository layout

```
├── Fiddler-MCP-Setup.bat        # Outer installer (place next to the zip)
├── Fiddler-MCP-Bundle.zip       # Runtime package
├── pack-release.bat             # Rebuild the zip from package/
├── package/                     # Files inside the zip, plus tests
└── docs/                        # Operator guides and PDFs
```

Source for a rebuild lives in `package/`. Maintainer: run `pack-release.bat` from the repo root.

## Documentation

- [QUICK_START_GUIDE.txt](docs/QUICK_START_GUIDE.txt)
- [MCP_Data_Flow.md](docs/MCP_Data_Flow.md) / [MCP_data_flow.pdf](docs/MCP_data_flow.pdf)
- [MCP_Server_Guide.md](docs/MCP_Server_Guide.md)
- [Fiddler_MCP_Guide.pdf](docs/Fiddler_MCP_Guide.pdf)
- [TROUBLESHOOTING.txt](docs/TROUBLESHOOTING.txt)
- [EKFIDDLE_WORKFLOW_GUIDE.md](docs/EKFIDDLE_WORKFLOW_GUIDE.md)
- [EKFIDDLE_QUICK_REFERENCE.txt](docs/EKFIDDLE_QUICK_REFERENCE.txt)

## LLM providers

Gemini is the default. DeepSeek and OpenRouter are optional. Switching providers uses `/model` in the client. A missing key is prompted once and saved locally in `gemini-fiddler-config.json`, which is not in this repository.

OpenRouter accepts a freeform `vendor/model` id when an OpenRouter key is present. Curated `/model` numbers for OpenRouter are 14 to 18. Direct DeepSeek API remains `/model 12` and `/model 13`.

## Prerequisites

- Windows 10/11 analysis VM, or macOS/Linux for development
- Python 3.10 or later
- Fiddler Classic, run at least once so Scripts exists
- At least one LLM API key when the client starts: Gemini, DeepSeek, or OpenRouter

## Troubleshooting

If dependency install fails, run `package/install-dependencies-manual.bat` then `package/deploy-mcp.bat`.

On FLARE VMs, pip often fails with `CERTIFICATE_VERIFY_FAILED` talking to pypi.org even when curl/ping work. That is Python's CA store. The package includes `pypi_tls.py`; setup bats probe PyPI and retry pip with `--trusted-host`. Force lab mode with `set FIDDLER_PIP_TRUSTED_HOST=1`.

See [TROUBLESHOOTING.txt](docs/TROUBLESHOOTING.txt). Common issues: Fiddler must be closed when CustomRules.js is copied; port 8081 must be free; Rules > Reload Script after deploy.

## Use cases

- Malware traffic analysis
- EKFiddle CustomRegex drafting from live session bodies
- Session forensics and timeline reconstruction
- JavaScript and redirect-chain review

## Acknowledgments

- EKFiddle for rule format inspiration
- Model Context Protocol specification
- Fiddler community
