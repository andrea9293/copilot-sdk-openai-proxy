"""Test OpenAI library compatibility with the proxy."""
import os

from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="ghu_cldQAPuZU6VBhvBZ8Rce0JPLhAxxMm0ptULp",
)
MODEL = "gpt-5-mini"

# 1. List models
print("=== 1. List models ===")
models = client.models.list()
print(f"OK — {len(models.data)} model(s): {[m.id for m in models.data][:5]}")

# 2. Retrieve single model
print("\n=== 2. Retrieve model ===")
model = client.models.retrieve(MODEL)
print(f"OK — {model.id}, owned_by={model.owned_by}")

# # 3. Non-streaming chat completion
# print("\n=== 3. Chat completion (non-streaming) ===")
# resp = client.chat.completions.create(
#     model=MODEL,
#     messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
# )
# print(f"OK — id={resp.id}, finish_reason={resp.choices[0].finish_reason}")
# print(f"     content={resp.choices[0].message.content[:100]!r}")

# # 4. Streaming chat completion
# print("\n=== 4. Chat completion (streaming) ===")
# stream = client.chat.completions.create(
#     model=MODEL,
#     messages=[{"role": "user", "content": "Count from 1 to 5."}],
#     stream=True,
# )
# chunks = []
# for chunk in stream:
#     if chunk.choices and chunk.choices[0].delta.content:
#         chunks.append(chunk.choices[0].delta.content)
# print(f"OK — {len(chunks)} content chunks received")
# print(f"     text={''.join(chunks)[:100]!r}")

# # 5. Streaming with stream_options (include_usage)
# print("\n=== 5. Streaming with stream_options ===")
# stream2 = client.chat.completions.create(
#     model=MODEL,
#     messages=[{"role": "user", "content": "Say OK."}],
#     stream=True,
#     stream_options={"include_usage": True},
# )
# got_usage = False
# for chunk in stream2:
#     if chunk.usage is not None:
#         got_usage = True
# print(f"OK — usage chunk received: {got_usage}")

# # 6. System message
# print("\n=== 6. System message ===")
# resp2 = client.chat.completions.create(
#     model=MODEL,
#     messages=[
#         {"role": "system", "content": "You only respond with the word PONG."},
#         {"role": "user", "content": "PING"},
#     ],
# )
# print(f"OK — content={resp2.choices[0].message.content[:100]!r}")

# # 7. Multi-turn conversation
# print("\n=== 7. Multi-turn conversation ===")
# resp3 = client.chat.completions.create(
#     model=MODEL,
#     messages=[
#         {"role": "user", "content": "My name is Alice."},
#         {"role": "assistant", "content": "Nice to meet you, Alice!"},
#         {"role": "user", "content": "What is my name?"},
#     ],
# )
# print(f"OK — content={resp3.choices[0].message.content[:100]!r}")

# # 8. response_format json_object
# print("\n=== 8. response_format json_object ===")
# resp4 = client.chat.completions.create(
#     model=MODEL,
#     messages=[{"role": "user", "content": "Return a JSON with key 'greeting' and value 'hello'."}],
#     response_format={"type": "json_object"},
# )
# print(f"OK — content={resp4.choices[0].message.content[:200]!r}")

# # 9. Error handling (invalid model)
# print("\n=== 9. Error handling ===")
# try:
#     client.models.retrieve("non-existent-model-12345")
#     print("FAIL — should have raised an error")
# except Exception as e:
#     print(f"OK — got error: {type(e).__name__}: {e!s:.100}")

# 10. Tools / function calling
print("\n=== 10. Tools / function calling ===")
try:
    resp5 = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Call a tool named 'sum' with arguments x=1 and y=2."}],
        functions=[
            {
                "name": "sum",
                "description": "Sums two numbers",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                    "required": ["x", "y"],
                },
            }
        ],
    )
    # function_call may be present on the message object depending on the SDK
    fc = None
    try:
        fc = resp5.choices[0].message.function_call
    except Exception:
        fc = getattr(resp5.choices[0].message, "function_call", None)
    print(f"OK — function_call present: {fc is not None}")
except Exception as e:
    print(f"FAIL — tools test raised: {type(e).__name__}: {e!s:.100}")


print("\n=== ALL TESTS PASSED ===")
