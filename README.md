# Copilot SDK OpenAI Proxy (Python)

OpenAI-compatible API server powered by the GitHub Copilot SDK.

It exposes the classic OpenAI endpoints so you can use standard OpenAI clients (including the official Python OpenAI SDK) against a local Copilot-backed proxy.

## Features

- **Authentication UI** — browser-based login via GitHub OAuth device flow (`GET /auth`)
- **Auth API endpoints** — programmatic device flow start/poll and token status check
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
- GitHub Copilot CLI available and authenticated on the host, **or** a valid GitHub token obtained via the built-in login UI

## Project Layout

- `server/main.py`: FastAPI app and endpoints
- `server/state.py`: shared per-token `CopilotClient` cache
- `server/auth.py`: authentication router (device flow + HTML UI)
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

## Authentication

The proxy supports two authentication methods.

### Option 1 — Login UI (browser, recommended)

Open `http://localhost:8081/auth` in your browser.

The page offers two flows:

1. **GitHub OAuth device flow** — click *Start GitHub Login*, enter the displayed one-time code at `github.com/login/device`, and the page automatically captures the token.
2. **Paste an existing token** — enter a GitHub fine-grained PAT (with *Copilot Requests* permission) or the token from `gh auth token`, then click *Verify & Use Token*.

After successful login the page shows the token and copy-to-clipboard button, plus a ready-to-use code snippet.

### Option 2 — Environment variable / system Copilot login

Set one of the following environment variables before starting the server:

```
COPILOT_GITHUB_TOKEN=<token>
GH_TOKEN=<token>
GITHUB_TOKEN=<token>
```

Or authenticate once with the GitHub Copilot CLI:

```bash
copilot login
```

When no `Authorization` header is provided by the client the proxy uses the locally authenticated user.

### Using the token with an OpenAI client

Pass the token as the `api_key`:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8081/v1",
    api_key="<token>",          # token obtained from /auth
)
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### Auth API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/auth` | Serve the login HTML page |
| `POST` | `/auth/device/start` | Start the GitHub device flow; returns `device_code`, `user_code`, `verification_uri` |
| `POST` | `/auth/device/poll` | Poll for device flow completion; returns `access_token` when authorized |
| `GET`  | `/auth/status` | Check auth status for the token in the `Authorization: Bearer <token>` header |

#### `POST /auth/device/start` — response

```json
{
  "device_code": "...",
  "user_code": "ABCD-1234",
  "verification_uri": "https://github.com/login/device",
  "expires_in": 900,
  "interval": 5
}
```

#### `POST /auth/device/poll` — request / response

```bash
curl -X POST http://localhost:8081/auth/device/poll \
  -H "Content-Type: application/json" \
  -d '{"device_code": "<device_code>"}'
```

While pending:

```json
{"pending": true, "error": "authorization_pending"}
```

When authorized:

```json
{"access_token": "gho_...", "token_type": "bearer"}
```

#### `GET /auth/status` — response

```bash
curl http://localhost:8081/auth/status \
  -H "Authorization: Bearer <token>"
```

```json
{"authenticated": true, "login": "your-github-login", "auth_type": "oauth"}
```

## Quick API Checks

```bash
curl http://localhost:8081/health

# check auth status for a token
curl http://localhost:8081/auth/status \
  -H "Authorization: Bearer <token>"

curl http://localhost:8081/v1/models \
  -H "Authorization: Bearer <token>"

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
- API key in OpenAI clients: the GitHub token (same value as `COPILOT_GITHUB_TOKEN`), or any non-empty string if the CLI is already authenticated on the host
- Login UI: `http://localhost:8081/auth` (not needed when token is set via env var)

## Notes

- The proxy keeps compatibility with OpenAI request/response shapes for chat completions.
- Tool execution follows the OpenAI flow: model requests tool calls, client executes tools, then client sends tool results back in follow-up messages.
