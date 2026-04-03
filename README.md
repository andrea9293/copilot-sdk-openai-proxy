# Copilot SDK OpenAI Proxy (Python)

OpenAI-compatible API server powered by the GitHub Copilot SDK.

It exposes the classic OpenAI endpoints so you can use standard OpenAI clients (including the official Python OpenAI SDK) against a local Copilot-backed proxy.

## Features

- OpenAI-compatible endpoints:
  - `GET /v1/models`
  - `POST /v1/chat/completions`
- Streaming and non-streaming chat completions
- Multi-turn conversation support
- Tool calling support (including multi-step tool loops)
- Multimodal image input (`image_url` content parts)
- FastAPI server with CORS enabled

## Requirements

- Python 3.11+
- GitHub Copilot CLI available and authenticated on the host
- A valid GitHub token with Copilot access (for Docker usage)

## Project Layout

- `server/main.py`: FastAPI app and endpoints
- `server/handlers.py`: Copilot session orchestration
- `server/converters.py`: OpenAI <-> Copilot conversion logic
- `server/models.py`: OpenAI-compatible request/response models
- `test_proxy.py`: end-to-end tests using the official OpenAI Python SDK
- `Dockerfile`: container image for running the proxy

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

python -m server.main --host 0.0.0.0 --port 8081
```

## Quick API Checks

```bash
curl http://localhost:8081/health

curl http://localhost:8081/v1/models

curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5-mini",
    "messages": [{"role": "user", "content": "Say hello in one word."}]
  }'
```

## Tool Calling Example

```bash
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5-mini",
    "messages": [{"role": "user", "content": "What is the weather in London?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string"}
          },
          "required": ["location"]
        }
      }
    }]
  }'
```

## Image Input Example

You can send OpenAI-style multimodal content (`text` + `image_url`, including `data:` URLs). The proxy converts image inputs into Copilot blob attachments.

## OpenAI SDK End-to-End Test

`test_proxy.py` validates:

- non-streaming responses
- streaming responses
- multi-turn behavior
- image description
- single tool call
- streaming tool call
- multi-step tool calling (date -> weather for tomorrow)

Run:

```bash
source .venv/bin/activate
python -m server.main --port 8081
```

In another terminal:

```bash
source .venv/bin/activate
python test_proxy.py
```

## Docker

Build:

```bash
docker build -t copilot-sdk-openai-proxy .
```

Run:

```bash
docker run --rm -p 8081:8081 \
  -e COPILOT_GITHUB_TOKEN="<your_token>" \
  -e PORT=8081 \
  copilot-sdk-openai-proxy
```

Then use:

- Base URL: `http://localhost:8081/v1`
- API key in OpenAI clients: any non-empty string (proxy does not validate OpenAI keys)

## Notes

- The proxy keeps compatibility with OpenAI request/response shapes for chat completions.
- Tool execution follows the OpenAI flow: model requests tool calls, client executes tools, then client sends tool results back in follow-up messages.
