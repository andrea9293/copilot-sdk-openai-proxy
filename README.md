# <p align="center"><img src="assets/hero.png" alt="hero" /></p>

# Copilot SDK OpenAI Proxy (Python)

OpenAI-compatible API server powered by the GitHub Copilot SDK.

It exposes the classic OpenAI endpoints so you can use standard OpenAI clients (including the official Python OpenAI SDK) against a local Copilot-backed proxy.

## Features

- Authentication UI via GitHub OAuth device flow (`GET /auth`)
- Token dashboard (`GET /auth/dashboard`) with quota and session management
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
- GitHub Copilot CLI available/authenticated on host, or a valid GitHub token with Copilot access

## Project Layout

- `server/main.py`: FastAPI app, root UI, and endpoints
- `server/auth.py`: Auth UI, dashboard UI, and auth/dashboard APIs
- `server/state.py`: Per-token `CopilotClient` cache and session retention pruning
- `server/handlers.py`: Copilot session orchestration
- `server/converters.py`: OpenAI <-> Copilot conversion logic
- `server/models.py`: OpenAI-compatible request/response models
- `test_proxy.py`: end-to-end tests using the official OpenAI Python SDK
- `Dockerfile`: container image for running the proxy

## UI Endpoints

- `GET /`: centralized home UI (navigation)
- `GET /auth`: authentication page
- `GET /auth/dashboard`: token dashboard

## Authentication

The proxy supports two authentication methods.

### 1. GitHub Token (Bearer Token)

Pass your GitHub token in the `Authorization` header with the `Bearer` scheme:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8081/v1",
    api_key="ghp_your_github_token"
)
```

### 2. OAuth Device Flow (Web UI)

Open `http://localhost:8081/auth` and complete GitHub device flow. A token is shown after authentication.

### Auth API endpoints

- `POST /auth/device/start`: start GitHub device flow
- `POST /auth/device/poll`: poll for device flow completion
- `GET /auth/status`: check token auth status

## Token Dashboard

Open `http://localhost:8081/auth/dashboard` to:

- paste/select the GitHub token to inspect
- view Copilot quota snapshots (`account.getQuota`) including used and remaining requests
- list persisted sessions for that token
- delete a single session
- prune old sessions keeping only the latest 10

## Session Retention

The proxy prunes persisted Copilot sessions automatically to avoid unbounded growth.

- Keeps the 10 most recently modified sessions per token by default
- Deletes older sessions through the SDK (`client.delete_session`)
- Pruning is throttled (default once every 120 seconds per token)

Environment variables:

- `COPILOT_SESSION_KEEP_COUNT` (default: `10`)
- `COPILOT_SESSION_PRUNE_INTERVAL_SECONDS` (default: `120`)

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

curl http://localhost:8081/auth/status \
  -H "Authorization: Bearer ghp_your_github_token"

curl http://localhost:8081/v1/models \
  -H "Authorization: Bearer ghp_your_github_token"

curl http://localhost:8081/v1/chat/completions \
  -H "Authorization: Bearer ghp_your_github_token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5-mini",
    "messages": [{"role": "user", "content": "Say hello in one word."}]
  }'
```

## OpenAI SDK End-to-End Test

Run server:

```bash
source .venv/bin/activate
python -m server.main --port 8081
```

In another terminal:

```bash
source .venv/bin/activate
export GITHUB_TOKEN=ghp_your_github_token
python test_proxy.py
```

## Docker

Docker Compose (recommended):

```bash
docker-compose up -d
```

or standalone Docker

Build:

```bash
docker build -t copilot-sdk-openai-proxy .
```

Run:

```bash
docker run --rm -p 8081:8081 \
  -e PORT=8081 \
  copilot-sdk-openai-proxy
```

Then open:

- Home UI: `http://localhost:8081/`
- Auth UI: `http://localhost:8081/auth`
- Dashboard UI: `http://localhost:8081/auth/dashboard`

## Notes

- The proxy keeps compatibility with OpenAI request/response shapes for chat completions.
- Tool execution follows the OpenAI flow: model requests tool calls, client executes tools, then client sends tool results back in follow-up messages.
- Each GitHub token gets its own cached `CopilotClient`, so multiple tokens can be used concurrently.
