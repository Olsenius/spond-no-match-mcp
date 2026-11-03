#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-https://spond.mcp.fn.flaatten.org}"
AUTH_TOKEN="${MCP_AUTH_TOKEN:-}"

AUTH_HEADER=()
if [[ -n "$AUTH_TOKEN" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer $AUTH_TOKEN")
fi

echo "=== spond MCP Service Test ==="
echo "URL: $BASE_URL"
[[ -n "$AUTH_TOKEN" ]] && echo "Auth: enabled" || echo "Auth: disabled"
echo ""

# Health check
echo -n "Health check... "
HEALTH=$(curl -sf "$BASE_URL/healthz")
[[ "$HEALTH" == "ok" ]] && echo "OK" || { echo "FAILED: $HEALTH"; exit 1; }

# The server is stateless: every request is a single POST to /mcp.
post() {
  curl -sf -X POST "$BASE_URL/mcp" \
    "${AUTH_HEADER[@]}" \
    -H "Accept: application/json, text/event-stream" \
    -H "Content-Type: application/json" -d "$1" | python3 -m json.tool
}

echo "--- Initialize ---"
post '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

echo ""
echo "--- Tools ---"
post '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

echo ""
echo "--- List Groups ---"
post '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_groups","arguments":{}}}'

echo ""
echo "--- Upcoming Events (7 days) ---"
post '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_upcoming_events","arguments":{"days":7}}}'

# Norwegian character test
echo ""
echo "--- Upcoming Events: Emma ---"
post '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_upcoming_events","arguments":{"kid_name":"Emma"}}}'

echo ""
echo "--- Search: trening ---"
post '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"search_events","arguments":{"query":"trening"}}}'

echo ""
echo "--- Attendance: Oliver ---"
post '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"get_attendance","arguments":{"kid_name":"Oliver"}}}'

echo ""
echo "=== Done ==="
echo ""
echo "To test RSVP (changes real data!), POST to $BASE_URL/mcp:"
echo "  Accept:  {\"jsonrpc\":\"2.0\",\"id\":10,\"method\":\"tools/call\",\"params\":{\"name\":\"respond_to_event\",\"arguments\":{\"event_id\":\"EVT_ID\",\"kid_name\":\"Oliver\",\"accept\":true}}}"
echo "  Decline: {\"jsonrpc\":\"2.0\",\"id\":11,\"method\":\"tools/call\",\"params\":{\"name\":\"respond_to_event\",\"arguments\":{\"event_id\":\"EVT_ID\",\"kid_name\":\"Oliver\",\"accept\":false,\"decline_message\":\"Syk\"}}}"
