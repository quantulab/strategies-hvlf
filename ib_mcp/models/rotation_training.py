"""Training pipeline for rotation strategy local ML models.

Trains scikit-learn and hmmlearn models on data from rotation_scanner.db,
serializes them to .model_cache/rotation/ for inference by rotation_classifiers.py.
"""

import logging
from datetime import datetime
from pathlib import Path

import numpy as np

from ib_mcp.models.rotation_classifiers import ROTATION_MODEL_DIR, clear_model_cache
from ib_mcp.rotation_db import (
    ROTATION_DB_PATH,
    ensure_ml_tables,
    get_crossover_training_data,
    get_regime_training_data,
    get_streak_training_data,
    get_volume_lead_training_data,
    register_trained_model,
)

logger = logging.getLogger(__name__)


def _save_model(model: object, name: str) -> str:
    """Save a model with joblib and return the artifact path."""
    import joblib
    artifact_path = ROTATION_MODEL_DIR / f"{name}.joblib"
    joblib.dump(model, artifact_path)
    logger.info(f"Saved model '{name}' to {artifact_path}")
    return str(artifact_path)


def train_hmm_regime_model(db_path: str | Path | None = None) -> dict:
    """Train HMM regime classifier on rotation_state data.

    Requires at least 50 rows in rotation_state table.
    Fits GaussianHMM with 3 hidden states (trending / mean-reverting / transition).

    Returns:
        dict with training metrics, model path, or error
    """
    db_path = db_path or ROTATION_DB_PATH
    ensure_ml_tables(db_path)

    data = get_regime_training_data(limit=500, db_path=db_path)
    if len(data) < 50:
        return {
            "error": f"Insufficient training data: {len(data)} rows (need 50+)",
            "model_name": "hmm_regime",
            "trained": False,
        }

    # Build observation matrix
    volume_map = {"high": 1.5, "normal": 1.0, "low": 0.5}
    gl_ratios = []
    breadth_values = []
    volume_values = []

    for row in reversed(data):  # Chronological order
        gl = row.get("gl_ratio")
        breadth = row.get("market_breadth")
        vol = row.get("volume_regime", "normal")

        if gl is not None and breadth is not None:
            gl_ratios.append(float(gl))
            breadth_values.append(float(breadth))
            volume_values.append(volume_map.get(vol, 1.0))

    if len(gl_ratios) < 50:
        return {
            "error": f"Insufficient valid rows after filtering: {len(gl_ratios)}",
            "model_name": "hmm_regime",
            "trained": False,
        }

    X = np.column_stack([gl_ratios, breadth_values, volume_values])

    # Normalize features
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds[stds == 0] = 1.0
    X_norm = (X - means) / stds

    try:
        from hmmlearn.hmm import GaussianHMM

        model = GaussianHMM(
            n_components=3,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        model.fit(X_norm)

        # Store normalization params with the model for inference
        model._norm_means = means
        model._norm_stds = stds

        # Compute training metrics
        log_likelihood = float(model.score(X_norm))
        state_seq = model.predict(X_norm)
        state_counts = {int(s): int(c) for s, c in zip(*np.unique(state_seq, return_counts=True))}

        artifact_path = _save_model(model, "hmm_regime")
        clear_model_cache("hmm_regime")

        metrics = {
            "log_likelihood": round(log_likelihood, 2),
            "state_distribution": state_counts,
            "n_observations": len(X_norm),
            "converged": model.monitor_.converged,
        }

        register_trained_model(
            model_name="hmm_regime",
            model_type="hmmlearn.GaussianHMM",
            artifact_path=artifact_path,
            training_rows=len(X_norm),
            training_metrics=metrics,
            feature_names=["gl_ratio", "market_breadth", "volume_regime"],
            db_path=db_path,
        )

        return {
            "model_name": "hmm_regime",
            "trained": True,
            "artifact_path": artifact_path,
            "training_rows": len(X_norm),
            "metrics": metrics,
        }

    except Exception as e:
        logger.error(f"HMM training failed: {e}")
        return {"error": str(e), "model_name": "hmm_regime", "trained": False}


def train_volume_conversion_model(db_path: str | Path | None = None) -> dict:
    """Train gradient boosting classifier for volume→gain scanner conversion.

    Requires at least 100 rows in volume_lead_signals table.

    Returns:
        dict with training metrics or error
    """
    db_path = db_path or ROTATION_DB_PATH
    ensure_ml_tables(db_path)

    data = get_volume_lead_training_data(limit=1000, db_path=db_path)
    if len(data) < 100:
        return {
            "error": f"Insufficient training data: {len(data)} rows (need 100+)",
            "model_name": "volume_conversion_gb",
            "trained": False,
        }

    # Build feature matrix
    features = []
    labels = []
    for row in data:
        lead_time = row.get("lead_time_minutes")
        price_change = row.get("price_change_pct")
        traded = row.get("traded", 0)

        # Label: converted if gain scanner appeared (lead_time is not None)
        # and resulted in positive price change
        converted = 1 if (lead_time is not None and (price_change or 0) > 0) else 0
        labels.append(converted)

        features.append([
            lead_time if lead_time is not None else 999,  # Fill with high value if no conversion
            traded or 0,
        ])

    X = np.array(features, dtype=np.float64)
    y = np.array(labels, dtype=np.int32)

    if len(np.unique(y)) < 2:
        return {
            "error": "All labels are the same class — cannot train",
            "model_name": "volume_conversion_gb",
            "trained": False,
        }

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score

        model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=42,
        )

        # Cross-validation
        cv_scores = cross_val_score(model, X, y, cv=min(5, len(y) // 10), scoring="accuracy")

        # Train on full data
        model.fit(X, y)

        artifact_path = _save_model(model, "volume_conversion_gb")
        clear_model_cache("volume_conversion_gb")

        metrics = {
            "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
            "cv_accuracy_std": round(float(cv_scores.std()), 4),
            "positive_rate": round(float(y.mean()), 4),
            "n_samples": len(y),
        }

        register_trained_model(
            model_name="volume_conversion_gb",
            model_type="sklearn.GradientBoostingClassifier",
            artifact_path=artifact_path,
            training_rows=len(y),
            training_metrics=metrics,
            feature_names=["lead_time_minutes", "traded"],
            db_path=db_path,
        )

        return {
            "model_name": "volume_conversion_gb",
            "trained": True,
            "artifact_path": artifact_path,
            "training_rows": len(y),
            "metrics": metrics,
        }

    except Exception as e:
        logger.error(f"Volume conversion training failed: {e}")
        return {"error": str(e), "model_name": "volume_conversion_gb", "trained": False}


def train_streak_survival_model(db_path: str | Path | None = None) -> dict:
    """Train gradient boosting classifier for streak survival prediction.

    Requires at least 30 rows in streak_tracker table.

    Returns:
        dict with training metrics or error
    """
    db_path = db_path or ROTATION_DB_PATH
    ensure_ml_tables(db_path)

    data = get_streak_training_data(limit=500, db_path=db_path)
    if len(data) < 30:
        return {
            "error": f"Insufficient training data: {len(data)} rows (need 30+)",
            "model_name": "streak_survival_gb",
            "trained": False,
        }

    scanner_map = {
        "TopGainers": 0, "GainSinceOpen": 1, "TopVolumeRate": 2,
        "MostActive": 3, "HotByVolume": 4, "TopLosers": 5,
    }

    features = []
    labels = []
    for row in data:
        streak_days = row.get("streak_days", 1)
        scanner_type = row.get("scanner_type", "TopGainers")
        status = row.get("status", "broken")

        # Label: 1 if streak survived (status still active or lasted long)
        survived = 1 if status == "active" or streak_days >= 10 else 0
        labels.append(survived)

        features.append([
            streak_days,
            scanner_map.get(scanner_type, 0),
        ])

    X = np.array(features, dtype=np.float64)
    y = np.array(labels, dtype=np.int32)

    if len(np.unique(y)) < 2:
        return {
            "error": "All labels are the same class — cannot train",
            "model_name": "streak_survival_gb",
            "trained": False,
        }

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score

        model = GradientBoostingClassifier(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            random_state=42,
        )

        cv_folds = min(5, max(2, len(y) // 10))
        cv_scores = cross_val_score(model, X, y, cv=cv_folds, scoring="accuracy")
        model.fit(X, y)

        artifact_path = _save_model(model, "streak_survival_gb")
        clear_model_cache("streak_survival_gb")

        metrics = {
            "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
            "cv_accuracy_std": round(float(cv_scores.std()), 4),
            "survival_rate": round(float(y.mean()), 4),
            "n_samples": len(y),
        }

        register_trained_model(
            model_name="streak_survival_gb",
            model_type="sklearn.GradientBoostingClassifier",
            artifact_path=artifact_path,
            training_rows=len(y),
            training_metrics=metrics,
            feature_names=["streak_days", "scanner_type"],
            db_path=db_path,
        )

        return {
            "model_name": "streak_survival_gb",
            "trained": True,
            "artifact_path": artifact_path,
            "training_rows": len(y),
            "metrics": metrics,
        }

    except Exception as e:
        logger.error(f"Streak survival training failed: {e}")
        return {"error": str(e), "model_name": "streak_survival_gb", "trained": False}


def train_premarket_persistence_model(db_path: str | Path | None = None) -> dict:
    """Train logistic regression for pre-market persistence prediction.

    Uses a simpler model since the base rate is 95.7% — the model needs to
    identify the 4.3% that fade, not predict the majority.

    Requires at least 50 labeled examples.

    Returns:
        dict with training metrics or error
    """
    db_path = db_path or ROTATION_DB_PATH
    ensure_ml_tables(db_path)

    # This model requires manually assembled training data
    # from comparing pre-market scanner appearances to post-open appearances.
    # For now, return not-yet-trainable status until data accumulates.
    return {
        "model_name": "premarket_persist_lr",
        "trained": False,
        "error": "Pre-market persistence model requires labeled pre-market vs post-open data. "
                 "Data will accumulate as strategy_35 runs and logs scanner comparisons.",
        "note": "Using 95.7% base rate heuristic until sufficient data available.",
    }


def train_all_rotation_models(db_path: str | Path | None = None) -> dict:
    """Train or retrain all rotation ML models.

    Returns:
        dict with results for each model
    """
    db_path = db_path or ROTATION_DB_PATH
    ensure_ml_tables(db_path)

    results = {}
    results["hmm_regime"] = train_hmm_regime_model(db_path)
    results["volume_conversion_gb"] = train_volume_conversion_model(db_path)
    results["streak_survival_gb"] = train_streak_survival_model(db_path)
    results["premarket_persist_lr"] = train_premarket_persistence_model(db_path)

    trained_count = sum(1 for r in results.values() if r.get("trained"))
    total = len(results)

    return {
        "summary": f"Trained {trained_count}/{total} models",
        "trained_at": datetime.now().isoformat(),
        "models": results,
    }
