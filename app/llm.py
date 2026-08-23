"""LLM access — one OpenAI-compatible client, provider chosen by env vars.

  LLM_API_KEY   (falls back to OPENAI_API_KEY)
  LLM_BASE_URL  (unset = api.openai.com; works with Groq/OpenRouter/Gemini
                 OpenAI-compatible endpoints too)
  LLM_MODEL     (default gpt-4o-mini)

Env is read lazily, so import order vs the .env loader never matters.
"""
import os

from openai import OpenAI

_client = None


def model():
    return os.environ.get("LLM_MODEL", "gpt-4o-mini")


def client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("LLM_API_KEY") or os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("LLM_BASE_URL") or None,
        )
    return _client


def chat(messages, tools=None):
    """One chat completion. Returns the raw message object."""
    kwargs = {"model": model(), "messages": messages, "temperature": 0}
    if tools:
        kwargs["tools"] = tools
    return client().chat.completions.create(**kwargs).choices[0].message
