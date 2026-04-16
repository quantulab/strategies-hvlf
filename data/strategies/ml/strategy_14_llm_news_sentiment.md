---
noteId: "TODO"
tags: [cron, trading, strategies, llm, sentiment, news, claude]

---

# Strategy 14: LLM News Sentiment + Scanner Confluence — Operating Instructions

## Schedule
Runs every 5 minutes during market hours (9:35 AM – 3:45 PM ET) via Claude Code CronCreate.
Sentiment cache expires after 30 minutes — stale scores are refreshed on next cycle.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- News headlines via MCP: `get_news_headlines(symbol, provider_codes, start, end, max_results)`
- News articles via MCP: `get_news_article(provider_code, article_id)`
- Historical bars via MCP: `get_historical_bars(symbol, duration, bar_size)`
- Indicators via MCP: `calculate_indicators(symbol, indicators, duration, bar_size, tail)`
- Sentiment cache: in-memory dictionary keyed by `(symbol, headline_id)` with 30-min TTL
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_14_llm_news_sentiment")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - Sentiment-specific: `headlines_scored`, `avg_sentiment`, `catalysts_found`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned (especially news-driven trade lessons)
2. **Load strategy file** from `data/strategies/` — confirm parameters
3. **Check sentiment cache** — purge entries older than 30 minutes
4. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions with `strategy_id = "llm_news_sentiment"`
   - If already at 5 concurrent positions, skip to Phase 6 (monitoring only)
5. **Check current open orders** via `get_open_orders()` — note pending orders
6. **Verify IB connection** — if disconnected, log error via `fail_job_execution` and attempt reconnect
7. **Load recent job executions** via `get_job_executions(job_id="strategy_14_llm_news_sentiment", limit=10)` to check for API rate limit issues
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

**Before any new trades, enforce the 8% stop-loss rule on ALL strategy_14 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="llm_news_sentiment", status="open")` to identify this strategy's positions
3. For each position with `pnl_pct <= -8%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")` to liquidate
   c. Log to `orders` table with `strategy_id = "llm_news_sentiment"`
   d. Log to `strategy_positions` — close with `exit_reason = "stop_loss_8pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, sentiment at entry, catalyst type, and lesson text
   f. Compute and log KPIs via `compute_and_log_kpis`
4. For short positions (quantity < 0) — close immediately with MKT BUY
5. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. For every position that disappeared: log to `lessons`, `strategy_positions`, and `orders`
6. **Scale-out check:** For positions up >= +15%, execute 50% scale-out:
   a. Calculate `scale_qty = floor(current_qty / 2)`
   b. If `scale_qty >= 1` and no scale-out already done (check `orders` table for prior partial sells):
      - Call `place_order(symbol=SYMBOL, action="SELL", quantity=scale_qty, order_type="MKT")`
      - Log to `orders` with `strategy_id = "llm_news_sentiment"`, note="scale_out_50pct_at_15pct"
      - Update `strategy_positions` — reduce quantity, set `scaled_out = True`
      - Move stop to breakeven on remaining shares: call `modify_order(order_id=STOP_ORDER_ID, stop_price=ENTRY_PRICE)`
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Scanner Data Collection
1. Call `get_scanner_dates()` to confirm today's date is available
2. Collect top-20 symbols from the two primary scanners:
   - Call `get_scanner_results(scanner="SmallCap-GainSinceOpen", date=TODAY, top_n=20)`
   - Call `get_scanner_results(scanner="MidCap-GainSinceOpen", date=TODAY, top_n=20)`
   - Call `get_scanner_results(scanner="SmallCap-HotByVolume", date=TODAY, top_n=20)`
   - Call `get_scanner_results(scanner="MidCap-HotByVolume", date=TODAY, top_n=20)`
   - Also check LargeCap variants if needed
3. Deduplicate symbols — create a unified candidate list of up to 20 unique symbols appearing on GainSinceOpen AND/OR HotByVolume

### News Collection (per candidate symbol)
For each of the top-20 candidate symbols:

1. Call `get_news_headlines(symbol=SYMBOL, provider_codes="BRFG,DJNL,BRFUPDN", start=TODAY_OPEN, end=NOW, max_results=5)`
   - Collect up to 5 most recent headlines
   - If no headlines found, mark symbol as `no_news = True`

2. **Check sentiment cache** — skip scoring if `(symbol, headline_id)` was scored within the last 30 minutes

3. For headlines not in cache, **score via Claude API prompt:**
   ```
   Rate the following news headline for {SYMBOL} on a scale of -1.0 (extremely bearish) to +1.0 (extremely bullish).
   Consider: Is this a fundamental catalyst (earnings, FDA, contract, M&A)? Or noise (analyst opinion, sector rotation)?

   Headline: "{headline_text}"

   Respond with JSON: {"sentiment": float, "is_catalyst": bool, "catalyst_type": string, "confidence": float}
   ```

4. If sentiment score >= +0.5 and `is_catalyst = True`, fetch the full article for deeper analysis:
   - Call `get_news_article(provider_code=PROVIDER, article_id=ARTICLE_ID)`
   - Re-score with full article context for higher confidence

5. **Cache sentiment results** with 30-minute TTL: `{symbol, headline_id, sentiment, is_catalyst, catalyst_type, confidence, scored_at}`

### Volume & Extension Checks (per candidate)
For each candidate with positive sentiment:

1. Call `get_historical_bars(symbol=SYMBOL, duration="5 D", bar_size="1 day")` to get 5-day average volume
2. Call `get_quote(symbol=SYMBOL)` for current price and volume
3. Compute:
   - `volume_ratio = today_volume / avg_5day_volume` — must be > 2.0x
   - `extension_pct = (last_price - prev_close) / prev_close * 100` — must be <= 30%
4. Call `calculate_indicators(symbol=SYMBOL, indicators=["RSI","ATR","SMA"], duration="5 D", bar_size="5 mins", tail=5)` for technical context

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Sentiment Aggregation & Signal Logic
For each candidate symbol, compute the composite signal:

1. **Aggregate sentiment:**
   - `avg_sentiment = mean(all headline sentiments for symbol)`
   - `max_sentiment = max(all headline sentiments)`
   - `catalyst_count = count(headlines where is_catalyst = True)`

2. **Apply entry criteria — ALL must be TRUE:**
   - `avg_sentiment >= +0.5` — overall bullish sentiment
   - `catalyst_count >= 1` — at least one fundamental catalyst identified
   - `volume_ratio > 2.0` — volume confirms interest (> 2x average)
   - `extension_pct <= 30%` — not overextended (avoid chasing >30% moves)
   - Symbol appears on **at least one** of GainSinceOpen or HotByVolume scanners
   - `no_news = False` — must have news coverage

3. **Conviction scoring:**
   - Base score = `avg_sentiment * 100` (range 50-100)
   - +10 if on BOTH GainSinceOpen AND HotByVolume
   - +10 if `catalyst_type` is "earnings_beat", "fda_approval", "contract_win", or "acquisition"
   - +5 if `volume_ratio > 5.0`
   - -10 if `extension_pct > 20%`
   - -10 if RSI > 80

4. **Signal classification:**
   - **TRADE:** All criteria met, conviction >= 60
   - **WATCH:** Sentiment >= +0.3 but missing one criterion — log but do not trade
   - **SKIP:** Sentiment < +0.3 or multiple criteria failures

5. **Rank TRADE signals** by conviction score descending

6. **Log all candidates to `scanner_picks` table:**
   - symbol, scanner (primary scanner), rank, conviction_score, conviction_tier ("tier1" if TRADE else "rejected"), scanners_present, action="BUY", rejected flag, reject_reason, avg_sentiment, catalyst_type

7. Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, run these checks via `get_quote(symbol=SYMBOL)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Current volume >= 100,000 shares (higher bar for news-driven trades)
3. **Maximum spread:** (ask - bid) / last <= 2%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Not already held:** Check `get_positions()` for existing position
6. **Not already ordered:** Check `get_open_orders()` for pending order
7. **Extension recheck:** Verify `extension_pct <= 30%` at time of order (price may have moved since Phase 3)
8. **Sentiment freshness:** Verify sentiment was scored within the last 30 minutes

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **5** concurrent positions for this strategy
- **1.5% of account** per trade — compute quantity from account value and last price
- Re-entry allowed after full exit if new catalyst emerges

### Order Structure
For each approved TRADE signal (in conviction-descending order, up to position limit):

1. **Entry order:** Call `place_order(symbol=SYMBOL, action="BUY", quantity=QTY, order_type="MKT")`
2. **Stop loss:** Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="STP", stop_price=ENTRY * 0.92)` — 8% stop
3. **Scale-out target:** No limit order — scale-out is handled in Phase 2 at +15% via monitoring
   - Record `target_scale_price = ENTRY * 1.15` in `strategy_positions` for tracking

### For EVERY order placed, log to database:
1. **`scanner_picks` table:** symbol, scanner, rank, conviction_score, scanners_present, action="BUY", rejected=0, avg_sentiment, catalyst_type
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, stop_price, entry_price, status, strategy_id="llm_news_sentiment", sentiment_score, catalyst_type
3. **`strategy_positions` table:** strategy_id="llm_news_sentiment", symbol, action="BUY", quantity, entry_price, entry_order_id, stop_price, stop_order_id, target_scale_price, scanners_at_entry, conviction_score, avg_sentiment, catalyst_type, headline_ids (JSON array), sentiment_snapshot (JSON)

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position with `strategy_id = "llm_news_sentiment"` every run:

1. Call `get_quote(symbol=SYMBOL)` to get current price data
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distance_to_stop, distance_to_scale_target
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown_pct)
4. **Sentiment refresh:** Every 30 minutes (based on cache TTL), re-fetch headlines:
   - Call `get_news_headlines(symbol=SYMBOL, provider_codes="BRFG,DJNL,BRFUPDN", start=TODAY_OPEN, end=NOW, max_results=5)`
   - Re-score new headlines via Claude API
   - If `avg_sentiment` drops below 0.0 (turned bearish), flag for potential early exit
   - Log sentiment change in price_snapshots metadata
5. **Check for negative catalyst:** If a new headline scores <= -0.5, consider immediate exit:
   - Log warning, but do not auto-exit unless sentiment drops below -0.3 aggregate
6. **Scale-out monitoring:** Check if `pnl_pct >= 15%` — if so, Phase 2 will handle the scale-out on next cycle

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

### On Exit (stop hit, scale-out complete, sentiment reversal, or manual close)
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L:
   - `exit_reason` options: "stop_loss_8pct", "scale_out_50pct", "full_exit_sentiment_reversal", "full_exit_target", "eod_close", "manual"
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="llm_news_sentiment", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - avg_sentiment_at_entry, avg_sentiment_at_exit
   - catalyst_type, headline_summary
   - volume_ratio_at_entry
   - lesson text: analyze whether the LLM sentiment signal was correct, whether the catalyst materialized
3. Compute and log KPIs for `llm_news_sentiment` via `compute_and_log_kpis`
4. **Sentiment accuracy tracking:** Record whether the trade outcome aligned with the sentiment prediction:
   - `sentiment_correct = 1 if (sentiment > 0 and pnl > 0) or (sentiment < 0 and pnl < 0) else 0`
5. If significant lesson (catalyst was a false positive, or sentiment reversal caused loss), write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, headlines_scored, avg_sentiment, catalysts_found, summary
2. Log `strategy_runs` for `llm_news_sentiment` with cycle-specific metrics:
   - symbols_scanned, headlines_fetched, headlines_scored
   - avg_sentiment, catalysts_identified, signals_generated
   - positions_opened, positions_closed, scale_outs_executed
3. Compute `strategy_kpis` for `llm_news_sentiment` if any positions were closed:
   - win_rate, avg_win, avg_loss, profit_factor, expectancy
   - avg_hold_duration, max_drawdown
   - sentiment_accuracy (% of trades where sentiment direction matched P&L direction)
   - catalyst_hit_rate (% of identified catalysts that led to profitable trades)
   - avg_volume_ratio_winners vs avg_volume_ratio_losers
4. Call `complete_job_execution(exec_id, summary)` with a full summary

---

## Model Training / Retraining Schedule

### LLM Prompt Calibration
- **No traditional model training** — this strategy uses Claude API for sentiment scoring
- **Prompt calibration** should be reviewed weekly:
  - Analyze `sentiment_accuracy` from `strategy_kpis` — if below 60%, revise prompt
  - Check for systematic biases (e.g., consistently over-bullish on biotech)
  - Update catalyst type categories based on observed patterns

### Sentiment Cache Management
- Cache TTL: 30 minutes — headlines older than this are re-scored
- Cache is in-memory — resets on cron job restart
- Maximum cache size: 500 entries — evict oldest when full

### Historical Backtesting
- Weekly on Sundays: replay past week's scanner data + headlines
- Score all headlines that appeared during scanner runs
- Compare LLM sentiment scores with actual 1-hour forward returns
- Generate calibration report: `data/models/sentiment_calibration_report.json`

### Prompt Version Control
- Store prompt versions in `data/models/sentiment_prompts/v{N}.txt`
- Log prompt version used in each `strategy_runs` entry
- Never modify the active prompt mid-day

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each cron run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with sentiment scores (accepted & rejected) | Phase 4, 5 |
| `orders` | Every order placed with sentiment context | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with sentiment snapshots and catalyst data | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + sentiment history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary with headline/sentiment metrics | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with sentiment accuracy analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, sentiment accuracy, catalyst hit rate | Phase 2, 8 |

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_dates()` | Phase 3 — confirm today's data is available |
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect top-20 from GainSinceOpen + HotByVolume |
| `get_news_headlines(symbol, provider_codes, start, end, max_results)` | Phase 3 (initial collection), Phase 6 (sentiment refresh) |
| `get_news_article(provider_code, article_id)` | Phase 3 — fetch full article for high-sentiment headlines |
| `get_quote(symbol)` | Phase 3 (volume/extension), Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, duration, bar_size)` | Phase 3 — 5-day average volume computation |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | Phase 3 — RSI, ATR, SMA for technical context |
| `get_positions()` | Phase 1, Phase 5 — check current holdings |
| `get_portfolio_pnl()` | Phase 1, Phase 2 — P&L for risk management |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5 — prevent duplicates |
| `get_closed_trades(save_to_db=True)` | Phase 2 — reconcile trades closed by IB |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | Phase 2 (stops, scale-outs), Phase 5 (entries + stops) |
| `modify_order(order_id, quantity, limit_price, stop_price)` | Phase 2 — move stop to breakeven after scale-out |
| `get_strategy_positions(strategy_id, status, limit)` | Phase 2, Phase 5 — check strategy-specific positions |
| `get_strategy_kpis_report(strategy_id)` | Phase 8 — compute and review KPIs |
| `get_trading_lessons(limit)` | Phase 1 — load historical lessons |
| `get_scan_runs(limit)` | Phase 8 — log run summary |
| `get_job_executions(job_id, limit)` | Phase 1 — check for repeated failures |
| `get_position_price_history(position_id)` | Phase 6 — review price trajectory |
