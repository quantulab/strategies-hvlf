import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from ib_insync import IB

from ib_mcp.config import IBConfig

log = logging.getLogger(__name__)

MAX_RETRIES = 5
INITIAL_BACKOFF_S = 2


@dataclass
class IBContext:
    ib: IB
    config: IBConfig
    _reconnect_task: asyncio.Task | None = field(default=None, repr=False)
    _shutting_down: bool = field(default=False, repr=False)

    async def auto_reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff. Returns True on success."""
        if self._shutting_down:
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            backoff = INITIAL_BACKOFF_S * (2 ** (attempt - 1))
            try:
                log.info("Auto-reconnect attempt %d/%d...", attempt, MAX_RETRIES)
                await self.ib.connectAsync(
                    host=self.config.host,
                    port=self.config.port,
                    clientId=self.config.client_id,
                    readonly=self.config.readonly,
                    timeout=min(backoff * 2, 30),
                )
                log.info("Auto-reconnect succeeded on attempt %d", attempt)
                return True
            except Exception as e:
                log.warning(
                    "Auto-reconnect attempt %d/%d failed: %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(backoff)

        log.error("Auto-reconnect failed after %d attempts", MAX_RETRIES)
        return False


def _on_disconnect(ctx: IBContext):
    """Callback fired when IB connection drops unexpectedly."""
    if ctx._shutting_down:
        return
    log.warning("IB connection lost — scheduling auto-reconnect...")
    loop = asyncio.get_event_loop()
    if ctx._reconnect_task is None or ctx._reconnect_task.done():
        ctx._reconnect_task = loop.create_task(ctx.auto_reconnect())


@asynccontextmanager
async def ib_lifespan(server):
    """FastMCP lifespan: connect to IB on startup, disconnect on shutdown.

    Registers a disconnect handler for automatic reconnection with
    exponential backoff (2s, 4s, 8s, 16s, 32s).
    """
    config = IBConfig()
    ib = IB()
    await ib.connectAsync(
        host=config.host,
        port=config.port,
        clientId=config.client_id,
        readonly=config.readonly,
    )

    ctx = IBContext(ib=ib, config=config)

    # Register auto-reconnect on unexpected disconnects
    ib.disconnectedEvent += lambda: _on_disconnect(ctx)

    try:
        yield ctx
    finally:
        ctx._shutting_down = True
        if ctx._reconnect_task and not ctx._reconnect_task.done():
            ctx._reconnect_task.cancel()
        ib.disconnect()
