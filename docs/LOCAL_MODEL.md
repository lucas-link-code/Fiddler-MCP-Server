# Pointing the client at a local model

Operator note. This is not a supported backend. The repo does not ship a local provider. Use this when an inference server already runs on the same host and you want the client to talk to it instead of a cloud API.

## What stays on the host already

Fiddler, enhanced-bridge.py on port 8081, and 5ire-bridge.py never leave the machine. CustomRules.js posts sessions to localhost. MCP tools stay local.

## This is he hop you will need to retarget!

Only gemini-fiddler-client.py calls an LLM. That is the hop you will need to retarget. Do not change CustomRules, the bridges, or the MCP tool list.

```
Fiddler Classic
  -> enhanced-bridge.py  :8081
  -> 5ire-bridge.py  MCP stdio
  -> gemini-fiddler-client.py
  -> local OpenAI compatible server  :11434 / :1234 / other
```

The model never talks to Fiddler. The client remains the middleman.

## This is DeepSeek slot reuse, not a new provider implementation
We are reusung the same schema as DeepSeek and OpenRouter.

DeepSeek and OpenRouter already use the OpenAI Python SDK with a configurable base url. DeepSeekProvider in package/llm_providers/deepseek_provider.py is the path you reuse. The client already reads deepseek_base_url from gemini-fiddler-config.json.

Nothing in this repository implements a fourth provider named local. You are pointing the existing DeepSeek client at 127.0.0.1.

## The local server must speak tools

This client is a native tool loop, not a chatbot. Every investigate style turn sends the ten Fiddler MCP tools as an OpenAI tools array. The model must return structured tool_calls. Prose that says to call a tool is not enough.

The inference server must accept:

```
POST /v1/chat/completions
```

with OpenAI tools and tool_calls. Chat only endpoints fail.

Example base urls:

```
Ollama:     http://127.0.0.1:11434/v1
LM Studio:  http://127.0.0.1:1234/v1
vLLM:       http://127.0.0.1:<port>/v1
llama.cpp:  http://127.0.0.1:<port>/v1
```

The DeepSeek cloud default is https://api.deepseek.com with no /v1. Local servers usually need /v1 on the url. Include it.

Do not bind the inference server to port 8081. That port is the Fiddler MCP HTTP bridge.

Raw Ollama /api/generate is not this API. Use the OpenAI compatible /v1 endpoint.

## Config on the analysis VM

The file sits next to the client. After the usual Windows install that path is:

```
%USERPROFILE%\Fiddler_MCP\gemini-fiddler-config.json
```

That is the same path config_file_path() uses. The file is local and is not in this repository.

Set at least these keys. Keep any existing Gemini or OpenRouter keys if you still use those providers later.

```json
{
  "provider": "deepseek",
  "model": "YOUR_LOCAL_MODEL_ID",
  "deepseek_api_key": "local",
  "deepseek_base_url": "http://127.0.0.1:11434/v1"
}
```

Restart the client after you save. Do not restart Fiddler or the bridge for this change.

Dummy key: the client refuses an empty deepseek_api_key. Ollama and most local servers ignore the value. Put any non empty string.

Pin provider to deepseek. provider_for_model treats names without a slash that are not deepseek-\* as Gemini. A local id such as qwen2.5-coder:32b will be sent to Gemini unless provider stays deepseek.

Model id: use the name the local server lists, not deepseek-v4-flash. For Ollama that is the ollama list name. For LM Studio it is the loaded model id.

## Raise the HTTP timeout

DeepSeekProvider reads DEEPSEEK_HTTP_TIMEOUT. Default is 90 seconds. A local generate plus a ten tool loop often needs more.

Windows cmd before you start the client:

```batch
set DEEPSEEK_HTTP_TIMEOUT=300
```

## Prove tool calling before you chat

Replace the model field with the id your server actually serves.

```bash
curl http://127.0.0.1:11434/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"YOUR_LOCAL_MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in London?\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"description\":\"Get weather for a city\",\"parameters\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}},\"required\":[\"city\"]}}}]}"
```

Unix:

```bash
curl http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "YOUR_LOCAL_MODEL_ID",
    "messages": [{"role": "user", "content": "What is the weather in London?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather for a city",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string"}
          },
          "required": ["city"]
        }
      }
    }]
  }'
```

If the JSON contains a tool_calls array, the Fiddler client can use this server. If you only get assistant text, stop. A local provider would not help until the inference stack implements tools.

Small chat models often fail a ten tool MCP loop even when this curl succeeds. Prefer a tool trained model with enough context for truncated session bodies.

## The UI will still say DeepSeek

Reply prefix, bind logs, and error strings stay DeepSeek. display_label is hardcoded in package/llm_providers/deepseek_provider.py.

Optional operator tweak on the VM only, not a repo change: set display_label to Model in that file and restart the client.

Error text may still tell you to curl https://api.deepseek.com. Ignore that when base url is localhost. Check the local /v1 url instead.

## Common failures

- Model too small to follow the ten MCP tools. Curl works, investigate does not.
- deepseek_base_url missing /v1. Local 404 or empty replies.
- provider not pinned to deepseek. Local model id routed to Gemini.
- empty deepseek_api_key. Client refuses to start that provider.
- DEEPSEEK_HTTP_TIMEOUT still at 90. Local generate times out mid loop.
- Inference server on 8081. Clash with enhanced-bridge.py.
- Talking to Ollama /api/generate instead of /v1/chat/completions.

## Do not do this

Do not point Fiddler at the model.

Do not put inference inside the MCP server.

Do not expect Gemini FunctionDeclarations against a local HTTP server. Gemini stays a Google API. The DeepSeek OpenAI slot is the only reuse path without code changes.
