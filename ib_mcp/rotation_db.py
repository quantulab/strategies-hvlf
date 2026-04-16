"""SQLite database helpers for rotation_scanner.db ML enhancement tables."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROTATION_DB_PATH = Path(__file__).resolve().parent.parent / "rotation_scanner.db"

_CREATE_ML_TABLES = """
CREATE TABLE IF NOT EXISTS ml_predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    model_name TEXT NOT NULL,
    model_version TEXT,
    sub_strategy TEXT,
    symbol TEXT,
    prediction_type TEXT NOT NULL,
    prediction_value REAL,
    prediction_label TEXT,
    prediction_json TEXT,
    features_json TEXT,
    confidence REAL,
    was_correct INTEGER,
    outcome_json TEXT,
    exec_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ml_pred_model ON ml_predictions(model_name, timestamp);
CREATE INDEX IF NOT EXISTS idx_ml_pred_symbol ON ml_predictions(symbol, timestamp);

CREATE TABLE IF NOT EXISTS trained_models (
    model_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL UNIQUE,
    model_type TEXT NOT NULL,
    trained_at TEXT NOT NULL DEFAULT (datetime('now')),
    training_rows INTEGER,
    training_metrics_json TEXT,
    artifact_path TEXT NOT NULL,
    feature_names_json TEXT,
    is_active INTEGER DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS drift_monitors (
    drift_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    sub_strategy TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    window_size INTEGER,
    baseline_value REAL,
    current_value REAL,
    p_value REAL,
    drift_detected INTEGER DEFAULT 0,
    test_method TEXT,
    action_taken TEXT
);
CREATE INDEX IF NOT EXISTS idx_drift_strategy ON drift_monitors(sub_strategy, timestamp);

CREATE TABLE IF NOT EXISTS autocorrelation_tracker (
    ac_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    window_days INTEGER DEFAULT 5,
    autocorrelation REAL,
    is_mean_reverting INTEGER,
    is_trending INTEGER,
    regime_label TEXT
);
CREATE INDEX IF NOT EXISTS idx_ac_symbol ON autocorrelation_tracker(symbol, timestamp);
"""


def _get_conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = str(db_path or ROTATION_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_ml_tables(db_path: str | Path | None = None) -> None:
    """Create ML enhancement tables if they don't exist."""
    conn = _get_conn(db_path)
    try:
        conn.executescript(_CREATE_ML_TABLES)
        conn.commit()
    finally:
        conn.close()


def log_prediction(
    model_name: str,
    prediction_type: str,
    prediction_value: float | None = None,
    prediction_label: str | None = None,
    prediction_json: dict | None = None,
    features_json: dict | None = None,
    confidence: float | None = None,
    sub_strategy: str | None = None,
    symbol: str | None = None,
    exec_id: int | None = None,
    model_version: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Log an ML prediction for tracking and outcome evaluation."""
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO ml_predictions
            (model_name, model_version, sub_strategy, symbol, prediction_type,
             prediction_value, prediction_label, prediction_json, features_json,
             confidence, exec_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_name, model_version, sub_strategy, symbol, prediction_type,
                prediction_value, prediction_label,
                json.dumps(prediction_json) if prediction_json else None,
                json.dumps(features_json) if features_json else None,
                confidence, exec_id,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def log_drift_result(
    sub_strategy: str,
    metric_name: str,
    window_size: int,
    baseline_value: float,
    current_value: float,
    p_value: float,
    drift_detected: bool,
    test_method: str = "ks_test",
    action_taken: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Log a concept drift detection result."""
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO drift_monitors
            (sub_strategy, metric_name, window_size, baseline_value, current_value,
             p_value, drift_detected, test_method, action_taken)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sub_strategy, metric_name, window_size, baseline_value,
                current_value, p_value, int(drift_detected), test_method,
                action_taken,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def log_autocorrelation(
    symbol: str,
    autocorrelation: float,
    window_days: int = 5,
    db_path: str | Path | None = None,
) -> int:
    """Log return autocorrelation for a symbol."""
    is_mr = 1 if autocorrelation < -0.2 else 0
    is_tr = 1 if autocorrelation > 0.2 else 0
    regime = "mean_reverting" if is_mr else ("trending" if is_tr else "random")
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO autocorrelation_tracker
            (symbol, window_days, autocorrelation, is_mean_reverting, is_trending, regime_label)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (symbol, window_days, autocorrelation, is_mr, is_tr, regime),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def register_trained_model(
    model_name: str,
    model_type: str,
    artifact_path: str,
    training_rows: int,
    training_metrics: dict | None = None,
    feature_names: list[str] | None = None,
    notes: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Register or update a trained model artifact."""
    conn = _get_conn(db_path)
    try:
        conn.execute(
            """INSERT INTO trained_models
            (model_name, model_type, artifact_path, training_rows,
             training_metrics_json, feature_names_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_name) DO UPDATE SET
                model_type=excluded.model_type,
                trained_at=datetime('now'),
                artifact_path=excluded.artifact_path,
                training_rows=excluded.training_rows,
                training_metrics_json=excluded.training_metrics_json,
                feature_names_json=excluded.feature_names_json,
                is_active=1,
                notes=excluded.notes""",
            (
                model_name, model_type, artifact_path, training_rows,
                json.dumps(training_metrics) if training_metrics else None,
                json.dumps(feature_names) if feature_names else None,
                notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_model_artifact_path(model_name: str, db_path: str | Path | None = None) -> str | None:
    """Get the artifact path for a trained model, or None if not trained."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT artifact_path FROM trained_models WHERE model_name=? AND is_active=1",
            (model_name,),
        ).fetchone()
        return row["artifact_path"] if row else None
    finally:
        conn.close()


# --- Training data query helpers ---

def get_regime_training_data(limit: int = 500, db_path: str | Path | None = None) -> list[dict]:
    """Get rotation_state data for HMM regime model training."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT gl_ratio, market_breadth, volume_regime, breadth_trend,
                      active_sub_strategy, timestamp
               FROM rotation_state ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_volume_lead_training_data(limit: int = 1000, db_path: str | Path | None = None) -> list[dict]:
    """Get volume_lead_signals data for volume conversion model training."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT symbol, volume_scanner, lead_time_minutes,
                      price_at_volume_signal, price_at_gain_signal, price_change_pct, traded
               FROM volume_lead_signals ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_streak_training_data(limit: int = 500, db_path: str | Path | None = None) -> list[dict]:
    """Get streak_tracker data for streak survival model training."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT symbol, scanner_type, streak_days, status, streak_start, streak_end
               FROM streak_tracker ORDER BY last_updated DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_crossover_training_data(limit: int = 500, db_path: str | Path | None = None) -> list[dict]:
    """Get capsize_crossovers data for Markov transition model."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT symbol, direction, source_cap, target_cap,
                      crossover_day_count, traded, timestamp
               FROM capsize_crossovers ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_strategy_metric_series(
    sub_strategy: str,
    metric: str = "pnl_pct",
    limit: int = 100,
    db_path: str | Path | None = None,
) -> list[float]:
    """Get a time series of a strategy metric for drift detection.

    Reads from strategy_positions (closed trades) or strategy_kpis.
    """
    conn = _get_conn(db_path)
    try:
        if metric == "win_rate":
            rows = conn.execute(
                """SELECT win_rate FROM strategy_kpis
                   WHERE sub_strategy=? ORDER BY timestamp DESC LIMIT ?""",
                (sub_strategy, limit),
            ).fetchall()
            return [r["win_rate"] for r in rows if r["win_rate"] is not None]
        elif metric in ("pnl_pct", "pnl"):
            rows = conn.execute(
                """SELECT pnl_pct FROM strategy_positions
                   WHERE sub_strategy=? AND status='closed'
                   ORDER BY exit_time DESC LIMIT ?""",
                (sub_strategy, limit),
            ).fetchall()
            return [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
        elif metric == "persistence_rate":
            # For premarket strategy: compute from scan_runs
            rows = conn.execute(
                """SELECT candidates_found, candidates_rejected FROM scan_runs
                   WHERE active_sub_strategies LIKE '%premarket%'
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            rates = []
            for r in rows:
                found = r["candidates_found"] or 0
                rejected = r["candidates_rejected"] or 0
                if found > 0:
                    rates.append((found - rejected) / found)
            return rates
        else:
            return []
    finally:
        conn.close()
