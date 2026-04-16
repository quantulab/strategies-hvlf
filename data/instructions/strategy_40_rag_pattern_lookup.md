---
noteId: "d0e6f4g260b144h4ee5bi920ff25j330"
tags: [cron, trading, strategies, rag, vector-db, chromadb, claude, risk-management]

---

# Strategy 40: RAG — Historical Pattern Lookup — Operating Instructions

## Schedule
- **Daily build:** 9:00 AM ET — update vector DB with previous day's scanner summary
- **Signal generation:** 10:00 AM ET — query similar days and generate trade recommendations
- **Monitoring:** Every 10 minutes from 10:10 AM – 3:50 PM ET
- Job ID: `strategy_40_rag_pattern_lookup`

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Vector DB: ChromaDB collection `scanner_daily_summaries`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_40_rag_pattern_lookup")` — returns `exec_id`
2. After each phase, call `update_job_execution(exec_id, ...)` with progress and counts
3. On completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**Additional tracking: `similar_days_found`, `retrieval_confidence`, `claude_recommendations_count`.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply learned rules
2. **Verify ChromaDB connection:**
   - Collection `scanner_daily_summaries` must exist and contain ≥ 30 days of data
   - Each document contains: date, market_theme, top_stocks (with scanners), outcomes (P&L per stock), best_trade, worst_trade, sector_summary
   - If collection missing or < 30 days → fall back to database-only mode using `get_scan_runs(limit=30)`
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check open orders** via `get_open_orders()`
5. **Count open strategy-40 positions** via `get_strategy_positions(strategy_id="rag_pattern_lookup", status="open")` — enforce max 3 concurrent
6. **Verify IB connection** — halt on disconnect
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY, runs FIRST)

**Enforce stop-loss based on historical worst case from retrieved similar days.**

1. Call `get_portfolio_pnl()` for current P&L
2. For each strategy-40 position:
   a. Retrieve the `historical_worst_loss_pct` stored at entry (from similar day analysis)
   b. If `pnl_pct <= historical_worst_loss_pct` (or <= -5% as absolute maximum):
      - Check `get_open_orders()` — skip if SELL order exists
      - Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
      - Log to `orders` with `strategy_id = "rag_pattern_lookup"`
      - Close in `strategy_positions` with `exit_reason = "historical_stop"`
      - Log to `lessons` with comparison to similar day outcomes
3. For accidental shorts:
   a. Call `place_order(symbol, action="BUY", quantity=abs(N), order_type="MKT")`
   b. Close with `exit_reason = "close_accidental_short"`
4. Reconcile: `get_closed_trades(save_to_db=True)`
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Today's State Summary (10:00 AM run)
1. **Collect current scanner state:** Call `get_scanner_results(scanner, date="today", top_n=20)` for all scanner types
2. **Identify market theme:** Analyze scanner results to determine today's character:
   - Which sectors dominate the gainers? (biotech, tech, energy, etc.)
   - Is it a broad momentum day (many gainers) or narrow (few big movers)?
   - Gap behavior: count of HighOpenGap vs LowOpenGap stocks
   - Volume profile: unusual volume concentration in any tier?
3. **Build today's summary document:**
   ```
   {
     "date": "2026-04-15",
     "market_theme": "biotech momentum, small-cap focus",
     "scanner_snapshot_time": "10:00",
     "top_stocks": [
       {"symbol": "XYZ", "scanners": ["GainSinceOpen_SmallCap", "HotByVolume_SmallCap"], "rank_best": 2, "price": 4.50, "intraday_return": 15.2},
       ...
     ],
     "sector_breakdown": {"biotech": 5, "tech": 3, "energy": 1, ...},
     "gap_stats": {"high_gap_count": 12, "low_gap_count": 8, "avg_gap_pct": 3.2},
     "volume_profile": {"large_cap_vol_ratio": 1.1, "small_cap_vol_ratio": 2.8}
   }
   ```
4. **Enrich with price data:** For top 10 candidates, call `get_quote(symbol)` and `calculate_indicators(symbol, indicators=["RSI", "VWAP", "ATR"], duration="1d", bar_size="5min", tail=20)`
5. **Get news context:** For top 5 candidates, call `get_news_headlines(symbol, max_results=5)` to identify catalysts
   - For any headline that seems significant, call `get_news_article(provider_code, article_id)` to get full text

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Step 1: Vector Similarity Search
1. Embed today's summary document using the same embedding model as the ChromaDB collection
2. Query ChromaDB for the **top-3 most similar historical days**:
   - Similarity metric: cosine similarity on document embeddings
   - Minimum similarity threshold: 0.65 (reject if all 3 are below this)
   - Retrieved documents include: date, theme, top_stocks, outcomes, best/worst trades

### Step 2: Profitability Gate
3. **Check profitability of similar days:**
   - For each of the 3 retrieved similar days, check if that day was net profitable
   - Count profitable_days = number of similar days where total P&L > 0
   - **If 0 out of 3 similar days were profitable → SKIP today entirely**
     - Log to `scanner_picks` with `rejected=1, reject_reason="0/3_similar_days_profitable"`
     - Log to `lessons`: "RAG found 3 similar days, none were profitable. Skipping trades today."
     - Call `complete_job_execution(exec_id, summary="Skipped — no profitable similar days")`
     - Exit early

### Step 3: Claude Recommendation via Retrieved Context
4. If ≥ 1 similar day was profitable, construct a prompt for Claude with retrieved context:
   ```
   Context: Here are 3 historically similar trading days based on scanner patterns:

   Day 1 (similarity: 0.87): [full retrieved document with outcomes]
   Day 2 (similarity: 0.79): [full retrieved document with outcomes]
   Day 3 (similarity: 0.71): [full retrieved document with outcomes]

   Today's scanner state: [today's summary document]
   Today's top candidates: [top 10 stocks with scanner presence, price, volume, RSI]

   Based on these historical patterns and outcomes, recommend:
   1. Top 3 stocks to trade today (BUY only)
   2. For each: expected entry time, expected return %, key risks
   3. Which historical day pattern is most relevant and why
   4. Overall confidence level (high/medium/low)
   ```
5. Parse Claude's recommendations:
   - Extract up to 3 stock recommendations with entry time, expected return, risk assessment
   - Extract confidence level

### Step 4: Cross-Check Validation
6. **Scanner presence requirement:** Each recommended symbol MUST appear on at least 1 scanner currently
   - Call `get_scanner_results(scanner="all", date="today", top_n=20)` and verify
   - If a recommended stock is NOT on any scanner → reject it
   - Log rejection: `reject_reason = "not_on_any_scanner"`
7. **Replacement:** If a recommendation is rejected, do NOT substitute — trade fewer stocks

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
For each validated recommendation, verify via `get_quote(symbol)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Position limit:** Current strategy-40 open positions < 3 (max 3)
6. **No duplicate:** No existing position or order for this symbol
7. **Claude confidence:** Overall recommendation confidence must be "medium" or "high"
8. **Profitability rate:** At least 1/3 similar days must have been profitable (already checked in Phase 4)

Log rejection to `scanner_picks` with `rejected=1` and `reject_reason`.

### Order Placement
For each stock passing all checks:

1. Position sizing:
   - `size_pct = 1.0%` of account value per position (max 3% total for strategy)
   - `quantity = floor(account_value × 0.01 / ask_price)`
2. Stop-loss from historical worst case:
   - Retrieve worst single-stock loss from the 3 similar days
   - `stop_pct = abs(historical_worst_loss_pct)` capped at 5%
   - `stop_price = entry_price × (1 - stop_pct)`
3. Target from historical best case:
   - Retrieve average winner return from profitable similar days
   - `target_price = entry_price × (1 + avg_winner_return_pct)`
4. Place orders:
   a. `place_order(symbol, action="BUY", quantity=N, order_type="MKT")` — entry
   b. `place_order(symbol, action="SELL", quantity=N, order_type="STP", stop_price=stop_price)` — stop
   c. `place_order(symbol, action="SELL", quantity=N, order_type="LMT", limit_price=target_price)` — target
5. Log to database:
   - `scanner_picks`: symbol, scanners_present, conviction_score, similar_days_dates, retrieval_similarity
   - `orders`: symbol, strategy_id="rag_pattern_lookup", full order details
   - `strategy_positions`: strategy_id="rag_pattern_lookup", symbol, entry_price, stop_price, target_price, similar_days (JSON), claude_recommendation (text), historical_worst_loss_pct, historical_avg_return_pct

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-40 position every 10-minute monitoring run:

1. Call `get_quote(symbol)` for current price
2. Log `price_snapshots`: symbol, bid, ask, last, volume, unrealized_pnl, pnl_pct
3. Call `get_position_price_history(position_id)` for trajectory
4. **Compare to historical trajectory:**
   - From the most similar day, retrieve the price trajectory of the same/similar stock
   - If today's stock is underperforming the historical pattern by > 50% → flag for early exit
   - Log comparison data
5. **Re-check scanner presence:**
   - Call `get_scanner_results(scanner="all", date="today", top_n=20)`
   - If the stock has dropped off ALL scanners → tighten stop to breakeven or 1% loss
6. **News monitoring:**
   - Call `get_news_headlines(symbol, max_results=3)` every 30 minutes
   - If negative news detected (e.g., SEC filing, offering), consider early exit
7. Update position extremes: MFE, MAE, peak, trough, drawdown

### Profit Protection — Trailing Stop Ratchet (MANDATORY, every cycle)
**Lesson: AGAE 2026-04-15 lost +26% gain, exited at -7%. This check runs EVERY cycle for EVERY open position.**

For each position, compute `unrealized_pnl_pct` from entry price, then apply:

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +5% to +10% | Breakeven (entry price) |
| +20% to +50% | +10% above entry (entry × 1.10) |
| +50% to +100% | MAX(entry × 1.25, peak_price × 0.80) |
| >+100% | Trail at peak_price × 0.75 |

**Implementation (every cycle):**
1. Get quote via `get_quote` — compute unrealized P&L %
2. Determine tier-required stop level from table above
3. Call `get_open_orders` — find existing STP SELL for this symbol
4. If existing stop is BELOW tier-required level → call `modify_order` to RAISE it
5. If NO stop order exists → place new GTC STP SELL at tier-required level
6. Stops only ratchet UP, never down
7. Log adjustment to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=6, positions_monitored=N, snapshots_logged=N)`

---

## PHASE 7: Exit Handling & Lessons

### On Exit (stop, target, pattern divergence, or manual)

1. Close position in `strategy_positions`:
   - `exit_reason` options: `"historical_stop"`, `"take_profit"`, `"pattern_divergence"`, `"scanner_lost"`, `"news_exit"`, `"eod_close"`, `"manual"`
2. Log to `lessons` table:
   - symbol, strategy_id="rag_pattern_lookup"
   - entry_price, exit_price, pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - **RAG-specific fields:**
     - similar_days: [date1, date2, date3] with similarity scores
     - similar_day_outcome_for_stock: what happened to this stock (or similar) on the most similar day
     - claude_recommendation_accuracy: did the recommendation match reality?
     - retrieval_quality: was the most similar day actually predictive?
   - lesson text (e.g., "RAG retrieved 2020-03-15 as most similar (biotech momentum day). That day's top pick returned +8%. Today's pick returned +3.2%. Pattern held but with lower magnitude.")
3. **Update ChromaDB:** Add today's outcome to the vector DB for future retrieval:
   - Append trade result to today's summary document
   - Re-embed and upsert into ChromaDB collection
4. Compute KPIs via `get_strategy_kpis_report(strategy_id="rag_pattern_lookup")`
5. Write lesson file to `data/lessons/` if retrieval quality was notably good or bad

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="rag_pattern_lookup":
   - Similar days retrieved: [dates with similarity scores]
   - Profitability gate result: passed/failed (N/3 profitable)
   - Claude recommendations: [symbols with expected returns]
   - Cross-check results: [symbols accepted/rejected]
   - Retrieval confidence: average similarity score
3. Compute `strategy_kpis` if positions closed:
   - Win rate, avg P&L, Sharpe ratio, max drawdown
   - **RAG-specific KPIs:**
     - Retrieval accuracy: % of similar days where the actual outcome matched the predicted direction
     - Claude recommendation accuracy: % of recommended trades that were profitable
     - Average similarity score of retrieved days
     - Skip rate: % of days where profitability gate triggered
4. Call `complete_job_execution(exec_id, summary)`

---

## Model Training / Retraining Schedule

### Vector DB Maintenance

#### Daily Update (9:00 AM, before trading)
1. Summarize previous trading day:
   - Compile all scanner results from yesterday
   - Record all trade outcomes (from `strategy_positions` and `orders`)
   - Identify best and worst trades with full context
   - Categorize market theme (sector focus, momentum type, volatility level)
2. Create summary document with structured fields:
   - `date`, `market_theme`, `top_stocks` (with scanners, ranks, outcomes)
   - `best_trade` (symbol, entry, exit, P&L, scanners, strategy)
   - `worst_trade` (symbol, entry, exit, P&L, scanners, reason)
   - `total_pnl`, `win_rate`, `num_trades`
3. Embed and insert into ChromaDB collection `scanner_daily_summaries`

#### Weekly Maintenance (Sunday evening)
1. Re-embed all documents if embedding model is updated
2. Remove documents older than 365 days (keep 1 year rolling window)
3. Validate collection integrity: check document count, test sample queries
4. Log maintenance event to `strategy_kpis`

#### Monthly Review
1. Analyze retrieval quality: for each trade, was the most similar day actually predictive?
2. If retrieval accuracy < 50% over the month → consider:
   - Changing embedding model
   - Adding more structured features to documents
   - Adjusting similarity threshold (currently 0.65)
3. Log findings to `data/lessons/`

### Claude Prompt Refinement
- Review Claude recommendation accuracy weekly
- If accuracy < 40% → refine prompt with more specific instructions
- Add new constraints based on lessons learned (e.g., "avoid recommending stocks that appeared on loss scanners on similar days")

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each run | Phase 0 (start), every phase, Phase 8 (complete) |
| `scanner_picks` | Candidates with retrieval metadata | Phase 3, 4, 5 |
| `orders` | Entry, stop, target orders | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with similar days and Claude recommendation | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + historical comparison data | Phase 6 |
| `strategy_runs` | Per-run retrieval and recommendation summary | Phase 8 |
| `scan_runs` | Overall cycle summary | Phase 8 |
| `lessons` | Trade lessons with retrieval quality analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, retrieval accuracy, recommendation accuracy | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — current and historical scanner data
- `get_scanner_dates()` — available scanner data dates for DB building
- `get_quote(symbol)` — real-time price for quality gate and monitoring
- `get_historical_bars(symbol, duration, bar_size)` — price bars for context
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — technical indicators
- `get_news_headlines(symbol, provider_codes, start, end, max_results)` — catalyst identification
- `get_news_article(provider_code, article_id)` — full news article text
- `get_positions()` — current IB positions
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — existing order check
- `get_closed_trades(save_to_db)` — reconcile closed positions
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — execute trades
- `cancel_order(order_id)` — cancel orders on exit
- `modify_order(order_id, quantity, limit_price, stop_price)` — adjust stops/targets
- `get_strategy_positions(strategy_id, status, limit)` — query strategy-40 positions
- `get_strategy_kpis_report(strategy_id)` — KPI computation
- `get_trading_lessons(limit)` — prior lessons for context
- `get_trading_picks(limit)` — historical picks for pattern building
- `get_scan_runs(limit)` — scan history for daily summaries
- `get_job_executions(job_id, limit)` — execution history
- `get_daily_kpis()` — daily performance metrics
- `get_position_price_history(position_id)` — position trajectory for comparison
