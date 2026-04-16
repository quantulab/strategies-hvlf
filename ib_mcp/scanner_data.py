r"""Scanner data parser for \\Station001\DATA\hvlf\rotating directory.

Provides structured access to scanner CSV data for ML model consumption.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_scanner_base() -> Path:
    """Get scanner base path from config, falling back to default."""
    from ib_mcp.config import IBConfig
    config = IBConfig()
    if config.scanner_path:
        return Path(config.scanner_path)
    return Path("//Station001/DATA/hvlf/rotating")  # legacy default


SCANNER_BASE_ROTATING = _get_scanner_base()

# All scanner types in the rotating directory
SCANNER_TYPES = [
    "GainSinceOpen", "HighOpenGap", "HotByPrice", "HotByPriceRange",
    "HotByVolume", "LossSinceOpen", "LowOpenGap", "MostActive",
    "TopGainers", "TopLosers", "TopVolumeRate",
]

CAP_TIERS = ["LargeCap", "MidCap", "SmallCap"]


def _parse_line(line: str) -> dict:
    """Parse a scanner CSV line: timestamp,0:SYM_STK,1:SYM_STK,..."""
    parts = line.strip().split(",")
    if not parts:
        return {}
    timestamp = parts[0]
    symbols = []
    for entry in parts[1:]:
        rank_sym = entry.split(":")
        if len(rank_sym) == 2:
            rank = int(rank_sym[0])
            sym = rank_sym[1].replace("_STK", "").strip()
            if sym:
                symbols.append({"rank": rank, "symbol": sym})
    return {"timestamp": timestamp, "symbols": symbols}


def load_scanner_file(
    date: str,
    cap_tier: str,
    scanner_type: str,
    last_n: int = 0,
) -> list[dict]:
    """Load all lines from a specific scanner CSV file.

    Args:
        date: YYYYMMDD format
        cap_tier: "LargeCap", "MidCap", or "SmallCap"
        scanner_type: e.g. "GainSinceOpen", "HotByVolume"
        last_n: If > 0, return only the last N lines

    Returns:
        List of parsed line dicts with timestamp and symbols
    """
    filename = f"{cap_tier}-{scanner_type}_Scanner.csv"
    path = SCANNER_BASE_ROTATING / date / filename
    if not path.exists():
        return []

    lines = []
    with open(path, "r") as f:
        for line in f:
            if line.strip():
                lines.append(_parse_line(line))

    if last_n > 0:
        return lines[-last_n:]
    return lines


def load_scanner_snapshot(date: str = "", top_n: int = 20) -> list[dict]:
    """Load the latest snapshot from ALL scanners for a given date.

    Args:
        date: YYYYMMDD format (default: today)
        top_n: Number of top symbols per scanner

    Returns:
        List of dicts, one per scanner, with latest timestamp and symbols
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    results = []
    date_dir = SCANNER_BASE_ROTATING / date
    if not date_dir.exists():
        return []

    for cap_tier in CAP_TIERS:
        for scanner_type in SCANNER_TYPES:
            lines = load_scanner_file(date, cap_tier, scanner_type, last_n=1)
            if lines:
                entry = lines[0]
                entry["scanner"] = f"{cap_tier}-{scanner_type}"
                entry["cap_tier"] = cap_tier
                entry["scanner_type"] = scanner_type
                if top_n:
                    entry["symbols"] = entry["symbols"][:top_n]
                results.append(entry)

    return results


def get_symbol_rank_history(
    symbol: str,
    scanner: str = "LargeCap-GainSinceOpen",
    date: str = "",
) -> list[int]:
    """Get a symbol's rank over time on a specific scanner for today.

    Args:
        symbol: Ticker symbol (e.g. "NVDA")
        scanner: Scanner in format "CapTier-ScannerType" (e.g. "LargeCap-GainSinceOpen")
        date: YYYYMMDD format (default: today)

    Returns:
        List of rank positions over time. 51 = not on scanner.
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    parts = scanner.split("-", 1)
    if len(parts) != 2:
        return []

    cap_tier, scanner_type = parts
    lines = load_scanner_file(date, cap_tier, scanner_type)

    ranks = []
    for line in lines:
        found = False
        for s in line.get("symbols", []):
            if s["symbol"] == symbol:
                ranks.append(s["rank"])
                found = True
                break
        if not found:
            ranks.append(51)  # Not on scanner

    return ranks


def get_symbol_cross_scanner_presence(
    symbol: str,
    date: str = "",
) -> dict:
    """Check which scanners a symbol currently appears on.

    Args:
        symbol: Ticker symbol
        date: YYYYMMDD format (default: today)

    Returns:
        Dict with scanner appearances, rank on each, and counts
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")

    appearances = []
    for cap_tier in CAP_TIERS:
        for scanner_type in SCANNER_TYPES:
            lines = load_scanner_file(date, cap_tier, scanner_type, last_n=1)
            if lines:
                for s in lines[0].get("symbols", []):
                    if s["symbol"] == symbol:
                        appearances.append({
                            "scanner": f"{cap_tier}-{scanner_type}",
                            "cap_tier": cap_tier,
                            "scanner_type": scanner_type,
                            "rank": s["rank"],
                        })
                        break

    gainer_scanners = [a for a in appearances if a["scanner_type"] in ("GainSinceOpen", "TopGainers", "HighOpenGap")]
    loser_scanners = [a for a in appearances if a["scanner_type"] in ("LossSinceOpen", "TopLosers", "LowOpenGap")]
    volume_scanners = [a for a in appearances if a["scanner_type"] in ("HotByVolume", "TopVolumeRate", "MostActive")]

    return {
        "symbol": symbol,
        "total_scanners": len(appearances),
        "gainer_count": len(gainer_scanners),
        "loser_count": len(loser_scanners),
        "volume_count": len(volume_scanners),
        "appearances": appearances,
        "on_gainer": len(gainer_scanners) > 0,
        "on_loser": len(loser_scanners) > 0,
        "on_volume": len(volume_scanners) > 0,
        "conflict": len(gainer_scanners) > 0 and len(loser_scanners) > 0,
    }


def generate_scanner_summary(date: str = "") -> str:
    """Generate a natural language summary of current scanner state.

    Used as input for regime classification and scenario matching.

    Args:
        date: YYYYMMDD format (default: today)
    """
    snapshot = load_scanner_snapshot(date, top_n=10)
    if not snapshot:
        return "No scanner data available."

    gainer_symbols = set()
    loser_symbols = set()
    volume_symbols = set()
    parts = []

    for scanner in snapshot:
        stype = scanner.get("scanner_type", "")
        cap = scanner.get("cap_tier", "")
        syms = [s["symbol"] for s in scanner.get("symbols", [])[:5]]

        if stype in ("GainSinceOpen", "TopGainers"):
            gainer_symbols.update(syms)
        elif stype in ("LossSinceOpen", "TopLosers"):
            loser_symbols.update(syms)
        elif stype in ("HotByVolume", "MostActive", "TopVolumeRate"):
            volume_symbols.update(syms)

    # Build summary
    if gainer_symbols:
        parts.append(f"Top gainers: {', '.join(list(gainer_symbols)[:10])}")
    if loser_symbols:
        parts.append(f"Top losers: {', '.join(list(loser_symbols)[:10])}")
    if volume_symbols:
        parts.append(f"Volume leaders: {', '.join(list(volume_symbols)[:10])}")

    ratio = len(gainer_symbols) / max(len(loser_symbols), 1)
    parts.append(f"Bull/bear ratio: {ratio:.1f}")

    overlap = gainer_symbols & volume_symbols
    if overlap:
        parts.append(f"Volume confirming gains: {', '.join(list(overlap)[:5])}")

    total_scanners = len(snapshot)
    parts.append(f"Active scanners: {total_scanners}")

    return ". ".join(parts)
