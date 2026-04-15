"""Scanner tools: read IB scanner results from shared CSV files."""

import json
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import Context

from ib_mcp.server import mcp

SCANNER_BASE = Path("//Station001/DATA/hvlf/scanner-monitor")

SCANNER_NAMES = [
    "GainSinceOpenLarge",
    "GainSinceOpenSmall",
    "HotByVolumeLarge",
    "HotByVolumeSmall",
    "LossSinceOpenLarge",
    "LossSinceOpenSmall",
    "PctGainLarge",
    "PctGainSmall",
    "PctLossLarge",
    "PctLossSmall",
]


def _parse_scanner_line(line: str) -> dict:
    """Parse a scanner CSV line into timestamp + ranked symbols."""
    parts = line.strip().split(",")
    timestamp = parts[0]
    symbols = []
    for entry in parts[1:]:
        # Format: "0:AAPL_STK"
        rank_sym = entry.split(":")
        if len(rank_sym) == 2:
            rank = int(rank_sym[0])
            sym_parts = rank_sym[1].split("_")
            symbol = sym_parts[0]
            sec_type = sym_parts[1] if len(sym_parts) > 1 else "STK"
            symbols.append({"rank": rank, "symbol": symbol, "secType": sec_type})
    return {"timestamp": timestamp, "symbols": symbols}


def _read_latest(scanner_name: str, date: str, top_n: int) -> dict:
    """Read the latest line from a scanner CSV file."""
    path = SCANNER_BASE / date / f"{scanner_name}_Scanner.csv"
    if not path.exists():
        return {"scanner": scanner_name, "error": f"File not found: {path}"}

    # Read last line efficiently
    last_line = ""
    with open(path, "r") as f:
        for line in f:
            if line.strip():
                last_line = line

    if not last_line:
        return {"scanner": scanner_name, "error": "Empty file"}

    parsed = _parse_scanner_line(last_line)
    if top_n:
        parsed["symbols"] = parsed["symbols"][:top_n]
    return {"scanner": scanner_name, **parsed}


@mcp.tool()
async def get_scanner_results(
    scanner: str = "all",
    date: str = "",
    top_n: int = 20,
    ctx: Context = None,
) -> str:
    """Get latest scanner results (top movers, gainers, losers, volume leaders).

    Args:
        scanner: Scanner name or "all". Options: GainSinceOpenLarge, HotByVolumeLarge,
            HotByVolumeSmall, LossSinceOpenLarge, PctGainLarge, PctGainSmall,
            PctLossLarge, PctLossSmall
        date: Date folder in YYYYMMDD format (default: today)
        top_n: Number of top symbols to return (default 20)
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    if scanner.lower() == "all":
        results = [_read_latest(name, date, top_n) for name in SCANNER_NAMES]
    else:
        # Match case-insensitively
        matched = [s for s in SCANNER_NAMES if s.lower() == scanner.lower()]
        if not matched:
            return f"Unknown scanner '{scanner}'. Available: {', '.join(SCANNER_NAMES)}"
        results = [_read_latest(matched[0], date, top_n)]

    return json.dumps(results, indent=2)


@mcp.tool()
async def get_scanner_dates(ctx: Context = None) -> str:
    """List available scanner date folders.

    Returns the most recent 30 dates that have scanner data.
    """
    if not SCANNER_BASE.exists():
        return f"Scanner base path not found: {SCANNER_BASE}"

    dates = sorted(
        [d.name for d in SCANNER_BASE.iterdir() if d.is_dir() and d.name.isdigit()],
        reverse=True,
    )
    return json.dumps(dates[:30], indent=2)
