"""Read-only check that the Langfuse project answers and has recent traces."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_BASE = "https://cloud.langfuse.com"
DEFAULT_PROJECT_URL = "https://cloud.langfuse.com/project/cmu7le5go05ffad0gp2xjvxjo"
LINE_HEALTH = "https://line.203.0.113.20.sslip.io/health"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _load_dotenv(path: str | None = None) -> None:
    candidate = path or os.environ.get("VORTEX_ENV_FILE") or ".env"
    if not os.path.isfile(candidate):
        return
    for line in open(candidate, encoding="utf-8"):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("LANGFUSE_"):
            continue
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key, value)


def _auth() -> str:
    public = _env("LANGFUSE_PUBLIC_KEY")
    secret = _env("LANGFUSE_SECRET_KEY")
    if not public or not secret:
        raise SystemExit("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY missing")
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return f"Basic {token}"


def _get(path: str, params: dict[str, str] | None = None) -> tuple[int, Any]:
    host = _env("LANGFUSE_BASE_URL", DEFAULT_BASE).rstrip("/")
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        host + path + query,
        headers={"Authorization": _auth(), "User-Agent": "vortex-hackspain"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        try:
            parsed = json.loads(body) if body else {"error": str(exc)}
        except json.JSONDecodeError:
            parsed = {"error": body or str(exc)}
        return exc.code, parsed


def project_url() -> str:
    return _env("LANGFUSE_PROJECT_URL", DEFAULT_PROJECT_URL)


def check() -> dict[str, Any]:
    _load_dotenv()
    status, projects = _get("/api/public/projects")
    if status != 200:
        return {"ok": False, "step": "projects", "http": status, "body": projects}
    rows = projects.get("data") if isinstance(projects, dict) else None
    project = rows[0] if rows else {}
    now = datetime.now(UTC)
    start = (now - timedelta(days=7)).isoformat()
    end = now.isoformat()
    obs_status, observations = _get(
        "/api/public/v2/observations",
        {
            "fromStartTime": start,
            "toStartTime": end,
            "limit": "10",
            "fields": "core,basic,trace_context",
        },
    )
    traces = []
    if obs_status == 200 and isinstance(observations, dict):
        seen: set[str] = set()
        for row in observations.get("data") or []:
            trace_id = str(row.get("traceId") or "")
            if trace_id and trace_id not in seen:
                seen.add(trace_id)
                traces.append(
                    {
                        "trace_id": trace_id,
                        "name": row.get("name") or row.get("traceName") or "",
                        "start": row.get("startTime") or "",
                    }
                )
    line: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(LINE_HEALTH, timeout=10) as response:
            line = json.loads(response.read().decode())
    except Exception as exc:
        line = {"error": type(exc).__name__}
    return {
        "ok": status == 200,
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "url": project_url(),
        },
        "environment": _env("LANGFUSE_TRACING_ENVIRONMENT") or _env("VORTEX_ENV"),
        "observations_http": obs_status,
        "recent_traces": traces,
        "line_has_keys": bool(line.get("has_langfuse_keys")),
        "line_environment": line.get("langfuse_environment") or "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Langfuse project + recent traces")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = check()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report.get("ok") else 1
    project = report.get("project") or {}
    print(f"project  {project.get('name')} ({project.get('id')})")
    print(f"url      {project.get('url')}")
    print(f"env      {report.get('environment') or '(unset)'}")
    print(f"line     has_langfuse_keys={report.get('line_has_keys')}")
    traces = report.get("recent_traces") or []
    if not traces:
        print("traces   none in the last 7 days")
    else:
        print(f"traces   {len(traces)} recent")
        for row in traces[:5]:
            print(f"         {row['name']} {row['trace_id'][:12]} {row['start']}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
