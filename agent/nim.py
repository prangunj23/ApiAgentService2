import json
import os
import re

from openai import OpenAI

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-pro-0813"


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply, ignoring reasoning blocks and code fences."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start : end + 1])


def chat_json(system: str, user: str) -> dict:
    client = OpenAI(base_url=NIM_BASE_URL, api_key=os.environ["NVIDIA_API_KEY"], timeout=600)
    model = os.environ.get("NIM_MODEL") or DEFAULT_MODEL
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    for attempt in range(2):
        completion = client.chat.completions.create(
            model=model, messages=messages, temperature=0.2, max_tokens=16384
        )
        content = completion.choices[0].message.content or ""
        try:
            return extract_json(content)
        except ValueError:
            if attempt == 1:
                raise
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "That was not valid JSON. Reply with only the JSON object."},
            ]
    raise AssertionError("unreachable")
