"""Langfuse observability client — no-op when env vars are absent."""

from __future__ import annotations

import os

_client = None


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
