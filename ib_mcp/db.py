"""SQLite database for tracking all trading activity, KPIs, and lessons."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "trading.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS scanner_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    scanner TEXT NOT NULL,
    current_rank INTEGER NOT NULL,
    rank_trend TEXT NOT NULL,
    improving_by REAL NOT NULL,
    reason TEXT NOT NULL,
    conviction_score INTEGER DEFAULT 0,
    conviction_tier TEXT DEFAULT '',
    scanners_present TEXT DEFAULT '',
    action TEXT DEFAULT 'BUY',
    rejected INTEGER DEFAULT 0,
    reject_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    scanner TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    order_type TEXT NOT NULL,
    order_id INTEGER,
    limit_price REAL,
    stop_price REAL,
    entry_price REAL,
    status TEXT,
    pick_id INTEGER REFERENCES scanner_picks(id),
    strategy_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS strategy_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    entry_order_id INTEGER,
    stop_price REAL,
    target_price REAL,
    stop_order_id INTEGER,
    target_order_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    exit_price REAL,
    exit_time TEXT,
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    hold_duration_minutes REAL,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    max_drawdown_pct REAL,
    peak_price REAL,
    trough_price REAL,
    scanners_at_entry TEXT DEFAULT '',
    conviction_score INTEGER DEFAULT 0,
    pick_id INTEGER REFERENCES scanner_picks(id)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    position_id INTEGER REFERENCES strategy_positions(id),
    bid REAL,
    ask REAL,
    last REAL,
    volume REAL,
    unrealized_pnl REAL,
    unrealized_pnl_pct REAL,
    distance_to_stop_pct REAL,
    distance_to_target_pct REAL,
    current_drawdown_pct REAL
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    candidates_found INTEGER DEFAULT 0,
    candidates_rejected INTEGER DEFAULT 0,
    orders_placed INTEGER DEFAULT 0,
    positions_open INTEGER DEFAULT 0,
    positions_closed_this_run INTEGER DEFAULT 0,
    total_unrealized_pnl REAL DEFAULT 0,
    total_realized_pnl REAL DEFAULT 0,
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    hold_duration_minutes REAL,
    max_drawdown_pct REAL,
    max_favorable_excursion REAL,
    scanner TEXT NOT NULL,
    exit_reason TEXT NOT NULL,
    lesson TEXT NOT NULL,
    pick_id INTEGER REFERENCES scanner_picks(id),
    position_id INTEGER REFERENCES strategy_positions(id)
);

CREATE TABLE IF NOT EXISTS strategy_kpis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0,
    avg_win_pct REAL DEFAULT 0,
    avg_loss_pct REAL DEFAULT 0,
    profit_factor REAL DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    max_drawdown_pct REAL DEFAULT 0,
    avg_hold_minutes REAL DEFAULT 0,
    sharpe_estimate REAL DEFAULT 0,
    expectancy REAL DEFAULT 0,
    best_trade_pnl REAL DEFAULT 0,
    worst_trade_pnl REAL DEFAULT 0,
    avg_mae REAL DEFAULT 0,
    avg_mfe REAL DEFAULT 0,
    consecutive_wins INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    candidates_found INTEGER NOT NULL,
    candidates_rejected INTEGER NOT NULL,
    orders_placed INTEGER NOT NULL,
    positions_held INTEGER NOT NULL,
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    phase_completed INTEGER DEFAULT 0,
    positions_checked INTEGER DEFAULT 0,
    losers_closed INTEGER DEFAULT 0,
    shorts_closed INTEGER DEFAULT 0,
    candidates_found INTEGER DEFAULT 0,
    candidates_rejected INTEGER DEFAULT 0,
    orders_placed INTEGER DEFAULT 0,
    positions_monitored INTEGER DEFAULT 0,
    snapshots_logged INTEGER DEFAULT 0,
    lessons_logged INTEGER DEFAULT 0,
    kpis_computed INTEGER DEFAULT 0,
    portfolio_pnl REAL,
    portfolio_pnl_pct REAL,
    error TEXT,
    summary TEXT DEFAULT ''
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLES)
    return conn


# --- Scanner Picks ---

def log_pick(
    symbol: str,
    scanner: str,
    current_rank: int,
    rank_trend: list[int],
    improving_by: float,
    reason: str,
    conviction_score: int = 0,
    conviction_tier: str = "",
    scanners_present: str = "",
    action: str = "BUY",
    rejected: bool = False,
    reject_reason: str = "",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO scanner_picks
           (timestamp, symbol, scanner, current_rank, rank_trend, improving_by,
            reason, conviction_score, conviction_tier, scanners_present,
            action, rejected, reject_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(), symbol, scanner, current_rank,
            ",".join(str(r) for r in rank_trend), improving_by, reason,
            conviction_score, conviction_tier, scanners_present,
            action, 1 if rejected else 0, reject_reason,
        ),
    )
    pick_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pick_id


# --- Orders ---

def log_order(
    symbol: str, scanner: str, action: str, quantity: float, order_type: str,
    order_id: int | None = None, limit_price: float | None = None,
    stop_price: float | None = None, entry_price: float | None = None,
    status: str | None = None, pick_id: int | None = None,
    strategy_id: str = "",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO orders
           (timestamp, symbol, scanner, action, quantity, order_type,
            order_id, limit_price, stop_price, entry_price, status, pick_id, strategy_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(), symbol, scanner, action, quantity,
            order_type, order_id, limit_price, stop_price, entry_price,
            status, pick_id, strategy_id,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# --- Strategy Positions ---

def open_position(
    strategy_id: str, symbol: str, action: str, quantity: float,
    entry_price: float, entry_order_id: int | None = None,
    stop_price: float | None = None, target_price: float | None = None,
    stop_order_id: int | None = None, target_order_id: int | None = None,
    scanners_at_entry: str = "", conviction_score: int = 0,
    pick_id: int | None = None,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO strategy_positions
           (strategy_id, symbol, action, quantity, entry_price, entry_time,
            entry_order_id, stop_price, target_price, stop_order_id, target_order_id,
            status, scanners_at_entry, conviction_score, pick_id,
            peak_price, trough_price, max_favorable_excursion, max_adverse_excursion, max_drawdown_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, 0, 0, 0)""",
        (
            strategy_id, symbol, action, quantity, entry_price,
            datetime.now().isoformat(), entry_order_id,
            stop_price, target_price, stop_order_id, target_order_id,
            scanners_at_entry, conviction_score, pick_id,
            entry_price, entry_price,
        ),
    )
    pos_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pos_id


def close_position(
    position_id: int, exit_price: float, exit_reason: str,
) -> dict:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM strategy_positions WHERE id = ?", (position_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {}

    pos = dict(row)
    entry = pos["entry_price"]
    action = pos["action"]

    if action == "BUY":
        pnl = (exit_price - entry) * pos["quantity"]
        pnl_pct = ((exit_price - entry) / entry) * 100 if entry else 0
    else:
        pnl = (entry - exit_price) * pos["quantity"]
        pnl_pct = ((entry - exit_price) / entry) * 100 if entry else 0

    entry_time = datetime.fromisoformat(pos["entry_time"])
    hold_mins = (datetime.now() - entry_time).total_seconds() / 60

    conn.execute(
        """UPDATE strategy_positions SET
           status='closed', exit_price=?, exit_time=?, exit_reason=?,
           pnl=?, pnl_pct=?, hold_duration_minutes=?
           WHERE id=?""",
        (exit_price, datetime.now().isoformat(), exit_reason,
         pnl, pnl_pct, hold_mins, position_id),
    )
    conn.commit()
    conn.close()

    pos.update(exit_price=exit_price, pnl=pnl, pnl_pct=pnl_pct,
               hold_duration_minutes=hold_mins, exit_reason=exit_reason)
    return pos


def update_position_extremes(position_id: int, current_price: float):
    """Update peak/trough/MFE/MAE/drawdown for a position."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM strategy_positions WHERE id = ?", (position_id,)
    ).fetchone()
    if not row:
        conn.close()
        return

    pos = dict(row)
    entry = pos["entry_price"]
    peak = max(pos["peak_price"] or entry, current_price)
    trough = min(pos["trough_price"] or entry, current_price)

    if pos["action"] == "BUY":
        mfe = max(pos["max_favorable_excursion"] or 0, current_price - entry)
        mae = max(pos["max_adverse_excursion"] or 0, entry - current_price)
        dd = ((peak - current_price) / peak * 100) if peak > 0 else 0
    else:
        mfe = max(pos["max_favorable_excursion"] or 0, entry - current_price)
        mae = max(pos["max_adverse_excursion"] or 0, current_price - entry)
        dd = ((current_price - trough) / trough * 100) if trough > 0 else 0

    max_dd = max(pos["max_drawdown_pct"] or 0, dd)

    conn.execute(
        """UPDATE strategy_positions SET
           peak_price=?, trough_price=?, max_favorable_excursion=?,
           max_adverse_excursion=?, max_drawdown_pct=?
           WHERE id=?""",
        (peak, trough, mfe, mae, max_dd, position_id),
    )
    conn.commit()
    conn.close()


def get_open_positions(strategy_id: str = "") -> list[dict]:
    conn = _get_conn()
    if strategy_id:
        rows = conn.execute(
            "SELECT * FROM strategy_positions WHERE status='open' AND strategy_id=?",
            (strategy_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM strategy_positions WHERE status='open'"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_closed_positions(strategy_id: str = "", limit: int = 100) -> list[dict]:
    conn = _get_conn()
    if strategy_id:
        rows = conn.execute(
            "SELECT * FROM strategy_positions WHERE status='closed' AND strategy_id=? ORDER BY id DESC LIMIT ?",
            (strategy_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM strategy_positions WHERE status='closed' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Price Snapshots ---

def log_price_snapshot(
    strategy_id: str, symbol: str, position_id: int,
    bid: float | None, ask: float | None, last: float | None,
    volume: float | None, entry_price: float,
    stop_price: float | None, target_price: float | None,
) -> int:
    unrealized = (last - entry_price) if last and entry_price else 0
    unrealized_pct = (unrealized / entry_price * 100) if entry_price else 0
    dist_stop = ((last - stop_price) / last * 100) if last and stop_price else None
    dist_target = ((target_price - last) / last * 100) if last and target_price else None

    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO price_snapshots
           (timestamp, strategy_id, symbol, position_id, bid, ask, last, volume,
            unrealized_pnl, unrealized_pnl_pct, distance_to_stop_pct, distance_to_target_pct,
            current_drawdown_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (
            datetime.now().isoformat(), strategy_id, symbol, position_id,
            bid, ask, last, volume, unrealized, unrealized_pct,
            dist_stop, dist_target,
        ),
    )
    snap_id = cur.lastrowid
    conn.commit()
    conn.close()
    return snap_id


# --- Strategy Runs ---

def log_strategy_run(
    strategy_id: str, strategy_name: str,
    candidates_found: int = 0, candidates_rejected: int = 0,
    orders_placed: int = 0, positions_open: int = 0,
    positions_closed_this_run: int = 0,
    total_unrealized_pnl: float = 0, total_realized_pnl: float = 0,
    summary: str = "",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO strategy_runs
           (timestamp, strategy_id, strategy_name, candidates_found, candidates_rejected,
            orders_placed, positions_open, positions_closed_this_run,
            total_unrealized_pnl, total_realized_pnl, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(), strategy_id, strategy_name,
            candidates_found, candidates_rejected, orders_placed,
            positions_open, positions_closed_this_run,
            total_unrealized_pnl, total_realized_pnl, summary,
        ),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


# --- KPIs ---

def compute_and_log_kpis(strategy_id: str) -> dict:
    """Compute strategy KPIs from closed positions and log them."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM strategy_positions WHERE status='closed' AND strategy_id=?",
        (strategy_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return {}

    positions = [dict(r) for r in rows]
    total = len(positions)
    winners = [p for p in positions if (p["pnl"] or 0) > 0]
    losers = [p for p in positions if (p["pnl"] or 0) <= 0]
    win_count = len(winners)
    loss_count = len(losers)
    win_rate = win_count / total if total else 0

    avg_win = sum(p["pnl_pct"] or 0 for p in winners) / win_count if win_count else 0
    avg_loss = sum(abs(p["pnl_pct"] or 0) for p in losers) / loss_count if loss_count else 0
    total_wins = sum(p["pnl"] or 0 for p in winners)
    total_losses = abs(sum(p["pnl"] or 0 for p in losers))
    profit_factor = total_wins / total_losses if total_losses else float("inf")
    total_pnl = sum(p["pnl"] or 0 for p in positions)

    max_dd = max((p["max_drawdown_pct"] or 0) for p in positions) if positions else 0
    avg_hold = sum(p["hold_duration_minutes"] or 0 for p in positions) / total if total else 0

    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    best = max((p["pnl"] or 0) for p in positions) if positions else 0
    worst = min((p["pnl"] or 0) for p in positions) if positions else 0
    avg_mae = sum(p["max_adverse_excursion"] or 0 for p in positions) / total if total else 0
    avg_mfe = sum(p["max_favorable_excursion"] or 0 for p in positions) / total if total else 0

    # Consecutive streaks
    max_consec_wins = max_consec_losses = cur_wins = cur_losses = 0
    for p in sorted(positions, key=lambda x: x["id"]):
        if (p["pnl"] or 0) > 0:
            cur_wins += 1
            cur_losses = 0
        else:
            cur_losses += 1
            cur_wins = 0
        max_consec_wins = max(max_consec_wins, cur_wins)
        max_consec_losses = max(max_consec_losses, cur_losses)

    kpis = dict(
        total_trades=total, winning_trades=win_count, losing_trades=loss_count,
        win_rate=round(win_rate, 4), avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4), profit_factor=round(profit_factor, 4),
        total_pnl=round(total_pnl, 4), max_drawdown_pct=round(max_dd, 4),
        avg_hold_minutes=round(avg_hold, 2), expectancy=round(expectancy, 4),
        best_trade_pnl=round(best, 4), worst_trade_pnl=round(worst, 4),
        avg_mae=round(avg_mae, 4), avg_mfe=round(avg_mfe, 4),
        consecutive_wins=max_consec_wins, consecutive_losses=max_consec_losses,
    )

    conn = _get_conn()
    conn.execute(
        """INSERT INTO strategy_kpis
           (timestamp, strategy_id, total_trades, winning_trades, losing_trades,
            win_rate, avg_win_pct, avg_loss_pct, profit_factor, total_pnl,
            max_drawdown_pct, avg_hold_minutes, expectancy, best_trade_pnl,
            worst_trade_pnl, avg_mae, avg_mfe, consecutive_wins, consecutive_losses)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), strategy_id, *kpis.values()),
    )
    conn.commit()
    conn.close()
    return kpis


# --- Lessons ---

def log_lesson(
    symbol: str, strategy_id: str, action: str,
    entry_price: float | None, exit_price: float | None,
    pnl: float | None, pnl_pct: float | None,
    hold_duration_minutes: float | None, max_drawdown_pct: float | None,
    max_favorable_excursion: float | None,
    scanner: str, exit_reason: str, lesson: str,
    pick_id: int | None = None, position_id: int | None = None,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO lessons
           (timestamp, symbol, strategy_id, action, entry_price, exit_price,
            pnl, pnl_pct, hold_duration_minutes, max_drawdown_pct,
            max_favorable_excursion, scanner, exit_reason, lesson, pick_id, position_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(), symbol, strategy_id, action,
            entry_price, exit_price, pnl, pnl_pct,
            hold_duration_minutes, max_drawdown_pct, max_favorable_excursion,
            scanner, exit_reason, lesson, pick_id, position_id,
        ),
    )
    lesson_id = cur.lastrowid
    conn.commit()
    conn.close()
    return lesson_id


def log_scan_run(
    candidates_found: int, candidates_rejected: int,
    orders_placed: int, positions_held: int, summary: str,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO scan_runs
           (timestamp, candidates_found, candidates_rejected, orders_placed,
            positions_held, summary)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), candidates_found, candidates_rejected,
         orders_placed, positions_held, summary),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


# --- Job Executions ---

def start_job_execution(job_id: str) -> int:
    """Record the start of a cron job execution. Returns execution ID."""
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO job_executions (job_id, started_at, status)
           VALUES (?, ?, 'running')""",
        (job_id, datetime.now().isoformat()),
    )
    exec_id = cur.lastrowid
    conn.commit()
    conn.close()
    return exec_id


def update_job_execution(
    exec_id: int,
    phase_completed: int | None = None,
    positions_checked: int | None = None,
    losers_closed: int | None = None,
    shorts_closed: int | None = None,
    candidates_found: int | None = None,
    candidates_rejected: int | None = None,
    orders_placed: int | None = None,
    positions_monitored: int | None = None,
    snapshots_logged: int | None = None,
    lessons_logged: int | None = None,
    kpis_computed: int | None = None,
    portfolio_pnl: float | None = None,
    portfolio_pnl_pct: float | None = None,
    error: str | None = None,
    summary: str | None = None,
) -> None:
    """Update a running job execution with incremental progress."""
    conn = _get_conn()
    updates = []
    params = []
    for col, val in [
        ("phase_completed", phase_completed),
        ("positions_checked", positions_checked),
        ("losers_closed", losers_closed),
        ("shorts_closed", shorts_closed),
        ("candidates_found", candidates_found),
        ("candidates_rejected", candidates_rejected),
        ("orders_placed", orders_placed),
        ("positions_monitored", positions_monitored),
        ("snapshots_logged", snapshots_logged),
        ("lessons_logged", lessons_logged),
        ("kpis_computed", kpis_computed),
        ("portfolio_pnl", portfolio_pnl),
        ("portfolio_pnl_pct", portfolio_pnl_pct),
        ("error", error),
        ("summary", summary),
    ]:
        if val is not None:
            updates.append(f"{col}=?")
            params.append(val)
    if updates:
        params.append(exec_id)
        conn.execute(
            f"UPDATE job_executions SET {', '.join(updates)} WHERE id=?", params
        )
        conn.commit()
    conn.close()


def complete_job_execution(exec_id: int, summary: str = "") -> None:
    """Mark a job execution as completed."""
    conn = _get_conn()
    conn.execute(
        """UPDATE job_executions SET status='completed', completed_at=?, summary=?
           WHERE id=?""",
        (datetime.now().isoformat(), summary, exec_id),
    )
    conn.commit()
    conn.close()


def fail_job_execution(exec_id: int, error: str) -> None:
    """Mark a job execution as failed."""
    conn = _get_conn()
    conn.execute(
        """UPDATE job_executions SET status='failed', completed_at=?, error=?
           WHERE id=?""",
        (datetime.now().isoformat(), error, exec_id),
    )
    conn.commit()
    conn.close()


def get_recent_job_executions(job_id: str = "", limit: int = 20) -> list[dict]:
    """Get recent job executions, optionally filtered by job_id."""
    conn = _get_conn()
    if job_id:
        rows = conn.execute(
            "SELECT * FROM job_executions WHERE job_id=? ORDER BY id DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM job_executions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Query helpers ---

def get_recent_picks(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM scanner_picks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_orders(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_lessons(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_runs(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_strategy_kpis(strategy_id: str = "", limit: int = 10) -> list[dict]:
    conn = _get_conn()
    if strategy_id:
        rows = conn.execute(
            "SELECT * FROM strategy_kpis WHERE strategy_id=? ORDER BY id DESC LIMIT ?",
            (strategy_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM strategy_kpis ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_price_history(position_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM price_snapshots WHERE position_id=? ORDER BY id", (position_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
