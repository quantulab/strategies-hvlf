"""Scanner tools: read IB scanner results from shared CSV files.

The scanner directory path is NOT hardcoded. It must be provided via:
1. The `path` parameter on each tool call (instruction-driven — the strategy
   instruction file specifies which scanner folder to read)
2. The IB_SCANNER_PATH environment variable / .env config (fallback)

This allows different strategies to read from different scanner directories.
"""

import json
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import Context

from ib_mcp.server import mcp


def _get_scanner_base(path: str) -> Path:
    """Resolve the scanner base directory from the given path or config.

    Args:
        path: Explicit path from caller, or empty to use config fallback.

    Returns:
        Path object for the scanner base directory.

    Raises:
        ValueError: If no path is configured.
    """
    if path:
        return Path(path)

    # Fallback: read from config
    from ib_mcp.config import IBConfig
    config = IBConfig()
    if config.scanner_path:
        return Path(config.scanner_path)

    raise ValueError(
        "No scanner path provided. Pass `path` parameter "
        "(e.g. path='//Station001/DATA/hvlf/rotating') "
        "or set IB_SCANNER_PATH in .env"
    )


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


def _read_latest(base: Path, date: str, scanner_name: str, top_n: int) -> dict:
    """Read the latest line from a scanner CSV file.

    Tries {scanner_name}_Scanner.csv in the date folder.
    """
    path = base / date / f"{scanner_name}_Scanner.csv"
    if not path.exists():
        return {"scanner": scanner_name, "error": f"File not found: {path}"}

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


def _discover_scanners(base: Path, date: str) -> list[str]:
    """Discover available scanner names from CSV files in the date folder."""
    date_dir = base / date
    if not date_dir.exists():
        return []

    names = []
    for f in sorted(date_dir.iterdir()):
        if f.is_file() and f.name.endswith("_Scanner.csv"):
            # Strip "_Scanner.csv" suffix to get scanner name
            name = f.name[: -len("_Scanner.csv")]
            names.append(name)
    return names


@mcp.tool()
async def get_scanner_results(
    scanner: str = "all",
    date: str = "",
    top_n: int = 20,
    path: str = "",
    ctx: Context = None,
) -> str:
    """Get latest scanner results (top movers, gainers, losers, volume leaders).

    The scanner directory is specified by the `path` parameter — read this from
    the strategy instruction file's "Data Sources > Scanners" field.

    Args:
        scanner: Scanner name or "all". The name matches the CSV filename prefix.
            For rotating folders: "LargeCap-TopGainers", "MidCap-HotByVolume", etc.
            For legacy folders: "GainSinceOpenLarge", "PctGainSmall", etc.
            Use "all" to read every scanner CSV in the date folder.
        date: Date folder in YYYYMMDD format (default: today)
        top_n: Number of top symbols to return per scanner (default 20)
        path: Scanner base directory path, e.g. "//Station001/DATA/hvlf/rotating".
            Read this from the strategy instruction file. Falls back to
            IB_SCANNER_PATH env var if not provided.
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    try:
        base = _get_scanner_base(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    if scanner.lower() == "all":
        scanner_names = _discover_scanners(base, date)
        if not scanner_names:
            return json.dumps({
                "error": f"No scanner data found in {base / date}",
                "path": str(base),
                "date": date,
            })
        results = [_read_latest(base, date, name, top_n) for name in scanner_names]
        # Filter out errors for cleaner output
        results = [r for r in results if "error" not in r]
    else:
        # Try exact match first
        scanner_names = _discover_scanners(base, date)
        matched = [s for s in scanner_names if s.lower() == scanner.lower()]
        if matched:
            results = [_read_latest(base, date, matched[0], top_n)]
        elif scanner_names:
            return json.dumps({
                "error": f"Unknown scanner '{scanner}'",
                "available": scanner_names,
                "path": str(base),
            })
        else:
            # No discovery possible, try direct file access
            results = [_read_latest(base, date, scanner, top_n)]

    return json.dumps(results, indent=2)


@mcp.tool()
async def get_scanner_dates(
    path: str = "",
    ctx: Context = None,
) -> str:
    """List available scanner date folders.

    Returns the most recent 30 dates that have scanner data.

    Args:
        path: Scanner base directory path. Read from strategy instruction file.
            Falls back to IB_SCANNER_PATH env var if not provided.
    """
    try:
        base = _get_scanner_base(path)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    if not base.exists():
        return json.dumps({"error": f"Scanner base path not found: {base}"})

    dates = sorted(
        [d.name for d in base.iterdir() if d.is_dir() and d.name.isdigit()],
        reverse=True,
    )
    return json.dumps(dates[:30], indent=2)
