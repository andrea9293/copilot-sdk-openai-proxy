"""End-to-end tests for the Copilot OpenAI proxy using the official OpenAI SDK.

Start the proxy first:
    source .venv/bin/activate
    python -m server.main --port 8081

Then run this file:
    GITHUB_TOKEN=ghp_... python test_proxy.py
"""

import base64
import json
import os
from pathlib import Path

from openai import OpenAI

BASE_URL = "http://localhost:8081/v1"
MODEL = "gpt-5-mini"

_token = os.environ.get("GITHUB_TOKEN", "")
if not _token:
    raise RuntimeError(
        "GITHUB_TOKEN environment variable is not set. "
        "Export your GitHub token before running this script:\n"
        "    export GITHUB_TOKEN=ghp_..."
    )

client = OpenAI(base_url=BASE_URL, api_key=_token)

# ── Helpers ──────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "Get the current date and day of the week",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather forecast for a given location and date",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                },
                "required": ["location", "date"],
            },
        },
    },
]


def fake_tool_result(name: str, arguments: dict) -> str:
    """Simulate tool execution and return a JSON string result."""
    if name == "get_current_date":
        return json.dumps({"date": "2026-04-04", "day": "Saturday"})
    if name == "get_weather":
        loc = arguments.get("location", "unknown")
        date = arguments.get("date", "unknown")
        return json.dumps({
            "location": loc,
            "date": date,
            "temperature_c": 18,
            "condition": "partly cloudy",
            "wind_kmh": 12,
        })
    return json.dumps({"error": f"Unknown tool: {name}"})


def separator(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


# ── 1. Non-streaming ────────────────────────────────────────────────────────


def test_non_streaming():
    separator("1. Non-streaming chat")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a concise assistant. Reply in 1-2 sentences."},
            {"role": "user", "content": "What is the capital of France?"},
        ],
    )
    print(f"Response: {resp.choices[0].message.content}")
    print(f"Finish reason: {resp.choices[0].finish_reason}")


# ── 2. Streaming ────────────────────────────────────────────────────────────


def test_streaming():
    separator("2. Streaming chat")
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": "Count from 1 to 5, one number per line."},
        ],
        stream=True,
    )
    print("Streamed content: ", end="")
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
    print()


# ── 3. Multi-turn ───────────────────────────────────────────────────────────


def test_multi_turn():
    separator("3. Multi-turn conversation")
    messages = [
        {"role": "user", "content": "My name is Andrea and I live in Rome."},
    ]
    r1 = client.chat.completions.create(model=MODEL, messages=messages)
    assistant_reply = r1.choices[0].message.content
    print(f"Turn 1 → {assistant_reply}")

    messages.append({"role": "assistant", "content": assistant_reply})
    messages.append({"role": "user", "content": "What is my name and where do I live? Reply with just the facts."})

    r2 = client.chat.completions.create(model=MODEL, messages=messages)
    print(f"Turn 2 → {r2.choices[0].message.content}")


# ── 4. Image description ────────────────────────────────────────────────────


def test_image_description():
    separator("4. Image description")
    image_path = Path(__file__).parent / "image_test.png"
    if not image_path.exists():
        print(f"SKIP: {image_path} not found")
        return

    b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_uri = f"data:image/png;base64,{b64}"

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in 1-2 sentences."},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    print(f"Description: {resp.choices[0].message.content}")


# ── 5. Single tool call ─────────────────────────────────────────────────────


def test_single_tool_call():
    separator("5. Single tool call")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "What's the weather in London on 2026-04-05?"}],
        tools=TOOLS,
    )
    msg = resp.choices[0].message
    print(f"Finish reason: {resp.choices[0].finish_reason}")

    if msg.tool_calls:
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            print(f"Tool call: {tc.function.name}({args})")
            result = fake_tool_result(tc.function.name, args)
            print(f"Tool result: {result}")

            # Send tool result back
            messages = [
                {"role": "user", "content": "What's the weather in London on 2026-04-05?"},
                msg.model_dump(),
                {"role": "tool", "tool_call_id": tc.id, "content": result},
            ]
            final = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
            print(f"Final answer: {final.choices[0].message.content}")
    else:
        print(f"No tool calls. Content: {msg.content}")


# ── 6. Single tool call (streaming) ─────────────────────────────────────────


def test_single_tool_call_streaming():
    separator("6. Single tool call (streaming)")
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "What's the weather in Rome on 2026-04-06?"}],
        tools=TOOLS,
        stream=True,
    )

    tool_calls_acc: dict[int, dict] = {}
    for chunk in stream:
        choice = chunk.choices[0]
        if choice.delta.tool_calls:
            for tc in choice.delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    tool_calls_acc[idx]["id"] = tc.id
                if tc.function and tc.function.name:
                    tool_calls_acc[idx]["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    tool_calls_acc[idx]["arguments"] += tc.function.arguments
        if choice.finish_reason:
            print(f"Finish reason: {choice.finish_reason}")

    for idx, tc in sorted(tool_calls_acc.items()):
        args = json.loads(tc["arguments"])
        result = fake_tool_result(tc["name"], args)
        print(f"Tool call #{idx}: {tc['name']}({args}) → {result}")


# ── 7. Multi-step tool calling ──────────────────────────────────────────────


def test_multi_step_tool_calling():
    separator("7. Multi-step tool calling (get date → get weather for tomorrow)")
    messages = [
        {
            "role": "user",
            "content": "What day is today? Then tell me the weather in Milan for tomorrow.",
        }
    ]

    step = 1
    while step <= 5:  # safety limit
        print(f"\n--- Step {step} ---")
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        finish = resp.choices[0].finish_reason
        print(f"Finish reason: {finish}")

        if finish == "tool_calls" and msg.tool_calls:
            # Append assistant message with tool calls
            messages.append(msg.model_dump())
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = fake_tool_result(tc.function.name, args)
                print(f"  → {tc.function.name}({args}) = {result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            step += 1
        else:
            # Model gave a final text answer
            print(f"Final answer: {msg.content}")
            break


# ── Run all ──────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    test_non_streaming()
    test_streaming()
    test_multi_turn()
    test_image_description()
    test_single_tool_call()
    test_single_tool_call_streaming()
    test_multi_step_tool_calling()
    print(f"\n{'=' * 60}")
    print("  All tests completed!")
    print(f"{'=' * 60}")
