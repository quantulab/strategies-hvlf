---
noteId: "s20_anomaly_detection"
tags: [strategy, anomaly-detection, isolation-forest, scanner-population, regime-shift]

---

# Strategy 20: Anomaly Detection — Scanner Population Shock — Operating Instructions

## Schedule
Runs every 10 minutes during market hours (9:40 AM–3:50 PM ET) via Claude Code CronCreate.
Model refit: daily at 7:00 PM ET using trailing 30 days of scanner population data.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types (11): GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Model: `D:\src\ai\mcp\ib\models\isolation_forest_v1.pkl`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_20_anomaly")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules (cut losers, gateway disconnect, accidental shorts)
2. **Load strategy file** from `data/strategies/` — verify Strategy 20 parameters
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged with `strategy_id = "anomaly_detection"`
   - If already at max 2 positions for today, skip to Phase 6 (monitoring only)
4. **Check open orders** via `get_open_orders()` — avoid duplicates
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Check daily trade count:** Query `orders` table for today's Strategy 20 entries — max 2 trades per day
7. **Load Isolation Forest model** — verify model file exists and was refit within last 2 days
8. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 4% stop-loss rule on ALL Strategy 20 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each Strategy 20 position with `pnl_pct <= -4%`:
   a. Check `get_open_orders()` — skip if a SELL/BUY-to-cover order already exists
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")` (for longs)
   c. Log to `orders` table with `strategy_id = "anomaly_detection"`, full order details
   d. Log to `strategy_positions` — close with `exit_reason = "stop_loss_4pct"`
   e. Log to `lessons` with symbol, entry/exit prices, P&L, anomaly type, lesson text
   f. Compute and log KPIs via `compute_and_log_kpis(strategy_id="anomaly_detection")`
3. For short positions that were closed or accidental:
   a. Call `place_order(symbol=SYMBOL, action="BUY", quantity=ABS_SHARES, order_type="MKT")`
   b. Log with `exit_reason = "close_accidental_short"` or `"stop_loss_4pct_short"`
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` to sync IB executions
   b. For every Strategy 20 position that closed externally:
      - Log to `lessons`, `strategy_positions`, and `orders` tables
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 Compute Scanner Population Metrics

For each of the 11 scanner types, call `get_scanner_results(scanner=SCANNER_TYPE, date=TODAY, top_n=50)`:

1. **Population count**: Number of unique symbols on each scanner in this snapshot
2. **Newcomer ratio**: Fraction of symbols that were NOT on the scanner in the previous snapshot
3. **Dropout ratio**: Fraction of symbols from previous snapshot that are no longer present
4. **Rank entropy**: Shannon entropy of rank positions — low entropy = one stock dominates, high = even distribution

Compute these 4 metrics × 11 scanner types = **44-dimensional feature vector**.

### 3.2 Historical Context

5. Call `get_scanner_dates()` to identify available historical dates
6. Load today's prior snapshots from database to compute running averages for comparison
7. Call `get_quote(symbol="SPY")` and `get_quote(symbol="QQQ")` for broad market context
8. Call `calculate_indicators(symbol="SPY", indicators=["ATR", "RSI", "BBANDS"], duration="5 D", bar_size="1 hour", tail=10)` for market regime

### 3.3 Feature Vector Assembly

9. Construct 44-dim feature vector: `[pop_count_scanner1, newcomer_ratio_scanner1, dropout_ratio_scanner1, rank_entropy_scanner1, ..., pop_count_scanner11, ..., rank_entropy_scanner11]`
10. Normalize each feature to z-score using trailing 30-day mean and std

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 Isolation Forest Anomaly Detection

1. Load model from `D:\src\ai\mcp\ib\models\isolation_forest_v1.pkl`
   - n_estimators=200, contamination=0.05, max_features=11
2. Feed 44-dim feature vector into the Isolation Forest
3. Get anomaly score: `score = model.decision_function(X)` — more negative = more anomalous
4. If `score < threshold` (anomaly detected), classify the anomaly type:

### 4.2 Anomaly Type Classification

Analyze which features are anomalous to determine the trading signal:

| Anomaly Pattern | Detection Rule | Trading Signal |
|----------------|----------------|---------------|
| **Population spike on Gainers** | `pop_count_TopGainers > 2σ` AND `pop_count_GainSinceOpen > 1.5σ` | BUY broad market (SPY/QQQ calls or top gainer) |
| **Mass dropout + Loser spike** | `dropout_ratio_TopGainers > 0.6` AND `pop_count_TopLosers > 2σ` | SHORT via puts on SPY or short top loser |
| **Entropy collapse** | `rank_entropy < 0.5` on any Gainer scanner (one stock dominates) | BUY the dominant stock on that scanner |
| **Newcomer flood on HotByVolume** | `newcomer_ratio_HotByVolume > 0.80` | BUY the top newcomer (fresh volume = new catalyst) |

5. For each detected anomaly pattern, identify the specific trading candidate:
   - For "population spike": Call `get_scanner_results(scanner="TopGainers", date=TODAY, top_n=3)` — buy rank #1
   - For "mass dropout + Loser spike": Call `get_scanner_results(scanner="TopLosers", date=TODAY, top_n=3)` — short rank #1, or buy SPY puts via `get_option_chain(symbol="SPY")`
   - For "entropy collapse": Identify the dominant stock (rank #1 with disproportionate weight)
   - For "newcomer flood": Identify top newcomer from HotByVolume that wasn't in previous snapshot

6. Log all anomaly detections and signals to `scanner_picks` table:
   - `symbol`, `scanner`, `anomaly_type`, `anomaly_score`, `conviction_score`, `action`, `rejected` flag
   - Log non-anomalous runs too with `rejected = 1, reject_reason = "no_anomaly_detected"`

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, call `get_quote(symbol=SYMBOL)` and verify:

1. **Minimum price:** `last >= $2.00` — reject sub-$2 stocks
2. **Minimum volume:** avg daily volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** `(ask - bid) / last <= 3%` — reject wide-spread stocks
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Anomaly confirmation:** Anomaly must persist in the NEXT scanner snapshot (wait 10 min, re-check) — prevents false-positive on transient data glitches
6. **Daily limit:** Maximum 2 trades per day for this strategy — reject if already at limit

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **2** open positions for Strategy 20 at any time
- Maximum **2** trades per day (new entries)
- Position size: **1% of account** per position
- Calculate shares: `quantity = floor(account_value * 0.01 / last_price)`
- Check for existing position/order via `get_positions()` and `get_open_orders()` before placing

### Order Structure

For LONG signals (population spike, entropy collapse, newcomer flood):
1. **Entry:** `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
2. **Stop loss (4%):** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=ENTRY * 0.96)`

For SHORT signals (mass dropout + Loser spike):
1. **Entry:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")`
2. **Stop loss (4%):** `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="STP", stop_price=ENTRY * 1.04)`

Alternative for SHORT — puts:
1. Call `get_option_chain(symbol="SPY")` to find available expirations
2. Call `get_option_quotes(symbol="SPY", expiration=NEAREST_WEEKLY, strike=ATM_STRIKE, right="P")` for pricing
3. `place_order(symbol="SPY", action="BUY", quantity=1, order_type="MKT")` for the put contract

### Database Logging (for EVERY order):

1. **`scanner_picks` table:** symbol, anomaly_type, anomaly_score, feature_vector_summary, action, rejected=0
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, stop_price, entry_price, status, pick_id, strategy_id="anomaly_detection"
3. **`strategy_positions` table:** strategy_id="anomaly_detection", symbol, action, quantity, entry_price, entry_order_id, stop_price, anomaly_type, anomaly_score, pick_id

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open Strategy 20 position every run:

1. Call `get_quote(symbol=SYMBOL)` for current price
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distance to stop
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown)
4. Call `get_position_price_history(position_id=POS_ID)` to review trajectory
5. **Anomaly normalization check**: Re-compute population metrics for the triggering scanner
   - If the anomaly has normalized (feature returns within 1σ of mean), consider taking profit
   - Log observation to `lessons` table
6. **No fixed take-profit** — exit when anomaly normalizes or at stop/EOD
7. **EOD exit** (3:45 PM ET):
   a. Close all positions via `place_order(symbol=SYMBOL, action=CLOSE_ACTION, quantity=SHARES, order_type="MKT")`
   b. Cancel open stop orders via `cancel_order(order_id=STOP_ORDER_ID)`
   c. Log exit with `exit_reason = "eod_close"`

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

### On Exit (stop hit, anomaly normalization, EOD, or manual close)

1. Close position in `strategy_positions` with exit_price, exit_reason, P&L
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="anomaly_detection", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - anomaly_type, anomaly_score at entry, feature_vector at entry
   - time_to_normalize (minutes from entry to anomaly returning to normal)
   - lesson text: was the anomaly a real regime shift or a data glitch?
3. Compute and log KPIs via `compute_and_log_kpis(strategy_id="anomaly_detection")`
4. **Track anomaly type accuracy:**
   - Which anomaly types (population spike, dropout, entropy collapse, newcomer flood) lead to profitable trades?
   - Update per-type win rates in `strategy_kpis`
5. If significant lesson, write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: anomaly_detected (bool), anomaly_type, anomaly_score, candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="anomaly_detection" with this cycle's metrics
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="anomaly_detection")`:
   - Win rate overall and per anomaly type
   - Average P&L per trade, max drawdown, expectancy
   - Anomaly detection rate: % of runs that detected an anomaly
   - False positive rate: anomalies detected that led to losses
   - Average time-to-normalize per anomaly type
4. Call `complete_job_execution(exec_id, summary)` with full summary

---

## Model Training / Retraining Schedule

### Daily Refit (7:00 PM ET)
1. Collect scanner population metrics from the last 30 trading days
   - Source: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` for each day
   - Compute 44-dim feature vector for each 10-min snapshot (~180 snapshots/day × 30 days = ~5,400 samples)
2. Fit Isolation Forest:
   - `n_estimators=200`, `contamination=0.05`, `max_features=11`, `random_state=42`
3. Validate on held-out last 5 days: anomaly rate should be 3-7% of snapshots
4. Save model to `D:\src\ai\mcp\ib\models\isolation_forest_v1.pkl`
5. Log refit metrics to `strategy_kpis` table

### Monthly Review
- Review anomaly type distribution via `get_strategy_kpis_report(strategy_id="anomaly_detection")`
- Adjust contamination parameter if anomaly rate is too high (>10%) or too low (<1%)
- Review feature importance: which of the 44 features contribute most to anomaly detection
- Consider adding cross-scanner correlation features (e.g., Gainer-Loser population ratio)

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every anomaly detection with type, score, and rejection reasons | Phase 4, 5 |
| `orders` | Every order placed (entry, stop, exit) | Phase 2, 5, 6 |
| `strategy_positions` | Position lifecycle with anomaly metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary with anomaly stats | Phase 8 |
| `scan_runs` | Scan cycle summary with anomaly detection results | Phase 8 |
| `lessons` | Exit lessons with anomaly type accuracy and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate per anomaly type, false positive rate, expectancy | Phase 2, 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_dates()` | 3 | Verify available scanner data dates |
| `get_scanner_results(scanner, date, top_n)` | 3, 4 | Fetch population data from all 11 scanners, identify candidates |
| `get_quote(symbol)` | 3, 5, 6 | Market context (SPY, QQQ), quality gate, position monitoring |
| `get_historical_bars(symbol, duration, bar_size)` | 3 | Historical price context for anomaly validation |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | 3 | ATR, RSI, BBANDS for market regime detection |
| `get_option_chain(symbol)` | 5 | Find put options for short signals |
| `get_option_quotes(symbol, expiration, strike, right)` | 5 | Price puts for mass-dropout short trades |
| `get_positions()` | 1, 5 | Check current positions and slot availability |
| `get_portfolio_pnl()` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders()` | 1, 2, 5 | Prevent duplicate orders and accidental shorts |
| `get_closed_trades(save_to_db=True)` | 2 | Reconcile externally closed trades |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | 2, 5, 6 | Execute entries, stops, exits (long and short) |
| `cancel_order(order_id)` | 6 | Cancel orphaned stop orders on exit |
| `get_position_price_history(position_id)` | 6 | Review position trajectory |
| `get_strategy_positions(strategy_id="anomaly_detection", status, limit)` | 1, 6 | Query strategy-specific positions |
| `get_strategy_kpis_report(strategy_id="anomaly_detection")` | 7, 8 | Compute and review strategy KPIs |
| `get_job_executions(job_id="strategy_20_anomaly", limit)` | 0 | Query execution history |
| `get_trading_orders(limit)` | 1 | Check daily trade count for 2/day limit |
