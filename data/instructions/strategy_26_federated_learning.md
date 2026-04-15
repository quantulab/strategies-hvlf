---
noteId: "a5c26e0038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy, ml, federated-learning, lightgbm, cross-tier, ensemble]

---

# Strategy 26: Federated Learning Across Cap Tiers — Operating Instructions

## Schedule

Runs every 10 minutes during market hours (9:50 AM – 3:30 PM ET) via Claude Code CronCreate.
Delayed start (9:50 AM) to accumulate 2 snapshots of scanner data before first inference. Positions force-closed at 3:30 PM ET.

## Data Sources

- **Scanner CSVs:** `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- **Scanner Types (11):** GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- **Cap Tiers (3):** LargeCap, MidCap, SmallCap — each tier has its own LightGBM model
- **Bar Data:** `D:\Data\Strategies\HVLF\MinuteBars_SB`
- **Database:** `D:\src\ai\mcp\ib\trading.db`
- **Lessons:** `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_26_federated")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (0–8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Additional: `large_cap_signals`, `mid_cap_signals`, `small_cap_signals`, `cross_tier_agreements`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply rules learned
2. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions by tier:
     - `strategy_id = "federated_large"` — max 2
     - `strategy_id = "federated_mid"` — max 2
     - `strategy_id = "federated_small"` — max 2
   - If ALL tiers are at max, skip to PHASE 6 (monitoring only)
3. **Check open orders** via `get_open_orders()`
4. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
5. **Time gate:** If current time > 2:45 PM ET, skip new entries. Proceed to PHASE 6 monitoring and wind-down.
6. **Model availability:** Verify all 3 tier models exist:
   - `D:\src\ai\mcp\ib\models\lgbm_largecap.pkl`
   - `D:\src\ai\mcp\ib\models\lgbm_midcap.pkl`
   - `D:\src\ai\mcp\ib\models\lgbm_smallcap.pkl`
   - If any model is missing, skip that tier's inference and log warning
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management

Before any new trades, enforce risk rules on ALL strategy_26 positions across all tiers.

1. Call `get_portfolio_pnl()` for current P&L
2. For each position with `strategy_id` in `["federated_large", "federated_mid", "federated_small"]`:
   a. **Hard stop at -4%:**
      - If `pnl_pct <= -4.0%`:
        - Check `get_open_orders()` — skip if SELL order already exists
        - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
        - Close in `strategy_positions` with `exit_reason = "stop_loss_4pct"`
        - Log to `orders`, `lessons`
   b. **Take profit at +3%:**
      - If `pnl_pct >= +3.0%`:
        - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
        - Close with `exit_reason = "target_3pct"`
        - Log to `orders`, `lessons`
   c. **30-minute rank sustainability check:**
      - If position held > 30 minutes, check if symbol is still in top-5 on any scanner for its tier
      - If dropped out of top-5 on ALL scanners: close with `exit_reason = "rank_not_sustained"`
3. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. For every externally closed position, log to `lessons`, `strategy_positions`, `orders`
4. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=0, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 — Per-Tier Feature Extraction

For each cap tier (LargeCap, MidCap, SmallCap), for each symbol currently in the top-5 on any scanner:

**Feature vector (42 features per symbol):**

| Feature # | Name | Description | Source |
|-----------|------|-------------|--------|
| 1–11 | `rank_scanner_1..11` | Current rank on each of 11 scanner types (0 if absent, normalized `1 - rank/top_n`) | `get_scanner_results(scanner, date, top_n=50)` |
| 12–22 | `rank_delta_1..11` | Rank change from previous snapshot for each scanner (positive = improving) | Computed from consecutive calls |
| 23–33 | `rank_velocity_1..11` | Rate of rank change over last 3 snapshots (2nd derivative) | Computed from 3 consecutive snapshots |
| 34 | `scanner_breadth` | Count of distinct scanner types the symbol appears on / 11 | Current snapshot |
| 35 | `price_change_pct` | Price change since open | `get_quote(symbol)` |
| 36 | `volume_ratio` | Current volume / avg daily volume | `get_quote(symbol)` |
| 37 | `spread_pct` | `(ask - bid) / last` | `get_quote(symbol)` |
| 38 | `rsi_5min` | 5-minute RSI | `calculate_indicators(symbol, indicators=["RSI"], duration="1 D", bar_size="5 mins", tail=1)` |
| 39 | `time_of_day` | Minutes since 9:30 AM / 390 | System clock |
| 40 | `consecutive_top5` | Number of consecutive snapshots the symbol has been in top-5 on its primary scanner | Computed from snapshot history |
| 41 | `loss_scanner_flag` | 1 if symbol appears on LossSinceOpen or TopLosers, 0 otherwise | Current snapshot |
| 42 | `gap_pct` | Open gap percentage (open - prev_close) / prev_close | `get_historical_bars(symbol, duration="2 D", bar_size="1 day", tail=2)` via `get_quote(symbol)` |

### 3.2 — Feature Matrix per Tier

- **LargeCap candidates:** Top-5 symbols across all 11 LargeCap scanners (deduplicated) — typically 10-30 unique symbols
- **MidCap candidates:** Top-5 symbols across all 11 MidCap scanners — typically 10-30 unique symbols
- **SmallCap candidates:** Top-5 symbols across all 11 SmallCap scanners — typically 10-30 unique symbols

Each candidate gets a 42-feature vector. Batch per tier for model inference.

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 — Per-Tier LightGBM Prediction

For each tier, load the tier-specific LightGBM model and run inference:

**LargeCap:**
1. Load `D:\src\ai\mcp\ib\models\lgbm_largecap.pkl`
2. Input: feature matrix of all LargeCap candidates `(N_large, 42)`
3. Output: probability that each symbol sustains top-5 rank for 30+ minutes
4. Select candidates with `prob >= 0.65`

**MidCap:**
1. Load `D:\src\ai\mcp\ib\models\lgbm_midcap.pkl`
2. Input: `(N_mid, 42)`
3. Output: sustainability probability
4. Select candidates with `prob >= 0.65`

**SmallCap:**
1. Load `D:\src\ai\mcp\ib\models\lgbm_smallcap.pkl`
2. Input: `(N_small, 42)`
3. Output: sustainability probability
4. Select candidates with `prob >= 0.65`

### 4.2 — Cross-Tier Confirmation Bonus

After individual tier predictions, check for **cross-tier agreement**:

For each symbol predicted as a BUY by its own tier model:
1. Check if the SAME symbol appears as a BUY candidate in a different tier's model output (unlikely but possible for dual-listed or reclassified stocks)
2. More importantly: check if the **sector** of the symbol is also generating BUY signals in 2+ tier models:
   - Extract sector for each BUY candidate via `get_contract_details(symbol)` — use the `industry` or `category` field
   - If 2+ tier models have BUY signals in the same sector: **cross-tier agreement detected**
3. **Cross-tier confirmation bonus:**
   - If 2+ tier models agree on the sector direction: **increase position size by +50%** for candidates in that sector
   - Normal size: 1% of account per tier per trade
   - Bonus size: 1.5% of account per tier per trade
   - Log the cross-tier agreement with sector name and agreeing tiers

### 4.3 — Rank by Signal Strength

Within each tier, rank candidates by:
- `signal_strength = prob * (1 + 0.3 * cross_tier_bonus)` where `cross_tier_bonus` = 1 if cross-tier agreement, 0 otherwise
- Take the top candidate per tier (max 1 new entry per tier per cycle)

### 4.4 — Rejection Criteria

Reject if:
- `prob < 0.65` — model not confident
- Symbol on LossSinceOpen or TopLosers (any tier)
- `loss_scanner_flag = 1`
- Already held as a strategy_26 position
- Tier at max positions (2 per tier)

Log all candidates to `scanner_picks`:
- `symbol`, `scanner` (primary scanner where rank is highest), `rank`, `prob`, `signal_strength`, `tier`, `cross_tier_bonus`, `action="BUY"`, `rejected` flag, `reject_reason`, `strategy_id`

Call `update_job_execution(exec_id, phase_completed=4, large_cap_signals=N, mid_cap_signals=N, small_cap_signals=N, cross_tier_agreements=N, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** `last >= $2.00`
2. **Minimum volume:** Average daily volume >= 50,000 shares
3. **Maximum spread:** `(ask - bid) / last <= 3%`
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Per-tier position limit:** Max 2 open positions per tier
6. **Existing position check:** No duplicate entries for the same symbol

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing

| Condition | Size per Position |
|-----------|------------------|
| Normal (single-tier signal) | 1% of total account |
| Cross-tier bonus (2+ tiers agree on sector) | 1.5% of total account (+50%) |

Calculate shares: `floor(account_value * size_pct / last_price)`
Minimum 1 share.

### Position Limits

- Maximum **2** concurrent positions per tier (6 total across all tiers)
- Maximum **1** new entry per tier per cycle

### Order Placement

For each accepted signal:

1. Determine `strategy_id` based on tier:
   - LargeCap → `"federated_large"`
   - MidCap → `"federated_mid"`
   - SmallCap → `"federated_small"`
2. Call `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
   - Record `entry_order_id`, `entry_price`
3. Place bracket orders:
   - **Stop Loss:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=round(entry_price * 0.96, 2))` — 4% stop
   - **Take Profit:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="LMT", limit_price=round(entry_price * 1.03, 2))` — 3% target
4. Log to database:
   - `scanner_picks`: symbol, scanner, rank, prob, signal_strength, tier, cross_tier_bonus, action="BUY", rejected=0
   - `orders`: symbol, strategy_id, action="BUY", quantity, order_type, order_id, entry_price, status
   - `strategy_positions`: strategy_id, symbol, action="BUY", quantity, entry_price, stop_price, target_price, entry_order_id, stop_order_id, target_order_id, tier, prob, cross_tier_bonus, sector

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open position with `strategy_id` in `["federated_large", "federated_mid", "federated_small"]`:

1. **Price snapshot:** Call `get_quote(symbol)` — log to `price_snapshots`: bid, ask, last, volume, unrealized_pnl, pnl_pct, tier
2. **Rank sustainability check:**
   - Call `get_scanner_results()` for the symbol's tier
   - If symbol has dropped out of top-5 on ALL scanners for its tier for 3 consecutive snapshots (30 min):
     - Exit at market with `exit_reason = "rank_not_sustained_30min"`
     - Cancel stop/target orders
3. **Cross-tier re-evaluation:** If the position was entered with cross-tier bonus:
   - Re-check if sector agreement still holds
   - If agreement dissolved (other tiers no longer signaling the sector): tighten stop to -2% from current price
4. **EOD exit:** If current time >= 3:30 PM ET:
   - Close ALL remaining positions at market
   - Cancel all stop/target orders via `cancel_order(order_id)`
   - Close in `strategy_positions` with `exit_reason = "eod_close_330pm"`
5. Update position extremes: peak, trough, MFE, MAE, drawdown

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

On every exit (stop hit, target hit, rank fade, EOD, or manual):

1. Close position in `strategy_positions`:
   - `exit_price`, `exit_time`, `exit_reason`, `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `tier`, `prob`, `cross_tier_bonus`, `sector`
2. Log to `lessons` table:
   - symbol, strategy_id, action="BUY", entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - tier, model_prob, cross_tier_bonus, sector
   - Did rank sustain top-5 for 30+ min? (sustainability_achieved flag)
   - exit_reason
   - lesson text: e.g., "LargeCap model predicted 0.78 sustainability for AAPL (rank 2 on GainSinceOpen). Cross-tier bonus active (Tech sector also signaled in MidCap). Rank sustained for 35 min, exited at +3% target. Federated agreement correctly identified strong sector momentum."
3. Compute and log KPIs via `get_strategy_kpis_report(strategy_id=STRATEGY_ID)` for the specific tier
4. If cross-tier bonus was active, write a detailed lesson file analyzing whether the bonus improved outcomes

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: strategy_id="federated", large_cap_signals, mid_cap_signals, small_cap_signals, cross_tier_agreements, candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for each tier that was active
3. Compute `strategy_kpis` if any positions were closed — separately for each tier:
   - Win rate, avg win %, avg loss %, profit factor, expectancy per tier
   - **Federated-specific metrics:**
     - Per-tier model accuracy: % of `prob >= 0.65` predictions where rank actually sustained 30+ min
     - Cross-tier bonus effectiveness: win rate with bonus vs. without bonus
     - Feature importance drift: top-5 most important features per tier (logged weekly)
     - Sector agreement frequency: how often 2+ tiers agree
4. Call `complete_job_execution(exec_id, summary)` with full summary including per-tier performance

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| **Data collection** | Continuous | Every scanner snapshot with feature vectors stored per tier |
| **Label generation** | Nightly | For each (symbol, timestep, tier): label=1 if symbol remained in top-5 on its primary scanner for 30+ min after the snapshot, label=0 otherwise. Source: bar data from `D:\Data\Strategies\HVLF\MinuteBars_SB` |
| **Per-tier model retraining** | Weekly (Saturday) | Train separate LightGBM per tier on last 45 days of labeled data. Hyperparameters: n_estimators=500, max_depth=6, learning_rate=0.05, min_child_samples=20, subsample=0.8, colsample_bytree=0.8. 5-fold time-series CV. Optimize for AUC-ROC |
| **FedAvg aggregation** | Weekly (after per-tier training) | Extract feature importance vectors from each tier model (42-dim vector). Compute FedAvg: `avg_importance = (imp_large + imp_mid + imp_small) / 3`. Use averaged importances to guide next week's feature selection — drop features with avg importance < 0.005 across all tiers. Log importance vectors to `strategy_kpis` |
| **Cross-tier bonus calibration** | Bi-weekly | Analyze historical trades with/without cross-tier bonus. If bonus trades underperform non-bonus trades, reduce bonus from +50% to +25% or disable |
| **Full backtest** | Monthly | Simulate strategy on last 90 days per tier. Compare live vs. backtest P&L. Halt tier if divergence > 25% |
| **Feature engineering review** | Monthly | Analyze which of the 42 features are most/least predictive per tier. Consider adding new features or removing dead ones |

**Model artifacts:**
- LargeCap: `D:\src\ai\mcp\ib\models\lgbm_largecap.pkl`
- MidCap: `D:\src\ai\mcp\ib\models\lgbm_midcap.pkl`
- SmallCap: `D:\src\ai\mcp\ib\models\lgbm_smallcap.pkl`
- FedAvg importance log: `D:\src\ai\mcp\ib\models\fedavg_importance_history.json`
- Training logs: `D:\src\ai\mcp\ib\models\training_logs\strategy_26\`

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each run with per-tier signal counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with prob, tier, cross_tier_bonus | Phase 4, 5 |
| `orders` | Every order placed per tier | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with tier and federated metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price/P&L history each cycle | Phase 6 |
| `strategy_runs` | Per-tier summary each cycle | Phase 8 |
| `scan_runs` | Overall run summary with cross-tier agreement stats | Phase 8 |
| `lessons` | Exit lessons with tier, prob, cross-tier analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L per tier, model accuracy, FedAvg metrics | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — collect scanner data per tier for feature extraction and rank monitoring
- `get_scanner_dates()` — verify available data
- `get_quote(symbol)` — quality gate, price features, position monitoring
- `get_historical_bars(symbol, duration="2 D", bar_size="1 day")` — gap percentage calculation
- `calculate_indicators(symbol, indicators=["RSI"], duration="1 D", bar_size="5 mins", tail=1)` — RSI feature
- `get_contract_details(symbol)` — extract sector/industry for cross-tier agreement detection
- `get_positions()` — current portfolio state
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — prevent duplicate orders
- `get_closed_trades(save_to_db=True)` — reconcile externally closed trades
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — entry and exit orders
- `cancel_order(order_id)` — cancel stop/target on rank-fade or EOD exit
- `get_strategy_positions(strategy_id, status="open")` — per-tier position count
- `get_strategy_kpis_report(strategy_id)` — KPI computation per tier
- `get_trading_lessons(limit=50)` — load historical lessons
- `get_scan_runs(limit=10)` — recent scan history
- `get_job_executions(job_id="strategy_26_federated", limit=5)` — execution history
- `get_daily_kpis()` — daily performance overview
- `get_position_price_history(position_id)` — full price trail
