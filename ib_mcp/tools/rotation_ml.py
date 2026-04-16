"""MCP tools for rotation strategy ML enhancements.

Provides 9 tools for sentiment scoring, regime classification, drift detection,
and trained model predictions used by rotation strategies 31-37.
"""

import json

from mcp.server.fastmcp import Context

from ib_mcp.server import mcp


# --- Tier 1 Tools: No training needed, immediate value ---


@mcp.tool()
async def score_rotation_sentiment(
    symbols: str,
    model: str = "finbert",
    ctx: Context = None,
) -> str:
    """Batch score news sentiment for rotation strategy candidates.

    Fetches recent headlines from IB for each symbol and scores sentiment.
    Returns a conviction_delta (+1, 0, or -1) per symbol for use in
    Phase 4 conviction scoring across all rotation sub-strategies.

    Args:
        symbols: JSON array of ticker strings, e.g. '["NVDA", "SOXL", "PLTR"]'
        model: Sentiment model: "finbert" (default, best), "distilroberta_financial" (fastest)
    """
    from ib_mcp.connection import IBContext
    from ib_mcp.models.sentiment import score_headlines_for_symbol
    from ib_mcp.rotation_db import ensure_ml_tables, log_prediction
    from ib_insync import Stock

    ensure_ml_tables()

    symbol_list = json.loads(symbols) if isinstance(symbols, str) else symbols
    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    results = []
    for symbol in symbol_list:
        try:
            contract = Stock(symbol, "SMART", "USD")
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                results.append({
                    "symbol": symbol, "sentiment": 0.0, "conviction_delta": 0,
                    "headline_count": 0, "error": "contract_not_found",
                })
                continue

            raw_headlines = await ib.reqHistoricalNewsAsync(
                conId=qualified[0].conId,
                providerCodes="BRFG+BRFUPDN+DJNL",
                startDateTime="",
                endDateTime="",
                totalResults=10,
            )

            if not raw_headlines:
                results.append({
                    "symbol": symbol, "sentiment": 0.0, "conviction_delta": 0,
                    "headline_count": 0,
                })
                continue

            headline_dicts = [
                {
                    "time": h.time.strftime("%Y-%m-%d %H:%M:%S") if h.time else "",
                    "providerCode": h.providerCode,
                    "articleId": h.articleId,
                    "headline": h.headline,
                }
                for h in raw_headlines
            ]

            scored = score_headlines_for_symbol(headline_dicts, model_key=model)
            avg_sentiment = scored.get("avg_sentiment", 0.0)

            # Map sentiment to conviction delta
            if avg_sentiment > 0.3:
                conviction_delta = 1
            elif avg_sentiment < -0.3:
                conviction_delta = -1
            else:
                conviction_delta = 0

            result = {
                "symbol": symbol,
                "sentiment": round(avg_sentiment, 3),
                "conviction_delta": conviction_delta,
                "headline_count": scored.get("headline_count", 0),
                "top_headline": scored.get("headlines", [{}])[0].get("headline", "") if scored.get("headlines") else "",
            }
            results.append(result)

            # Log prediction
            log_prediction(
                model_name=f"sentiment_{model}",
                prediction_type="sentiment",
                prediction_value=avg_sentiment,
                prediction_label="positive" if avg_sentiment > 0.3 else ("negative" if avg_sentiment < -0.3 else "neutral"),
                prediction_json=result,
                symbol=symbol,
            )

        except Exception as e:
            results.append({
                "symbol": symbol, "sentiment": 0.0, "conviction_delta": 0,
                "error": str(e),
            })

    return json.dumps({"symbols": results, "model": model}, indent=2)


@mcp.tool()
async def classify_rotation_regime(
    lookback_days: int = 20,
    ctx: Context = None,
) -> str:
    """Classify current market regime for rotation strategy priority.

    Uses HMM regime classifier trained on scanner state data. Falls back to
    simple G/L ratio threshold if HMM model not yet trained.
    Replaces hardcoded BULL/BEAR/NEUTRAL logic in Phase 1 Step 8.

    Returns regime (trending/mean_reverting/transition), confidence,
    and recommended sub-strategies for the current regime.

    Args:
        lookback_days: Number of days of rotation_state history to use (default 20)
    """
    from ib_mcp.models.rotation_classifiers import classify_hmm_regime
    from ib_mcp.rotation_db import ensure_ml_tables, get_regime_training_data, log_prediction

    ensure_ml_tables()

    data = get_regime_training_data(limit=lookback_days)
    volume_map = {"high": 1.5, "normal": 1.0, "low": 0.5}

    gl_ratios = []
    breadth_values = []
    volume_ratios = []

    for row in reversed(data):  # Chronological order
        gl = row.get("gl_ratio")
        breadth = row.get("market_breadth")
        vol = row.get("volume_regime", "normal")
        if gl is not None and breadth is not None:
            gl_ratios.append(float(gl))
            breadth_values.append(float(breadth))
            volume_ratios.append(volume_map.get(vol, 1.0))

    if not gl_ratios:
        return json.dumps({
            "regime": "transition",
            "confidence": 0.5,
            "model_available": False,
            "error": "No rotation_state data available",
            "recommended_strategies": [],
        }, indent=2)

    result = classify_hmm_regime(gl_ratios, breadth_values, volume_ratios)

    log_prediction(
        model_name="hmm_regime",
        prediction_type="regime",
        prediction_label=result.get("regime"),
        confidence=result.get("confidence"),
        prediction_json=result,
        features_json={"gl_ratios_last3": gl_ratios[-3:], "lookback_days": lookback_days},
    )

    return json.dumps(result, indent=2)


@mcp.tool()
async def compute_whipsaw_autocorrelation(
    symbol: str,
    window_days: int = 5,
    ctx: Context = None,
) -> str:
    """Compute rolling return autocorrelation for whipsaw fade scoring.

    Negative autocorrelation indicates mean-reversion tendency (good for fades).
    Positive autocorrelation indicates trending (bad for fades).
    Used by Strategy 34 (Whipsaw Fade) to dynamically score fade candidates.

    Args:
        symbol: Ticker symbol (e.g. "SOXL")
        window_days: Rolling window in days for autocorrelation (default 5)
    """
    from ib_mcp.connection import IBContext
    from ib_mcp.models.rotation_classifiers import compute_return_autocorrelation
    from ib_mcp.rotation_db import ensure_ml_tables, log_autocorrelation, log_prediction
    from ib_insync import Stock

    ensure_ml_tables()

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"error": f"Could not find contract for {symbol}"})

    # Fetch daily bars for autocorrelation computation
    duration = f"{window_days * 3} D"
    bars = await ib.reqHistoricalDataAsync(
        qualified[0], endDateTime="", durationStr=duration,
        barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
    )

    if not bars or len(bars) < window_days + 2:
        return json.dumps({
            "symbol": symbol,
            "error": f"Insufficient price history ({len(bars) if bars else 0} bars, need {window_days + 2}+)",
        })

    # Compute daily returns
    closes = [b.close for b in bars]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    result = compute_return_autocorrelation(returns, window=window_days)
    result["symbol"] = symbol
    result["window_days"] = window_days

    # Map to conviction adjustment for whipsaw fade
    if result["is_mean_reverting"]:
        result["fade_conviction_delta"] = 2
    elif result["is_trending"]:
        result["fade_conviction_delta"] = -2
    else:
        result["fade_conviction_delta"] = 0

    # Log to DB
    log_autocorrelation(symbol, result["autocorrelation"], window_days)
    log_prediction(
        model_name="autocorrelation",
        prediction_type="regime",
        prediction_value=result["autocorrelation"],
        prediction_label=result["regime"],
        symbol=symbol,
        features_json={"window_days": window_days, "n_returns": len(returns)},
    )

    return json.dumps(result, indent=2)


@mcp.tool()
async def detect_strategy_drift(
    sub_strategy: str,
    metric: str = "win_rate",
    window_size: int = 20,
    ctx: Context = None,
) -> str:
    """Detect concept drift in a rotation sub-strategy's performance.

    Compares recent performance (last window_size trades) against baseline
    (prior 50 trades) using Kolmogorov-Smirnov test. Flags when the strategy's
    edge has statistically degraded.

    Used by S31 (master) Phase 8 and S35 (pre-market) for auto-monitoring.

    Args:
        sub_strategy: Sub-strategy ID (e.g. "rotation_volume_surge")
        metric: Metric to test — "win_rate", "pnl_pct", or "persistence_rate"
        window_size: Number of recent values to compare (default 20)
    """
    from ib_mcp.models.rotation_classifiers import detect_concept_drift
    from ib_mcp.rotation_db import (
        ensure_ml_tables, get_strategy_metric_series,
        log_drift_result, log_prediction,
    )

    ensure_ml_tables()

    # Get full metric series
    all_values = get_strategy_metric_series(sub_strategy, metric, limit=window_size + 50)

    if len(all_values) < window_size + 10:
        return json.dumps({
            "sub_strategy": sub_strategy,
            "metric": metric,
            "drift_detected": False,
            "error": f"Insufficient data: {len(all_values)} values (need {window_size + 10}+)",
            "recommendation": "insufficient_data",
        }, indent=2)

    recent = all_values[:window_size]
    baseline = all_values[window_size:]

    result = detect_concept_drift(recent, baseline)
    result["sub_strategy"] = sub_strategy
    result["metric"] = metric

    # Log drift result
    log_drift_result(
        sub_strategy=sub_strategy,
        metric_name=metric,
        window_size=window_size,
        baseline_value=result.get("baseline_mean", 0),
        current_value=result.get("current_mean", 0),
        p_value=result.get("p_value", 1.0),
        drift_detected=result.get("drift_detected", False),
        action_taken=result.get("recommendation"),
    )

    log_prediction(
        model_name="concept_drift",
        prediction_type="drift",
        prediction_value=result.get("p_value"),
        prediction_label="drift" if result.get("drift_detected") else "stable",
        sub_strategy=sub_strategy,
        prediction_json=result,
    )

    return json.dumps(result, indent=2)


# --- Tier 2 Tools: Require trained models ---


@mcp.tool()
async def predict_volume_conversion(
    symbol: str,
    volume_rank: int = 25,
    volume_scanner_count: int = 1,
    cap_tier: str = "LargeCap",
    is_known_predictable: bool = False,
    on_whipsaw_list: bool = False,
    price: float = 10.0,
    spread_pct: float = 1.0,
    ctx: Context = None,
) -> str:
    """Predict whether a volume surge will convert to a gain scanner appearance.

    Uses trained gradient boosting model, falling back to heuristic if not trained.
    Used by Strategy 32 (Volume Surge) in Phase 3.

    Args:
        symbol: Ticker symbol
        volume_rank: Current rank on volume scanner (1=highest)
        volume_scanner_count: Number of distinct volume scanners the symbol appears on
        cap_tier: "SmallCap", "MidCap", or "LargeCap"
        is_known_predictable: Whether symbol is in the top-25 predictable tickers list
        on_whipsaw_list: Whether symbol is on the whipsaw watchlist
        price: Current price
        spread_pct: Current bid-ask spread as percentage
    """
    from ib_mcp.models.rotation_classifiers import predict_volume_conversion as _predict
    from ib_mcp.rotation_db import ensure_ml_tables, log_prediction

    ensure_ml_tables()

    features = {
        "volume_rank": volume_rank,
        "volume_scanner_count": volume_scanner_count,
        "cap_tier": cap_tier,
        "is_known_predictable": is_known_predictable,
        "on_whipsaw_list": on_whipsaw_list,
        "price": price,
        "spread_pct": spread_pct,
    }

    result = _predict(features)
    result["symbol"] = symbol

    log_prediction(
        model_name="volume_conversion_gb",
        prediction_type="probability",
        prediction_value=result.get("probability"),
        prediction_label="convert" if result.get("will_convert") else "no_convert",
        symbol=symbol,
        sub_strategy="rotation_volume_surge",
        features_json=features,
        confidence=result.get("probability"),
    )

    return json.dumps(result, indent=2)


@mcp.tool()
async def predict_streak_survival(
    symbol: str,
    scanner_type: str = "TopGainers",
    streak_days: int = 3,
    rank_stability: float = 0.0,
    is_leveraged_etf: bool = False,
    on_whipsaw_list: bool = False,
    ctx: Context = None,
) -> str:
    """Predict whether a scanner streak will continue tomorrow.

    Uses trained gradient boosting model, falling back to bimodal heuristic.
    Used by Strategy 33 (Streak Continuation) in Phase 3.

    Args:
        symbol: Ticker symbol
        scanner_type: Scanner the streak is on (e.g. "TopGainers", "MostActive")
        streak_days: Current streak length in days
        rank_stability: Standard deviation of rank over streak (lower = more stable)
        is_leveraged_etf: Whether the symbol is a leveraged ETF
        on_whipsaw_list: Whether symbol is on whipsaw watchlist
    """
    from ib_mcp.models.rotation_classifiers import predict_streak_survival as _predict
    from ib_mcp.rotation_db import ensure_ml_tables, log_prediction

    ensure_ml_tables()

    features = {
        "streak_days": streak_days,
        "scanner_type": scanner_type,
        "rank_stability": rank_stability,
        "is_leveraged_etf": is_leveraged_etf,
        "on_whipsaw_list": on_whipsaw_list,
    }

    result = _predict(features)
    result["symbol"] = symbol
    result["scanner_type"] = scanner_type
    result["streak_days"] = streak_days

    log_prediction(
        model_name="streak_survival_gb",
        prediction_type="probability",
        prediction_value=result.get("continuation_prob"),
        prediction_label="continues" if result.get("continues") else "breaks",
        symbol=symbol,
        sub_strategy="rotation_streak_continuation",
        features_json=features,
        confidence=result.get("continuation_prob"),
    )

    return json.dumps(result, indent=2)


@mcp.tool()
async def predict_premarket_persistence(
    symbol: str,
    gap_pct: float = 2.0,
    premarket_volume_ratio: float = 1.0,
    whipsaw_days: int = 0,
    is_known_persister: bool = False,
    ctx: Context = None,
) -> str:
    """Predict whether a pre-market mover will persist into regular hours.

    Uses trained logistic regression, falling back to 95.7% base rate adjusted
    by whipsaw risk. Used by Strategy 35 (Pre-Market Persistence) in Phase 3.

    Args:
        symbol: Ticker symbol
        gap_pct: Pre-market gap size as percentage
        premarket_volume_ratio: Pre-market volume relative to average
        whipsaw_days: Number of historical whipsaw days for this symbol
        is_known_persister: Whether symbol is in the known reliable persisters list
    """
    from ib_mcp.models.rotation_classifiers import predict_premarket_persistence as _predict
    from ib_mcp.rotation_db import ensure_ml_tables, log_prediction

    ensure_ml_tables()

    features = {
        "gap_pct": gap_pct,
        "premarket_volume_ratio": premarket_volume_ratio,
        "whipsaw_days": whipsaw_days,
        "is_known_persister": is_known_persister,
    }

    result = _predict(features)
    result["symbol"] = symbol

    log_prediction(
        model_name="premarket_persist_lr",
        prediction_type="probability",
        prediction_value=result.get("probability"),
        prediction_label="persists" if result.get("persists") else "fades",
        symbol=symbol,
        sub_strategy="rotation_premarket_persist",
        features_json=features,
        confidence=result.get("probability"),
    )

    return json.dumps(result, indent=2)


@mcp.tool()
async def predict_capsize_transition(
    symbol: str,
    current_tier: str = "SmallCap",
    ctx: Context = None,
) -> str:
    """Predict cap-tier transition probabilities using Markov chain model.

    Computes empirical transition probabilities from historical crossover data.
    Used by Strategy 36 (Cap-Size Breakout) in Phase 3.

    Args:
        symbol: Ticker symbol
        current_tier: Current cap tier — "SmallCap", "MidCap", or "LargeCap"
    """
    from ib_mcp.models.rotation_classifiers import compute_markov_transition
    from ib_mcp.rotation_db import ensure_ml_tables, get_crossover_training_data, log_prediction

    ensure_ml_tables()

    # Get crossover history for this symbol
    all_data = get_crossover_training_data(limit=500)
    symbol_data = [d for d in all_data if d.get("symbol") == symbol]

    # Also use all data for the global transition matrix
    global_result = compute_markov_transition(all_data)
    symbol_result = compute_markov_transition(symbol_data) if len(symbol_data) >= 3 else None

    # Use symbol-specific if available, else global
    if symbol_result and symbol_result.get("model_available"):
        transition_probs = symbol_result["transition_matrix"].get(current_tier, {})
        source = "symbol_specific"
    else:
        transition_probs = global_result["transition_matrix"].get(current_tier, {})
        source = "global"

    # Determine most likely next tier and sustainability
    tiers = ["SmallCap", "MidCap", "LargeCap"]
    tier_idx = {t: i for i, t in enumerate(tiers)}
    cur_idx = tier_idx.get(current_tier, 0)

    upgrade_prob = sum(
        transition_probs.get(t, 0) for t in tiers if tier_idx.get(t, 0) > cur_idx
    )
    stay_prob = transition_probs.get(current_tier, 0)
    downgrade_prob = sum(
        transition_probs.get(t, 0) for t in tiers if tier_idx.get(t, 0) < cur_idx
    )

    result = {
        "symbol": symbol,
        "current_tier": current_tier,
        "transition_probs": transition_probs,
        "upgrade_probability": round(upgrade_prob, 3),
        "stay_probability": round(stay_prob, 3),
        "downgrade_probability": round(downgrade_prob, 3),
        "source": source,
        "symbol_events": len(symbol_data),
        "global_events": len(all_data),
        "model_available": global_result.get("model_available", False),
        "conviction_delta": 1 if upgrade_prob > 0.3 else (-1 if upgrade_prob < 0.1 else 0),
    }

    log_prediction(
        model_name="markov_transition",
        prediction_type="probability",
        prediction_value=upgrade_prob,
        prediction_label=f"upgrade_prob_{round(upgrade_prob, 2)}",
        symbol=symbol,
        sub_strategy="rotation_capsize_breakout",
        features_json={"current_tier": current_tier, "symbol_events": len(symbol_data)},
        confidence=upgrade_prob,
    )

    return json.dumps(result, indent=2)


# --- Training trigger tool ---


@mcp.tool()
async def train_rotation_models(
    model_name: str = "all",
    ctx: Context = None,
) -> str:
    """Train or retrain rotation strategy ML models.

    Trains local sklearn/hmmlearn models on data from rotation_scanner.db.
    Call with model_name="all" for weekly retraining, or specify a single model.

    Available models: "hmm_regime", "volume_conversion_gb", "streak_survival_gb",
    "premarket_persist_lr", "all"

    Args:
        model_name: Which model to train — "all" or a specific model name
    """
    from ib_mcp.models.rotation_training import (
        train_all_rotation_models,
        train_hmm_regime_model,
        train_premarket_persistence_model,
        train_streak_survival_model,
        train_volume_conversion_model,
    )

    trainers = {
        "hmm_regime": train_hmm_regime_model,
        "volume_conversion_gb": train_volume_conversion_model,
        "streak_survival_gb": train_streak_survival_model,
        "premarket_persist_lr": train_premarket_persistence_model,
    }

    if model_name == "all":
        result = train_all_rotation_models()
    elif model_name in trainers:
        result = trainers[model_name]()
    else:
        result = {
            "error": f"Unknown model: {model_name}. Available: {list(trainers.keys()) + ['all']}",
        }

    return json.dumps(result, indent=2)
