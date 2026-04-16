---
noteId: "a28f3c9038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy-28, sentiment, composite-score, bayesian-optimization]

---

# Strategy 28: Sentiment-Weighted Scanner Composite Score — Operating Instructions

## Schedule

- **Live scoring:** Every 10 minutes during market hours 9:35 AM - 3:50 PM ET (`job_id = "sentiment_composite"`)
- **Weekly weight optimization:** Sunday 5 PM ET via Claude Code CronCreate (`job_id = "sentiment_composite_optimize"`)
- **End-of-day summary:** 4:05 PM ET

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- News: IB news via `get_news_headlines()` and `get_news_article()`
- Options flow: `get_option_chain()` and `get_option_quotes()` for institutional activity inference
- Minute bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="sentiment_composite")` to create a new execution record -- returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` -- apply all learned rules
2. **Load composite weights** (from latest `strategy_runs` with `run_type = "weight_optimization"`):
   - Initial defaults: Scanner=40%, News=25%, Social=15%, Institutional=20%
   - After first Bayesian optimization, use optimized weights
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check current open orders** via `get_open_orders()`
5. **Verify IB connection** -- if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Track active composite scores** for all monitored symbols (carry forward from prior run)
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY, runs FIRST)

**Before any new trades, enforce exit rules on ALL strategy-28 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="sentiment_composite", status="open")` to identify this strategy's positions
3. **Composite score exit:** For each open position, recompute composite score (see Phase 3):
   - If composite score drops below 50: `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   - Log with `exit_reason = "composite_below_50"`
4. **Hard stop:** For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` -- skip if SELL order already exists
   b. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   c. Log with `exit_reason = "hard_stop_5pct"`
5. Call `get_closed_trades(save_to_db=True)` to reconcile with IB
6. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Component 1: Scanner Score (0-100)

1. Pull all scanner types for all cap tiers:
   - `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=20)`
   - `get_scanner_results(scanner="TopGainers", date="YYYY-MM-DD", top_n=20)`
   - `get_scanner_results(scanner="HotByVolume", date="YYYY-MM-DD", top_n=20)`
   - `get_scanner_results(scanner="HotByPrice", date="YYYY-MM-DD", top_n=20)`
   - `get_scanner_results(scanner="MostActive", date="YYYY-MM-DD", top_n=20)`
   - `get_scanner_results(scanner="TopVolumeRate", date="YYYY-MM-DD", top_n=20)`
   - `get_scanner_results(scanner="HighOpenGap", date="YYYY-MM-DD", top_n=20)`
2. For each unique symbol, compute weighted rank sum:
   - Per scanner: `rank_score = max(0, 21 - rank)` (rank 1 = 20 pts, rank 20 = 1 pt, not present = 0)
   - Scanner weights: GainSinceOpen=2x, TopGainers=2x, HotByVolume=1.5x, others=1x
   - Penalty: -10 if on any loss scanner (LossSinceOpen, TopLosers)
   - Normalize to 0-100 scale: `scanner_score = min(100, raw_sum / max_possible_sum * 100)`

### Component 2: News Sentiment (0-100)

1. For each candidate symbol:
   - Call `get_news_headlines(symbol=SYM, provider_codes="BRFG,DJ", start="YYYY-MM-DDT09:00:00", end="YYYY-MM-DDT{now}", max_results=10)`
   - For each headline, call `get_news_article(provider_code=PROVIDER, article_id=ID)` (max 3 articles)
2. LLM sentiment scoring per article:
   - Very Positive = 100, Positive = 75, Neutral = 50, Negative = 25, Very Negative = 0
   - Recency weighting: articles in last 30 min get 2x weight, last hour 1.5x, older 1x
3. Aggregate: `news_sentiment = weighted_mean(article_scores)`
4. If no news found: `news_sentiment = 50` (neutral, does not block entry)

### Component 3: Social Buzz (0-100)

1. Proxy via scanner breadth and velocity:
   - Count number of distinct scanners the symbol appears on: `breadth`
   - Count consecutive scan cycles symbol has appeared: `persistence`
   - Rate of rank improvement over last 3 cycles: `velocity`
2. Score: `social_buzz = min(100, breadth * 15 + persistence * 10 + velocity * 20)`
3. This component approximates retail attention without external social data

### Component 4: Institutional Flow (0-100)

1. Call `get_option_chain(symbol=SYM)` to retrieve available expirations and strikes
2. For the nearest weekly expiration, call `get_option_quotes(symbol=SYM, expiration=EXP, strike=ATM, right="C")` and `get_option_quotes(symbol=SYM, expiration=EXP, strike=ATM, right="P")`
3. Compute put/call ratio and unusual volume indicators:
   - Call volume > 2x open interest = unusual bullish activity = 80-100
   - Call/Put ratio > 2.0 = bullish institutional flow = 70-90
   - Normal activity = 40-60
   - Put/Call ratio > 2.0 = bearish institutional flow = 10-30
   - No options available: `institutional_flow = 50` (neutral)
4. Adjust by option premium size: large premium (>$1) trades carry more weight

### Composite Score Calculation

```
composite = (scanner_score * w_scanner) + (news_sentiment * w_news) + (social_buzz * w_social) + (institutional_flow * w_institutional)
```

Where initial weights: `w_scanner=0.40, w_news=0.25, w_social=0.15, w_institutional=0.20`

Store all component scores and composite in `scanner_picks` metadata.

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Entry Signal Rules

A symbol qualifies for entry when ALL of the following are met:

1. **Composite score >= 80**
2. **No component below 30:**
   - Scanner Score >= 30
   - News Sentiment >= 30
   - Social Buzz >= 30
   - Institutional Flow >= 30
3. **Not already in portfolio** (check `get_positions()`)
4. **Not rejected by lesson rules** (scanner conflict, illiquid, etc.)

### Position Sizing (proportional to composite score)

| Composite Score | Account Allocation |
|----------------|--------------------|
| 80-84 | 1.0% |
| 85-89 | 1.25% |
| 90-94 | 1.5% |
| 95-100 | 2.0% |

### Candidate Ranking

If multiple symbols qualify, rank by composite score descending. Enter highest-scored first, up to max position limit.

### Signal Metadata

For each candidate, record in `scanner_picks`:
- `composite_score`, `scanner_score`, `news_sentiment`, `social_buzz`, `institutional_flow`
- `weights_used` (current optimization weights)
- `conviction_tier`: 95+ = "tier1_ultra", 90-94 = "tier1_high", 85-89 = "tier1", 80-84 = "tier2"
- `rejected` flag and `reject_reason` if any component < 30

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Pre-Order Quality Checks (MANDATORY)

For each qualifying candidate, run via `get_quote(symbol=SYM)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume today >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Max positions for this strategy:** 6 open positions maximum
6. **$5-$10 bracket check:** If price in $5-$10, require 2+ consecutive scanner appearances before entry
7. **Composite freshness:** Score must have been computed within the last 15 minutes

Log rejection reason to `scanner_picks` if any check fails.

### Order Placement

1. Call `get_quote(symbol=SYM)` for current price
2. Calculate quantity based on composite-proportional sizing:
   - `allocation_pct = size_from_score_table(composite_score)`
   - `qty = floor(account_value * allocation_pct / last_price)`
3. Entry order: `place_order(symbol=SYM, action="BUY", quantity=qty, order_type="MKT")`
4. Stop loss (5% below entry): `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="STP", stop_price=round(last_price * 0.95, 2))`
5. No fixed take-profit -- exit is composite-score-driven (Phase 2/7)

### Database Logging

For EVERY order placed, log to:
1. **`scanner_picks`:** symbol, all 4 component scores, composite_score, action="BUY", strategy_id="sentiment_composite"
2. **`orders`:** symbol, action, quantity, order_type, order_id, strategy_id="sentiment_composite"
3. **`strategy_positions`:** strategy_id="sentiment_composite", symbol, entry_price, stop_price, entry_composite_score, component_scores_at_entry

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-28 position, every 10-min cycle:

1. Call `get_quote(symbol=SYM)` for current bid/ask/last/volume
2. Log to `price_snapshots`: bid, ask, last, volume, unrealized P&L
3. **Recompute composite score** using current data (all 4 components):
   - Store updated composite in `price_snapshots` metadata
   - Track composite trajectory: rising, stable, or declining
4. **Composite alert levels:**
   - Composite drops below 60: tighten stop to 3% (modify existing stop order via `modify_order(order_id, stop_price=new_stop)`)
   - Composite drops below 50: EXIT (handled in Phase 2 next cycle, or immediately if detected here)
5. **Upside management:**
   - If unrealized P&L > 3%, trail stop to breakeven
   - If unrealized P&L > 5%, trail stop to +2%
6. **Component monitoring:** Flag if any single component drops below 20 (early warning)

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

### Exit Triggers (in priority order)

1. **Hard stop (5%):** Immediate market sell
2. **Composite below 50:** Market sell within current cycle
3. **Single component collapse (<20):** Market sell -- one rotten component invalidates thesis
4. **End of day (3:50 PM):** Close all remaining positions (no overnight hold)

### Exit Execution

1. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
2. Cancel any open stop orders: `cancel_order(order_id=STOP_ORDER_ID)`
3. Close position in `strategy_positions`:
   - `exit_price`, `exit_reason` (hard_stop / composite_below_50 / component_collapse / eod_close)
   - `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `exit_composite_score`, `exit_component_scores`
4. Log to `lessons` table:
   - Entry composite vs exit composite
   - Which component degraded most (scanner, news, social, institutional)
   - Time from peak composite to exit
   - Was composite decline predictive of price decline?
   - Lesson text summarizing what the composite model got right/wrong
5. Compute KPIs via `compute_and_log_kpis(strategy_id="sentiment_composite")`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="sentiment_composite" with:
   - Mean composite score of entries, mean composite at exits
   - Component contribution analysis: which component was most predictive this run
   - Weight effectiveness: predicted vs actual returns by component weight
3. Compute `strategy_kpis` for any closed positions:
   - Win rate, avg P&L, max drawdown, Sharpe ratio
   - **Composite-specific KPIs:** avg entry composite, avg exit composite, composite-P&L correlation, component predictive power rankings
4. Call `complete_job_execution(exec_id, summary)` with full run summary
5. Call `get_daily_kpis()` to compare against other strategies

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| Bayesian weight optimization | Weekly (Sunday 5 PM) | Optimize w_scanner, w_news, w_social, w_institutional to maximize Sharpe ratio |
| Component calibration | Weekly | Re-normalize each component's 0-100 scale based on rolling 20-day distribution |
| Backtested weight validation | Weekly | Compare optimized weights vs equal weights on holdout data (last 5 days) |
| News sentiment model review | Bi-weekly | Review LLM sentiment accuracy against actual price moves post-news |
| Institutional flow thresholds | Monthly | Re-calibrate put/call ratio and unusual volume thresholds |

### Bayesian Optimization Details (Sunday rebuild)

1. Objective function: Sharpe ratio of simulated returns using historical composite scores
2. Parameter space: `w_scanner in [0.2, 0.6]`, `w_news in [0.1, 0.4]`, `w_social in [0.05, 0.3]`, `w_institutional in [0.1, 0.4]`
3. Constraint: all weights sum to 1.0
4. Use 40 trading days of historical data from `strategy_positions` and `price_snapshots`
5. Gaussian process surrogate with Expected Improvement acquisition function
6. 50 iterations, select weights with highest expected Sharpe
7. Store optimized weights in `strategy_runs` with `run_type = "weight_optimization"`

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Candidates with all 4 component scores and composite | Phase 4, 5 |
| `orders` | Entry/exit orders with full details | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle with composite metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + composite score history each cycle | Phase 6 |
| `strategy_runs` | Per-run summary, weight optimization results | Phase 8, weekly rebuild |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with composite analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, component predictive power | Phase 2, 8 |

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` -- scanner score component
- `get_scanner_dates()` -- verify historical data for weight optimization
- `get_quote(symbol)` -- price checks, monitoring, quality gate
- `get_historical_bars(symbol, duration, bar_size)` -- volume confirmation
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` -- technical overlays
- `get_news_headlines(symbol, provider_codes, start, end, max_results)` -- news sentiment component
- `get_news_article(provider_code, article_id)` -- full article text for LLM sentiment
- `get_option_chain(symbol)` -- institutional flow component (available strikes/expirations)
- `get_option_quotes(symbol, expiration, strike, right)` -- put/call volume and OI for flow analysis
- `get_positions()` -- check current portfolio holdings
- `get_portfolio_pnl()` -- P&L monitoring and stop enforcement
- `get_open_orders()` -- prevent duplicate orders
- `get_closed_trades(save_to_db=True)` -- reconcile IB executions
- `place_order(symbol, action, quantity, order_type, stop_price)` -- entry and exit
- `cancel_order(order_id)` -- cancel stops on exit
- `modify_order(order_id, quantity, limit_price, stop_price)` -- tighten stops dynamically
- `get_strategy_positions(strategy_id="sentiment_composite", status, limit)` -- query positions
- `get_strategy_kpis_report(strategy_id="sentiment_composite")` -- performance review
- `get_job_executions(job_id="sentiment_composite", limit)` -- execution history
- `get_daily_kpis()` -- cross-strategy comparison
