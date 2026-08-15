#!/usr/bin/env python3
"""Refresh the pinned `tools` manifest in a param file from its live server.

A manifest is a snapshot of an upstream we do not control, so it goes stale
silently — a tool renamed upstream keeps being advertised until someone looks.
Re-run this when a server changes, and commit the diff.

    python tools/refresh_manifests.py services/specs/labs/*.json
    python tools/refresh_manifests.py --check services/specs/labs/*.json   # CI-style

Streamable HTTP is a handshake, not one request: initialize -> capture
Mcp-Session-Id -> notifications/initialized -> tools/list. Responses may be
plain JSON or SSE-framed.

Servers that need a credential take it from the environment, under the param
file's own `secret_name` — the same variable the connectivity test reads, so
one `set -a; . services/seller.secrets.txt; set +a` covers both:

    set -a; . services/seller.secrets.txt; set +a
    python tools/refresh_manifests.py services/specs/labs/github-mcp.json

No token is ever passed on the command line: argv is visible to every other
process on the machine and lands in shell history.
"""

import json
import os
import sys
import pathlib
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"


def _post(
    url: str, payload: dict, session: str | None, token: str | None = None
) -> tuple[dict | None, dict]:
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL,
    }
    if session:
        headers["Mcp-Session-Id"] = session
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", "replace")
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
    # SSE frames arrive as "event: message\ndata: {...}"
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.startswith("{"):
            try:
                return json.loads(line), hdrs
            except json.JSONDecodeError:
                continue
    return None, hdrs


def probe(url: str, token: str | None = None) -> list[dict]:
    init, hdrs = _post(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "unitysvc-catalog-probe", "version": "1"},
            },
        },
        None,
        token,
    )
    if init is None or "result" not in init:
        raise RuntimeError(f"initialize failed: {init}")
    session = hdrs.get("mcp-session-id")
    try:
        _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session, token)
    except Exception:
        pass  # servers that don't track sessions ignore this
    listed, _ = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session, token)
    if listed is None or "result" not in listed:
        raise RuntimeError(f"tools/list failed: {listed}")
    return listed["result"].get("tools", [])


def to_manifest(tools: list[dict]) -> list[dict]:
    """Catalog shape: input_schema (snake_case), no extra keys."""
    out = []
    for t in sorted(tools, key=lambda x: x.get("name", "")):
        entry = {
            "name": t["name"],
            "description": (t.get("description") or "").strip(),
            "input_schema": t.get("inputSchema") or t.get("input_schema") or {},
        }
        if t.get("annotations"):
            entry["annotations"] = t["annotations"]
        out.append(entry)
    return out



def refresh(path: pathlib.Path, *, check: bool) -> bool:
    """Update one param file. Returns True when it already matched."""
    doc = json.loads(path.read_text())
    # The documented invocation globs `specs/labs/*.json`, which also matches
    # the `<name>.service.json` sidecars holding the uploaded service_id. They
    # are not param files; skip rather than crash on the first one.
    if "parameters" not in doc:
        return True
    params = doc["parameters"]

    # A server needing a credential says so via `secret_name`. Missing token is
    # "skipped", not "failed": running the tool over the whole catalog should
    # refresh every keyless server rather than abort on the first gated one.
    secret_name = params.get("secret_name")
    token = os.environ.get(secret_name) if secret_name else None
    if secret_name and not token:
        print(f"{path.name}: skipped — {secret_name} not set in the environment")
        return True

    try:
        live = to_manifest(probe(params["upstream_url"], token))
    except urllib.error.HTTPError as exc:
        # 401 is the expected failure when a token is wrong, expired, or of the
        # wrong kind — several of these providers issue more than one sort of
        # credential and only one authenticates here. Say so instead of raising
        # a traceback at someone who just pasted a key.
        if exc.code in (401, 403):
            detail = exc.read().decode("utf-8", "replace").strip()[:200]
            print(
                f"{path.name}: {secret_name or 'credential'} rejected "
                f"(HTTP {exc.code}) — {detail}",
                file=sys.stderr,
            )
            return False
        raise
    if live == params.get("tools"):
        print(f"{path.name}: up to date ({len(live)} tools)")
        return True

    old = {t["name"] for t in params.get("tools", [])}
    new = {t["name"] for t in live}
    for name in sorted(new - old):
        print(f"{path.name}: + {name}")
    for name in sorted(old - new):
        print(f"{path.name}: - {name}")
    if old & new and old == new:
        print(f"{path.name}: schema/description changes only")

    if check:
        return False
    params["tools"] = live
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"{path.name}: updated to {len(live)} tools")
    return False


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv[1:]
    stale = [p for p in (pathlib.Path(a) for a in args) if not refresh(p, check=check)]
    if check and stale:
        print(f"\n{len(stale)} manifest(s) differ from the live servers", file=sys.stderr)
        sys.exit(1)
