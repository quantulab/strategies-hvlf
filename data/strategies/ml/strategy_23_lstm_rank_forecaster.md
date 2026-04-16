---
noteId: "a2c23e0038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy, ml, lstm, rank-forecasting, deep-learning]

---

# Strategy 23: LSTM Rank Forecaster — Operating Instructions

## Schedule

Runs every 10 minutes during market hours (9:40 AM – 4:00 PM ET) via Claude Code CronCreate.
Model inference on every cycle. Positions force-closed after 45 minutes or at 3:45 PM ET (whichever comes first).

## Data Sources

- **Scanner CSVs:** `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- **Scanner Types (11):** GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- **Cap Tiers (3):** LargeCap, MidCap, SmallCap
- **Bar Data:** `D:\Data\Strategies\HVLF\MinuteBars_SB`
- **Database:** `D:\src\ai\mcp\ib\trading.db`
- **Lessons:** `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_23_lstm_rank")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (0–8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply cut-losers, conflict-filter, gateway-check rules
2. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged `strategy_id = "lstm_rank"` — if >= 3, skip to PHASE 6 (monitoring only)
3. **Check open orders** via `get_open_orders()` — identify pending fills for this strategy
4. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
5. **Time gate:** If current time > 3:00 PM ET, skip new entries. Proceed to PHASE 6 monitoring only.
6. **Minimum history check:** Verify at least 60 scanner snapshots are available for the current day (10 hours × 6/hr = 60). If fewer than 60 snapshots exist (early in the day), use all available and pad with zeros. Do NOT enter trades before 10:30 AM ET (minimum 6 snapshots needed for meaningful lookback).
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management

Before any new trades, enforce risk rules on ALL strategy_23 positions.

1. Call `get_portfolio_pnl()` for current P&L on every position
2. For each position with `strategy_id = "lstm_rank"`:
   a. **Hard stop at -5%:**
      - If `pnl_pct <= -5.0%`:
        - Check `get_open_orders()` — skip if SELL order already exists
        - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
        - Close in `strategy_positions` with `exit_reason = "stop_loss_5pct"`
        - Log to `orders` and `lessons` tables
   b. **45-minute time expiry:**
      - If position held > 45 minutes and not yet exited:
        - Close at market with `exit_reason = "time_expiry_45min"`
        - Log to `orders`, `strategy_positions`, `lessons`
3. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. For every externally closed position, log to `lessons`, `strategy_positions`, `orders`
4. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=0, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 — Build Feature Tensor

For each symbol currently appearing on ANY scanner, construct the feature tensor:

**Per-timestep feature vector (27 features):**

| Feature # | Name | Description | Source |
|-----------|------|-------------|--------|
| 1–11 | `rank_scanner_1..11` | Normalized rank on each of 11 scanner types. 0 if not present, `1 - (rank / top_n)` if present | `get_scanner_results(scanner, date, top_n=120)` |
| 12–22 | `rank_velocity_1..11` | Change in rank from previous timestep for each scanner. Positive = improving. 0 if no change or not present | Computed from consecutive snapshots |
| 23–25 | `time_sin`, `time_cos`, `time_linear` | Sinusoidal and linear encoding of time-of-day. `sin(2π × min_since_930 / 390)`, `cos(2π × min_since_930 / 390)`, `min_since_930 / 390` | System clock |
| 26 | `cap_tier` | One-hot-ish encoding: LargeCap=1.0, MidCap=0.5, SmallCap=0.0 | Scanner filename tier |
| 27 | `scanner_breadth` | Count of distinct scanner types the symbol appears on, normalized to [0, 1] by dividing by 11 | Computed from current snapshot |

**Lookback window:** 60 timesteps (most recent 60 scanner snapshots, ~10 hours at 10-min intervals)

**Final tensor shape per symbol:** `(60, 27)` — 60 timesteps × 27 features

### 3.2 — Candidate Filter

Only build tensors for symbols meeting ALL criteria:
- Currently ranked > 15 on GainSinceOpen (any cap tier) — this is the "current rank >15" entry condition
- Has appeared on at least 1 scanner in at least 10 of the last 60 snapshots (not a flash-in-the-pan)
- Not currently held as a strategy_23 position

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 — BiLSTM Forward Pass

For each candidate feature tensor:

1. Load the BiLSTM model from `D:\src\ai\mcp\ib\models\bilstm_rank_forecaster.pt`
   - Architecture: 2-layer BiLSTM, hidden_size=128, dropout=0.3, followed by FC → 1 output
   - Input: `(batch, 60, 27)` tensor
   - Output: predicted rank on GainSinceOpen scanner 30 minutes ahead (continuous value 1–120)
2. Run inference: `predicted_rank = model(feature_tensor)`

### 4.2 — Entry Signal Logic

**BUY signal fires when BOTH conditions are met:**
- `predicted_rank <= 5` — model predicts the symbol will enter top-5 on GainSinceOpen within 30 min
- `current_rank > 15` — the symbol is NOT already in the top-15 (capturing the move before it happens)

**Signal strength = 15 - predicted_rank** (higher is better, range 10–14 for valid signals)

### 4.3 — Rejection Criteria

Reject the signal if:
- Symbol appears on LossSinceOpen or TopLosers (any tier) — conflicting momentum
- `predicted_rank > 5` — model not confident enough
- `current_rank <= 15` — already near the top, limited upside
- Signal strength < 10 (predicted_rank > 5)

Log all candidates to `scanner_picks`:
- `symbol`, `scanner="GainSinceOpen"`, `rank=current_rank`, `predicted_rank`, `signal_strength`, `action="BUY"`, `rejected` flag, `reject_reason`, `strategy_id="lstm_rank"`

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** `last >= $2.00` — reject sub-$2 stocks
2. **Minimum volume:** Average daily volume >= 50,000 shares
3. **Maximum spread:** `(ask - bid) / last <= 3%`
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Existing position check:** Call `get_strategy_positions(strategy_id="lstm_rank", status="open")` — reject if symbol already held

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing

- **1.5% of total account value** per position
- Calculate shares: `floor(account_value * 0.015 / last_price)`
- Minimum 1 share

### Position Limits

- Maximum **3** concurrent positions for strategy_23
- If count >= 3, reject with `reject_reason = "max_positions_reached"`

### Order Placement

For each accepted signal:

1. Call `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
   - Record `entry_order_id` and `entry_price` (fill price)
2. Place stop-loss order:
   - `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=round(entry_price * 0.95, 2))` — 5% stop
3. **No take-profit limit order** — exit is rank-based (see PHASE 6) or time-based (45 min)
4. Record entry timestamp for time-expiry tracking
5. Log to database:
   - `scanner_picks`: symbol, scanner="GainSinceOpen", rank=current_rank, predicted_rank, signal_strength, action="BUY", rejected=0
   - `orders`: symbol, strategy_id="lstm_rank", action="BUY", quantity, order_type="MKT", order_id, entry_price, status="FILLED"
   - `strategy_positions`: strategy_id="lstm_rank", symbol, action="BUY", quantity, entry_price, stop_price, entry_order_id, stop_order_id, predicted_rank, current_rank_at_entry, signal_strength, entry_timestamp

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open position with `strategy_id = "lstm_rank"`:

1. **Price snapshot:** Call `get_quote(symbol)` — log to `price_snapshots` with bid, ask, last, volume, unrealized_pnl, pnl_pct
2. **Rank check:** Call `get_scanner_results(scanner="GainSinceOpen", date="YYYYMMDD", top_n=10)` for all cap tiers
   - If symbol appears in top-5 on GainSinceOpen (any tier):
     - **EXIT — predicted rank achieved**
     - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
     - Cancel the stop order via `cancel_order(stop_order_id)`
     - Close in `strategy_positions` with `exit_reason = "rank_target_hit_top5"`
     - Log actual rank achieved, time to achievement, P&L
3. **Time expiry:** If `minutes_since_entry >= 45`:
   - Exit at market with `exit_reason = "time_expiry_45min"`
   - Cancel stop order
4. **EOD exit:** If current time >= 3:45 PM ET:
   - Exit all remaining positions with `exit_reason = "eod_close_345pm"`
   - Cancel all associated stop orders
5. Update position extremes: peak, trough, MFE, MAE, drawdown from peak

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

On every exit (stop hit, rank target achieved, time expiry, or EOD close):

1. Close position in `strategy_positions`:
   - `exit_price`, `exit_time`, `exit_reason`, `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `predicted_rank` vs `actual_rank_at_exit` — record for model calibration
2. Log to `lessons` table:
   - symbol, strategy_id="lstm_rank", action="BUY", entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - predicted_rank, actual_rank_at_exit, current_rank_at_entry
   - exit_reason
   - lesson text: e.g., "LSTM predicted rank 3 for ABCD (current rank 22). Actual rank hit 4 in 18 min, +3.1% gain. Model correctly identified momentum acceleration from scanner breadth increase."
3. Compute and log KPIs via `get_strategy_kpis_report(strategy_id="lstm_rank")`
4. If rank prediction was off by > 10 positions, write a lesson file to `data/lessons/` analyzing why

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: strategy_id="lstm_rank", candidates_found, candidates_rejected, orders_placed, positions_held, avg_predicted_rank, avg_signal_strength, summary
2. Log `strategy_runs` for this strategy's activity
3. Compute `strategy_kpis` if any positions were closed:
   - Win rate, avg win %, avg loss %, profit factor, expectancy
   - **Model-specific metrics:**
     - Mean absolute error: avg `|predicted_rank - actual_rank_at_exit|`
     - Rank prediction accuracy: % of times predicted rank <= 5 AND actual rank <= 5
     - Time-to-target: avg minutes for rank to hit top-5 (for winning trades)
4. Call `complete_job_execution(exec_id, summary)` with full summary

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| **Data collection** | Continuous | Every scanner snapshot stored; feature tensors built and cached per symbol per day |
| **Label generation** | Nightly | For each (symbol, timestep), record actual rank on GainSinceOpen 30 min later. Labels from bar data at `D:\Data\Strategies\HVLF\MinuteBars_SB` |
| **Model retraining** | Weekly (Sunday) | Train BiLSTM on last 60 days of labeled sequences. Train/val/test split: 70/15/15 by date. AdamW optimizer, lr=1e-3, batch_size=64, max 100 epochs. Early stopping on val MAE, patience=10 |
| **Feature importance** | Weekly | Compute permutation importance for all 27 features. Drop features with importance < 0.01. Log results |
| **Threshold review** | Bi-weekly | Analyze if predicted_rank <= 5 threshold is optimal. Test thresholds 3, 4, 5, 6, 7 on validation set |
| **Full backtest** | Monthly | Simulate strategy on last 90 days. Compare live vs. backtest P&L. Halt strategy if divergence > 25% |

**Model artifact path:** `D:\src\ai\mcp\ib\models\bilstm_rank_forecaster.pt`
**Training logs:** `D:\src\ai\mcp\ib\models\training_logs\strategy_23\`

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with predicted_rank and signal_strength | Phase 4, 5 |
| `orders` | Every order placed | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with rank tracking metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price/P&L history each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with rank prediction accuracy | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, rank MAE, prediction accuracy | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — collect scanner rank data for feature engineering and rank monitoring
- `get_scanner_dates()` — verify available scanner data dates
- `get_quote(symbol)` — quality gate checks and position monitoring
- `get_historical_bars(symbol, duration, bar_size)` — supplementary price data for label generation
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — optional technical indicator overlay
- `get_positions()` — current portfolio state
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — prevent duplicate orders
- `get_closed_trades(save_to_db=True)` — reconcile externally closed trades
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — entry and exit orders
- `cancel_order(order_id)` — cancel stop orders on rank-target or time-based exit
- `get_strategy_positions(strategy_id="lstm_rank", status="open")` — position count and lifecycle
- `get_strategy_kpis_report(strategy_id="lstm_rank")` — KPI computation
- `get_trading_lessons(limit=50)` — load historical lessons
- `get_scan_runs(limit=10)` — recent scan history
- `get_job_executions(job_id="strategy_23_lstm_rank", limit=5)` — execution history
- `get_daily_kpis()` — daily performance overview
- `get_position_price_history(position_id)` — full price trail for post-trade analysis
