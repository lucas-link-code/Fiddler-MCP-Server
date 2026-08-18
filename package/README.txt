Fiddler MCP package

These files are the extracted runtime. The usual install is the two files at
the GitHub repo root:

  Fiddler-MCP-Setup.bat
  Fiddler-MCP-Bundle.zip

Setup extracts this package to %USERPROFILE%\Fiddler_MCP, deploys CustomRules.js,
starts the HTTP bridge and the client. API keys are entered in the client window.

Already extracted: run deploy-mcp.bat from this folder.
Day to day restart: start-fiddler-mcp.bat

5ire-bridge.py is started by the client as the MCP child. No separate console.
