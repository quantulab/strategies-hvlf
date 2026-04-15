"""Full multi-strategy scanner cycle. Run with: uv run python run_scan.py"""

import json
import sqlite3
import traceback
from pathlib import Path
from collections import defaultdict
from datetime import datetime

DB = Path(__file__).resolve().parent / "trading.db"
SCANNER_BASE = Path("//Station001/DATA/hvlf/scanner-monitor")
NOW = datetime.now()
DATE = NOW.strftime("%Y%m%d")

GAIN_SET = {"GainSinceOpenLarge", "GainSinceOpenSmall", "PctGainLarge", "PctGainSmall"}
LOSS_SET = {"LossSinceOpenLarge", "LossSinceOpenSmall", "PctLossLarge", "PctLossSmall"}
VOL_SET = {"HotByVolumeLarge", "HotByVolumeSmall"}
ALL_SCANNERS = sorted(GAIN_SET | LOSS_SET | VOL_SET)

# --- Quality gate constants ---
MIN_PRICE = 2.00           # Reject sub-$2 stocks (25% win rate on sub-$1)
MIN_AVG_VOLUME = 50_000    # Reject illiquid names
MAX_SPREAD_PCT = 0.03      # Reject if bid-ask spread > 3%
MIN_SCORE = 5              # Tier1 only (was 3/Tier2)
MAX_POSITIONS = 10         # Was 15 — forces selectivity
WARRANT_SUFFIXES = {"R", "W", "WS", "U"}  # Exclude warrants/units/rights


def db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def is_warrant(sym: str) -> bool:
    """Check if symbol looks like a warrant/unit/right by suffix."""
    upper = sym.upper()
    for suffix in WARRANT_SUFFIXES:
        if len(upper) > len(suffix) and upper.endswith(suffix):
            # Make sure we're not matching common tickers (e.g. "W" the stock)
            base = upper[:-len(suffix)]
            if base and base[-1].isalpha():
                return True
    return False


def log_error(strategy_id, step, symbol, error_type, error_msg, context=""):
    try:
        conn = db()
        conn.execute(
            "INSERT INTO errors (timestamp,strategy_id,step,symbol,error_type,error_message,context) "
            "VALUES (?,?,?,?,?,?,?)",
            (NOW.isoformat(), strategy_id, step, symbol, error_type, error_msg, context),
        )
        conn.commit()
        conn.close()
    except Exception:
        print(f"  FAILED to log error: {error_type}: {error_msg}")


def parse_line(line):
    parts = line.strip().split(",")
    syms = {}
    for e in parts[1:]:
        rk = e.split(":")
        if len(rk) == 2:
            syms[rk[1].split("_")[0]] = int(rk[0])
    return parts[0], syms


def run():
    print("=" * 70)
    print(f"MULTI-STRATEGY SCAN — {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ===== STEP 1: Scan all scanner files =====
    print("\n[STEP 1] Scanning all scanner files...")
    scanner_data = {}
    current_top10 = {}
    sym_scanners = defaultdict(set)

    for s in ALL_SCANNERS:
        try:
            p = SCANNER_BASE / DATE / f"{s}_Scanner.csv"
            if not p.exists():
                log_error("", "scan", "", "FileNotFound", f"{p} not found")
                continue
            lines = p.read_text().strip().split("\n")
            scanner_data[s] = lines
            _, syms = parse_line(lines[-1])
            current_top10[s] = {sym for sym, rank in syms.items() if rank < 10}
            for sym in current_top10[s]:
                sym_scanners[sym].add(s)
        except Exception as e:
            log_error("", "scan", "", type(e).__name__, str(e), s)
            print(f"  ERROR scanning {s}: {e}")

    print(f"  Loaded {len(scanner_data)} scanners, {len(sym_scanners)} unique symbols in top-10")

    # ===== STEP 2: Trending analysis + conviction scoring =====
    print("\n[STEP 2] Analyzing trends and scoring...")
    trending = []
    for s, lines in scanner_data.items():
        try:
            recent = lines[-20:] if len(lines) >= 20 else lines
            rank_history = defaultdict(list)
            for line in recent:
                _, syms = parse_line(line)
                for sym, rank in syms.items():
                    rank_history[sym].append(rank)
            _, latest = parse_line(lines[-1])
            for sym, rank in latest.items():
                if rank > 9:
                    continue
                if is_warrant(sym):
                    continue
                h = rank_history.get(sym, [])
                if len(h) < 3:
                    continue
                mid = len(h) // 2
                f_avg = sum(h[:mid]) / mid
                s_avg = sum(h[mid:]) / (len(h) - mid)
                if s_avg >= f_avg:
                    continue

                all_s = sym_scanners.get(sym, set())
                score = 0
                for sc in all_s:
                    if sc in {"PctGainLarge", "PctGainSmall"}:
                        score += 2
                    elif sc in VOL_SET:
                        score += 2
                    elif sc in {"GainSinceOpenLarge", "GainSinceOpenSmall"}:
                        score += 1
                    if sc in LOSS_SET:
                        score -= 2
                on_gain = bool(all_s & GAIN_SET)
                on_loss = bool(all_s & LOSS_SET)
                on_vol = bool(all_s & VOL_SET)
                if on_gain and on_loss:
                    score -= 1

                if s in GAIN_SET:
                    action = "BUY"
                elif s in VOL_SET:
                    action = "SELL" if on_loss else "BUY"
                else:
                    action = "SELL"

                rejected = False
                reject_reason = ""
                conflict = "NONE"
                if on_gain and on_loss and on_vol:
                    conflict = "RED"
                    rejected = True
                    reject_reason = "RED: gain+loss+vol conflict"
                elif on_gain and on_loss:
                    conflict = "ORANGE"
                    rejected = True
                    reject_reason = "ORANGE: gain+loss conflict"
                elif on_gain and on_vol:
                    conflict = "YELLOW"

                if score >= MIN_SCORE:
                    tier = "Tier1"
                elif score >= 3:
                    tier = "Tier2"
                elif score >= 1:
                    tier = "Tier3"
                else:
                    tier = "Blacklist"

                if tier != "Tier1" and not rejected:
                    rejected = True
                    reject_reason = f"Score {score} below Tier1 (need {MIN_SCORE}+)"

                trending.append(
                    dict(
                        symbol=sym, scanner=s, rank=rank, trend=h,
                        improving=round(f_avg - s_avg, 1), action=action,
                        score=score, tier=tier, scanners=",".join(sorted(all_s)),
                        conflict=conflict, rejected=rejected, reject_reason=reject_reason,
                    )
                )
        except Exception as e:
            log_error("S09", "scoring", "", type(e).__name__, str(e), s)
            print(f"  ERROR scoring {s}: {e}")

    # Dedup by symbol
    seen = {}
    for t in trending:
        sym = t["symbol"]
        if sym not in seen or t["score"] > seen[sym]["score"]:
            seen[sym] = t
    candidates = sorted(seen.values(), key=lambda x: (-x["score"], -x["improving"]))
    tradeable = [c for c in candidates if not c["rejected"]]
    rejected_list = [c for c in candidates if c["rejected"]]

    print(f"  Total: {len(candidates)} | Tradeable: {len(tradeable)} | Rejected: {len(rejected_list)}")
    for t in tradeable:
        print(f"  + {t['symbol']:8s} score={t['score']:+d} {t['tier']:6s} {t['action']:4s} rank={t['rank']} scanners={t['scanners']}")
    for t in rejected_list[:5]:
        print(f"  - {t['symbol']:8s} score={t['score']:+d} {t['tier']:9s} {t['reject_reason']}")
    if len(rejected_list) > 5:
        print(f"  ... and {len(rejected_list) - 5} more rejected")

    # ===== STEP 3: Log all picks to DB =====
    print("\n[STEP 3] Logging picks to DB...")
    conn = db()
    pick_ids = {}
    for c in candidates:
        try:
            cur = conn.execute(
                """INSERT INTO scanner_picks (timestamp,symbol,scanner,current_rank,rank_trend,improving_by,
                   reason,conviction_score,conviction_tier,scanners_present,action,rejected,reject_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    NOW.isoformat(), c["symbol"], c["scanner"], c["rank"],
                    ",".join(str(r) for r in c["trend"]), c["improving"],
                    f"{c['tier']} {c['action']}: rank {c['rank']}, score {c['score']}, conflict={c['conflict']}",
                    c["score"], c["tier"], c["scanners"], c["action"],
                    1 if c["rejected"] else 0, c["reject_reason"],
                ),
            )
            pick_ids[c["symbol"]] = cur.lastrowid
        except Exception as e:
            log_error("S09", "log_pick", c["symbol"], type(e).__name__, str(e))
    conn.commit()
    conn.close()
    print(f"  Logged {len(pick_ids)} picks")

    # ===== STEP 6: Log the run =====
    print("\n[STEP 6] Logging strategy run...")
    try:
        conn = db()
        conn.execute(
            """INSERT INTO strategy_runs (timestamp,strategy_id,strategy_name,candidates_found,
               candidates_rejected,orders_placed,positions_open,positions_closed_this_run,
               total_unrealized_pnl,total_realized_pnl,summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                NOW.isoformat(), "S09", "Multi-Scanner Conviction",
                len(candidates), len(rejected_list), 0, 0, 0, 0, 0,
                f"Scan: {len(candidates)} candidates, {len(tradeable)} tradeable, "
                f"{len(rejected_list)} rejected. "
                f"Tradeable: {', '.join(t['symbol'] for t in tradeable) or 'none'}",
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log_error("S09", "log_run", "", type(e).__name__, str(e))

    # ===== STEP 7: Summary =====
    red_count = sum(1 for c in candidates if c["conflict"] == "RED")
    orange_count = sum(1 for c in candidates if c["conflict"] == "ORANGE")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"| {'Strategy':<22} | {'Found':>5} | {'Trade':>5} | {'Reject':>6} | Action")
    print(f"|{'-' * 24}|{'-' * 7}|{'-' * 7}|{'-' * 8}|--------")
    print(f"| S09 Conviction        | {len(candidates):>5} | {len(tradeable):>5} | {len(rejected_list):>6} | {len(tradeable)} signals")
    print(f"| S07 Conflict Filter   |     - |     - |      - | {red_count} RED, {orange_count} ORANGE vetoes")
    print(f"| S04 Cut Losers        |     - |     - |      - | check via IB")
    print(f"| S11 Quantum           |     - |     - |      - | monitor IONX/IONL/QUBX")
    print("=" * 70)

    # Error count
    conn = db()
    errs = conn.execute("SELECT COUNT(*) as c FROM errors WHERE timestamp >= ?",
                        (NOW.strftime("%Y-%m-%d"),)).fetchone()
    conn.close()
    print(f"\nErrors today: {errs['c']}")
    print("Done.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log_error("MAIN", "run", "", type(e).__name__, str(e), traceback.format_exc())
        print(f"FATAL: {e}")
        traceback.print_exc()
