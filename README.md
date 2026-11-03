# spond-no-match-mcp

An [MCP](https://modelcontextprotocol.io/) server for managing kids' sports activities on [Spond](https://spond.com/). Built for parents who want to give AI assistants access to upcoming matches, training schedules, and attendance — so you can ask "what's on this week?" or "sign Oliver up for Saturday's match" from any MCP-capable client.

## Features

- **Six tools** — list groups, upcoming events, event details, attendance status, RSVP, and search
- **Finds your kids** — kids where you are a guardian in Spond, with their status on every event
- **Norwegian output** — responses formatted in Norwegian (dates, weekdays, status labels)
- **TTL caching** — groups cached 1h, events 5min to minimize API calls
- **Keeps other families' data out** — see [Privacy](#privacy)
- **Bearer token auth** — optional authentication for protecting sensitive family data
- **Scale-to-zero ready** — lightweight Python server, works great on Knative

## Tools

| Tool                  | Description                                                     |
| --------------------- | --------------------------------------------------------------- |
| `list_groups`         | List all Spond groups with member counts and which kids are in them |
| `get_upcoming_events` | Get upcoming events with each kid's response, filterable by kid or group |
| `get_event_details`   | Full details for a specific event (location, description, RSVP) |
| `get_event_participants` | Full names of the participants in an event, per response    |
| `get_attendance`      | Show which events are missing responses for your kids           |
| `respond_to_event`    | Accept or decline an event for a family member                  |
| `search_events`       | Search upcoming events by text in title or description          |

## Quick Start

### Prerequisites

- Python 3.11+
- A [Spond](https://spond.com/) account with active group memberships

### Run locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
SPOND_USERNAME=you@example.com \
SPOND_PASSWORD=your-password \
python main.py
```

The server starts on port 8080:

- Health check: `http://localhost:8080/healthz` (`/health` also works)
- Health check with a Spond login: `http://localhost:8080/healthz?check=1` (needs the bearer token)
- MCP endpoint (Streamable HTTP): `http://localhost:8080/mcp`

### Docker

```bash
docker build -t spond-mcp .
docker run -p 8080:8080 \
  -e SPOND_USERNAME=you@example.com \
  -e SPOND_PASSWORD=your-password \
  spond-mcp
```

### Environment Variables

| Variable         | Required | Default                 | Description                                       |
| ---------------- | -------- | ----------------------- | ------------------------------------------------- |
| `SPOND_USERNAME` | Yes      |                         | Spond account email                               |
| `SPOND_PASSWORD` | Yes      |                         | Spond account password                            |
| `KIDS_CONFIG`    | No       | `[]`                    | JSON array of first names, to limit which kids are used |
| `MCP_AUTH_TOKEN` | No       |                         | Bearer token for authentication (see below)       |
| `MCP_READ_ONLY`  | No       | `false`                 | `true` hides and refuses `respond_to_event`       |
| `PORT`           | No       | `8080`                  | Server port                                       |

### Kids

The server finds your kids by itself: every group member where the Spond account is a
guardian. A kid has a separate member ID in each group and may be spelled differently
("Oliver" in one group, "Oliver Nordmann" in another); the first word of the first name
ties them together. Each event shows the response of every kid invited to it, and
`respond_to_event` answers with the kid's member ID in that event's group.

`KIDS_CONFIG` is optional. Set it to limit the kids, e.g. when the account is also a
guardian for someone else's child:

```json
["Oliver", "Emma"]
```

The older format, `[{"name": "Oliver", "groups": ["Team 2013"]}]`, still works; `groups` is ignored.

## Privacy

Spond returns every member of a group, with guardians, e-mail addresses and phone
numbers, both in groups and in each event. The server cannot ask for less, so it
slims everything right after fetching:

- Groups keep their name, member count and your kids' member IDs.
- Events keep what the tools show; responses keep the counts and only your kids' IDs.
- Posts and chats keep the text, time and the sender's first name.
- The raw copies the Spond library keeps of its last responses are dropped.

Tool answers and the cache therefore hold no other members' names or contact details,
apart from what people write in posts and messages, and `get_event_participants`.
That tool shows the full names of the participants in one event, as the Spond app does.
It fetches the event fresh each time, never caches the names, shows no contact details,
and shows nothing when the organiser has hidden the participants. Logs hold no kid names, member IDs
or Spond responses, and a failed login does not log Spond's login answer.

## Authentication

This server handles sensitive family data and supports optional bearer token authentication. When `MCP_AUTH_TOKEN` is set, all requests (except `/health` and `/healthz`) must include an `Authorization: Bearer <token>` header.

- `/health` and `/healthz` are always exempt (required for health probes); `/healthz?check=1` is not
- When `MCP_AUTH_TOKEN` is empty or unset, auth is disabled (backward compatible)
- Uses constant-time comparison (`hmac.compare_digest`) to prevent timing attacks

```bash
# Run with auth enabled
MCP_AUTH_TOKEN=my-secret-token \
SPOND_USERNAME=you@example.com \
SPOND_PASSWORD=your-password \
python main.py

# Test with auth
curl -X POST http://localhost:8080/mcp \
  -H "Authorization: Bearer my-secret-token" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

For Kubernetes deployments, store the token as a Secret and reference it in your service manifest:

```yaml
env:
- name: MCP_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: mcp-auth-token
      key: token
```

## Usage with mcporter

[mcporter](https://github.com/steipete/mcporter) can connect to this server as a remote MCP tool:

```bash
# List all groups
mcporter call spond.list_groups

# Get this week's events for a specific kid
mcporter call spond.get_upcoming_events kid_name=Oliver days=7

# Check what needs a response
mcporter call spond.get_attendance kid_name=Oliver

# Accept a match
mcporter call spond.respond_to_event event_id=ABC123 kid_name=Oliver accept=true

# Search for upcoming matches
mcporter call spond.search_events query=kamp days=30
```

For authenticated servers, configure mcporter with the Authorization header in `~/.mcporter/mcporter.json`:

```json
{
  "mcpServers": {
    "spond": {
      "url": "https://your-spond-mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-token-here"
      }
    }
  }
}
```

## Architecture

```text
MCP Client (mcporter, Claude, etc.)
    │ Streamable HTTP (JSON-RPC)
    ▼
spond-mcp (:8080)
    │
    └── api.spond.com (Spond API)
```

- Implements the [Model Context Protocol](https://modelcontextprotocol.io/) over Streamable HTTP
- Uses [mcp](https://pypi.org/project/mcp/) SDK in stateless mode: each request stands alone, with no server-side session
- Uses [spond](https://github.com/Olen/Spond) library for API access
- Stateless — all caching is in-memory with configurable TTLs

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (87 tests, including auth middleware tests)
pytest -v

# Lint
ruff check .
```

## Homelab Deployment

This server is designed to run on Knative with scale-to-zero. See [knative-service.yaml](config/knative-service.yaml) and [.mise.toml](.mise.toml) for deployment tasks.

Authentication is enabled via `MCP_AUTH_TOKEN` from a K8s Secret (`mcp-auth-token` in `mcp` namespace).

```bash
# Build and deploy (requires mise + Docker + kubectl)
mise run full-deploy

# Integration test against deployed service (auto-fetches auth token from K8s)
mise run test:mcp
```

## Data Source

- **Spond API** via [Olen/Spond](https://github.com/Olen/Spond) — unofficial Python wrapper for the Spond mobile app API

## License

MIT
