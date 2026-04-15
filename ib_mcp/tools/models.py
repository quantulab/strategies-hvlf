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
    ctx: Context = None,
) -> str:
    """Forecast a stock's future scanner rank trajectory using Chronos.

    Predicts where a stock's rank will be on a given scanner in the future.
    Used by Strategy 23 (Rank Forecaster) and Strategy 17 (Transformer).

    Args:
        symbol: Ticker symbol to forecast rank for
        scanner: Scanner name (default GainSinceOpenLarge)
        prediction_steps: Number of future snapshots to predict (default 60 = ~30 min)
        model: Chronos variant: "chronos_small" (fast), "chronos_bolt", "chronos_large"
    """
    from ib_mcp.models.timeseries import forecast_rank_trajectory
    from ib_mcp.scanner_data import get_symbol_rank_history

    rank_history = get_symbol_rank_history(symbol, scanner)

    if len(rank_history) < 20:
        return json.dumps({
            "error": f"Insufficient rank history for {symbol} on {scanner} "
                     f"(got {len(rank_history)}, need 20+)",
        })

    result = forecast_rank_trajectory(rank_history, prediction_steps, model_key=model)
    result["symbol"] = symbol
    result["scanner"] = scanner
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
    ctx: Context = None,
) -> str:
    """Classify current market regime from scanner state.

    Uses zero-shot classification (BART-MNLI) to determine if the market
    is in: rally, chop, selloff, drift, earnings-driven, or macro-shock mode.
    Returns sub-strategy recommendation for each regime.
    Used by Strategy 15 and 25.

    Args:
        scanner_summary: Natural language summary of current scanner state.
            If empty, auto-generates from latest scanner data.
    """
    from ib_mcp.models.classifiers import classify_market_regime as _classify

    if not scanner_summary:
        # Auto-generate from scanner data
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
