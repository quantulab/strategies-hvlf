"""SQLite database for ML strategy analytics — signals, execution quality, model metrics, and dashboards."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

ANALYTICS_DB_PATH = Path(__file__).resolve().parent.parent / "strategy_analytics.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS strategy_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    signal_strength REAL,
    probability REAL,
    model_name TEXT,
    model_version TEXT,
    features_json TEXT,
    feature_importance_json TEXT,
    scanner TEXT,
    scanner_rank INTEGER,
    confidence_tier TEXT,
    regime_at_signal TEXT,
    was_acted_on INTEGER DEFAULT 0,
    outcome_pnl REAL,
    outcome_pnl_pct REAL,
    position_id INTEGER,
    job_exec_id INTEGER,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_signals_strategy_ts ON strategy_signals(strategy_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON strategy_signals(symbol, timestamp);

CREATE TABLE IF NOT EXISTS execution_quality (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    position_id INTEGER,
    order_id INTEGER,
    order_type TEXT,
    intended_price REAL,
    limit_price REAL,
    fill_price REAL,
    slippage REAL,
    slippage_pct REAL,
    spread_at_signal REAL,
    spread_at_fill REAL,
    fill_time_seconds REAL,
    market_impact_pct REAL,
    volume_at_entry REAL,
    avg_daily_volume REAL,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_exec_strategy ON execution_quality(strategy_id, timestamp);

CREATE TABLE IF NOT EXISTS model_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    accuracy REAL,
    precision_score REAL,
    recall_score REAL,
    f1_score REAL,
    auc_roc REAL,
    brier_score REAL,
    calibration_json TEXT,
    signals_generated INTEGER DEFAULT 0,
    signals_acted_on INTEGER DEFAULT 0,
    signals_profitable INTEGER DEFAULT 0,
    signal_hit_rate REAL,
    avg_signal_pnl REAL,
    feature_importance_json TEXT,
    top_features_json TEXT,
    training_samples INTEGER,
    prediction_samples INTEGER,
    lookback_days INTEGER,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_model_strategy ON model_metrics(strategy_id, timestamp);

CREATE TABLE IF NOT EXISTS cross_strategy_correlation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    window_minutes INTEGER DEFAULT 10,
    strategies_bullish TEXT,
    strategies_bearish TEXT,
    strategies_neutral TEXT,
    agreement_score REAL,
    total_strategies_active INTEGER,
    bullish_count INTEGER DEFAULT 0,
    bearish_count INTEGER DEFAULT 0,
    neutral_count INTEGER DEFAULT 0,
    outcome_30m_pct REAL,
    outcome_60m_pct REAL,
    outcome_eod_pct REAL,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_corr_symbol_ts ON cross_strategy_correlation(symbol, timestamp);

CREATE TABLE IF NOT EXISTS market_regime_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    regime_label TEXT NOT NULL,
    regime_confidence REAL,
    regime_source TEXT,
    vix_level REAL,
    vix_change_pct REAL,
    spy_price REAL,
    spy_change_pct REAL,
    spy_rsi_14 REAL,
    qqq_change_pct REAL,
    iwm_change_pct REAL,
    advancers INTEGER,
    decliners INTEGER,
    advance_decline_ratio REAL,
    new_highs INTEGER,
    new_lows INTEGER,
    total_scanner_candidates INTEGER,
    top_gainer_pct REAL,
    avg_gain_top10_pct REAL,
    scanner_churn_rate REAL,
    leading_sector TEXT,
    lagging_sector TEXT,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON market_regime_log(timestamp);

CREATE TABLE IF NOT EXISTS real_time_dashboard (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_open_positions INTEGER DEFAULT 0,
    total_strategies_active INTEGER DEFAULT 0,
    portfolio_unrealized_pnl REAL DEFAULT 0,
    portfolio_realized_pnl_today REAL DEFAULT 0,
    portfolio_total_pnl_today REAL DEFAULT 0,
    current_regime TEXT,
    regime_confidence REAL,
    vix_level REAL,
    portfolio_heat_pct REAL,
    max_drawdown_today_pct REAL,
    strategy_summary_json TEXT,
    signals_generated_today INTEGER DEFAULT 0,
    signals_acted_on_today INTEGER DEFAULT 0,
    orders_placed_today INTEGER DEFAULT 0,
    trades_closed_today INTEGER DEFAULT 0,
    best_position_json TEXT,
    worst_position_json TEXT,
    jobs_completed_today INTEGER DEFAULT 0,
    jobs_failed_today INTEGER DEFAULT 0,
    last_job_timestamp TEXT,
    avg_job_duration_seconds REAL,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dashboard_ts ON real_time_dashboard(timestamp);

CREATE TABLE IF NOT EXISTS strategy_pnl_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    date TEXT NOT NULL,
    cumulative_pnl REAL DEFAULT 0,
    cumulative_trades INTEGER DEFAULT 0,
    cumulative_wins INTEGER DEFAULT 0,
    daily_pnl REAL DEFAULT 0,
    daily_trades INTEGER DEFAULT 0,
    daily_wins INTEGER DEFAULT 0,
    daily_win_rate REAL,
    equity REAL,
    high_water_mark REAL,
    drawdown_from_hwm REAL,
    drawdown_from_hwm_pct REAL,
    sharpe_rolling_20d REAL,
    sortino_rolling_20d REAL,
    calmar_ratio REAL,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pnl_curve_strategy_date ON strategy_pnl_curve(strategy_id, date);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(ANALYTICS_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLES)
    return conn


# ---------------------------------------------------------------------------
# Strategy Signals
# ---------------------------------------------------------------------------

def log_signal(
    strategy_id: str, symbol: str, action: str,
    signal_strength: float | None = None, probability: float | None = None,
    model_name: str = "", model_version: str = "",
    features_json: str = "", feature_importance_json: str = "",
    scanner: str = "", scanner_rank: int | None = None,
    confidence_tier: str = "", regime_at_signal: str = "",
    was_acted_on: bool = False, position_id: int | None = None,
    job_exec_id: int | None = None, notes: str = "",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO strategy_signals
           (timestamp, strategy_id, symbol, action, signal_strength, probability,
            model_name, model_version, features_json, feature_importance_json,
            scanner, scanner_rank, confidence_tier, regime_at_signal,
            was_acted_on, position_id, job_exec_id, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), strategy_id, symbol, action,
            signal_strength, probability, model_name, model_version,
            features_json, feature_importance_json, scanner, scanner_rank,
            confidence_tier, regime_at_signal, 1 if was_acted_on else 0,
            position_id, job_exec_id, notes,
        ),
    )
    sig_id = cur.lastrowid
    conn.commit()
    conn.close()
    return sig_id


def update_signal_outcome(signal_id: int, outcome_pnl: float, outcome_pnl_pct: float) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE strategy_signals SET outcome_pnl=?, outcome_pnl_pct=? WHERE id=?",
        (outcome_pnl, outcome_pnl_pct, signal_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Execution Quality
# ---------------------------------------------------------------------------

def log_execution_quality(
    strategy_id: str, symbol: str, action: str,
    position_id: int | None = None, order_id: int | None = None,
    order_type: str = "", intended_price: float | None = None,
    limit_price: float | None = None, fill_price: float | None = None,
    spread_at_signal: float | None = None, spread_at_fill: float | None = None,
    fill_time_seconds: float | None = None,
    volume_at_entry: float | None = None, avg_daily_volume: float | None = None,
    notes: str = "",
) -> int:
    slippage = None
    slippage_pct = None
    market_impact_pct = None
    if intended_price and fill_price:
        slippage = fill_price - intended_price
        slippage_pct = (slippage / intended_price) * 100
        market_impact_pct = abs(slippage_pct)

    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO execution_quality
           (timestamp, strategy_id, symbol, action, position_id, order_id,
            order_type, intended_price, limit_price, fill_price,
            slippage, slippage_pct, spread_at_signal, spread_at_fill,
            fill_time_seconds, market_impact_pct, volume_at_entry, avg_daily_volume, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), strategy_id, symbol, action,
            position_id, order_id, order_type, intended_price, limit_price,
            fill_price, slippage, slippage_pct, spread_at_signal,
            spread_at_fill, fill_time_seconds, market_impact_pct,
            volume_at_entry, avg_daily_volume, notes,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# Model Metrics
# ---------------------------------------------------------------------------

def log_model_metrics(
    strategy_id: str, model_name: str, model_version: str = "",
    accuracy: float | None = None, precision_score: float | None = None,
    recall_score: float | None = None, f1_score: float | None = None,
    auc_roc: float | None = None, brier_score: float | None = None,
    calibration_json: str = "",
    signals_generated: int = 0, signals_acted_on: int = 0,
    signals_profitable: int = 0,
    feature_importance_json: str = "", top_features_json: str = "",
    training_samples: int | None = None, prediction_samples: int | None = None,
    lookback_days: int | None = None, notes: str = "",
) -> int:
    hit_rate = (signals_profitable / signals_acted_on) if signals_acted_on else None
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO model_metrics
           (timestamp, strategy_id, model_name, model_version,
            accuracy, precision_score, recall_score, f1_score, auc_roc,
            brier_score, calibration_json,
            signals_generated, signals_acted_on, signals_profitable, signal_hit_rate,
            feature_importance_json, top_features_json,
            training_samples, prediction_samples, lookback_days, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), strategy_id, model_name, model_version,
            accuracy, precision_score, recall_score, f1_score, auc_roc,
            brier_score, calibration_json,
            signals_generated, signals_acted_on, signals_profitable, hit_rate,
            feature_importance_json, top_features_json,
            training_samples, prediction_samples, lookback_days, notes,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# Cross-Strategy Correlation
# ---------------------------------------------------------------------------

def log_cross_strategy_correlation(
    symbol: str,
    strategies_bullish: list[str] | None = None,
    strategies_bearish: list[str] | None = None,
    strategies_neutral: list[str] | None = None,
    window_minutes: int = 10, notes: str = "",
) -> int:
    bull = strategies_bullish or []
    bear = strategies_bearish or []
    neut = strategies_neutral or []
    total = len(bull) + len(bear) + len(neut)
    majority = max(len(bull), len(bear), len(neut))
    agreement = majority / total if total else 0

    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO cross_strategy_correlation
           (timestamp, symbol, window_minutes, strategies_bullish, strategies_bearish,
            strategies_neutral, agreement_score, total_strategies_active,
            bullish_count, bearish_count, neutral_count, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), symbol, window_minutes,
            json.dumps(bull), json.dumps(bear), json.dumps(neut),
            round(agreement, 4), total,
            len(bull), len(bear), len(neut), notes,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def update_correlation_outcome(
    correlation_id: int,
    outcome_30m_pct: float | None = None,
    outcome_60m_pct: float | None = None,
    outcome_eod_pct: float | None = None,
) -> None:
    conn = _get_conn()
    updates, params = [], []
    for col, val in [("outcome_30m_pct", outcome_30m_pct),
                     ("outcome_60m_pct", outcome_60m_pct),
                     ("outcome_eod_pct", outcome_eod_pct)]:
        if val is not None:
            updates.append(f"{col}=?")
            params.append(val)
    if updates:
        params.append(correlation_id)
        conn.execute(f"UPDATE cross_strategy_correlation SET {', '.join(updates)} WHERE id=?", params)
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Market Regime Log
# ---------------------------------------------------------------------------

def log_market_regime(
    regime_label: str, regime_confidence: float | None = None,
    regime_source: str = "",
    vix_level: float | None = None, vix_change_pct: float | None = None,
    spy_price: float | None = None, spy_change_pct: float | None = None,
    spy_rsi_14: float | None = None,
    qqq_change_pct: float | None = None, iwm_change_pct: float | None = None,
    advancers: int | None = None, decliners: int | None = None,
    new_highs: int | None = None, new_lows: int | None = None,
    total_scanner_candidates: int | None = None,
    top_gainer_pct: float | None = None, avg_gain_top10_pct: float | None = None,
    scanner_churn_rate: float | None = None,
    leading_sector: str = "", lagging_sector: str = "",
    notes: str = "",
) -> int:
    ad_ratio = (advancers / decliners) if advancers and decliners and decliners > 0 else None
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO market_regime_log
           (timestamp, regime_label, regime_confidence, regime_source,
            vix_level, vix_change_pct, spy_price, spy_change_pct, spy_rsi_14,
            qqq_change_pct, iwm_change_pct,
            advancers, decliners, advance_decline_ratio, new_highs, new_lows,
            total_scanner_candidates, top_gainer_pct, avg_gain_top10_pct,
            scanner_churn_rate, leading_sector, lagging_sector, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), regime_label, regime_confidence, regime_source,
            vix_level, vix_change_pct, spy_price, spy_change_pct, spy_rsi_14,
            qqq_change_pct, iwm_change_pct,
            advancers, decliners, ad_ratio, new_highs, new_lows,
            total_scanner_candidates, top_gainer_pct, avg_gain_top10_pct,
            scanner_churn_rate, leading_sector, lagging_sector, notes,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# Real-Time Dashboard
# ---------------------------------------------------------------------------

def log_dashboard_snapshot(
    total_open_positions: int = 0, total_strategies_active: int = 0,
    portfolio_unrealized_pnl: float = 0, portfolio_realized_pnl_today: float = 0,
    portfolio_total_pnl_today: float = 0,
    current_regime: str = "", regime_confidence: float | None = None,
    vix_level: float | None = None, portfolio_heat_pct: float | None = None,
    max_drawdown_today_pct: float | None = None,
    strategy_summary_json: str = "",
    signals_generated_today: int = 0, signals_acted_on_today: int = 0,
    orders_placed_today: int = 0, trades_closed_today: int = 0,
    best_position_json: str = "", worst_position_json: str = "",
    jobs_completed_today: int = 0, jobs_failed_today: int = 0,
    last_job_timestamp: str = "", avg_job_duration_seconds: float | None = None,
    notes: str = "",
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO real_time_dashboard
           (timestamp, total_open_positions, total_strategies_active,
            portfolio_unrealized_pnl, portfolio_realized_pnl_today, portfolio_total_pnl_today,
            current_regime, regime_confidence, vix_level,
            portfolio_heat_pct, max_drawdown_today_pct, strategy_summary_json,
            signals_generated_today, signals_acted_on_today,
            orders_placed_today, trades_closed_today,
            best_position_json, worst_position_json,
            jobs_completed_today, jobs_failed_today,
            last_job_timestamp, avg_job_duration_seconds, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), total_open_positions, total_strategies_active,
            portfolio_unrealized_pnl, portfolio_realized_pnl_today, portfolio_total_pnl_today,
            current_regime, regime_confidence, vix_level,
            portfolio_heat_pct, max_drawdown_today_pct, strategy_summary_json,
            signals_generated_today, signals_acted_on_today,
            orders_placed_today, trades_closed_today,
            best_position_json, worst_position_json,
            jobs_completed_today, jobs_failed_today,
            last_job_timestamp, avg_job_duration_seconds, notes,
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# Strategy P&L Curve
# ---------------------------------------------------------------------------

def log_pnl_curve_point(
    strategy_id: str, daily_pnl: float = 0,
    daily_trades: int = 0, daily_wins: int = 0,
    equity: float | None = None, starting_capital: float = 10000,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()

    # Get previous cumulative values
    prev = conn.execute(
        "SELECT * FROM strategy_pnl_curve WHERE strategy_id=? ORDER BY id DESC LIMIT 1",
        (strategy_id,),
    ).fetchone()

    if prev:
        prev = dict(prev)
        cum_pnl = (prev["cumulative_pnl"] or 0) + daily_pnl
        cum_trades = (prev["cumulative_trades"] or 0) + daily_trades
        cum_wins = (prev["cumulative_wins"] or 0) + daily_wins
        hwm = prev["high_water_mark"] or starting_capital
    else:
        cum_pnl = daily_pnl
        cum_trades = daily_trades
        cum_wins = daily_wins
        hwm = starting_capital

    eq = equity if equity is not None else (starting_capital + cum_pnl)
    hwm = max(hwm, eq)
    dd = hwm - eq
    dd_pct = (dd / hwm * 100) if hwm > 0 else 0
    win_rate = (daily_wins / daily_trades) if daily_trades > 0 else None

    cur = conn.execute(
        """INSERT INTO strategy_pnl_curve
           (timestamp, strategy_id, date, cumulative_pnl, cumulative_trades,
            cumulative_wins, daily_pnl, daily_trades, daily_wins, daily_win_rate,
            equity, high_water_mark, drawdown_from_hwm, drawdown_from_hwm_pct)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), strategy_id, today,
            round(cum_pnl, 4), cum_trades, cum_wins,
            round(daily_pnl, 4), daily_trades, daily_wins, win_rate,
            round(eq, 2), round(hwm, 2), round(dd, 2), round(dd_pct, 4),
        ),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------

def get_recent_signals(strategy_id: str = "", symbol: str = "", limit: int = 50) -> list[dict]:
    conn = _get_conn()
    where, params = [], []
    if strategy_id:
        where.append("strategy_id=?")
        params.append(strategy_id)
    if symbol:
        where.append("symbol=?")
        params.append(symbol)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    rows = conn.execute(f"SELECT * FROM strategy_signals {clause} ORDER BY id DESC LIMIT ?", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_execution_quality_report(strategy_id: str = "", limit: int = 50) -> list[dict]:
    conn = _get_conn()
    if strategy_id:
        rows = conn.execute(
            "SELECT * FROM execution_quality WHERE strategy_id=? ORDER BY id DESC LIMIT ?",
            (strategy_id, limit),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM execution_quality ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_model_metrics_history(strategy_id: str = "", model_name: str = "", limit: int = 20) -> list[dict]:
    conn = _get_conn()
    where, params = [], []
    if strategy_id:
        where.append("strategy_id=?")
        params.append(strategy_id)
    if model_name:
        where.append("model_name=?")
        params.append(model_name)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    rows = conn.execute(f"SELECT * FROM model_metrics {clause} ORDER BY id DESC LIMIT ?", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cross_strategy_view(symbol: str = "", limit: int = 50) -> list[dict]:
    conn = _get_conn()
    if symbol:
        rows = conn.execute(
            "SELECT * FROM cross_strategy_correlation WHERE symbol=? ORDER BY id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM cross_strategy_correlation ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_regime_history(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM market_regime_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_dashboard() -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM real_time_dashboard ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_pnl_curve(strategy_id: str, days: int = 30) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM strategy_pnl_curve WHERE strategy_id=? ORDER BY id DESC LIMIT ?",
        (strategy_id, days),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_signal_quality_summary(strategy_id: str = "") -> list[dict]:
    """Aggregate signal quality: hit rate, avg P&L per strategy."""
    conn = _get_conn()
    where = "WHERE strategy_id=?" if strategy_id else ""
    params = [strategy_id] if strategy_id else []
    rows = conn.execute(
        f"""SELECT strategy_id,
                   COUNT(*) as total_signals,
                   SUM(was_acted_on) as acted_on,
                   SUM(CASE WHEN outcome_pnl > 0 THEN 1 ELSE 0 END) as profitable,
                   AVG(CASE WHEN was_acted_on=1 THEN outcome_pnl END) as avg_pnl,
                   AVG(CASE WHEN was_acted_on=1 THEN outcome_pnl_pct END) as avg_pnl_pct,
                   AVG(probability) as avg_probability,
                   MIN(timestamp) as first_signal,
                   MAX(timestamp) as last_signal
            FROM strategy_signals {where}
            GROUP BY strategy_id
            ORDER BY total_signals DESC""",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
