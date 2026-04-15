---
noteId: "a1c22e0038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy, ml, cnn, scanner-heatmap, deep-learning]

---

# Strategy 22: CNN on Scanner Heatmaps — Operating Instructions

## Schedule

Runs every 10 minutes during market hours (9:40 AM – 3:00 PM ET) via Claude Code CronCreate.
Model inference triggered when a new scanner snapshot arrives. Positions force-closed at 3:00 PM ET.

## Data Sources

- **Scanner CSVs:** `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- **Scanner Types (11):** GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- **Cap Tiers:** LargeCap, MidCap, SmallCap
- **Bar Data:** `D:\Data\Strategies\HVLF\MinuteBars_SB`
- **Database:** `D:\src\ai\mcp\ib\trading.db`
- **Strategies:** `D:\src\ai\mcp\ib\data\strategies\`
- **Lessons:** `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_22_cnn_heatmap")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (0–8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply rules learned (cut losers, conflict filters, gateway checks)
2. **Load strategy file** `data/strategies/` — verify no strategy-level overrides or pauses
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged `strategy_id = "cnn_heatmap"` — if >= 4, skip to PHASE 6 (monitoring only)
4. **Check open orders** via `get_open_orders()` — identify any pending fills for this strategy
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Time gate:** If current time > 2:30 PM ET, skip new entries (not enough runway for 30-min target horizon). Proceed to PHASE 6 only.
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management

Before any new trades, enforce stop-loss rules on ALL strategy_22 positions.

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each position with `strategy_id = "cnn_heatmap"`:
   a. If `pnl_pct <= -3.0%` (strategy-specific stop):
      - Check `get_open_orders()` — skip if a SELL order already exists for this symbol
      - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
      - Log to `orders` table with `strategy_id = "cnn_heatmap"`, full order details
      - Close in `strategy_positions` with `exit_reason = "stop_loss_3pct"`
      - Log to `lessons` table with entry/exit prices, P&L, hold duration, lesson text
   b. If `pnl_pct >= +2.5%` (strategy-specific target):
      - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
      - Close in `strategy_positions` with `exit_reason = "target_2_5pct"`
      - Log to `lessons` table
3. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` — get all completed executions from IB
   b. For every position that disappeared externally, log to `lessons`, `strategy_positions`, `orders`
4. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=0, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 — Collect Scanner Snapshots

1. Call `get_scanner_results(scanner="ALL", date="YYYYMMDD", top_n=120)` for all 11 scanner types across all 3 cap tiers
2. Build a **rank matrix** per symbol per snapshot:
   - Rows: 11 scanner types (GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate)
   - Columns: 120 timesteps (one per scanner snapshot, ~10-min intervals covering the full day so far)
   - Cell value: normalized rank in [0, 1] where 0 = not present, 1 = rank #1

### 3.2 — Render Heatmap Images

For each candidate symbol currently appearing on HotByVolume:

1. Extract the 11×120 rank matrix for the last 3 hours (18 snapshots × 10 min = 180 min)
2. Segment into three 1-hour blocks:
   - **Red channel:** Hour T-3 to T-2 (6 snapshots, interpolated to 120 columns)
   - **Green channel:** Hour T-2 to T-1 (6 snapshots, interpolated to 120 columns)
   - **Blue channel:** Hour T-1 to T-0 (6 snapshots, interpolated to 120 columns)
3. Stack into a 3-channel (RGB) image of shape 11×120×3
4. Resize to 224×224 via bicubic interpolation for ResNet-18 input

### 3.3 — Supplementary Features

For each candidate, also collect:
- Current price via `get_quote(symbol)` — extract last, bid, ask, volume
- 5-min RSI and VWAP via `calculate_indicators(symbol, indicators=["RSI", "VWAP"], duration="1 D", bar_size="5 mins", tail=5)`
- Spread percentage: `(ask - bid) / last`
- Time-of-day encoding: minutes since 9:30 AM / 390

### 3.4 — Filter to HotByVolume Only

Only symbols currently appearing on any HotByVolume scanner (LargeCap, MidCap, or SmallCap) are eligible for CNN inference. Discard all others.

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 — ResNet-18 Forward Pass

For each candidate heatmap image:

1. Load the fine-tuned ResNet-18 model from `D:\src\ai\mcp\ib\models\resnet18_scanner_heatmap.pt`
2. Run inference: input = 224×224×3 image tensor (normalized to ImageNet stats)
3. Output: sigmoid probability `p` that the symbol gains +2% within the next 30 minutes

### 4.2 — Signal Threshold

- If `p >= 0.72`: **SIGNAL = BUY** — candidate passes to PHASE 5
- If `0.60 <= p < 0.72`: **WATCHLIST** — log to `scanner_picks` with `rejected = 1`, `reject_reason = "prob_below_threshold"`, record probability for model monitoring
- If `p < 0.60`: **DISCARD** — no log needed

### 4.3 — Conviction Scoring

For each BUY signal, compute conviction score:
- Base score = `round(p * 10)` (so p=0.72 yields score 7, p=0.95 yields score 10)
- +1 if symbol appears on 3+ scanner types simultaneously
- +1 if rank on HotByVolume improved by 5+ positions in last 2 snapshots
- -2 if symbol appears on ANY loss scanner (LossSinceOpen, TopLosers)
- -1 if spread > 2%

**Only proceed if final conviction score >= 7.**

Log all candidates (accepted and rejected) to `scanner_picks` with: symbol, scanner="HotByVolume", rank, conviction_score, `model_prob=p`, action="BUY", rejected flag, reject_reason

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** `last >= $2.00` — reject sub-$2 stocks
2. **Minimum volume:** Average daily volume >= 50,000 shares — reject illiquid
3. **Maximum spread:** `(ask - bid) / last <= 3%` — reject wide spreads
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **No loss-scanner conflict:** Symbol must NOT appear on LossSinceOpen or TopLosers at time of entry

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing

- **1% of total account value** per position
- Calculate shares: `floor(account_value * 0.01 / last_price)`
- Minimum 1 share, no fractional shares

### Position Limits

- Maximum **4** concurrent positions for strategy_22
- Check existing strategy_22 positions via `get_strategy_positions(strategy_id="cnn_heatmap", status="open")` — if count >= 4, reject with `reject_reason = "max_positions_reached"`

### Order Placement

For each accepted signal:

1. Call `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
   - Record `entry_order_id`
2. Immediately place bracket orders:
   - **Stop Loss:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=round(entry_price * 0.97, 2))`  — 3% stop
   - **Take Profit:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="LMT", limit_price=round(entry_price * 1.025, 2))` — 2.5% target
3. Log to database:
   - `scanner_picks`: symbol, scanner, rank, conviction_score, model_prob, action="BUY", rejected=0
   - `orders`: symbol, strategy_id="cnn_heatmap", action="BUY", quantity, order_type, order_id, entry_price, status
   - `strategy_positions`: strategy_id="cnn_heatmap", symbol, action="BUY", quantity, entry_price, stop_price, target_price, entry_order_id, stop_order_id, target_order_id, model_prob, conviction_score, scanners_at_entry

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open position with `strategy_id = "cnn_heatmap"`:

1. Call `get_quote(symbol)` — get current bid, ask, last, volume
2. Log `price_snapshots`: symbol, bid, ask, last, volume, unrealized_pnl, pnl_pct, distance_to_stop, distance_to_target, model_prob_at_entry
3. Update position extremes: peak price, trough price, MFE (max favorable excursion), MAE (max adverse excursion), current drawdown from peak
4. **Time-based exit check:** If current time >= 3:00 PM ET and position is still open:
   - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
   - Cancel any open stop/limit orders via `cancel_order(order_id)` for the stop and target orders
   - Close in `strategy_positions` with `exit_reason = "eod_close_3pm"`
   - Log to `lessons` table
5. **30-minute expiry check:** If position has been held > 30 minutes and P&L is between -1% and +1% (stagnant):
   - Consider closing at market — the 30-min prediction window has expired
   - Close with `exit_reason = "signal_expired_30min"`

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

On every exit (stop hit, target hit, time expiry, or manual close):

1. Close position in `strategy_positions`:
   - `exit_price`, `exit_time`, `exit_reason`, `pnl`, `pnl_pct`, `hold_duration_minutes`
2. Log to `lessons` table:
   - symbol, strategy_id="cnn_heatmap", action="BUY", entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - model_prob at entry, conviction_score, scanner that triggered entry
   - exit_reason
   - lesson text: e.g., "CNN prob 0.78, actual move +2.3% in 22 min — model correctly predicted momentum burst from HotByVolume rank improvement"
3. Compute and log KPIs via `get_strategy_kpis_report(strategy_id="cnn_heatmap")`
4. If the trade was a significant win (>2%) or loss (>-2%), write a markdown lesson file to `data/lessons/` with detailed analysis

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: strategy_id="cnn_heatmap", candidates_found, candidates_rejected, orders_placed, positions_held, heatmaps_generated, avg_model_prob, summary
2. Log `strategy_runs` for this strategy's activity this cycle
3. Compute `strategy_kpis` if any positions were closed:
   - Win rate, avg win %, avg loss %, profit factor, expectancy
   - Model calibration: avg predicted prob vs. actual hit rate for +2% in 30 min
4. Call `complete_job_execution(exec_id, summary)` with a full summary including: heatmaps processed, signals generated, orders placed, positions monitored, exits triggered

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| **Data collection** | Continuous | Every scanner snapshot is stored; heatmaps generated and cached daily |
| **Label generation** | Nightly | For each heatmap, check if symbol gained +2% within 30 min of snapshot time using bar data from `D:\Data\Strategies\HVLF\MinuteBars_SB` |
| **Model retraining** | Weekly (Sunday) | Fine-tune ResNet-18 on last 30 days of labeled heatmaps. Train/val split: 80/20 by date. Early stopping on val AUC, patience=5 |
| **Threshold calibration** | Weekly | Adjust the 0.72 threshold to maintain precision >= 60% on validation set. Log new threshold to `strategy_kpis` |
| **Backtest** | Monthly | Full backtest on last 90 days. Compare live P&L vs. simulated. Flag if divergence > 20% |

**Model artifact path:** `D:\src\ai\mcp\ib\models\resnet18_scanner_heatmap.pt`
**Training logs:** `D:\src\ai\mcp\ib\models\training_logs\strategy_22\`

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run with operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate found — accepted and rejected with model_prob | Phase 4, 5 |
| `orders` | Every order placed with full details | Phase 2, 5 |
| `strategy_positions` | Position lifecycle: open → monitor → close | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price/P&L history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with P&L, model_prob, and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, model calibration, expectancy | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — collect scanner rank data for heatmap construction
- `get_scanner_dates()` — verify available scanner data dates
- `get_quote(symbol)` — quality gate checks and position monitoring
- `get_historical_bars(symbol, duration, bar_size)` — supplementary price context
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — RSI, VWAP for feature engineering
- `get_positions()` — current portfolio state
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — prevent duplicate orders and check for existing stops
- `get_closed_trades(save_to_db=True)` — reconcile externally closed trades
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — entry and exit orders
- `cancel_order(order_id)` — cancel stale stop/target orders on time-based exit
- `get_strategy_positions(strategy_id="cnn_heatmap", status="open")` — position count check
- `get_strategy_kpis_report(strategy_id="cnn_heatmap")` — KPI computation
- `get_trading_lessons(limit=50)` — load historical lessons for pre-trade checklist
- `get_scan_runs(limit=10)` — recent scan history
- `get_job_executions(job_id="strategy_22_cnn_heatmap", limit=5)` — execution history
- `get_daily_kpis()` — daily performance overview
- `get_position_price_history(position_id)` — full price trail for post-trade analysis
