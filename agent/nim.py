import json
import os
import re

import openai
from openai import OpenAI

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-pro-0813"


def require_env(*names: str) -> None:
    """Exit with a clear message if a required setting is missing.

    GitHub Actions passes an empty string for a secret or variable that doesn't exist.
    """
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit(
            f"Missing required setting(s): {', '.join(missing)}.\n"
            "Add them to this repository under Settings → Secrets and variables → Actions. "
            "Check that each secret is a repository secret (not a variable or an environment secret) "
            "and that the name matches exactly."
        )


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply, ignoring reasoning blocks and code fences."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start : end + 1])


def chat_json(system: str, user: str) -> dict:
    # Pasted secrets often end in a newline, which isn't allowed in an HTTP header.
    api_key = os.environ["NVIDIA_API_KEY"].strip()
    client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key, timeout=600, max_retries=5)
    model = os.environ.get("NIM_MODEL", "").strip() or DEFAULT_MODEL
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    for attempt in range(2):
        try:
            completion = client.chat.completions.create(
                model=model, messages=messages, temperature=0.2, max_tokens=16384
            )
        except openai.APIConnectionError as err:
            # The SDK only says "Connection error."; include the underlying network error.
            raise RuntimeError(f"Couldn't reach NVIDIA NIM at {NIM_BASE_URL}: {err.__cause__!r}") from err

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
