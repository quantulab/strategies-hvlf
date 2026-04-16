"""Rotation strategy ML classifiers — inference functions for local models.

Includes pure computation functions (autocorrelation, drift detection) and
trained model inference (HMM regime, gradient boosting classifiers).
Local models are stored as joblib artifacts, separate from the HuggingFace ModelRegistry.
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Resolve model cache dir without importing ib_mcp.models (avoids torch dependency)
_MODEL_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".model_cache"
_MODEL_CACHE_DIR.mkdir(exist_ok=True)

ROTATION_MODEL_DIR = _MODEL_CACHE_DIR / "rotation"
ROTATION_MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Local model cache (lazy-loaded)
_local_model_cache: dict[str, object] = {}


def _load_local_model(name: str) -> object | None:
    """Load a local sklearn/hmmlearn model from disk, with caching."""
    if name in _local_model_cache:
        return _local_model_cache[name]

    artifact_path = ROTATION_MODEL_DIR / f"{name}.joblib"
    if not artifact_path.exists():
        logger.warning(f"Local model '{name}' not found at {artifact_path}")
        return None

    try:
        import joblib
        model = joblib.load(artifact_path)
        _local_model_cache[name] = model
        logger.info(f"Loaded local model '{name}' from {artifact_path}")
        return model
    except Exception as e:
        logger.error(f"Failed to load local model '{name}': {e}")
        return None


def clear_model_cache(name: str | None = None) -> None:
    """Clear one or all cached local models (e.g., after retraining)."""
    if name:
        _local_model_cache.pop(name, None)
    else:
        _local_model_cache.clear()


# --- Pure computation functions (no training needed) ---


def compute_return_autocorrelation(
    returns: list[float],
    window: int = 5,
) -> dict:
    """Compute rolling return autocorrelation for mean-reversion detection.

    Args:
        returns: List of daily returns (e.g., [0.02, -0.01, 0.03, ...])
        window: Lag window in days (default 5)

    Returns:
        dict with autocorrelation, regime label, and classification flags
    """
    arr = np.array(returns, dtype=np.float64)
    if len(arr) < window + 2:
        return {
            "autocorrelation": 0.0,
            "regime": "insufficient_data",
            "is_mean_reverting": False,
            "is_trending": False,
            "sample_size": len(arr),
        }

    # Use last `window * 2` returns for lag-1 autocorrelation
    recent = arr[-(window * 2):]
    if len(recent) < 4:
        return {
            "autocorrelation": 0.0,
            "regime": "insufficient_data",
            "is_mean_reverting": False,
            "is_trending": False,
            "sample_size": len(recent),
        }

    # Lag-1 autocorrelation
    x = recent[:-1]
    y = recent[1:]
    if np.std(x) == 0 or np.std(y) == 0:
        ac = 0.0
    else:
        ac = float(np.corrcoef(x, y)[0, 1])

    is_mr = ac < -0.2
    is_tr = ac > 0.2
    regime = "mean_reverting" if is_mr else ("trending" if is_tr else "random")

    return {
        "autocorrelation": round(ac, 4),
        "regime": regime,
        "is_mean_reverting": is_mr,
        "is_trending": is_tr,
        "sample_size": len(recent),
    }


def detect_concept_drift(
    recent_values: list[float],
    baseline_values: list[float],
    method: str = "ks_test",
    significance: float = 0.05,
) -> dict:
    """Detect concept drift between recent and baseline metric distributions.

    Args:
        recent_values: Recent metric values (e.g., last 20 trades' win rates)
        baseline_values: Baseline metric values (e.g., prior 50 trades)
        method: Test method — "ks_test" (Kolmogorov-Smirnov) or "mean_shift"
        significance: P-value threshold for drift detection (default 0.05)

    Returns:
        dict with drift_detected, p_value, statistics, recommendation
    """
    recent = np.array(recent_values, dtype=np.float64)
    baseline = np.array(baseline_values, dtype=np.float64)

    if len(recent) < 5 or len(baseline) < 10:
        return {
            "drift_detected": False,
            "p_value": 1.0,
            "method": method,
            "baseline_mean": float(np.mean(baseline)) if len(baseline) > 0 else 0.0,
            "current_mean": float(np.mean(recent)) if len(recent) > 0 else 0.0,
            "recommendation": "insufficient_data",
            "recent_n": len(recent),
            "baseline_n": len(baseline),
        }

    baseline_mean = float(np.mean(baseline))
    current_mean = float(np.mean(recent))

    if method == "ks_test":
        from scipy.stats import ks_2samp
        stat, p_value = ks_2samp(recent, baseline)
    elif method == "mean_shift":
        from scipy.stats import ttest_ind
        stat, p_value = ttest_ind(recent, baseline, equal_var=False)
    else:
        return {"error": f"Unknown method: {method}"}

    p_value = float(p_value)
    drift_detected = p_value < significance

    if drift_detected:
        if current_mean < baseline_mean * 0.7:
            recommendation = "pause_strategy"
        elif current_mean < baseline_mean * 0.85:
            recommendation = "tighten_thresholds"
        else:
            recommendation = "monitor_closely"
    else:
        recommendation = "no_action"

    return {
        "drift_detected": drift_detected,
        "p_value": round(p_value, 6),
        "test_statistic": round(float(stat), 4),
        "method": method,
        "baseline_mean": round(baseline_mean, 4),
        "current_mean": round(current_mean, 4),
        "change_pct": round((current_mean - baseline_mean) / abs(baseline_mean) * 100, 1) if baseline_mean != 0 else 0.0,
        "recommendation": recommendation,
        "recent_n": len(recent),
        "baseline_n": len(baseline),
    }


# --- Trained model inference (graceful fallback) ---


def classify_hmm_regime(
    gl_ratios: list[float],
    breadth_values: list[float],
    volume_ratios: list[float],
) -> dict:
    """Classify market regime using HMM on scanner state features.

    Falls back to simple G/L ratio threshold if HMM model not trained.

    Args:
        gl_ratios: Recent gain/loss ratios (most recent last)
        breadth_values: Market breadth values (unique ticker counts)
        volume_ratios: Volume regime ratios (today vs average)

    Returns:
        dict with regime, confidence, transition matrix, recommended strategies
    """
    # Strategy recommendations per regime
    REGIME_STRATEGIES = {
        "trending": [
            "rotation_streak_continuation",
            "rotation_volume_surge",
            "rotation_elite_accumulation",
        ],
        "mean_reverting": [
            "rotation_whipsaw_fade",
            "rotation_premarket_persist",
        ],
        "transition": [
            "rotation_elite_accumulation",
            "rotation_volume_surge",
        ],
    }

    model = _load_local_model("hmm_regime")

    if model is not None:
        try:
            # Build observation matrix: [gl_ratio, breadth, volume]
            n = min(len(gl_ratios), len(breadth_values), len(volume_ratios))
            if n < 3:
                return _hmm_fallback(gl_ratios, REGIME_STRATEGIES)

            X = np.column_stack([
                gl_ratios[-n:],
                breadth_values[-n:],
                volume_ratios[-n:],
            ])

            # Predict most likely state sequence
            log_prob, state_seq = model.decode(X, algorithm="viterbi")
            current_state = int(state_seq[-1])

            # Get state probabilities for current observation
            state_probs = model.predict_proba(X)[-1]

            # Map states to regime labels (ordered by G/L ratio mean)
            state_means = model.means_[:, 0]  # G/L ratio column
            sorted_states = np.argsort(state_means)
            label_map = {
                int(sorted_states[0]): "mean_reverting",  # lowest G/L
                int(sorted_states[1]): "transition",       # middle G/L
                int(sorted_states[2]): "trending",          # highest G/L
            }

            regime = label_map.get(current_state, "transition")
            confidence = float(state_probs[current_state])

            return {
                "regime": regime,
                "confidence": round(confidence, 3),
                "model_available": True,
                "all_probs": {
                    label_map.get(i, f"state_{i}"): round(float(p), 3)
                    for i, p in enumerate(state_probs)
                },
                "recommended_strategies": REGIME_STRATEGIES.get(regime, []),
                "gl_ratio": round(float(gl_ratios[-1]), 3) if gl_ratios else None,
                "breadth": int(breadth_values[-1]) if breadth_values else None,
            }
        except Exception as e:
            logger.warning(f"HMM inference failed, using fallback: {e}")
            return _hmm_fallback(gl_ratios, REGIME_STRATEGIES)
    else:
        return _hmm_fallback(gl_ratios, REGIME_STRATEGIES)


def _hmm_fallback(gl_ratios: list[float], regime_strategies: dict) -> dict:
    """Simple G/L ratio threshold fallback when HMM not available."""
    gl = gl_ratios[-1] if gl_ratios else 1.0
    if gl > 1.2:
        regime = "trending"
        confidence = min(0.5 + (gl - 1.2) * 0.5, 0.8)
    elif gl < 0.8:
        regime = "mean_reverting"
        confidence = min(0.5 + (0.8 - gl) * 0.5, 0.8)
    else:
        regime = "transition"
        confidence = 0.5

    return {
        "regime": regime,
        "confidence": round(confidence, 3),
        "model_available": False,
        "fallback": "gl_ratio_threshold",
        "recommended_strategies": regime_strategies.get(regime, []),
        "gl_ratio": round(gl, 3),
    }


def predict_volume_conversion(features: dict) -> dict:
    """Predict whether a volume surge will convert to gain scanner appearance.

    Falls back to heuristic if model not trained.

    Args:
        features: dict with keys: volume_rank, volume_scanner_count, cap_tier,
                  is_known_predictable, on_whipsaw_list, price, spread_pct

    Returns:
        dict with will_convert, probability, expected_lead_time_min
    """
    model = _load_local_model("volume_conversion_gb")

    if model is not None:
        try:
            # Encode features for the model
            cap_map = {"SmallCap": 0, "MidCap": 1, "LargeCap": 2}
            X = np.array([[
                features.get("volume_rank", 25),
                features.get("volume_scanner_count", 1),
                cap_map.get(features.get("cap_tier", "LargeCap"), 2),
                int(features.get("is_known_predictable", False)),
                int(features.get("on_whipsaw_list", False)),
                features.get("price", 10.0),
                features.get("spread_pct", 1.0),
            ]])

            prob = float(model.predict_proba(X)[0, 1])
            will_convert = prob >= 0.5

            return {
                "will_convert": will_convert,
                "probability": round(prob, 3),
                "model_available": True,
                "conviction_delta": 1 if prob > 0.7 else (-1 if prob < 0.3 else 0),
            }
        except Exception as e:
            logger.warning(f"Volume conversion model failed: {e}")

    # Heuristic fallback
    score = 0
    if features.get("is_known_predictable"):
        score += 3
    if features.get("volume_scanner_count", 1) >= 2:
        score += 2
    if features.get("on_whipsaw_list"):
        score -= 3

    prob = min(max(0.3 + score * 0.1, 0.1), 0.9)
    return {
        "will_convert": prob >= 0.5,
        "probability": round(prob, 3),
        "model_available": False,
        "fallback": "heuristic_scoring",
        "conviction_delta": 1 if prob > 0.7 else (-1 if prob < 0.3 else 0),
    }


def predict_streak_survival(features: dict) -> dict:
    """Predict whether a scanner streak will continue tomorrow.

    Falls back to heuristic based on streak length.

    Args:
        features: dict with keys: streak_days, scanner_type, rank_stability,
                  is_leveraged_etf, on_whipsaw_list

    Returns:
        dict with continues, continuation_prob, expected_remaining_days
    """
    model = _load_local_model("streak_survival_gb")

    if model is not None:
        try:
            scanner_map = {
                "TopGainers": 0, "GainSinceOpen": 1, "TopVolumeRate": 2,
                "MostActive": 3, "HotByVolume": 4, "TopLosers": 5,
            }
            X = np.array([[
                features.get("streak_days", 3),
                scanner_map.get(features.get("scanner_type", "TopGainers"), 0),
                features.get("rank_stability", 0.0),
                int(features.get("is_leveraged_etf", False)),
                int(features.get("on_whipsaw_list", False)),
            ]])

            prob = float(model.predict_proba(X)[0, 1])
            continues = prob >= 0.5

            return {
                "continues": continues,
                "continuation_prob": round(prob, 3),
                "model_available": True,
                "conviction_delta": 1 if prob > 0.7 else (-1 if prob < 0.4 else 0),
            }
        except Exception as e:
            logger.warning(f"Streak survival model failed: {e}")

    # Heuristic fallback: bimodal distribution from report
    streak_days = features.get("streak_days", 3)
    if streak_days >= 5:
        prob = 0.85  # Past day 5, streaks tend to persist
    elif streak_days >= 3:
        prob = 0.65  # Day 3-4 is the filter zone
    else:
        prob = 0.40  # Day 1-2 entries have higher break rate

    if features.get("on_whipsaw_list"):
        prob -= 0.15

    prob = max(0.1, min(prob, 0.95))
    return {
        "continues": prob >= 0.5,
        "continuation_prob": round(prob, 3),
        "model_available": False,
        "fallback": "bimodal_heuristic",
        "conviction_delta": 1 if prob > 0.7 else (-1 if prob < 0.4 else 0),
    }


def predict_premarket_persistence(features: dict) -> dict:
    """Predict whether a pre-market mover will persist into regular hours.

    Falls back to base rate (95.7%) adjusted by whipsaw risk.

    Args:
        features: dict with keys: gap_pct, premarket_volume_ratio,
                  whipsaw_days, is_known_persister, sector

    Returns:
        dict with persists, probability, risk_factors
    """
    model = _load_local_model("premarket_persist_lr")

    if model is not None:
        try:
            X = np.array([[
                features.get("gap_pct", 2.0),
                features.get("premarket_volume_ratio", 1.0),
                features.get("whipsaw_days", 0),
                int(features.get("is_known_persister", False)),
            ]])

            prob = float(model.predict_proba(X)[0, 1])
            risk_factors = []
            if features.get("whipsaw_days", 0) > 15:
                risk_factors.append("high_whipsaw_history")
            if features.get("gap_pct", 0) > 10:
                risk_factors.append("excessive_gap")

            return {
                "persists": prob >= 0.9,
                "probability": round(prob, 3),
                "model_available": True,
                "risk_factors": risk_factors,
                "conviction_delta": 1 if prob > 0.95 else (-1 if prob < 0.85 else 0),
            }
        except Exception as e:
            logger.warning(f"Premarket persistence model failed: {e}")

    # Heuristic fallback: 95.7% base adjusted by risk factors
    prob = 0.957
    risk_factors = []

    whipsaw_days = features.get("whipsaw_days", 0)
    if whipsaw_days >= 30:
        prob -= 0.15
        risk_factors.append("extreme_whipsaw")
    elif whipsaw_days >= 15:
        prob -= 0.08
        risk_factors.append("high_whipsaw")

    gap_pct = features.get("gap_pct", 2.0)
    if gap_pct > 10:
        prob -= 0.05
        risk_factors.append("excessive_gap")

    prob = max(0.5, min(prob, 0.99))
    return {
        "persists": prob >= 0.9,
        "probability": round(prob, 3),
        "model_available": False,
        "fallback": "base_rate_adjusted",
        "risk_factors": risk_factors,
        "conviction_delta": 1 if prob > 0.95 else (-1 if prob < 0.85 else 0),
    }


def compute_markov_transition(crossover_history: list[dict]) -> dict:
    """Compute empirical Markov transition probabilities between cap tiers.

    Args:
        crossover_history: List of dicts with source_cap, target_cap, symbol

    Returns:
        dict with transition_matrix, stationary_distribution, sustainability
    """
    tiers = ["SmallCap", "MidCap", "LargeCap"]
    tier_idx = {t: i for i, t in enumerate(tiers)}
    n = len(tiers)

    # Count transitions
    counts = np.zeros((n, n), dtype=np.float64)
    for event in crossover_history:
        src = event.get("source_cap", "")
        tgt = event.get("target_cap", "")
        if src in tier_idx and tgt in tier_idx:
            counts[tier_idx[src], tier_idx[tgt]] += 1

    # Add self-transitions (assume staying is 2x as likely as any single transition)
    for i in range(n):
        row_sum = counts[i].sum()
        if row_sum > 0:
            counts[i, i] += row_sum * 2
        else:
            counts[i, i] = 1  # Prior: stay in same tier

    # Normalize to transition probabilities
    row_sums = counts.sum(axis=1, keepdims=True)
    transition_matrix = counts / np.maximum(row_sums, 1e-10)

    # Compute stationary distribution via eigenvalue decomposition
    try:
        eigenvalues, eigenvectors = np.linalg.eig(transition_matrix.T)
        idx = np.argmin(np.abs(eigenvalues - 1.0))
        stationary = np.real(eigenvectors[:, idx])
        stationary = stationary / stationary.sum()
    except Exception:
        stationary = np.ones(n) / n

    return {
        "transition_matrix": {
            tiers[i]: {tiers[j]: round(float(transition_matrix[i, j]), 3) for j in range(n)}
            for i in range(n)
        },
        "stationary_distribution": {
            tiers[i]: round(float(stationary[i]), 3) for i in range(n)
        },
        "total_events": len(crossover_history),
        "model_available": len(crossover_history) >= 10,
    }
