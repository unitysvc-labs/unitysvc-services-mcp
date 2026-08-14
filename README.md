# unitysvc-services-mcp

MCP services published to the UnitySVC catalog and reached through the
[MCP gateway](https://github.com/unitysvc/mcp-gateway).

Customers configure **one** MCP endpoint in their AI client and see the tools of
every MCP service they're enrolled in. Enrolling and un-enrolling here is how
they manage what the client sees — no per-server configuration, no scattered
API keys.

Design: unitysvc/unitysvc#1799 (gateway), unitysvc/unitysvc#1803 (catalog model).

## Services

| Folder | Service | Upstream |
|---|---|---|
| [`services/specs/unitysvc`](services/specs/unitysvc) | The UnitySVC marketplace + docs as MCP tools | `https://mcp.unitysvc.com/mcp` |

## What makes an MCP service different

**They are offering-only.** A listing here carries **no `user_access_interfaces`**,
because customers never address an MCP service directly — they connect to the
gateway, which resolves the service by `service_id`. That's the interfaceless
shape from unitysvc/unitysvc#1715 phase 3, and `validate_mcp_offering` in
`unitysvc-core` enforces it.

**The channel key is the tool namespace.** The gateway exposes each upstream tool
as `<channel>__<tool>`, so a channel named `unitysvc` yields
`unitysvc__market_list_services`. Two consequences:

- Namespaces must be unique **across the whole catalog**, not just within an
  offering. The backend enforces this at ingest; a collision would silently
  shadow another seller's entire toolset.
- Keep them short and legal. MCP clients cap tool names at 64 characters and
  allow only `[a-zA-Z0-9_-]`, and a single illegal name fails the *whole*
  `tools/list` payload — not just that tool.

**The pinned tool manifest lives in `details.tools`**, not on the channel. It's
catalog-facing and secret-free, so the gateway serves `tools/list` from it
without ever reading `upstream_access_config`. Capture it from a live
`tools/list` rather than writing it by hand. Note the catalog stores
`input_schema` (snake_case) where the protocol emits `inputSchema`.

## Adding a service

```bash
mkdir -p services/specs/<name>
# author provider.json, offering.json, listing.json, connectivity.sh.j2

cd services
usvc_seller specs validate     # schema + MCP rules
usvc_seller specs format       # alphabetical key sorting; CI checks this
usvc_seller specs run-tests    # local mode: probes the upstream directly
```

A service is not ready until all three pass **and** it has a connectivity test —
that's enforced, not advisory.

Requires `unitysvc-core>=0.2.15` for `ServiceTypeEnum.mcp`. An older version
rejects the spec with `'mcp' is not one of [...]`.

## Connectivity tests

MCP isn't one request — Streamable HTTP needs a handshake: `initialize` ->
capture `Mcp-Session-Id` -> `notifications/initialized` -> `tools/list`. A single
`curl` proves liveness but not that the tools are reachable, which is the half
that matters.

Each test has two branches:

- **local** (`specs run-tests`) — talks to the upstream MCP server directly.
- **gateway** (`services run-tests`) — talks to the UnitySVC MCP gateway with a
  customer key, and asserts on the **namespaced** tool name.

## CI

Thin callers into the shared reusable workflows in `unitysvc-labs/.github`, same
as every other `unitysvc-services-*` repo:

| Workflow | Trigger |
|---|---|
| `validate-data` | PR + push to `main` |
| `format-check` | PR + push to `main` |
| `upload-to-staging` | PR merged to `main`, or manual |
| `upload-to-production` | Manual only |

The repo name matters: `update-staging.sh` iterates `unitysvc-services-*/`, so a
spec outside that pattern is never picked up by a staging data refresh.
