---
noteId: "a27f3c9038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy-27, granger-causality, lead-lag, quantitative]

---

# Strategy 27: Causal Inference — Granger Lead-Lag Discovery — Operating Instructions

## Schedule

- **Weekly model rebuild:** Sunday 6 PM ET via Claude Code CronCreate (`job_id = "granger_lead_lag_rebuild"`)
- **Live trading:** Every 5 minutes during market hours 9:35 AM - 3:45 PM ET (`job_id = "granger_lead_lag"`)
- **End-of-day summary:** 4:05 PM ET

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types for causality graph: GainSinceOpen, HotByPrice, HotByPriceRange, HotByVolume, TopGainers, TopVolumeRate, MostActive
- Cap tiers: SmallCap, MidCap, LargeCap
- Minute bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="granger_lead_lag")` to create a new execution record -- returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` -- apply rules learned (gateway disconnect, accidental shorts, etc.)
2. **Load strategy parameters:**
   - Causality graph (rebuilt weekly, stored in `strategy_runs` metadata)
   - Leading scanner list and expected lag windows
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Confirm no more than 4 open positions for this strategy
4. **Check current open orders** via `get_open_orders()`
5. **Verify IB connection** -- if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Time gate:** Do not open new positions after 3:30 PM ET (insufficient hold time)
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management -- Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 3% stop-loss rule on ALL strategy-27 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="granger_lead_lag", status="open")` to identify this strategy's positions
3. For each position with `pnl_pct <= -3%`:
   a. Check `get_open_orders()` -- skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   c. Log to `orders` table with `strategy_id = "granger_lead_lag"`, `exit_reason = "stop_loss_3pct"`
   d. Close position in `strategy_positions` with exit details
   e. Log to `lessons` table with full trade context
4. For any position held longer than 15 minutes:
   a. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   b. Log with `exit_reason = "time_stop_15min"`
5. Call `get_closed_trades(save_to_db=True)` to reconcile with IB
6. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3A: Scanner Snapshot Collection (every 5-min run)

1. Call `get_scanner_results(scanner="HotByVolume", date="YYYY-MM-DD", top_n=20)` for all 3 cap tiers
2. Call `get_scanner_results(scanner="HotByPrice", date="YYYY-MM-DD", top_n=20)` for all 3 cap tiers
3. Call `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=20)` for all 3 cap tiers
4. Call `get_scanner_results(scanner="TopGainers", date="YYYY-MM-DD", top_n=20)` for all 3 cap tiers
5. Call `get_scanner_results(scanner="TopVolumeRate", date="YYYY-MM-DD", top_n=20)` for all 3 cap tiers
6. Call `get_scanner_results(scanner="MostActive", date="YYYY-MM-DD", top_n=20)` for all 3 cap tiers
7. Store snapshot with timestamp in `scan_runs` metadata

### 3B: Weekly Granger Causality Test (Sunday rebuild only)

**Pairwise Granger causality between all scanner type pairs:**

1. Collect 5 days of scanner snapshots (stored in `scan_runs`)
2. For each unique symbol that appeared across scanners:
   - Build binary time series for each scanner type: `S_i(t) = 1 if symbol in top-10 at time t`
   - Test Granger causality from scanner A to scanner B at lags 1-10 minutes
   - Record F-statistic and p-value for each (A, B, lag) triplet
3. Filter edges where p-value < 0.05
4. Build directed causality graph:
   - Nodes = scanner types
   - Edge weight = mean F-statistic across symbols
   - Edge label = optimal lag (minutes)
5. **Expected dominant edges:**
   - HotByVolume --> GainSinceOpen (lag 5-10 min)
   - HotByPrice --> TopGainers (lag 3-7 min)
   - TopVolumeRate --> HotByVolume (lag 1-3 min)
   - MostActive --> GainSinceOpen (lag 5-8 min)
6. Store causality graph in `strategy_runs` with `strategy_id = "granger_lead_lag"`, `run_type = "model_rebuild"`

### 3C: Leading Signal Detection (every 5-min run)

1. Load causality graph from latest rebuild
2. For each symbol currently in top-10 of a LEADING scanner:
   - Look up expected lag to LAGGING scanner
   - Check if symbol is NOT YET in top-10 of lagging scanner
   - If so, mark as a candidate with `signal_type = "leading"`, `expected_confirm_minutes = lag`
3. Collect candidate list with: symbol, leading_scanner, lag, timestamp_first_seen

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Signal Scoring

For each candidate from Phase 3C:

1. **Leading scanner strength:**
   - Rank on leading scanner (top-3 = strong, top-5 = moderate, top-10 = weak)
   - Score: top-3 = +3, top-5 = +2, top-10 = +1
2. **Causality edge strength:**
   - F-statistic of the (leading_scanner --> lagging_scanner) edge
   - Score: F > 10 = +3, F > 5 = +2, F > 2 = +1
3. **Lag consistency:**
   - How consistent is the lag across historical observations?
   - StdDev of lag < 2 min = +2, < 4 min = +1, else 0
4. **Price confirmation:**
   - Call `get_quote(symbol=SYM)`
   - Price trending up (last > open) = +1, else 0
   - Call `calculate_indicators(symbol=SYM, indicators=["RSI", "VWAP"], duration="1 D", bar_size="1 min", tail=20)`
   - RSI between 40-70 = +1 (not overbought, not oversold)
   - Price above VWAP = +1
5. **Volume confirmation:**
   - Call `get_historical_bars(symbol=SYM, duration="1 D", bar_size="1 min")`
   - Current volume > 1.5x average = +1

**Total signal score: sum of all components (max 12)**

### Signal Threshold

- **Score >= 7:** ENTER -- strong leading signal with confirmation
- **Score 5-6:** WATCHLIST -- monitor for next cycle
- **Score < 5:** REJECT -- insufficient evidence

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Pre-Order Quality Checks (MANDATORY)

For each candidate scoring >= 7, run these checks via `get_quote(symbol=SYM)`:

1. **Minimum price:** Last price >= $2.00 -- reject sub-$2 stocks
2. **Minimum volume:** Volume today >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Not already in portfolio:** Check `get_positions()` for existing position
6. **Position limit:** Max 4 open positions for this strategy
7. **Confirm leading scanner appearance is < 10 minutes old** (signal freshness)

Log rejection reason to `scanner_picks` table if any check fails.

### Position Sizing

- **Fixed allocation:** 1% of account per position
- No scaling by signal score -- all qualifying trades get equal size

### Order Placement

1. Call `get_quote(symbol=SYM)` for current price
2. Calculate quantity: `qty = floor(account_value * 0.01 / last_price)`
3. Entry order: `place_order(symbol=SYM, action="BUY", quantity=qty, order_type="MKT")`
4. Stop loss (3% below entry): `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="STP", stop_price=round(last_price * 0.97, 2))`
5. Time stop: record `max_hold_time = entry_time + 15 minutes` in `strategy_positions`

### Database Logging

For EVERY order placed, log to:
1. **`scanner_picks`:** symbol, scanner (leading scanner name), rank, conviction_score (signal score), action="BUY", strategy_id="granger_lead_lag"
2. **`orders`:** symbol, action, quantity, order_type, order_id, strategy_id="granger_lead_lag"
3. **`strategy_positions`:** strategy_id="granger_lead_lag", symbol, entry_price, stop_price, scanners_at_entry (leading + expected lagging), expected_confirm_scanner, expected_lag_minutes

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-27 position, every 5-min cycle:

1. Call `get_quote(symbol=SYM)` for current bid/ask/last/volume
2. Log to `price_snapshots`: bid, ask, last, volume, unrealized P&L, distance to stop
3. **Check lagging scanner confirmation:**
   - Call `get_scanner_results(scanner=LAGGING_SCANNER, date="YYYY-MM-DD", top_n=20)`
   - If symbol NOW appears in top-10 of the lagging scanner: mark `lagging_confirmed = true`
   - This is the expected exit signal (see Phase 7)
4. **Check time stop:** If `current_time > entry_time + 15 minutes`, flag for exit
5. **Check 3% stop:** If unrealized P&L <= -3%, flag for immediate exit
6. **Trail stop:** If P&L > +2%, move stop to breakeven (entry price)

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

1. **Stop loss hit (3%):** Immediate market sell
2. **Time stop (15 min):** Market sell
3. **Lagging scanner confirmation:** When symbol appears on expected lagging scanner, sell within 1-2 minutes
   - This is the primary profit-taking mechanism -- the thesis is complete
4. **End of day (3:45 PM):** Close all remaining positions

### Exit Execution

1. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
2. Cancel any open stop orders: `cancel_order(order_id=STOP_ORDER_ID)`
3. Close position in `strategy_positions`:
   - `exit_price`, `exit_reason` (stop_loss / time_stop / lagging_confirmed / eod_close)
   - `pnl`, `pnl_pct`, `hold_duration_minutes`
4. Log to `lessons` table:
   - Was the lagging scanner confirmation observed? (Y/N)
   - Time between leading signal and lagging confirmation (actual vs expected lag)
   - P&L at moment of lagging confirmation vs exit
   - Lesson text: what worked or failed about the causal inference
5. Compute KPIs via `compute_and_log_kpis(strategy_id="granger_lead_lag")`
6. If notable outcome (P&L > 3% or < -3%), write detailed lesson to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="granger_lead_lag" with:
   - Leading signals detected, lagging confirmations observed
   - Causality graph edge utilization (which edges triggered trades)
   - Mean actual lag vs expected lag
3. Compute `strategy_kpis` for any closed positions:
   - Win rate, avg P&L, max drawdown, Sharpe ratio, avg hold time
   - **Causality-specific KPIs:** confirmation rate (% of leading signals that produced lagging confirmation), lag accuracy (actual vs expected), edge profitability (P&L by causality edge)
4. Call `complete_job_execution(exec_id, summary)` with full run summary
5. Call `get_daily_kpis()` to compare against other strategies

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| Granger causality rebuild | Weekly (Sunday 6 PM) | Pairwise tests across all scanner pairs, lags 1-10 min |
| Causality graph pruning | Weekly | Remove edges with p-value > 0.10 or < 5 supporting observations |
| Lag window calibration | Weekly | Update expected lag per edge based on rolling 10-day median |
| Edge strength decay | Daily | Reduce F-statistic confidence by 10% per day without confirmation |
| Full backtest | Monthly | Re-run on 40-day history, validate edge stability |

**Retraining data requirements:**
- Minimum 5 trading days of scanner snapshots (5-min intervals)
- Minimum 20 unique symbols per scanner pair for reliable causality test
- Use `get_scanner_dates()` to verify data availability

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Leading signal candidates (accepted & rejected) | Phase 4, 5 |
| `orders` | Entry/exit orders with full details | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle with causality metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history each cycle per position | Phase 6 |
| `strategy_runs` | Per-run summary with causality graph stats | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with causality analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, confirmation rate, lag accuracy | Phase 2, 8 |

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` -- collect scanner snapshots for causality analysis
- `get_scanner_dates()` -- verify available historical data for model rebuild
- `get_quote(symbol)` -- price confirmation and position monitoring
- `get_historical_bars(symbol, duration, bar_size)` -- volume analysis
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` -- RSI, VWAP for signal scoring
- `get_positions()` -- check current portfolio holdings
- `get_portfolio_pnl()` -- P&L monitoring and stop-loss enforcement
- `get_open_orders()` -- prevent duplicate orders and verify stops
- `get_closed_trades(save_to_db=True)` -- reconcile IB executions with DB
- `place_order(symbol, action, quantity, order_type, stop_price)` -- entry and exit execution
- `cancel_order(order_id)` -- cancel stops on exit
- `get_strategy_positions(strategy_id="granger_lead_lag", status, limit)` -- query strategy positions
- `get_strategy_kpis_report(strategy_id="granger_lead_lag")` -- performance review
- `get_job_executions(job_id="granger_lead_lag", limit)` -- execution history
- `get_daily_kpis()` -- cross-strategy comparison
