# Fiddler MCP Bridge

Real-time web traffic analysis powered by Gemini. Connect Fiddler Classic to large language models via the Model Context Protocol.

## What This Does

This bridge streams captured HTTP/S sessions from Fiddler directly to Gemini (or any MCP-compatible LLM client). Ask natural language questions about your traffic:

- "Show me sessions from the last 5 minutes"
- "Are there any suspicious downloads?"
- "Analyze the JavaScript in session 147"
- "Find all POST requests to api.example.com"

The LLM receives raw session data (headers, bodies, metadata) and performs the analysis itself. No black-box threat scoring; you see what the model sees.

## Architecture

```
Fiddler Classic          enhanced-bridge.py        5ire-bridge.py         Gemini Client
     |                         |                        |                      |
     |   POST /live-session    |                        |                      |
     |------------------------>|  REST API (8081)       |                      |
     |   (JSON session data)   |----------------------->|   MCP tools          |
     |                         |  /api/sessions/...     |--------------------->|
     |                         |                        |   (stdin/stdout)     |
     |                         |                        |                      |
```

1. **Fiddler** captures traffic and POSTs JSON to the bridge via CustomRules.js
2. **enhanced-bridge.py** buffers sessions in memory and exposes REST endpoints
3. **5ire-bridge.py** translates REST calls into MCP tools for the LLM
4. **gemini-fiddler-client.py** connects everything and provides an interactive chat interface

## Prerequisites

- Windows 10/11
- Python 3.8 or later
- Fiddler Classic (must be installed and run at least once)
- Gemini API key (free tier available at https://makersuite.google.com/app/apikey)

## Quick Start

Run the one-click deployment script:

```batch
deploy-mcp.bat
```

The script handles everything:
1. Checks Python installation
2. Locates your Fiddler Scripts directory
3. Installs Python dependencies
4. Prompts for your Gemini API key
5. Deploys CustomRules.js to Fiddler
6. Launches the bridge and client in separate windows

After deployment:
1. In Fiddler, reload the script: Rules > Reload Script (Ctrl+R)
2. Browse the web to generate traffic
3. Ask questions in the Gemini Fiddler Client window

## MCP Tools

Seven tools are exposed to the LLM:

| Tool | Purpose |
|------|---------|
| `fiddler_mcp__live_sessions` | List recent sessions with metadata and risk indicators |
| `fiddler_mcp__sessions_search` | Filter by host, URL, status, method, size, MIME type |
| `fiddler_mcp__session_headers` | Get request/response headers for a session |
| `fiddler_mcp__session_body` | Get request/response bodies (content) |
| `fiddler_mcp__live_stats` | Buffer depth, capture rate, uptime |
| `fiddler_mcp__sessions_timeline` | Aggregate by time, host, status, or content type |
| `fiddler_mcp__sessions_clear` | Clear buffers after exporting evidence |

Tools return raw data. The LLM performs reasoning based on the returned headers, bodies, and metadata.

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
├── deploy-mcp.bat              # One-click setup (run this first)
├── enhanced-bridge.py          # HTTP server, session buffer (port 8081)
├── 5ire-bridge.py              # MCP server (FastMCP over stdin/stdout)
├── gemini-fiddler-client.py    # Interactive Gemini chat client
├── CustomRules.js              # Fiddler script (auto-deployed)
├── requirements-gemini.txt     # Gemini client dependencies
├── requirements-mcp.txt        # MCP bridge dependencies
├── gemini-fiddler-config.json  # Generated config (API key, model)
├── MCP_Data_Flow.md            # Data flow walkthrough
├── MCP_Server_Guide.md         # Architecture overview
└── MCP_TOOL_CONTRACT.md        # Tool schemas and responses
```

## Manual Setup

If the one-click script fails, install manually:

```batch
:: Install dependencies
pip install google-generativeai rich mcp pydantic Flask requests

:: Copy CustomRules.js to Fiddler
copy CustomRules.js "%USERPROFILE%\Documents\Fiddler2\Scripts\"

:: Start the bridge (terminal 1)
python enhanced-bridge.py

:: Start the client (terminal 2)
python gemini-fiddler-client.py
```

The client prompts for your API key on first run.

## Configuration

`gemini-fiddler-config.json` (created by deploy-mcp.bat):

```json
{
  "api_key": "your-api-key",
  "model": "gemini-2.5-flash",
  "auto_save_full_bodies": false,
  "mcp_server_command": ["python", "5ire-bridge.py"],
  "bridge_url": "http://127.0.0.1:8081"
}
```

Available models:
- `gemini-2.5-flash` (recommended, fast)
- `gemini-2.5-pro` (more capable)
- `gemini-2.0-flash`
- `gemini-1.5-pro`
- `gemini-1.5-flash`

## Troubleshooting

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

**Enable debug mode**
```batch
SET DEPLOY_DEBUG=1
deploy-mcp.bat
```

## How It Works

The system follows this data path for every captured session:

1. Fiddler intercepts a request/response pair
2. CustomRules.js serializes the session to JSON and POSTs to `http://127.0.0.1:8081/live-session`
3. enhanced-bridge.py stores the session in a ring buffer (up to 2000 sessions)
4. When the LLM calls a tool like `session_headers`, 5ire-bridge.py fetches from the REST API
5. The JSON response is injected into the Gemini prompt
6. Gemini analyzes the data and responds in natural language

See `MCP_Data_Flow.md` for a detailed walkthrough with code snippets.

## Use Cases

- Malware traffic analysis (FakeUpdates, SocGholish, exploit kits)
- API debugging and inspection
- Session forensics and timeline reconstruction
- JavaScript deobfuscation assistance
- Header and cookie analysis
- Redirect chain investigation

## Acknowledgments

- EKFiddle for rule format inspiration
- Model Context Protocol specification
- Fiddler community
