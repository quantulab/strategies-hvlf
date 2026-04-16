"""System tools: connection health check and reconnection."""

import asyncio
import json
import logging
from datetime import datetime

from mcp.server.fastmcp import Context

from ib_mcp.connection import IBContext
from ib_mcp.server import mcp

log = logging.getLogger(__name__)

MAX_RETRIES = 5
INITIAL_BACKOFF_S = 2


def _get_ctx(ctx: Context) -> IBContext:
    return ctx.request_context.lifespan_context


async def _try_reconnect(ib, config, max_retries: int = MAX_RETRIES) -> dict:
    """Attempt to reconnect with exponential backoff.

    Returns a dict with connection result and attempt details.
    """
    if ib.isConnected():
        ib.disconnect()

    attempts = []
    for attempt in range(1, max_retries + 1):
        backoff = INITIAL_BACKOFF_S * (2 ** (attempt - 1))  # 2, 4, 8, 16, 32s
        try:
            await ib.connectAsync(
                host=config.host,
                port=config.port,
                clientId=config.client_id,
                readonly=config.readonly,
                timeout=min(backoff * 2, 30),
            )
            attempts.append({"attempt": attempt, "status": "connected"})
            log.info("IB reconnected on attempt %d", attempt)
            return {
                "connected": True,
                "attempts": attempts,
                "serverVersion": ib.client.serverVersion(),
                "managedAccounts": ib.managedAccounts(),
            }
        except Exception as e:
            attempts.append({
                "attempt": attempt,
                "status": "failed",
                "error": str(e),
                "next_retry_s": backoff if attempt < max_retries else None,
            })
            log.warning(
                "IB reconnect attempt %d/%d failed: %s. Retrying in %ds...",
                attempt, max_retries, e, backoff,
            )
            if attempt < max_retries:
                await asyncio.sleep(backoff)

    log.error("IB reconnect failed after %d attempts", max_retries)
    return {"connected": False, "attempts": attempts}


@mcp.tool()
async def get_connection_status(ctx: Context = None) -> str:
    """Check IB connection health: connected status, server version, account, config."""
    ib_ctx = _get_ctx(ctx)
    ib = ib_ctx.ib
    config = ib_ctx.config

    result = {
        "connected": ib.isConnected(),
        "serverVersion": ib.client.serverVersion() if ib.isConnected() else None,
        "connectionTime": (
            datetime.fromtimestamp(
                ib.client.connectionStats().startTime
            ).isoformat()
            if ib.isConnected()
            else None
        ),
        "managedAccounts": ib.managedAccounts() if ib.isConnected() else [],
        "host": config.host,
        "port": config.port,
        "clientId": config.client_id,
        "readonly": config.readonly,
    }

    return json.dumps(result, indent=2)


@mcp.tool()
async def reconnect(ctx: Context = None) -> str:
    """Force reconnection to IB TWS/Gateway with automatic retry and exponential backoff.

    Tries up to 5 times with backoff: 2s, 4s, 8s, 16s, 32s between attempts.
    """
    ib_ctx = _get_ctx(ctx)
    was_connected = ib_ctx.ib.isConnected()

    result = await _try_reconnect(ib_ctx.ib, ib_ctx.config)
    result["previouslyConnected"] = was_connected

    return json.dumps(result, indent=2)


@mcp.tool()
async def ensure_connected(ctx: Context = None) -> str:
    """Check connection and auto-reconnect if disconnected.

    Use this at the start of any workflow to guarantee a live connection.
    Returns immediately if already connected; retries with backoff if not.
    """
    ib_ctx = _get_ctx(ctx)
    ib = ib_ctx.ib

    if ib.isConnected():
        return json.dumps({
            "connected": True,
            "action": "already_connected",
            "serverVersion": ib.client.serverVersion(),
        }, indent=2)

    log.info("IB disconnected — attempting auto-reconnect...")
    result = await _try_reconnect(ib, ib_ctx.config)
    result["action"] = "reconnected" if result["connected"] else "reconnect_failed"

    return json.dumps(result, indent=2)
