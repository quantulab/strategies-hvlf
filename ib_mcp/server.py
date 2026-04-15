from mcp.server.fastmcp import FastMCP

from ib_mcp.connection import ib_lifespan

mcp = FastMCP("ib-mcp", lifespan=ib_lifespan)

# Import tool modules to register them on the mcp instance
import ib_mcp.tools.account  # noqa: F401, E402
import ib_mcp.tools.market_data  # noqa: F401, E402
import ib_mcp.tools.news  # noqa: F401, E402
import ib_mcp.tools.orders  # noqa: F401, E402
import ib_mcp.tools.research  # noqa: F401, E402
import ib_mcp.tools.scanners  # noqa: F401, E402
import ib_mcp.tools.system  # noqa: F401, E402
import ib_mcp.tools.trading_log  # noqa: F401, E402
import ib_mcp.tools.models  # noqa: F401, E402


def main():
    mcp.run(transport="stdio")
