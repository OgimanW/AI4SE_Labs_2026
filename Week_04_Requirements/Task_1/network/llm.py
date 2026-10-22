"""Thin wrapper around ChatOpenAI with structured output, retries and usage logging."""
import time
from functools import lru_cache
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=None)
def _chat(model: str, params_key: tuple) -> ChatOpenAI:
    """Cached client per model (API key is read from OPENAI_API_KEY by the SDK)."""
    return ChatOpenAI(model=model, max_retries=config.LLM_MAX_RETRIES,
                      timeout=config.LLM_TIMEOUT_S, **dict(params_key))


def model_for(node: str) -> str:
    return config.MODELS[node]


def structured_call(node: str, schema: type[T], system: str, user: str,
                    model: str | None = None) -> tuple[T | None, dict[str, Any]]:
    """Call the node's model and parse into `schema`.

    Returns (parsed_or_None, call_record). Never raises: failures are recorded
    in the call record so one failing fan-out branch cannot crash the run.
    """
    model = model or model_for(node)
    params = tuple(sorted(config.MODEL_PARAMS.get(node, {}).items()))
    runnable = _chat(model, params).with_structured_output(
        schema, method="json_schema", include_raw=True, strict=True)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    record: dict[str, Any] = {"type": "llm_call", "node": node, "model": model,
                              "input_tokens": 0, "output_tokens": 0, "attempts": 0}
    start = time.time()
    last_error = ""
    for attempt in range(1, config.LLM_PARSE_RETRIES + 1):
        record["attempts"] = attempt
        try:
            out = runnable.invoke(messages)
            usage = getattr(out.get("raw"), "usage_metadata", None) or {}
            record["input_tokens"] += usage.get("input_tokens", 0)
            record["output_tokens"] += usage.get("output_tokens", 0)
            parsed = out.get("parsed")
            if parsed is not None:
                record.update(ok=True, seconds=round(time.time() - start, 1))
                return parsed, record
            last_error = f"parsing_error: {out.get('parsing_error')}"
        except Exception as exc:  # noqa: BLE001 - recorded, retried, never fatal
            last_error = f"{type(exc).__name__}: {exc}"[:500]
        time.sleep(min(2 ** attempt, 30))
    record.update(ok=False, error=last_error, seconds=round(time.time() - start, 1))
    return None, record
