---
noteId: "b8c4d2e048f922f2cc39g708dd03h118"
tags: [cron, trading, strategies, ml, knowledge-distillation, low-latency, risk-management]

---

# Strategy 38: Knowledge Distillation — Compress Complex Signals — Operating Instructions

## Schedule
- **Student model:** Runs every 500ms during market hours (9:35 AM – 3:55 PM ET) — lightweight inference loop
- **Teacher model:** Runs every 30 seconds — full ensemble evaluation
- **Confirmation window:** 2-minute window after student signal for teacher confirmation
- Job ID: `strategy_38_knowledge_distillation`

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Teacher ensemble: Weighted outputs from strategies 12–37 (26 strategies)
- Training data: 30 days rolling window (~50K samples)
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every teacher cycle (30s) MUST be recorded in `job_executions`. Student cycles log only on signal generation.**

1. Call `start_job_execution(job_id="strategy_38_knowledge_distillation")` at each teacher cycle — returns `exec_id`
2. After each phase, call `update_job_execution(exec_id, ...)` with phase progress and counts
3. On completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**Student-only signals that do not receive teacher confirmation within 2 minutes must be logged as `student_only_timeout` events.**

---

## PHASE 1: Pre-Trade Checklist (every teacher cycle — 30s)

1. **Load lessons** from `data/lessons/` — apply all learned rules
2. **Verify model files exist:**
   - Student model weights: check that the 2-layer MLP is loaded (32 hidden units, <5K parameters)
   - Teacher ensemble config: verify weighted strategy list (strategies 12–37)
   - If student model missing or corrupt, fall back to teacher-only mode (no latency advantage)
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check open orders** via `get_open_orders()`
5. **Count open strategy-38 positions** via `get_strategy_positions(strategy_id="knowledge_distillation", status="open")`
6. **Verify IB connection** — halt on disconnect
7. **Check student-teacher agreement rate** from `strategy_kpis`:
   - If agreement rate < 60% over last 50 signals → flag model drift, consider retraining
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 2% stop-loss rule on ALL strategy-38 positions.**

1. Call `get_portfolio_pnl()` for current P&L
2. For each strategy-38 position with `pnl_pct <= -2.0%`:
   a. Check `get_open_orders()` — skip if SELL order exists
   b. Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
   c. Log to `orders` with `strategy_id = "knowledge_distillation"`
   d. Close in `strategy_positions` with `exit_reason = "stop_loss_2pct"`
   e. Log to `lessons` with trade details
3. **Teacher disagreement exit:** For any position where the teacher model's latest output disagrees with the student's entry signal:
   a. If teacher says SELL/NEUTRAL and position is LONG → exit immediately
   b. Call `place_order(symbol, action="SELL", quantity=N, order_type="MKT")`
   c. Close with `exit_reason = "teacher_disagrees"`
   d. Log lesson: "Teacher overrode student signal — model compression may have lost nuance for this pattern"
4. Reconcile closed trades: `get_closed_trades(save_to_db=True)`
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Feature Vector Construction (30 features)
For each candidate symbol, construct the 30-dimensional feature vector used by both teacher and student:

1. **Scanner features (12):** Call `get_scanner_results(scanner, date, top_n=20)` for relevant scanners
   - Rank on GainSinceOpen (per tier) → 3 features (NaN if absent)
   - Rank on HotByVolume (per tier) → 3 features
   - Rank on TopGainers (per tier) → 3 features
   - Count of scanner appearances → 1 feature
   - Best rank across all scanners → 1 feature
   - Time since first scanner appearance → 1 feature

2. **Price features (8):** Call `get_quote(symbol)` and `get_historical_bars(symbol, duration="1d", bar_size="1min")`
   - Last price, bid-ask spread %, intraday return %
   - Distance from VWAP %, distance from day high %, distance from day low %
   - 5-min momentum (price change), 15-min momentum

3. **Technical features (6):** Call `calculate_indicators(symbol, indicators=["RSI", "VWAP", "ATR", "EMA9", "EMA21", "MACD"], duration="1d", bar_size="5min", tail=20)`
   - RSI(14), ATR(14), EMA9/EMA21 ratio
   - MACD signal, MACD histogram, VWAP deviation

4. **Volume features (4):** From `get_historical_bars` and `get_quote`
   - Current volume / avg volume ratio
   - Volume acceleration (current 5-min vs prior 5-min)
   - Relative volume rank among all scanner candidates
   - Volume-weighted price trend (positive = buying pressure)

### Normalization
- All features z-score normalized using rolling 30-day mean/std
- NaN features (absent scanner ranks) filled with -1 (below worst rank)

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Teacher Model (runs every 30 seconds)
1. For each candidate, compute weighted ensemble output from strategies 12–37:
   - Each strategy provides a signal ∈ {-1 (sell), 0 (neutral), +1 (buy)} and confidence ∈ [0, 1]
   - Teacher output = Σ(weight_i × signal_i × confidence_i) for i in strategies 12–37
   - Weights learned from historical performance (updated weekly)
2. Teacher produces soft probability distribution over {sell, hold, buy} using softmax with temperature τ=3.0:
   - `P_teacher(action) = softmax(logits / τ)` where τ=3.0 softens the distribution
3. Store teacher output with timestamp for student comparison

### Student Model (runs every 500ms)
1. Feed the 30-feature vector into the 2-layer MLP:
   - Architecture: Input(30) → Linear(32) → ReLU → Linear(3) → Softmax
   - Parameters: 30×32 + 32 + 32×3 + 3 = 1,091 parameters (<5K requirement met)
2. Student produces soft probability distribution over {sell, hold, buy}
3. **Signal generation:** If P_student(buy) > 0.7 → generate BUY signal with `confidence = P_student(buy)`
4. **Latency advantage:** Student runs 29.5 seconds before teacher confirmation
   - Log signal timestamp for latency tracking

### Student-Teacher Reconciliation
5. On BUY signal from student:
   - **Immediate action:** Open 0.5% account position (student-only bet)
   - Start 2-minute confirmation timer
6. Within 2-minute window, when teacher runs:
   - **Teacher confirms (P_teacher(buy) > 0.5):** Add 0.5% more (total 1.0% account)
   - **Teacher disagrees (P_teacher(buy) ≤ 0.5):** Exit student position immediately
   - **Teacher timeout (>2 min no confirmation):** Hold student position but tighten stop to 1%
7. Log agreement/disagreement to `scanner_picks` and `strategy_runs`

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Position limit:** No more than 2 concurrent strategy-38 positions
6. **No duplicate:** No existing position or open order for this symbol
7. **Student confidence threshold:** P_student(buy) > 0.7

Log rejection to `scanner_picks` with `rejected=1` and `reject_reason`.

### Order Placement — Student Signal (0.5% initial)
1. Compute initial position:
   - `size_pct = 0.5%` of account value
   - `quantity = floor(account_value × 0.005 / ask_price)`
   - `stop_price = entry_price × (1 - 0.02)` — 2% stop
   - `target_price = entry_price × (1 + 0.015)` — 1.5% target
2. Place orders:
   a. `place_order(symbol, action="BUY", quantity=N, order_type="MKT")` — student entry
   b. `place_order(symbol, action="SELL", quantity=N, order_type="STP", stop_price=stop_price)` — stop
   c. `place_order(symbol, action="SELL", quantity=N, order_type="LMT", limit_price=target_price)` — target
3. Log to `orders`, `strategy_positions`, `scanner_picks` with `signal_source="student"`

### Order Placement — Teacher Confirmation (additional 0.5%)
If teacher confirms within 2 minutes:
1. Add to position:
   - `additional_quantity = floor(account_value × 0.005 / ask_price)`
2. Call `place_order(symbol, action="BUY", quantity=additional_quantity, order_type="MKT")`
3. Update stop and target orders via `modify_order(order_id, quantity=total_quantity, ...)`
4. Update `strategy_positions` with new total quantity and `signal_source="student+teacher"`

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-38 position every teacher cycle (30s):

1. Call `get_quote(symbol)` for current price
2. Log `price_snapshots`: symbol, bid, ask, last, volume, unrealized_pnl, pnl_pct
3. Call `get_position_price_history(position_id)` for trajectory analysis
4. **Continuous student monitoring (every 500ms cycle):**
   - Re-run student inference on updated features
   - If P_student(sell) > 0.7 → flag for immediate exit review
   - If P_student(hold) > 0.7 and position is profitable → hold
5. **Teacher re-evaluation (every 30s):**
   - Re-run teacher ensemble
   - If teacher flips from buy to sell → exit immediately (Phase 2 rule)
6. Track student vs teacher agreement over position lifetime
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

### On Exit (stop, target, teacher override, or signal loss)

1. Close position in `strategy_positions`:
   - `exit_reason` options: `"stop_loss_2pct"`, `"take_profit_1.5pct"`, `"teacher_disagrees"`, `"student_sell_signal"`, `"teacher_timeout"`, `"eod_close"`, `"manual"`
2. Log to `lessons` table:
   - symbol, strategy_id="knowledge_distillation"
   - entry_price, exit_price, pnl, pnl_pct, hold_duration_minutes
   - signal_source: "student", "student+teacher", or "teacher_only"
   - student_confidence_at_entry, teacher_confidence_at_entry
   - student_teacher_agreement: true/false
   - latency_advantage_ms: time between student signal and teacher confirmation
   - lesson text describing what happened (e.g., "Student caught early momentum 28s before teacher — teacher confirmed and position added. +1.2% in 15 min")
3. **Distillation quality metrics:**
   - KL divergence between student and teacher outputs at entry
   - Was the student's latency advantage used profitably?
   - Did teacher confirmation improve or worsen the trade?
4. Compute KPIs via `get_strategy_kpis_report(strategy_id="knowledge_distillation")`
5. Write lesson file to `data/lessons/` if trade reveals student model weakness or strength

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each teacher cycle (30s):

1. Log `scan_runs`: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="knowledge_distillation":
   - Student signals generated this cycle
   - Teacher evaluations completed
   - Student-teacher agreement rate (rolling 50 signals)
   - Average latency advantage realized (ms)
   - Student-only P&L vs student+teacher P&L
3. Compute `strategy_kpis` if any positions closed:
   - Win rate (student-only vs teacher-confirmed separately)
   - Avg P&L, Sharpe ratio, max drawdown
   - **Distillation KPIs:** KL divergence trend, agreement rate, latency advantage profit
4. Call `complete_job_execution(exec_id, summary)`

---

## Model Training / Retraining Schedule

### Training Data Preparation
- Source: 30 days of historical feature vectors + teacher ensemble outputs
- Target: ~50,000 samples (30 days × ~1,700 teacher evaluations/day at 30s intervals)
- Features: 30-dimensional vector (see Phase 3)
- Labels: Soft probability distributions from teacher (not hard labels)

### Training Procedure
1. **Loss function:** KL divergence between student output and teacher soft labels
   - `L = Σ P_teacher(a) × log(P_teacher(a) / P_student(a))` for a ∈ {sell, hold, buy}
   - Temperature τ = 3.0 applied to both student and teacher logits during training
   - At inference, use τ = 1.0 for sharper predictions
2. **Architecture:** Input(30) → Linear(32) → ReLU → Linear(3) → Softmax
3. **Optimizer:** Adam, lr=0.001, batch_size=256, epochs=50
4. **Validation:** 20% holdout, early stopping on validation KL divergence

### Retraining Triggers
- **Scheduled:** Every Sunday evening (weekly retrain on latest 30-day window)
- **Triggered:** If student-teacher agreement rate drops below 60% for 50 consecutive signals
- **Triggered:** If student-only win rate drops below 35%
- **Emergency:** If 3 consecutive teacher-disagreement exits result in losses > 2% total

### Retraining Procedure
1. Collect latest 30 days of (feature, teacher_output) pairs from database
2. Retrain student MLP from scratch (random initialization)
3. Validate on holdout set — require KL divergence < 0.15
4. If validation passes, deploy new student weights
5. If validation fails, keep old student weights and log alert
6. Log retraining event to `lessons` and `strategy_kpis`

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each teacher cycle | Phase 0 (start), every phase, Phase 8 (complete) |
| `scanner_picks` | Candidates with student/teacher signals | Phase 3, 4, 5 |
| `orders` | Entry, stop, target, and add-on orders | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with signal source tracking | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price data at each monitoring cycle | Phase 6 |
| `strategy_runs` | Per-cycle summary with agreement metrics | Phase 8 |
| `scan_runs` | Overall cycle summary | Phase 8 |
| `lessons` | Trade lessons with distillation quality metrics | Phase 2, 7 |
| `strategy_kpis` | Win rate, KL divergence, latency advantage stats | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — scanner data for feature construction
- `get_scanner_dates()` — available data dates
- `get_quote(symbol)` — real-time price/spread/volume
- `get_historical_bars(symbol, duration, bar_size)` — intraday bars for features
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — technical indicators
- `get_positions()` — current IB positions
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — existing order check
- `get_closed_trades(save_to_db)` — reconcile closed positions
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — execute trades
- `cancel_order(order_id)` — cancel orders on exit
- `modify_order(order_id, quantity, limit_price, stop_price)` — update stop/target on position add
- `get_strategy_positions(strategy_id, status, limit)` — query strategy-38 positions
- `get_strategy_kpis_report(strategy_id)` — KPI computation
- `get_trading_lessons(limit)` — prior lessons
- `get_scan_runs(limit)` — scan history
- `get_job_executions(job_id, limit)` — execution history
- `get_daily_kpis()` — daily metrics
- `get_position_price_history(position_id)` — position price trajectory
