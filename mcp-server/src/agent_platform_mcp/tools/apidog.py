"""API Dog REST API tools."""

from __future__ import annotations

from typing import Any

import httpx

from agent_platform_mcp.config import ConfigError, apidog_config

DEFAULT_TIMEOUT_SEC = 30
APIDOG_BASE_URL = "https://api.apidog.com"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str] | dict[str, Any]:
    """Return request headers or an error dict if config is missing."""
    try:
        cfg = apidog_config()
    except ConfigError as exc:
        return {"error": str(exc)}
    return {
        "X-Apidog-Api-Access-Token": cfg["token"],
        "Accept": "application/json",
    }


def _summarize_openapi(spec: dict) -> list[dict[str, str]]:
    """Extract a flat endpoint list from an OpenAPI 3.x spec dict."""
    endpoints = []
    for path, methods in spec.get("paths", {}).items():
        for method, detail in methods.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                continue
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": detail.get("summary", ""),
                "operation_id": detail.get("operationId", ""),
                "tags": ", ".join(detail.get("tags", [])),
            })
    return endpoints


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def export_openapi(project_id: str) -> dict[str, Any]:
    """Export full OpenAPI 3.0 spec from an API Dog project.

    Returns {project_id, openapi_version, title, endpoints_count, spec} on success,
    or {error: "..."} on failure.
    """
    headers = _headers()
    if "error" in headers:
        return headers  # type: ignore[return-value]

    try:
        resp = httpx.get(
            f"{APIDOG_BASE_URL}/api/v1/projects/{project_id}/export-openapi",
            params={"version": "3.0"},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"API Dog request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if resp.status_code == 401:
        return {"error": "API Dog auth failed. Check APIDOG_API_TOKEN."}
    if resp.status_code == 403:
        return {"error": f"API Dog: no access to project {project_id}. Check token permissions."}
    if resp.status_code == 404:
        return {"error": f"API Dog project not found: {project_id}"}
    if resp.status_code != 200:
        return {"error": f"API Dog API error: HTTP {resp.status_code}"}

    try:
        spec = resp.json()
    except ValueError:
        return {"error": "API Dog returned a non-JSON response"}

    info = spec.get("info", {})
    endpoints = _summarize_openapi(spec)

    return {
        "project_id": project_id,
        "openapi_version": spec.get("openapi", ""),
        "title": info.get("title", ""),
        "version": info.get("version", ""),
        "endpoints_count": len(endpoints),
        "spec": spec,
    }


def list_endpoints(project_id: str) -> dict[str, Any]:
    """List all API endpoints from an API Dog project (summarized, no full spec).

    Returns {project_id, title, endpoints: [{method, path, summary, operation_id, tags}]}
    or {error: "..."} on failure.
    """
    result = export_openapi(project_id)
    if "error" in result:
        return result

    return {
        "project_id": project_id,
        "title": result.get("title", ""),
        "version": result.get("version", ""),
        "endpoints_count": result["endpoints_count"],
        "endpoints": _summarize_openapi(result["spec"]),
    }


def fetch_endpoint_detail(project_id: str, path: str, method: str) -> dict[str, Any]:
    """Fetch full request/response detail for a single endpoint from the OpenAPI spec.

    Returns {method, path, summary, parameters, request_body, responses}
    or {error: "..."} on failure.
    """
    result = export_openapi(project_id)
    if "error" in result:
        return result

    spec = result["spec"]
    method_lower = method.lower()
    path_item = spec.get("paths", {}).get(path)

    if not path_item:
        return {"error": f"Path '{path}' not found in project {project_id}"}

    detail = path_item.get(method_lower)
    if not detail:
        return {"error": f"Method '{method.upper()} {path}' not found in project {project_id}"}

    return {
        "method": method.upper(),
        "path": path,
        "summary": detail.get("summary", ""),
        "description": detail.get("description", ""),
        "operation_id": detail.get("operationId", ""),
        "tags": detail.get("tags", []),
        "parameters": detail.get("parameters", []),
        "request_body": detail.get("requestBody", {}),
        "responses": detail.get("responses", {}),
        "security": detail.get("security", []),
    }
