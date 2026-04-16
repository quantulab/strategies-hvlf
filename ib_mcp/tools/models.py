"""MCP tools for HuggingFace model inference in trading strategies."""

import json

from mcp.server.fastmcp import Context

from ib_mcp.server import mcp


@mcp.tool()
async def analyze_news_sentiment(
    symbol: str = "",
    headlines: str = "",
    model: str = "finbert",
    ctx: Context = None,
) -> str:
    """Analyze financial news sentiment using HuggingFace models.

    If symbol is provided, fetches headlines from IB automatically.
    If headlines is provided (JSON array of strings), analyzes those directly.

    Args:
        symbol: Ticker symbol to fetch and analyze headlines for (e.g. "NVDA")
        headlines: JSON array of headline strings to analyze directly
        model: Model to use: "finbert" (default), "distilroberta_financial",
               "twitter_sentiment", "deberta_finance", "cryptobert"
    """
    from ib_mcp.models.sentiment import analyze_sentiment, score_headlines_for_symbol

    if headlines:
        texts = json.loads(headlines)
        results = analyze_sentiment(texts, model_key=model)
        return json.dumps([
            {"text": r.text, "label": r.label, "score": r.score, "sentiment": r.sentiment}
            for r in results
        ], indent=2)

    if symbol:
        # Fetch headlines from IB and score them
        from ib_mcp.connection import IBContext
        ib_ctx: IBContext = ctx.request_context.lifespan_context
        ib = ib_ctx.ib
        from ib_insync import Stock

        contract = Stock(symbol, "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            return json.dumps({"error": f"Could not find contract for {symbol}"})

        raw_headlines = await ib.reqHistoricalNewsAsync(
            conId=qualified[0].conId,
            providerCodes="BRFG+BRFUPDN+DJNL",
            startDateTime="",
            endDateTime="",
            totalResults=10,
        )

        if not raw_headlines:
            return json.dumps({"error": f"No headlines found for {symbol}"})

        headline_dicts = [
            {
                "time": h.time.strftime("%Y-%m-%d %H:%M:%S") if h.time else "",
                "providerCode": h.providerCode,
                "articleId": h.articleId,
                "headline": h.headline,
            }
            for h in raw_headlines
        ]

        result = score_headlines_for_symbol(headline_dicts, model_key=model)
        return json.dumps(result, indent=2)

    return json.dumps({"error": "Provide either symbol or headlines"})


@mcp.tool()
async def detect_news_burst(
    symbol: str,
    window_minutes: int = 10,
    burst_threshold: int = 3,
    ctx: Context = None,
) -> str:
    """Detect rapid news publication bursts for a symbol and score sentiment.

    Used by Strategy 24 (News Velocity). Checks if >= burst_threshold headlines
    were published within window_minutes, indicating a potential catalyst event.

    Args:
        symbol: Ticker symbol (e.g. "NVDA")
        window_minutes: Rolling window in minutes (default 10)
        burst_threshold: Minimum headlines to trigger burst (default 3)
    """
    from ib_mcp.connection import IBContext
    from ib_mcp.models.sentiment import detect_news_velocity
    from ib_insync import Stock

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"error": f"Could not find contract for {symbol}"})

    raw_headlines = await ib.reqHistoricalNewsAsync(
        conId=qualified[0].conId,
        providerCodes="BRFG+BRFUPDN+DJNL",
        startDateTime="",
        endDateTime="",
        totalResults=30,
    )

    if not raw_headlines:
        return json.dumps({"is_burst": False, "burst_count": 0, "reason": "No headlines"})

    headline_dicts = [
        {
            "time": h.time.strftime("%Y-%m-%d %H:%M:%S") if h.time else "",
            "headline": h.headline,
        }
        for h in raw_headlines
    ]

    result = detect_news_velocity(
        headline_dicts, window_minutes=window_minutes,
        burst_threshold=burst_threshold,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def forecast_scanner_rank(
    symbol: str,
    scanner: str = "GainSinceOpenLarge",
    prediction_steps: int = 60,
    model: str = "chronos_small",
    multi_day: bool = False,
    ctx: Context = None,
) -> str:
    """Forecast a stock's future scanner rank trajectory using Chronos.

    Predicts where a stock's rank will be on a given scanner in the future.
    Used by Strategy 23 (Rank Forecaster) and Strategy 17 (Transformer).

    When multi_day=True, forecasts daily rank evolution (used by rotation
    strategies 33/37 for multi-day rank prediction). In this mode,
    prediction_steps represents days, not intraday snapshots.

    Args:
        symbol: Ticker symbol to forecast rank for
        scanner: Scanner name (default GainSinceOpenLarge)
        prediction_steps: Future snapshots to predict (default 60 intraday, or days if multi_day)
        model: Chronos variant: "chronos_small" (fast), "chronos_bolt", "chronos_large"
        multi_day: If True, use daily rank history instead of intraday (default False)
    """
    from ib_mcp.models.timeseries import forecast_rank_trajectory
    from ib_mcp.scanner_data import get_symbol_rank_history

    if multi_day:
        # Query daily best rank from rotation_scanner.db streak_tracker
        # or fall back to daily scanner archives
        from ib_mcp.scanner_data import get_symbol_daily_rank_history
        try:
            rank_history = get_symbol_daily_rank_history(symbol, scanner)
        except (AttributeError, ImportError):
            # Fallback: use intraday history sampled at daily granularity
            rank_history = get_symbol_rank_history(symbol, scanner)
            if len(rank_history) > 50:
                # Sample roughly once per day (assuming ~40 snapshots/day)
                rank_history = rank_history[::40]
        # Use smaller prediction steps for daily forecasts
        if prediction_steps > 10:
            prediction_steps = 5  # 5 trading days ahead
    else:
        rank_history = get_symbol_rank_history(symbol, scanner)

    if len(rank_history) < 20:
        min_needed = 5 if multi_day else 20
        if len(rank_history) < min_needed:
            return json.dumps({
                "error": f"Insufficient rank history for {symbol} on {scanner} "
                         f"(got {len(rank_history)}, need {min_needed}+)",
            })

    result = forecast_rank_trajectory(rank_history, prediction_steps, model_key=model)
    result["symbol"] = symbol
    result["scanner"] = scanner
    result["multi_day"] = multi_day
    return json.dumps(result, indent=2)


@mcp.tool()
async def forecast_price_monte_carlo(
    symbol: str,
    duration: str = "1 D",
    bar_size: str = "1 min",
    prediction_length: int = 30,
    num_samples: int = 1000,
    model: str = "chronos_bolt",
    ctx: Context = None,
) -> str:
    """Generate Monte Carlo price forecast distribution using Chronos.

    Returns probability of +2%, probability of -3%, expected return, CVaR,
    quantile-based stop/target levels, and Kelly criterion sizing.
    Used by Strategy 29.

    Args:
        symbol: Ticker symbol (e.g. "NVDA")
        duration: How far back to fetch price history (default "1 D")
        bar_size: Bar size (default "1 min")
        prediction_length: Forward steps to simulate (default 30 = 30 min)
        num_samples: Monte Carlo sample paths (default 1000)
        model: Chronos variant (default "chronos_bolt" for speed)
    """
    from ib_mcp.connection import IBContext
    from ib_mcp.models.timeseries import forecast_price_distribution
    from ib_insync import Stock

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"error": f"Could not find contract for {symbol}"})

    bars = await ib.reqHistoricalDataAsync(
        qualified[0], endDateTime="", durationStr=duration,
        barSizeSetting=bar_size, whatToShow="TRADES", useRTH=True,
    )

    if not bars or len(bars) < 30:
        return json.dumps({"error": f"Insufficient price history for {symbol}"})

    prices = [b.close for b in bars]
    result = forecast_price_distribution(
        prices, prediction_length=prediction_length,
        model_key=model, num_samples=num_samples,
    )
    result["symbol"] = symbol
    return json.dumps(result, indent=2)


@mcp.tool()
async def classify_market_regime(
    scanner_summary: str = "",
    method: str = "zero_shot",
    breadth: int = 0,
    gl_ratio: float = 0.0,
    volume_level: float = 0.5,
    ctx: Context = None,
) -> str:
    """Classify current market regime from scanner state.

    Supports two methods:
    - "zero_shot" (default): BART-MNLI text classification into rally/chop/selloff/etc.
    - "hmm": 3-state Gaussian HMM into bull_momentum/bear_mean_reversion/range_bound.
      The HMM method is preferred for rotation strategies as it provides
      sub-strategy routing recommendations.

    Args:
        scanner_summary: Natural language summary of current scanner state.
            If empty, auto-generates from latest scanner data.
        method: "zero_shot" (default, text-based) or "hmm" (numeric features)
        breadth: Market breadth for HMM method (unique tickers, e.g. 2000)
        gl_ratio: Gain/loss ratio for HMM method (e.g. 1.2)
        volume_level: Normalized volume 0-1 for HMM method (e.g. 0.7)
    """
    if method == "hmm":
        from ib_mcp.models.classifiers import detect_hmm_regime
        result = detect_hmm_regime(
            breadth=float(breadth) if breadth > 0 else 2000.0,
            gl_ratio=gl_ratio if gl_ratio > 0 else 1.0,
            volume_level=volume_level,
        )
        return json.dumps(result, indent=2)

    # Default: zero-shot classification
    from ib_mcp.models.classifiers import classify_market_regime as _classify

    if not scanner_summary:
        from ib_mcp.scanner_data import generate_scanner_summary
        scanner_summary = generate_scanner_summary()

    result = _classify(scanner_summary)
    return json.dumps(result, indent=2)


@mcp.tool()
async def classify_news_catalyst(
    headline: str,
    ctx: Context = None,
) -> str:
    """Classify a news headline by catalyst type (fundamental vs technical).

    Returns catalyst classification (earnings, FDA, analyst upgrade, etc.)
    and whether it's a fundamental catalyst. Used by Strategy 14.

    Args:
        headline: News headline text to classify
    """
    from ib_mcp.models.classifiers import classify_catalyst
    result = classify_catalyst(headline)
    return json.dumps(result, indent=2)


@mcp.tool()
async def extract_ticker_entities(
    text: str,
    ctx: Context = None,
) -> str:
    """Extract company/organization names from text and map to ticker symbols.

    Uses BERT NER model to find entity mentions, then maps to known tickers.
    Used by Strategy 14, 24, 40 for headline → ticker resolution.

    Args:
        text: Text to extract entities from (headline, article, etc.)
    """
    from ib_mcp.models.classifiers import extract_entities, entities_to_tickers
    entities = extract_entities([text])
    tickers = entities_to_tickers(entities[0])
    return json.dumps(tickers, indent=2)


@mcp.tool()
async def find_similar_trading_days(
    scanner_summary: str = "",
    top_k: int = 3,
    ctx: Context = None,
) -> str:
    """Find historical trading days most similar to today's scanner pattern.

    Uses BGE-large embeddings to search a vector index of historical scanner
    day summaries. Returns the most similar days with their outcomes.
    Used by Strategy 36 (Contrastive Fingerprints) and Strategy 40 (RAG).

    Args:
        scanner_summary: Today's scanner state summary. If empty, auto-generates.
        top_k: Number of similar days to return (default 3)
    """
    from ib_mcp.models.embeddings import ScannerDayIndex

    if not scanner_summary:
        from ib_mcp.scanner_data import generate_scanner_summary
        scanner_summary = generate_scanner_summary()

    index = ScannerDayIndex(model_key="bge_large")

    if index.count() == 0:
        return json.dumps({
            "error": "No historical days indexed yet. Run index_scanner_day first.",
            "index_count": 0,
        })

    results = index.find_similar_days(scanner_summary, top_k=top_k)
    return json.dumps({
        "query": scanner_summary[:200],
        "index_count": index.count(),
        "similar_days": results,
    }, indent=2)


@mcp.tool()
async def index_scanner_day(
    date: str = "",
    outcome: str = "",
    ctx: Context = None,
) -> str:
    """Index a historical scanner day into the vector database for similarity search.

    Should be run at end of each trading day to build up the historical index.
    Used by Strategy 36 and 40.

    Args:
        date: Date in YYYYMMDD format (default: today)
        outcome: JSON string with day outcome data (e.g. top gainer returns)
    """
    from datetime import datetime as dt
    from ib_mcp.models.embeddings import ScannerDayIndex, build_scanner_day_summary
    from ib_mcp.scanner_data import load_scanner_snapshot

    if not date:
        date = dt.now().strftime("%Y%m%d")

    scanner_data = load_scanner_snapshot(date)
    if not scanner_data:
        return json.dumps({"error": f"No scanner data found for {date}"})

    outcome_dict = json.loads(outcome) if outcome else {}
    summary = build_scanner_day_summary(date, scanner_data, outcome_dict)

    index = ScannerDayIndex(model_key="bge_large")
    index.add_day(date, summary, outcome=outcome_dict)

    return json.dumps({
        "indexed": True,
        "date": date,
        "summary_preview": summary[:300],
        "total_days_indexed": index.count(),
    }, indent=2)


@mcp.tool()
async def get_sentiment_gate(
    symbol: str,
    model: str = "finbert",
    threshold: float = -0.3,
    ctx: Context = None,
) -> str:
    """Quick sentiment check returning approve/reject gate for trade entry.

    Fetches recent headlines for a symbol, scores them with FinBERT, and
    returns a binary approve/reject decision based on average sentiment.
    Used as a universal conviction modifier across all rotation strategies.

    Args:
        symbol: Ticker symbol (e.g. "NVDA")
        model: Sentiment model (default "finbert")
        threshold: Minimum avg sentiment to approve (default -0.3; reject if below)
    """
    from ib_mcp.models.sentiment import analyze_sentiment
    from ib_mcp.connection import IBContext
    from ib_insync import Stock

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"gate": "approve", "reason": "no_contract", "avg_sentiment": 0.0})

    raw_headlines = await ib.reqHistoricalNewsAsync(
        conId=qualified[0].conId,
        providerCodes="BRFG+BRFUPDN+DJNL",
        startDateTime="",
        endDateTime="",
        totalResults=5,
    )

    if not raw_headlines:
        # No news = neutral, approve by default
        return json.dumps({
            "symbol": symbol,
            "gate": "approve",
            "reason": "no_headlines",
            "avg_sentiment": 0.0,
            "headline_count": 0,
        })

    texts = [h.headline for h in raw_headlines]
    results = analyze_sentiment(texts, model_key=model)

    sentiments = [r.sentiment for r in results]
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

    pos = sum(1 for s in sentiments if s > 0.1)
    neg = sum(1 for s in sentiments if s < -0.1)
    neu = len(sentiments) - pos - neg

    gate = "approve" if avg_sentiment >= threshold else "reject"

    return json.dumps({
        "symbol": symbol,
        "gate": gate,
        "avg_sentiment": round(avg_sentiment, 4),
        "headline_count": len(raw_headlines),
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count": neu,
        "threshold": threshold,
        "model": model,
    }, indent=2)


@mcp.tool()
async def forecast_volume_trajectory(
    symbol: str,
    duration: str = "1 D",
    bar_size: str = "5 mins",
    prediction_length: int = 12,
    model: str = "chronos_bolt",
    ctx: Context = None,
) -> str:
    """Forecast future volume trajectory to predict if a volume surge will sustain.

    Uses Chronos time series model on historical volume data. Returns a trend
    classification (rising/falling/flat) and predicted volume values.
    Used by Strategy 32 (Volume Surge) to skip signals where volume is fading.

    Args:
        symbol: Ticker symbol (e.g. "NVDA")
        duration: How far back to fetch volume history (default "1 D")
        bar_size: Bar size for volume data (default "5 mins")
        prediction_length: Steps ahead to forecast (default 12 = 60 min at 5-min bars)
        model: Chronos variant (default "chronos_bolt" for speed)
    """
    from ib_mcp.connection import IBContext
    from ib_mcp.models.timeseries import forecast_volume_series
    from ib_insync import Stock

    ib_ctx: IBContext = ctx.request_context.lifespan_context
    ib = ib_ctx.ib

    contract = Stock(symbol, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return json.dumps({"error": f"Could not find contract for {symbol}"})

    bars = await ib.reqHistoricalDataAsync(
        qualified[0], endDateTime="", durationStr=duration,
        barSizeSetting=bar_size, whatToShow="TRADES", useRTH=True,
    )

    if not bars or len(bars) < 20:
        return json.dumps({"error": f"Insufficient volume history for {symbol}"})

    volumes = [float(b.volume) for b in bars]
    result = forecast_volume_series(
        volumes, prediction_length=prediction_length, model_key=model,
    )
    result["symbol"] = symbol
    return json.dumps(result, indent=2)


@mcp.tool()
async def classify_catalyst_topic(
    headline: str,
    ctx: Context = None,
) -> str:
    """Classify a news headline by financial topic to distinguish catalyst types.

    Uses a FinBERT-based topic classifier to categorize headlines into topics
    like earnings, M&A, macro, analyst actions, etc. Returns whether the
    catalyst is fundamental (more likely to persist) vs technical.
    Used by rotation strategies 34-36 for conviction scoring.

    Args:
        headline: News headline text to classify
    """
    from ib_mcp.models.sentiment import classify_topic

    results = classify_topic([headline])
    if results:
        return json.dumps(results[0], indent=2)
    return json.dumps({"error": "Classification failed"})


@mcp.tool()
async def detect_regime_hmm(
    scanner_summary: str = "",
    breadth: int = 0,
    gl_ratio: float = 0.0,
    volume_level: float = 0.5,
    ctx: Context = None,
) -> str:
    """Detect market regime using Hidden Markov Model (3-state Gaussian HMM).

    Classifies market into: bull_momentum, bear_mean_reversion, or range_bound.
    Returns routing recommendations for which rotation sub-strategies to prioritize.
    Used by Strategy 31 master rotation controller (Phase 1).

    Args:
        scanner_summary: Natural language scanner summary (auto-generates features if provided)
        breadth: Market breadth — unique tickers on scanners today (e.g. 2000)
        gl_ratio: Gain/loss scanner ratio (e.g. 1.2)
        volume_level: Normalized volume level 0-1 (e.g. 0.7 = above average)
    """
    from ib_mcp.models.classifiers import detect_hmm_regime

    if scanner_summary and (breadth == 0 or gl_ratio == 0.0):
        # Try to extract numeric features from summary text
        import re
        breadth_match = re.search(r'(\d{3,5})\s*(?:unique|tickers|breadth)', scanner_summary)
        gl_match = re.search(r'(?:G/L|gain.?loss|ratio)[:\s]*(\d+\.?\d*)', scanner_summary, re.IGNORECASE)
        if breadth_match:
            breadth = int(breadth_match.group(1))
        if gl_match:
            gl_ratio = float(gl_match.group(1))

        # Defaults if still missing
        if breadth == 0:
            breadth = 2000
        if gl_ratio == 0.0:
            gl_ratio = 1.0

    result = detect_hmm_regime(
        breadth=float(breadth),
        gl_ratio=gl_ratio,
        volume_level=volume_level,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_models(ctx: Context = None) -> str:
    """List all available HuggingFace models and their loading status.

    Shows which models are loaded in memory, their HuggingFace model IDs,
    and which strategies use them.
    """
    from ib_mcp.models import registry
    from ib_mcp.models.config import STRATEGY_MODELS

    models = registry.list_models()

    # Add strategy mapping
    for key in models:
        strategies = [s for s, m_list in STRATEGY_MODELS.items() if key in m_list]
        models[key]["strategies"] = strategies

    return json.dumps(models, indent=2)
