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
| [`services/specs/unitysvc-mcp`](services/specs/unitysvc-mcp) | The UnitySVC marketplace + docs as MCP tools | `https://mcp.unitysvc.com/mcp` |

## What makes an MCP service different

**One interface, at the shared gateway.** A listing carries exactly one
`user_access_interface`:

```json
"mcp_gateway": {
  "access_method": "mcp",
  "base_url": "${MCP_GATEWAY_BASE_URL}",
  "routing_key": {"namespace": "unitysvc"}
}
```

Customers never address an MCP service at its own URL — they connect to the one
gateway endpoint and it resolves each enrolled service. `base_url` takes no path
suffix; `routing_key.namespace` does the selecting, the same role
`routing_key.username` plays for SMTP (unitysvc/unitysvc#1803).

**The namespace is not the service name.** They answer different questions:

| | Example | What it does |
|---|---|---|
| Service name | `unitysvc-mcp`, `labs/github-mcp` | Identifies the catalog entry |
| `routing_key.namespace` | `unitysvc`, `github` | Prefixes every tool the gateway exposes |

So `unitysvc-mcp` publishes `unitysvc__market_list_services`. Keep the namespace
free of the `-mcp` suffix: every tool in an MCP client is already an MCP tool,
and the grammar `^[a-z0-9][a-z0-9_]{0,23}$` forbids `-` regardless. Two
consequences follow from the namespace being global:

- It must be unique **across the whole catalog**, not just within an offering.
  The backend enforces this at ingest; a collision would silently shadow
  another seller's entire toolset.
- Keep it short. MCP clients cap tool names at 64 characters, and the 24-char
  namespace cap leaves at least 38 for the upstream tool name before the
  gateway has to truncate-and-hash. A single illegal name fails the *whole*
  `tools/list` payload — not just that tool — which is why the grammar is
  client-legal by construction.

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

Requires `unitysvc-core>=0.2.17`: 0.2.15 added `ServiceTypeEnum.mcp` but
*rejected* the gateway interface, so a spec in the shape above fails to
validate against it.

**Naming.** First-party services take a bare handle (`unitysvc-mcp`); everything
else is provider-scoped (`labs/github-mcp`). The `-mcp` suffix is what keeps the
service distinguishable from the provider, the org, and the namespace — this
service was called plain `unitysvc` and was confusing in exactly that way.

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
