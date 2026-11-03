"""Spond MCP server entry point — Starlette app with health + Streamable HTTP endpoints."""

import contextlib
import hmac
import json
import logging
import os
from collections.abc import AsyncIterator

import uvicorn
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from spond.spond import Spond
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from server import TOOLS, SpondService, handle_tool_call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("spond-mcp")

AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

service: SpondService | None = None
session_manager: StreamableHTTPSessionManager | None = None


def is_public(request: Request) -> bool:
    """Liveness probes need no auth; /healthz?check=1 runs real checks and does."""
    if request.url.path == "/health":
        return True
    return request.url.path == "/healthz" and "check" not in request.query_params


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token on all requests except liveness probes."""

    async def dispatch(self, request: Request, call_next):
        if is_public(request) or not AUTH_TOKEN:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], AUTH_TOKEN):
            logger.warning(
                "Unauthorized request to %s from %s",
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return PlainTextResponse("unauthorized", status_code=401)
        return await call_next(request)


def create_service() -> SpondService:
    username = os.environ.get("SPOND_USERNAME", "")
    password = os.environ.get("SPOND_PASSWORD", "")
    kids_json = os.environ.get("KIDS_CONFIG", "[]")

    if not username or not password:
        logger.warning("SPOND_USERNAME/SPOND_PASSWORD not set — API calls will fail")

    kids_config = json.loads(kids_json)
    client = Spond(username=username, password=password)
    return SpondService(client=client, kids_config=kids_config)


def get_service() -> SpondService:
    global service
    if service is None:
        service = create_service()
    return service


# MCP server setup
mcp_server = Server("spond")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(**t) for t in TOOLS]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    try:
        result = await handle_tool_call(get_service(), name, arguments)
    except Exception as e:
        logger.exception("Tool %s failed", name)
        result = f"Feil: {e}"
    return [TextContent(type="text", text=result)]


# HTTP handlers
class MCPEndpoint:
    """ASGI endpoint for /mcp that hands requests to the session manager."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if session_manager is None:
            raise RuntimeError("session manager is not running")
        await session_manager.handle_request(scope, receive, send)


async def health(request: Request):
    return PlainTextResponse("ok")


async def healthz(request: Request):
    if "check" not in request.query_params:
        return PlainTextResponse("ok")
    checks = []
    if not os.environ.get("SPOND_USERNAME") or not os.environ.get("SPOND_PASSWORD"):
        checks.append({"name": "Login", "ok": False, "detail": "SPOND_USERNAME and SPOND_PASSWORD must be set"})
    else:
        try:
            groups = await get_service().get_groups()
            checks.append({"name": "Login", "ok": True, "detail": f"logged in, {len(groups or [])} groups"})
        except Exception:
            # The Spond library puts the raw login response in its errors; keep it out of the answer.
            logger.exception("Health check failed")
            checks.append({"name": "Login", "ok": False, "detail": "could not log in to Spond"})
    ok = all(c["ok"] for c in checks)
    body = {"ok": ok, "status": "ok" if ok else "error", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)


@contextlib.asynccontextmanager
async def lifespan(app) -> AsyncIterator[None]:
    global session_manager
    # Stateless: each request stands alone, so any replica can serve it.
    session_manager = StreamableHTTPSessionManager(app=mcp_server, stateless=True, json_response=True)
    async with session_manager.run():
        try:
            yield
        finally:
            session_manager = None
            if service is not None:
                await service.close()


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/healthz", healthz),
        Route("/mcp", MCPEndpoint(), methods=["GET", "POST", "DELETE"]),
    ],
    middleware=[Middleware(BearerAuthMiddleware)],
    lifespan=lifespan,
)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    if AUTH_TOKEN:
        logger.info("spond MCP server starting on :%d (auth enabled)", port)
    else:
        logger.warning("spond MCP server starting on :%d (NO AUTH — set MCP_AUTH_TOKEN)", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", http="h11")
