---
noteId: "s17_transformer_rank_trajectory"
tags: [strategy, transformer, ml, rank-trajectory, breakout-prediction]

---

# Strategy 17: Transformer Sequence Model — Rank Trajectories — Operating Instructions

## Schedule
Runs every 10 minutes during market hours (9:40 AM–3:30 PM ET) via Claude Code CronCreate.
Model retraining: weekly on Sundays using 40 most recent trading days.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types (11): GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Model weights: `D:\src\ai\mcp\ib\models\transformer_rank_v1.pt`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_17_transformer")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned (gateway disconnect, accidental shorts, cut losers)
2. **Load strategy file** `data/strategies/` — verify Strategy 17 parameters are current
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged with `strategy_id = "transformer_rank"`
   - If already at max 5 positions for this strategy, skip to Phase 6 (monitoring only)
4. **Check open orders** via `get_open_orders()` — avoid duplicate entries
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Check model availability** — verify transformer weights file exists and was trained within the last 7 days
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 4% stop-loss rule on ALL Strategy 17 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each Strategy 17 position with `pnl_pct <= -4%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")`
   c. Log to `orders` table with `strategy_id = "transformer_rank"`, full order details
   d. Log to `strategy_positions` — close the position with `exit_reason = "stop_loss_4pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, scanner, and lesson text
   f. Compute and log KPIs via `compute_and_log_kpis(strategy_id="transformer_rank")`
3. For short positions (quantity < 0) created accidentally:
   a. Call `place_order(symbol=SYMBOL, action="BUY", quantity=ABS_SHARES, order_type="MKT")`
   b. Log with `exit_reason = "close_accidental_short"`
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. For every Strategy 17 position that closed externally (stop/limit/manual):
      - Log to `lessons`, `strategy_positions`, and `orders` tables with actual exit details
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 Collect Scanner Rank Time Series

1. Call `get_scanner_dates()` to verify today's data is available
2. For each of the 11 scanner types, call `get_scanner_results(scanner=SCANNER_TYPE, date=TODAY, top_n=50)`:
   - `GainSinceOpen`, `HighOpenGap`, `HotByPrice`, `HotByPriceRange`, `HotByVolume`
   - `LossSinceOpen`, `LowOpenGap`, `MostActive`, `TopGainers`, `TopLosers`, `TopVolumeRate`
3. For each unique symbol found across scanners, build a rank trajectory vector:
   - **Shape per symbol**: 120 timesteps × 11 scanners
   - Each cell = rank position (1-50) on that scanner at that timestep, or 0 if absent
   - Timesteps: last 120 scanner snapshots (~20 hours of 10-min intervals, spanning ~3 trading days)
4. Store historical rank data from prior days' scanner CSVs at `\\Station001\DATA\hvlf\rotating\`

### 3.2 Supplemental Features

5. For each candidate symbol, call `get_quote(symbol=SYMBOL)` to get current bid/ask/last/volume
6. Call `calculate_indicators(symbol=SYMBOL, indicators=["RSI", "MACD", "ATR", "BBANDS"], duration="2 D", bar_size="5 mins", tail=20)` for technical context
7. Call `get_historical_bars(symbol=SYMBOL, duration="1 D", bar_size="1 min")` for intraday price pattern

### 3.3 Feature Matrix Construction

8. Construct input tensor per symbol: `[120, 11]` — rank positions across scanner snapshots
9. Append auxiliary features: current RSI, MACD signal, ATR, Bollinger %B, relative volume
10. Normalize ranks to [0, 1] range (rank / 50). Zero-fill for absent scanners.

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 Transformer Architecture (reference)
- 4-layer Transformer encoder
- 8 attention heads
- d_model = 128
- Positional encoding: sinusoidal over 120 timesteps
- Output: binary classification — breakout probability (+3% in next 30 minutes)

### 4.2 Run Inference

1. Load model weights from `D:\src\ai\mcp\ib\models\transformer_rank_v1.pt`
2. For each candidate symbol with rank trajectory data:
   a. Feed [120, 11] rank trajectory through the encoder
   b. Get breakout probability `p_breakout` ∈ [0, 1]
3. **Confidence filter**: Only retain candidates where `p_breakout >= 0.75`

### 4.3 Scanner Cross-Validation Filter

4. For each high-confidence candidate, verify:
   a. Symbol is on **at least 1 Gainer scanner** (TopGainers, GainSinceOpen, HighOpenGap) — REQUIRED
   b. Symbol is **NOT on any Loser scanner** (TopLosers, LossSinceOpen, LowOpenGap) — HARD VETO
   c. If on Loser scanner → reject, log `reject_reason = "loser_scanner_veto"`
5. Rank remaining candidates by `p_breakout` descending
6. Log all candidates to `scanner_picks` table:
   - `symbol`, `scanner` (primary scanner), `conviction_score` (mapped from p_breakout), `conviction_tier = "tier1"` if p_breakout >= 0.75
   - `rejected = 1` for vetoed candidates, with `reject_reason`

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, call `get_quote(symbol=SYMBOL)` and verify:

1. **Minimum price:** `last >= $2.00` — reject sub-$2 stocks
2. **Minimum volume:** avg daily volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** `(ask - bid) / last <= 3%` — reject wide-spread stocks
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Model freshness:** Model weights must be < 7 days old — reject if stale model

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **5** open positions for Strategy 17 at any time
- Position size: **1% of account** per position
- Calculate shares: `quantity = floor(account_value * 0.01 / last_price)`
- Check for existing position/order via `get_positions()` and `get_open_orders()` before placing

### Order Structure

For each accepted candidate (top candidates by p_breakout, up to available slots):

1. **Entry order:** `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
2. **Stop loss (4%):** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=ENTRY * 0.96)`
3. **Take profit (3%):** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="LMT", limit_price=ENTRY * 1.03)`

### Database Logging (for EVERY order):

1. **`scanner_picks` table:** symbol, scanner, rank, rank_trend, conviction_score (p_breakout), conviction_tier, scanners_present, action="BUY", rejected=0
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status, pick_id, strategy_id="transformer_rank"
3. **`strategy_positions` table:** strategy_id="transformer_rank", symbol, action="BUY", quantity, entry_price, entry_order_id, stop_price, target_price, stop/target_order_ids, scanners_at_entry, conviction_score, pick_id

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open Strategy 17 position every run:

1. Call `get_quote(symbol=SYMBOL)` for current price
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distances to stop/target
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown)
4. Call `get_position_price_history(position_id=POS_ID)` to review trajectory
5. **Time-based exit**: If current time >= 3:30 PM ET:
   a. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")` to close
   b. Cancel open stop/target orders via `cancel_order(order_id=STOP_ORDER_ID)` and `cancel_order(order_id=TARGET_ORDER_ID)`
   c. Log exit with `exit_reason = "eod_close_330pm"`
6. **Model confidence re-check**: Run inference on updated rank trajectory — if confidence drops below 0.50, consider early exit

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

### On Exit (stop hit, target hit, time stop, or manual close)

1. Close position in `strategy_positions` with exit_price, exit_reason, P&L
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="transformer_rank", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - transformer_confidence at entry
   - lesson text: what the model got right/wrong, rank trajectory pattern
3. Compute and log KPIs via `compute_and_log_kpis(strategy_id="transformer_rank")`
4. If significant lesson (loss > 2% or unexpected pattern), write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="transformer_rank" with this cycle's metrics
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="transformer_rank")`:
   - Win rate, avg P&L per trade, max drawdown, Sharpe ratio, expectancy
   - Model accuracy: actual breakout rate vs predicted confidence
4. Call `complete_job_execution(exec_id, summary)` with full summary of all operations

---

## Model Training / Retraining Schedule

### Weekly Training (Sunday)
1. Gather rank trajectory data from last 40 trading days (~320K samples)
   - Source: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` for each day
   - Label: 1 if stock gained +3% within 30 minutes of the snapshot, else 0
2. Train/val split: 80/20 by day (32 train days, 8 val days)
3. Architecture: 4-layer Transformer encoder, 8 heads, d_model=128, dropout=0.1
4. Training: AdamW, lr=1e-4, batch_size=256, 50 epochs, early stopping patience=5
5. Validation metrics: AUC-ROC > 0.70, precision @ 0.75 threshold > 0.60
6. Save weights to `D:\src\ai\mcp\ib\models\transformer_rank_v1.pt`
7. Log training metrics to `strategy_kpis` table

### Monthly Review
- Compare model predictions vs actual outcomes via `get_strategy_kpis_report(strategy_id="transformer_rank")`
- Retune confidence threshold if precision drifts below 55%
- Review feature importance via attention weight analysis

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with transformer confidence & rejection reasons | Phase 4, 5 |
| `orders` | Every order placed (entry, stop, target, exit) | Phase 2, 5, 6 |
| `strategy_positions` | Position lifecycle (open → monitor → close) | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with P&L, confidence, and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, drawdown, model accuracy per strategy | Phase 2, 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_dates()` | 3 | Verify available scanner data dates |
| `get_scanner_results(scanner, date, top_n)` | 3 | Fetch rank data from each of 11 scanner types |
| `get_quote(symbol)` | 3, 5, 6 | Real-time price for features, quality gate, monitoring |
| `get_historical_bars(symbol, duration, bar_size)` | 3 | Intraday bars for labeling and price context |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | 3 | RSI, MACD, ATR, BBANDS for auxiliary features |
| `get_positions()` | 1, 5 | Check current positions and slot availability |
| `get_portfolio_pnl()` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders()` | 1, 2, 5 | Prevent duplicate orders and accidental shorts |
| `get_closed_trades(save_to_db=True)` | 2 | Reconcile externally closed trades |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | 2, 5, 6 | Execute entries, stops, targets, exits |
| `cancel_order(order_id)` | 6 | Cancel orphaned stop/target orders on time exit |
| `get_position_price_history(position_id)` | 6 | Review position trajectory |
| `get_strategy_positions(strategy_id="transformer_rank", status, limit)` | 1, 6 | Query strategy-specific positions |
| `get_strategy_kpis_report(strategy_id="transformer_rank")` | 8 | Compute and review strategy KPIs |
| `get_job_executions(job_id="strategy_17_transformer", limit)` | 0 | Query execution history |
