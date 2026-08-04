"""Grove LLM client (OpenAI-compatible) with a structured-output ladder.

Grove authenticates via a custom `api-key` header (not Bearer) and accepts
`response_format: json_schema` (verified in P0 with gpt-5.4-mini @ temp 0).
The ladder degrades: json_schema -> json_object -> plain-prompt+parse, each with
one retry-with-error-feedback. Roles `fast`/`reasoning` map to env models.

NO embedding calls live here or anywhere in /agent — memory embeddings are
produced inside Atlas (Automated Embedding). This module is chat-completions only.
"""
from __future__ import annotations

import json
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import settings

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.grove_base_url,
            api_key="unused",  # Grove ignores Bearer; auth is the api-key header
            default_headers={"api-key": settings.grove_api_key},
            timeout=settings.grove_timeout_seconds,
            max_retries=2,
        )
    return _client


def _model_for(role: str) -> str:
    if role == "vision":
        return settings.llm_vision_model
    return settings.llm_reasoning_model if role == "reasoning" else settings.llm_fast_model


def _strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a pydantic JSON schema acceptable to OpenAI strict json_schema:
    additionalProperties=false everywhere; every property listed in required."""
    def walk(s: Any):
        if isinstance(s, dict):
            if s.get("type") == "object" and "properties" in s:
                s["additionalProperties"] = False
                s["required"] = list(s["properties"].keys())
            for v in s.values():
                walk(v)
        elif isinstance(s, list):
            for v in s:
                walk(v)
    walk(schema)
    return schema


def _kwargs(temperature: float | None) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    t = settings.grove_send_temperature if temperature is None else temperature
    if t is not None:
        kw["temperature"] = t
    return kw


def _chat(model: str, messages: list[dict], response_format: dict | None, temperature) -> tuple[str, dict]:
    kw = _kwargs(temperature)
    if response_format is not None:
        kw["response_format"] = response_format
    resp = client().chat.completions.create(model=model, messages=messages, **kw)
    usage = {
        "prompt": getattr(resp.usage, "prompt_tokens", 0) or 0,
        "completion": getattr(resp.usage, "completion_tokens", 0) or 0,
        "total": getattr(resp.usage, "total_tokens", 0) or 0,
    }
    return resp.choices[0].message.content or "", usage


def structured(
    schema: type[T],
    system: str,
    user: str,
    role: str = "reasoning",
    temperature: float | None = None,
    image_url: str | None = None,
) -> tuple[T, dict]:
    """Return (validated model, token usage). Tries the configured mode then degrades."""
    model = _model_for(role)
    js = _strictify(schema.model_json_schema())
    modes = ["json_schema", "json_object", "prompt"]
    start = settings.grove_structured_mode if settings.grove_structured_mode in modes else "json_schema"
    order = modes[modes.index(start):] + modes[: modes.index(start)]

    schema_hint = json.dumps(schema.model_json_schema())
    last_err = ""
    total_usage = {"prompt": 0, "completion": 0, "total": 0}

    for mode in order:
        sys = system
        if mode == "prompt":
            sys = f"{system}\n\nReply with ONLY a JSON object matching this schema (no prose):\n{schema_hint}"
        for attempt in range(2):
            user_content: Any = user
            if image_url is not None:
                user_content = [{"type": "text", "text": user},
                                {"type": "image_url", "image_url": {"url": image_url}}]
            messages = [{"role": "system", "content": sys}, {"role": "user", "content": user_content}]
            if attempt == 1 and last_err:
                messages.append({"role": "user", "content": f"Your previous reply failed validation: {last_err}. Return corrected JSON only."})
            rf: dict | None = None
            if mode == "json_schema":
                rf = {"type": "json_schema", "json_schema": {"name": schema.__name__, "strict": True, "schema": js}}
            elif mode == "json_object":
                rf = {"type": "json_object"}
            try:
                content, usage = _chat(model, messages, rf, temperature)
                for k in total_usage:
                    total_usage[k] += usage[k]
                obj = json.loads(content)
                return schema.model_validate(obj), total_usage
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = str(e)[:300]
                continue
            except Exception as e:  # API error (e.g. mode unsupported) -> next mode
                last_err = str(e)[:300]
                break
    raise RuntimeError(f"structured() exhausted ladder: {last_err}")


def converse(system: str, messages: list[dict], role: str = "fast") -> tuple[str, dict]:
    """Plain-text chat over prior turns. messages = [{"role","content"}...]."""
    return _chat(_model_for(role), [{"role": "system", "content": system}, *messages], None, None)


def health() -> bool:
    try:
        content, _ = _chat(_model_for("fast"), [{"role": "user", "content": "reply PONG"}], None, 0)
        return "PONG" in content.upper()
    except Exception:
        return False
