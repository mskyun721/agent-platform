"""Langfuse observability client — no-op when env vars are absent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT

_client = None
_HOOK_CONTEXT_FILE: Path = ROOT / ".claude" / "langfuse" / "active-session.json"


def get_client():
    """Return a Langfuse client if LANGFUSE_PUBLIC_KEY/SECRET_KEY are set, else None."""
    global _client
    if _client is not None:
        return _client

    pk = os.getenv("LANGFUSE_PUBLIC_KEY")
    sk = os.getenv("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        return None

    try:
        from langfuse import Langfuse  # noqa: PLC0415

        _client = Langfuse(
            public_key=pk,
            secret_key=sk,
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )
    except Exception:
        return None

    return _client


def _read_hook_context() -> dict[str, Any]:
    try:
        data = json.loads(_HOOK_CONTEXT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def current_trace_context() -> dict[str, str]:
    """Return the current hook session/trace context when available."""
    hook_context = _read_hook_context()
    session_id = os.getenv("LANGFUSE_SESSION_ID") or str(hook_context.get("session_id") or "")
    trace_id = os.getenv("LANGFUSE_TRACE_ID") or str(hook_context.get("trace_id") or "")
    return {"session_id": session_id, "trace_id": trace_id}


def summarize_text(text: str | None) -> dict[str, int | bool]:
    """Return a redacted summary for arbitrary text content."""
    if not text:
        return {"present": False, "chars": 0, "lines": 0}
    return {"present": True, "chars": len(text), "lines": text.count("\n") + 1}


def _call_with_fallbacks(func, candidates: list[dict[str, Any]]):
    for candidate in candidates:
        filtered = {
            key: value
            for key, value in candidate.items()
            if value not in (None, "", {}, [])
        }
        try:
            return func(**filtered)
        except TypeError:
            continue
        except Exception:
            return None
    return None


def start_cli_span(
    *,
    trace_name: str,
    span_name: str,
    metadata: dict[str, Any],
    prompt: str,
):
    """Start a Langfuse span that reuses the active Claude trace when possible."""
    lf = get_client()
    if lf is None:
        return None

    context = current_trace_context()
    trace_metadata = {"source": "mcp-sdk", **metadata}
    if context["session_id"]:
        trace_metadata.setdefault("session_id", context["session_id"])
    if context["trace_id"]:
        trace_metadata.setdefault("hook_trace_id", context["trace_id"])

    trace_candidates: list[dict[str, Any]] = []
    if context["trace_id"]:
        trace_candidates.append(
            {
                "id": context["trace_id"],
                "name": trace_name,
                "session_id": context["session_id"],
                "metadata": trace_metadata,
            }
        )
        trace_candidates.append(
            {
                "id": context["trace_id"],
                "name": trace_name,
                "metadata": trace_metadata,
            }
        )
    trace_candidates.append(
        {
            "name": trace_name,
            "session_id": context["session_id"],
            "metadata": trace_metadata,
        }
    )
    trace_candidates.append({"name": trace_name, "metadata": trace_metadata})

    trace = _call_with_fallbacks(lf.trace, trace_candidates)
    if trace is None:
        return None

    span_input = {"prompt_summary": summarize_text(prompt)}
    span_metadata = dict(trace_metadata)
    return _call_with_fallbacks(
        trace.span,
        [
            {"name": span_name, "input": span_input, "metadata": span_metadata},
            {"name": span_name, "input": span_input},
            {"name": span_name},
        ],
    )


def end_cli_span(
    span,
    *,
    stdout: str | None,
    stderr: str | None,
    exit_code: int | None,
    elapsed_sec: float,
    timed_out: bool = False,
) -> None:
    """End a Langfuse span without exporting raw prompt or subprocess output."""
    if span is None:
        return

    level = "ERROR" if timed_out or (exit_code not in (None, 0)) else "DEFAULT"
    output = {
        "stdout_summary": summarize_text(stdout),
        "stderr_summary": summarize_text(stderr),
    }
    metadata: dict[str, Any] = {"elapsed_sec": elapsed_sec, "timed_out": timed_out}
    if exit_code is not None:
        metadata["exit_code"] = exit_code

    _call_with_fallbacks(
        span.end,
        [
            {"output": output, "metadata": metadata, "level": level},
            {"output": output, "metadata": metadata},
            {"output": output},
        ],
    )
