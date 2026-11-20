"""Spond MCP server entry point — Starlette app with health, settings and Streamable HTTP endpoints.

The gateway contract (https://github.com/Olsenius/mcp-gateway):

  POST /mcp                Streamable HTTP MCP, Bearer MCP_AUTH_TOKEN
  GET  /healthz            liveness, no auth
  GET  /healthz?check=1    logs in to Spond with the current settings, Bearer CONFIG_TOKEN
  GET  /config             settings schema and values (never secrets), Bearer CONFIG_TOKEN
  POST /config             {"values": {"ENV_NAME": "value"}, "clear": ["ENV_NAME"]}

CONFIG_TOKEN defaults to MCP_AUTH_TOKEN.
"""

import asyncio
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
from spond import AuthenticationError
from spond.spond import Spond
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

import telemetry
from server import TOOLS, WRITE_TOOLS, SpondService, handle_tool_call
from settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("spond-mcp")

AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
CONFIG_TOKEN = os.environ.get("CONFIG_TOKEN", "")
MAX_CONFIG_BODY = 64 * 1024
TOOL_NAMES = {t["name"] for t in TOOLS}

settings = Settings()
service: SpondService | None = None
service_lock = asyncio.Lock()
session_manager: StreamableHTTPSessionManager | None = None


def config_token() -> str:
    return CONFIG_TOKEN or AUTH_TOKEN


def needs_config_token(request: Request) -> bool:
    return request.url.path == "/config" or (request.url.path == "/healthz" and "check" in request.query_params)


def is_public(request: Request) -> bool:
    """Liveness probes need no auth; /healthz?check=1 runs real checks and does."""
    if request.url.path == "/health":
        return True
    return request.url.path == "/healthz" and "check" not in request.query_params


def authorized(request: Request, token: str) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate the Bearer token on all requests except liveness probes."""

    async def dispatch(self, request: Request, call_next):
        if is_public(request):
            return await call_next(request)
        if request.url.path == "/config" and not config_token():
            # Without a token anyone could change the account; keep the settings API off.
            return PlainTextResponse("not found", status_code=404)
        token = config_token() if needs_config_token(request) else AUTH_TOKEN
        if not token:
            return await call_next(request)
        if not authorized(request, token):
            logger.warning(
                "Unauthorized request to %s from %s",
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return PlainTextResponse("unauthorized", status_code=401)
        return await call_next(request)


def create_service() -> SpondService:
    if not settings.configured:
        logger.warning("SPOND_USERNAME/SPOND_PASSWORD not set — API calls will fail")
    client = Spond(username=settings.username, password=settings.password)
    return SpondService(client=client, kids_config=settings.kids)


def get_service() -> SpondService:
    global service
    if service is None:
        service = create_service()
    return service


async def reset_service() -> None:
    """Apply new settings without a restart: the next call logs in again."""
    global service
    async with service_lock:
        old, service = service, None
    if old is not None:
        await old.close()


# MCP server setup
mcp_server = Server("spond")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(**t) for t in TOOLS if not (settings.read_only and t["name"] in WRITE_TOOLS)]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    label = name if name in TOOL_NAMES else "unknown"
    with telemetry.span(f"tool {label}", attributes={"mcp.tool.name": label}) as current:
        if settings.read_only and name in WRITE_TOOLS:
            return [TextContent(type="text", text=f"{name} er slått av (MCP_READ_ONLY).")]
        try:
            result = await handle_tool_call(get_service(), name, arguments)
        except AuthenticationError as e:
            # The error message holds Spond's raw login response; keep it out of logs and answers.
            telemetry.mark_error(current, e)
            logger.error("Tool %s failed: Spond login failed", label)
            # The library closes its HTTP session when login fails; start over on the next call.
            await reset_service()
            result = "Feil: innlogging til Spond feilet. Sjekk SPOND_USERNAME og SPOND_PASSWORD."
        except Exception as e:
            telemetry.mark_error(current, e)
            logger.exception("Tool %s failed", label)
            result = f"Feil: {e}"
    return [TextContent(type="text", text=result)]


# HTTP handlers
class MCPEndpoint:
    """ASGI endpoint for /mcp that hands requests to the session manager."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if session_manager is None:
            raise RuntimeError("session manager is not running")
        await session_manager.handle_request(scope, receive, send)


def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


async def health(request: Request):
    return PlainTextResponse("ok")


async def healthz(request: Request):
    if "check" not in request.query_params:
        return PlainTextResponse("ok")
    checks = []
    if not settings.configured:
        checks.append({"name": "Login", "ok": False, "detail": "SPOND_USERNAME and SPOND_PASSWORD must be set"})
        status = "not configured"
    else:
        try:
            groups = await get_service().get_groups()
            checks.append({"name": "Login", "ok": True, "detail": f"logged in, {len(groups or [])} groups"})
        except Exception as e:
            # The Spond library puts the raw login response in its errors; keep it out of logs and answers.
            logger.error("Health check failed: %s", type(e).__name__)
            if isinstance(e, AuthenticationError):
                await reset_service()
            checks.append({"name": "Login", "ok": False, "detail": "could not log in to Spond"})
        status = "ok" if checks[0]["ok"] else "failing"
    ok = all(c["ok"] for c in checks)
    return no_store(JSONResponse({"ok": ok, "status": status, "checks": checks}, status_code=200 if ok else 503))


async def config(request: Request):
    if request.method == "GET":
        return no_store(JSONResponse(settings.doc()))
    body = await request.body()
    if len(body) > MAX_CONFIG_BODY:
        return no_store(JSONResponse({"error": "request body too large"}, status_code=413))
    try:
        update = json.loads(body or b"{}")
        if not isinstance(update, dict):
            raise ValueError('expected {"values": {...}, "clear": [...]}')
        settings.update(update.get("values") or {}, update.get("clear") or [])
    except json.JSONDecodeError:
        return no_store(JSONResponse({"error": "invalid JSON"}, status_code=400))
    except ValueError as e:
        return no_store(JSONResponse({"error": str(e)}, status_code=400))
    except OSError as e:
        logger.error("Could not save settings: %s", type(e).__name__)
        return no_store(JSONResponse({"error": "could not save settings"}, status_code=500))
    await reset_service()
    logger.info("settings updated via /config")
    return no_store(JSONResponse(settings.doc()))


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
            await reset_service()


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/healthz", healthz),
        Route("/config", config, methods=["GET", "POST"]),
        Route("/mcp", MCPEndpoint(), methods=["GET", "POST", "DELETE"]),
    ],
    middleware=[Middleware(telemetry.TraceHTTP), Middleware(BearerAuthMiddleware)],
    lifespan=lifespan,
)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    shutdown = telemetry.configure()
    if AUTH_TOKEN:
        logger.info("spond MCP server starting on :%d (auth enabled, read-only=%s)", port, settings.read_only)
    else:
        logger.warning("spond MCP server starting on :%d (NO AUTH — set MCP_AUTH_TOKEN)", port)
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", http="h11")
    finally:
        shutdown()
