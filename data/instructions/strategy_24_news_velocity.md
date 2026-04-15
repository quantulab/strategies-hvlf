---
noteId: "a3c24e0038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy, news, event-driven, scanner-confirmation, nlp]

---

# Strategy 24: News Event Velocity + Scanner Confirmation — Operating Instructions

## Schedule

Runs every **2 minutes** during market hours (9:32 AM – 3:50 PM ET) via Claude Code CronCreate.
Higher frequency than standard scanner cron because news events are time-sensitive. Positions must close by EOD (3:50 PM hard cutoff).

## Data Sources

- **News:** IB news feed via `get_news_headlines(symbol, provider_codes, start, end, max_results)` and `get_news_article(provider_code, article_id)`
- **Scanner CSVs:** `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- **Scanner Types (11):** GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- **Cap Tiers (3):** LargeCap, MidCap, SmallCap
- **Bar Data:** `D:\Data\Strategies\HVLF\MinuteBars_SB`
- **Database:** `D:\src\ai\mcp\ib\trading.db`
- **Lessons:** `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_24_news_velocity")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (0–8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Additional: `headlines_scanned`, `bursts_detected`, `scanner_confirmations`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply rules learned
2. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged `strategy_id = "news_velocity"` — if >= 2, skip to PHASE 6 (monitoring only)
3. **Check open orders** via `get_open_orders()`
4. **Count today's trades** for this strategy: query `orders` table for `strategy_id = "news_velocity"` and today's date
   - If >= 2 trades already placed today (max 2/day), skip to PHASE 6
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Time gate:** If current time > 3:00 PM ET, skip new entries. Only monitor/exit existing positions.
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management

Before any new trades, enforce risk rules on ALL strategy_24 positions.

1. Call `get_portfolio_pnl()` for current P&L
2. For each position with `strategy_id = "news_velocity"`:
   a. **Hard stop at -6%:**
      - If `pnl_pct <= -6.0%`:
        - Check `get_open_orders()` — skip if SELL order already exists
        - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
        - Close in `strategy_positions` with `exit_reason = "stop_loss_6pct"`
        - Log to `orders`, `lessons`
   b. **Take profit at +10%:**
      - If `pnl_pct >= +10.0%`:
        - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
        - Close with `exit_reason = "target_10pct"`
        - Log to `orders`, `lessons`
3. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. For every externally closed position, log to `lessons`, `strategy_positions`, `orders`
4. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=0, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 — News Headline Scanning

**Objective:** Detect headline bursts — symbols receiving >= 3 headlines within a 10-minute window.

1. **Build watchlist:** Get all symbols currently on any scanner via `get_scanner_results(scanner="ALL", date="YYYYMMDD", top_n=50)` across all tiers. Also include symbols from recent `scanner_picks` in the last 30 minutes.

2. **Poll headlines for each watchlist symbol:**
   - Call `get_news_headlines(symbol=SYMBOL, provider_codes="BRFG,DJNL,BRFUPDN", start="NOW-10min", end="NOW", max_results=10)`
   - Record: headline_count, timestamps, headline_texts, article_ids

3. **Burst detection logic:**
   - For each symbol, count distinct headlines in the last 10 minutes
   - **BURST DETECTED** if `headline_count >= 3` within a rolling 10-minute window
   - Track burst start time as timestamp of the 1st headline in the burst
   - Track burst intensity: `headline_count / 10` (headlines per minute)

4. **Headline sentiment pre-screen:**
   - For each burst, read the first 2 articles via `get_news_article(provider_code, article_id)`
   - Simple keyword sentiment:
     - **Positive keywords:** upgrade, beat, raise, approve, partnership, acquisition, contract, FDA approval, revenue growth, breakthrough
     - **Negative keywords:** downgrade, miss, cut, recall, lawsuit, investigation, dilution, bankruptcy, SEC, fraud
   - If majority negative keywords: mark burst as `sentiment = "negative"`, reject for entry
   - If majority positive or neutral: mark `sentiment = "positive"` or `sentiment = "neutral"`, proceed

### 3.2 — Scanner Confirmation

For each symbol with a detected burst AND positive/neutral sentiment:

1. Call `get_scanner_results(scanner="ALL", date="YYYYMMDD", top_n=50)` — get current snapshot
2. Check if the symbol appears on **>= 2 distinct scanner types** within the last 5 minutes of scanner data
3. For the HotByVolume scanner specifically:
   - Check current rank vs. rank from 2 snapshots ago (20 min prior)
   - **Rank improvement threshold:** rank must have improved by >= 5 positions (e.g., from rank 25 to rank 20 or better)
4. **CONFIRMATION = TRUE** if ALL of the following hold:
   - Symbol on >= 2 scanner types in last 5 min
   - Rank on HotByVolume improved by >= 5 positions
   - Symbol currently appears on HotByVolume (any tier)

### 3.3 — Feature Assembly

For confirmed candidates, collect:
- `headline_count`: total headlines in burst window
- `burst_intensity`: headlines per minute
- `sentiment`: positive/neutral
- `scanner_count`: number of distinct scanner types
- `volume_rank`: current rank on HotByVolume
- `volume_rank_delta`: rank improvement over last 2 snapshots
- `price`: via `get_quote(symbol)` — last, bid, ask, volume
- `rsi_5min`: via `calculate_indicators(symbol, indicators=["RSI"], duration="1 D", bar_size="5 mins", tail=3)`
- `spread_pct`: `(ask - bid) / last`

Call `update_job_execution(exec_id, phase_completed=3, headlines_scanned=N, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 — Rule-Based Signal (No ML Model)

This strategy uses deterministic rules rather than a trained model. The signal fires on event confluence:

**BUY SIGNAL when ALL conditions are met:**

| # | Condition | Threshold | Rationale |
|---|-----------|-----------|-----------|
| 1 | Headline burst | >= 3 headlines in 10 min | Significant news event detected |
| 2 | Sentiment | positive or neutral | Not a negative catalyst |
| 3 | Scanner breadth | >= 2 distinct scanner types | Market is reacting, not just news noise |
| 4 | HotByVolume presence | Currently ranked on HotByVolume | Volume confirming the move |
| 5 | Rank improvement | HotByVolume rank improved by >= 5 | Accelerating interest, not fading |
| 6 | Burst recency | Burst started < 15 min ago | Fresh event, not stale news |

### 4.2 — Conviction Scoring

- Base score = `headline_count` (3 = minimum, 10+ = very strong)
- +2 if sentiment is strongly positive (>= 3 positive keywords)
- +2 if scanner_count >= 4 (broad market reaction)
- +1 if volume_rank <= 5 (top of HotByVolume)
- -3 if symbol appears on LossSinceOpen or TopLosers
- -2 if spread_pct > 2%
- -1 if RSI > 80 (overbought risk)

**Minimum conviction for entry: 5**

### 4.3 — Logging

Log all candidates (accepted and rejected) to `scanner_picks`:
- `symbol`, `scanner="HotByVolume"`, `rank=volume_rank`, `conviction_score`, `headline_count`, `burst_intensity`, `sentiment`, `scanner_count`, `action="BUY"`, `rejected` flag, `reject_reason`, `strategy_id="news_velocity"`

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N, bursts_detected=N, scanner_confirmations=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** `last >= $2.00` — reject sub-$2
2. **Minimum volume:** Average daily volume >= 50,000 shares
3. **Maximum spread:** `(ask - bid) / last <= 3%`
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Daily trade limit:** Query `orders` table — max 2 trades per day for this strategy
6. **No duplicate positions:** Check `get_strategy_positions(strategy_id="news_velocity", status="open")` — reject if symbol already held
7. **News staleness:** Reject if burst started > 15 minutes ago (news is priced in)

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing

- **2% of total account value** per position
- Calculate shares: `floor(account_value * 0.02 / last_price)`
- Minimum 1 share

### Position Limits

- Maximum **2** concurrent positions for strategy_24
- Maximum **2** total trades per day for strategy_24

### Order Placement

For each accepted signal:

1. Call `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
   - Record `entry_order_id`, `entry_price`
2. Place bracket orders:
   - **Stop Loss:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=round(entry_price * 0.94, 2))` — 6% stop
   - **Take Profit:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="LMT", limit_price=round(entry_price * 1.10, 2))` — 10% target
3. Log to database:
   - `scanner_picks`: symbol, scanner="HotByVolume", rank, conviction_score, headline_count, burst_intensity, sentiment, action="BUY", rejected=0
   - `orders`: symbol, strategy_id="news_velocity", action="BUY", quantity, order_type="MKT", order_id, entry_price, status
   - `strategy_positions`: strategy_id="news_velocity", symbol, action="BUY", quantity, entry_price, stop_price, target_price, entry_order_id, stop_order_id, target_order_id, headline_count, burst_intensity, sentiment, scanner_count, scanners_at_entry

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open position with `strategy_id = "news_velocity"`:

1. **Price snapshot:** Call `get_quote(symbol)` — log to `price_snapshots`: bid, ask, last, volume, unrealized_pnl, pnl_pct, distance_to_stop, distance_to_target
2. **News follow-up:** Call `get_news_headlines(symbol=SYMBOL, provider_codes="BRFG,DJNL,BRFUPDN", start="NOW-5min", end="NOW", max_results=5)`
   - If new negative headlines appear (downgrade, miss, recall), consider early exit
   - If additional positive headlines appear, log as confirmation — hold position
3. **Scanner persistence check:** Call `get_scanner_results(scanner="HotByVolume", date="YYYYMMDD", top_n=50)`
   - If symbol dropped off HotByVolume entirely: flag as "volume fading" — tighten stop to -3% from current price
   - If symbol rank worsened by 10+ positions: flag as "momentum fading"
4. **EOD exit:** If current time >= 3:50 PM ET:
   - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
   - Cancel open stop/target orders via `cancel_order(order_id)`
   - Close in `strategy_positions` with `exit_reason = "eod_close"`
5. Update position extremes: peak, trough, MFE, MAE, drawdown from peak

### Profit Protection — Trailing Stop Ratchet (MANDATORY, every cycle)
**Lesson: AGAE 2026-04-15 lost +26% gain, exited at -7%. This check runs EVERY cycle for EVERY open position.**

For each position, compute `unrealized_pnl_pct` from entry price, then apply:

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +10% to +20% | Breakeven (entry price) |
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

On every exit (stop hit, target hit, EOD close, or manual):

1. Close position in `strategy_positions`:
   - `exit_price`, `exit_time`, `exit_reason`, `pnl`, `pnl_pct`, `hold_duration_minutes`
2. Log to `lessons` table:
   - symbol, strategy_id="news_velocity", action="BUY", entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - headline_count, burst_intensity, sentiment, scanner_count at entry
   - exit_reason
   - **News event analysis:** What was the catalyst? Did the move sustain? Was the burst a one-time pop or sustained interest?
   - lesson text: e.g., "ABCD had 5 headlines in 8 min (FDA approval), appeared on HotByVolume (rank 3) and TopGainers simultaneously. Entry at $12.50, exited at +10% target in 45 min. News velocity correctly signaled sustained momentum."
3. Compute and log KPIs via `get_strategy_kpis_report(strategy_id="news_velocity")`
4. Write a lesson file to `data/lessons/` for every trade (this strategy has low frequency, so every trade is worth documenting)

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: strategy_id="news_velocity", headlines_scanned, bursts_detected, scanner_confirmations, candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for this strategy's activity
3. Compute `strategy_kpis` if any positions were closed:
   - Win rate, avg win %, avg loss %, profit factor, expectancy
   - **News-specific metrics:**
     - Burst-to-trade conversion rate: % of detected bursts that led to trades
     - Avg headline count for winning vs. losing trades
     - Sentiment accuracy: % of positive-sentiment bursts that yielded positive P&L
     - Scanner confirmation reliability: % of confirmed signals that were profitable
     - Avg time from burst detection to entry
4. Call `complete_job_execution(exec_id, summary)` with full summary

---

## Model Training / Retraining Schedule

This strategy is rule-based, not ML-based. However, regular review of thresholds is required:

| Task | Frequency | Details |
|------|-----------|---------|
| **Threshold review** | Weekly | Analyze if burst threshold (3 headlines / 10 min) is optimal. Test 2, 3, 4, 5 on historical data |
| **Sentiment keyword update** | Bi-weekly | Review false positives/negatives. Add/remove keywords from positive/negative lists |
| **Scanner confirmation review** | Weekly | Analyze if "2 scanner types + rank improvement >= 5" is too strict or loose |
| **Provider performance** | Monthly | Compare headline coverage by provider (BRFG vs. DJNL vs. BRFUPDN). Drop providers with high latency or low coverage |
| **Full backtest** | Monthly | Replay last 60 days of news + scanner data. Compare live P&L vs. simulated |
| **Daily trade limit review** | Monthly | If win rate > 70%, consider increasing max from 2 to 3 trades/day |

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with headline_count, burst_intensity, sentiment | Phase 4, 5 |
| `orders` | Every order placed | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with news metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price/P&L history each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary with burst detection stats | Phase 8 |
| `lessons` | Exit lessons with news event analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, burst conversion rate, sentiment accuracy | Phase 7, 8 |

---

## MCP Tools Used

- `get_news_headlines(symbol, provider_codes, start, end, max_results)` — headline burst detection (polled every 2 min)
- `get_news_article(provider_code, article_id)` — read full article text for sentiment analysis
- `get_scanner_results(scanner, date, top_n)` — scanner confirmation checks
- `get_scanner_dates()` — verify available data
- `get_quote(symbol)` — quality gate, price monitoring, spread checks
- `get_historical_bars(symbol, duration, bar_size)` — supplementary price context
- `calculate_indicators(symbol, indicators=["RSI"], duration="1 D", bar_size="5 mins", tail=3)` — overbought detection
- `get_positions()` — current portfolio state
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — prevent duplicate orders
- `get_closed_trades(save_to_db=True)` — reconcile externally closed trades
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — entry and exit orders
- `cancel_order(order_id)` — cancel stop/target on EOD exit
- `get_strategy_positions(strategy_id="news_velocity", status="open")` — position count
- `get_strategy_kpis_report(strategy_id="news_velocity")` — KPI computation
- `get_trading_lessons(limit=50)` — load historical lessons
- `get_trading_orders(limit=20)` — check daily trade count
- `get_scan_runs(limit=10)` — recent scan history
- `get_job_executions(job_id="strategy_24_news_velocity", limit=5)` — execution history
- `get_daily_kpis()` — daily performance overview
- `get_position_price_history(position_id)` — full price trail
