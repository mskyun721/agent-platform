"""Versioned event contracts only; persistence and collection belong to P4."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

ROLES = {"orchestrator", "planner", "backend", "reviewer", "security", "qa", "cicd"}
EVENT_TYPES = {"run_started", "run_ended", "handoff", "verification", "review_result", "usage"}
COMPLETENESS = {"full", "partial", "unavailable"}


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    source: str
    completeness: str


@dataclass(frozen=True)
class ReviewResult:
    decision_id: str
    review_cycle_id: str
    review_attempt_id: str
    reviewer_id: str
    role: str
    attempt: int
    decision: str
    code_fingerprint: str
    run_id: str | None
    artifact: str


@dataclass(frozen=True)
class RunEvent:
    event_id: str
    run_id: str
    parent_run_id: str | None
    project_id: str | None
    task_id: str
    role: str
    event_type: str
    ts: str
    backend: str | None
    model: str | None
    skill_versions: dict[str, str]
    payload: dict[str, Any]
    collection_source: str
    completeness: str
    schema_version: int = 1


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value and UUID(value).version == 4
    except (ValueError, AttributeError):
        return False


def _choice(value: Any, values: set[str]) -> bool:
    return isinstance(value, str) and value in values


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_usage(usage: Usage) -> list[str]:
    errors = []
    counts = [usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens]
    if any(value is not None and (type(value) is not int or value < 0) for value in counts):
        errors.append("token counts must be nonnegative integers or null")
    if not isinstance(usage.source, str) or not usage.source.strip():
        errors.append("usage source required")
    if not _choice(usage.completeness, COMPLETENESS):
        errors.append("invalid usage completeness")
    if usage.completeness == "unavailable" and any(value is not None for value in counts):
        errors.append("unavailable usage must contain null counts")
    if usage.completeness == "full" and (usage.input_tokens is None or usage.output_tokens is None):
        errors.append("full usage requires input/output counts")
    return errors


def validate_review(result: ReviewResult) -> list[str]:
    errors = []
    for name in ("decision_id", "review_cycle_id", "review_attempt_id"):
        if not _uuid(getattr(result, name)):
            errors.append(f"{name} must be a UUID4")
    if result.run_id is not None and not _uuid(result.run_id):
        errors.append("review run_id must be UUID4 or null")
    if not _choice(result.role, {"reviewer", "security", "qa"}):
        errors.append("invalid review role")
    if type(result.attempt) is not int or result.attempt < 1:
        errors.append("review attempt must be positive integer")
    if not _choice(result.decision, {"approved", "rejected"}):
        errors.append("invalid review decision")
    if not isinstance(result.reviewer_id, str) or not result.reviewer_id.strip():
        errors.append("reviewer_id required")
    if not _hash(result.code_fingerprint):
        errors.append("code_fingerprint must be SHA256")
    if not isinstance(result.artifact, str) or not result.artifact.startswith("docs/") or "\\" in result.artifact:
        errors.append("artifact must be a docs-relative path")
    elif any(ord(char) < 32 for char in result.artifact) or ".." in PurePosixPath(result.artifact).parts or not result.artifact.endswith(".md"):
        errors.append("invalid artifact path")
    return errors


def validate(event: RunEvent) -> list[str]:
    errors = []
    if type(event.schema_version) is not int or event.schema_version != 1:
        errors.append("unsupported event schema")
    for name in ("event_id", "run_id"):
        if not _uuid(getattr(event, name)):
            errors.append(f"{name} must be UUID4")
    if event.parent_run_id is not None and (not _uuid(event.parent_run_id) or event.parent_run_id == event.run_id):
        errors.append("invalid parent_run_id")
    if not isinstance(event.task_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}(?:/[a-z][a-z0-9-]{1,63})*", event.task_id):
        errors.append("invalid task_id")
    for name, choices in (("role", ROLES), ("event_type", EVENT_TYPES),
                          ("collection_source", {"wrapper", "direct", "native_import"}),
                          ("completeness", COMPLETENESS)):
        if not _choice(getattr(event, name), choices):
            errors.append(f"invalid {name}")
    for name in ("project_id", "backend", "model"):
        value = getattr(event, name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"{name} must be nonempty string or null")
    try:
        timestamp = datetime.fromisoformat(event.ts)
        if timestamp.utcoffset() != timedelta(0):
            errors.append("ts must use UTC")
    except (ValueError, TypeError):
        errors.append("invalid ts")
    if not isinstance(event.skill_versions, dict) or any(
        not isinstance(key, str) or not key or not _hash(value) for key, value in event.skill_versions.items()
    ):
        errors.append("skill_versions must map IDs to SHA256 hashes")
    if not isinstance(event.payload, dict):
        errors.append("payload must be an object")
        return errors
    try:
        json.dumps(asdict(event), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        errors.append("event must be JSON serializable without nonfinite numbers")
    if event.event_type == "usage":
        try:
            errors.extend(validate_usage(Usage(**event.payload)))
        except TypeError:
            errors.append("invalid usage payload fields")
    if event.event_type == "review_result":
        try:
            review = ReviewResult(**event.payload)
            errors.extend(validate_review(review))
            if review.role != event.role or review.run_id != event.run_id:
                errors.append("review role/run must match enclosing event")
        except TypeError:
            errors.append("invalid review payload fields")
    return errors
