from contextlib import asynccontextmanager
from dataclasses import dataclass

from ib_insync import IB

from ib_mcp.config import IBConfig


@dataclass
class IBContext:
    ib: IB
    config: IBConfig


@asynccontextmanager
async def ib_lifespan(server):
    """FastMCP lifespan: connect to IB on startup, disconnect on shutdown."""
    config = IBConfig()
    ib = IB()
    await ib.connectAsync(
        host=config.host,
        port=config.port,
        clientId=config.client_id,
        readonly=config.readonly,
    )
    try:
        yield IBContext(ib=ib, config=config)
    finally:
        ib.disconnect()
