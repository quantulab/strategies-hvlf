---
noteId: "s34_attention_scanner_wt_01"
tags: [strategy, cron, ml, attention, transformer, scanner-weighting, per-stock]

---

# Strategy 34: Attention-Based Scanner Importance Weighting — Operating Instructions

## Schedule

Runs every 10 minutes during market hours (9:35 AM – 3:40 PM ET) via Claude Code CronCreate.
Primary trading window: 9:45 AM – 1:00 PM ET (attention model performs best with sufficient scanner history).
Model requires at least 11 scanner snapshots (~55 min of data) before generating signals — first valid signal at ~10:30 AM.
Max 4 concurrent positions.

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- All 11 scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Model artifacts: `D:\src\ai\mcp\ib\models\attention\scanner_attention_4head.pt`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_34_attention_scanner")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1–8)
   - Operation counts: `positions_checked`, `losers_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - Model-specific: `predicted_return`, `attention_entropy`, `top_attention_scanners`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply attention-specific rules (sector-scanner affinity patterns, entropy thresholds)
2. **Load strategy files** — this strategy (S34) plus S04 (cut losers), S07 (conflict filter)
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check open orders** via `get_open_orders()`
5. **Count open S34 positions** via `get_strategy_positions(strategy_id="attention_scanner_wt", status="open")` — enforce max 4 concurrent
6. **Check scanner snapshot count today:** Verify at least 11 snapshots have been collected. If fewer than 11, log `skip_reason = "insufficient_scanner_history"` and skip Phases 3–5 (still run Phases 2, 6, 7 for existing positions).
7. **Verify IB connection** — if `get_positions()` fails, call `fail_job_execution(exec_id, "IB disconnected")` and abort
8. **Verify model artifact:** Confirm `scanner_attention_4head.pt` exists and was trained within the last 14 days. If stale, log warning and continue with caveat.
9. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs BEFORE any new trades)

1. Call `get_portfolio_pnl()` for current P&L across all positions
2. For each S34 position with `pnl_pct <= -3.0%` (strategy stop):
   a. Check `get_open_orders()` — skip if SELL order already exists
   b. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")`
   c. Log to `orders` with `strategy_id = "attention_scanner_wt"`
   d. Close in `strategy_positions` with `exit_reason = "stop_loss_3pct"`
   e. Log to `lessons`: entry/exit prices, P&L, which scanners the attention model weighted highest, attention entropy at entry
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. Cross-check open DB positions against IB positions
   c. Close any orphaned DB positions
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Step 1: Build Scanner Tensor

The attention model ingests a 3D tensor per symbol: **11 scanners x 11 time steps**.

1. For each of the 11 scanner types, call `get_scanner_results(scanner=type, date="today", top_n=30)` across all cap tiers
2. Build the rolling window of the **last 11 scanner snapshots** (each ~5 min apart = ~55 min window)
3. For each candidate symbol, construct the input tensor:

```
Input shape: (11 scanners) × (11 time steps) = 121 features per symbol

Cell value encoding:
- If symbol is on scanner at time t: cell = normalized_rank (1/rank, so rank 1 → 1.0, rank 10 → 0.1)
- If symbol is NOT on scanner at time t: cell = 0.0
```

4. Flatten to a 121-dim vector for each candidate

### Step 2: Candidate Universe

- Include any symbol that appeared on **at least 1 scanner** in **at least 3 of the last 11 time steps**
- This filters out one-off appearances and focuses on symbols with sustained scanner presence

### Step 3: Supplementary Features

For each candidate, also collect:

| Feature | Source | Purpose |
|---------|--------|---------|
| Current price | `get_quote(symbol)` | Spread check, price filter |
| Volume ratio (current 5-min / avg 5-min) | `get_historical_bars(symbol, duration="1 D", bar_size="5 mins")` | Volume confirmation |
| Sector/industry | `get_contract_details(symbol)` | Attention model learns sector-scanner affinities |
| RSI (14-period, 1-min) | `calculate_indicators(symbol, indicators=["RSI"], duration="1 D", bar_size="1 min", tail=30)` | Overbought filter |
| VWAP distance | `calculate_indicators(symbol, indicators=["VWAP"], duration="1 D", bar_size="1 min", tail=5)` | Price relative to volume-weighted average |

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Step 1: Attention Model Architecture (Reference)

The deployed model is a multi-head self-attention network:

```
Architecture:
- Input: 121-dim vector (11 scanners × 11 time steps, flattened)
- Reshape to: (11 scanners) × (11 time-step features)
- Multi-head self-attention: 4 heads, d_model=11, d_k=3, d_v=3
  - Attention is over the SCANNER dimension (11 positions)
  - Each head learns which scanners are important for THIS stock
- Output projection: 4 heads × 3 = 12 → FC(12, 32) → ReLU → FC(32, 1) → predicted 15-min return
- Side output: attention weights (4 heads × 11 scanners) for interpretability
```

### Step 2: Run Inference

For each candidate:

1. Pass the 121-dim input through the model
2. Collect:
   - `predicted_return`: predicted 15-minute return (%)
   - `attention_weights`: (4 heads × 11 scanners) matrix
   - `attention_entropy`: Shannon entropy of the averaged attention distribution

### Step 3: Attention Interpretation

From the 4-head attention weights:

1. Average across heads → 11-dim vector (one weight per scanner)
2. Identify **top-2 attention scanners** — the scanners the model considers most predictive for this stock
3. Compute **attention entropy**: `H = -sum(w * log(w))` where w is the averaged attention distribution
   - Low entropy (< 2.0) = model is focused on specific scanners = higher confidence
   - High entropy (> 2.5) = model is uncertain, spreading attention across all scanners = lower confidence

### Step 4: Signal Filtering

| Criterion | Threshold | Action if Fail |
|-----------|-----------|----------------|
| Predicted return | >= 1.5% | Reject — insufficient edge |
| Top-2 attention scanners show rank <= 20 | Both must qualify | Reject — attention scanners don't confirm |
| Attention entropy | < 2.0 | Reject — model too uncertain |
| RSI (14-period) | < 75 | Reject — overbought |
| Not on any Loser scanner | Must pass | Reject — directional conflict |

### Step 5: Rank and Select

- Rank passing candidates by `predicted_return × (2.5 - attention_entropy)` — rewards high return AND low entropy
- Select top candidates up to (4 - current open S34 positions)

### Step 6: Log Attention Insights

For every candidate (passing or rejected), log to `scanner_picks`:
- `metadata`: attention_weights per scanner, top-2 scanners, entropy, predicted_return
- This data is critical for understanding which scanners matter for which sectors

Example insights the model learns over time:
- Biotech stocks: HotByVolume attention weight ~0.35, HotByPrice ~0.08 (volume leads price)
- Tech stocks: HotByPriceRange attention weight ~0.30, TopVolumeRate ~0.25 (price range and volume rate co-move)
- Penny stocks: TopGainers attention weight ~0.40 (momentum is the primary driver)

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

1. **Minimum price:** `get_quote(symbol)` → last >= $2.00
2. **Minimum volume:** Avg daily volume >= 50,000
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Position limit:** Open S34 positions < 4
6. **No duplicate:** Symbol not in `get_positions()` or `get_open_orders()`
7. **Time window:** At least 11 scanner snapshots available AND current time <= 1:00 PM ET
8. **Account exposure:** Total S34 exposure < 4% of account (4 positions × 1%)

### Position Sizing

- **Size:** 1% of account value per position
- Calculate shares: `floor(account_value * 0.01 / ask_price)`

### Order Placement

For each approved candidate:

1. **Entry order:** `place_order(symbol, action="BUY", quantity=shares, order_type="MKT")`
2. **Stop loss:** `place_order(symbol, action="SELL", quantity=shares, order_type="STP", stop_price=round(ask * 0.97, 2))` — 3% stop
3. **Target:** `place_order(symbol, action="SELL", quantity=shares, order_type="LMT", limit_price=round(ask * (1 + predicted_return / 100), 2))` — target = predicted return

### Database Logging (MANDATORY)

1. **`scanner_picks`**: symbol, scanner=top_attention_scanner, rank, predicted_return, attention_entropy, action="BUY", rejected=0, metadata={attention_weights, top2_scanners}
2. **`orders`**: symbol, action="BUY", quantity, order_type, order_id, strategy_id="attention_scanner_wt"
3. **`strategy_positions`**: strategy_id="attention_scanner_wt", symbol, action="BUY", quantity, entry_price, stop_price, target_price, metadata={predicted_return, attention_weights, attention_entropy, top2_scanners, sector}

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open S34 position every run:

1. **Price snapshot:** `get_quote(symbol)` → log to `price_snapshots` (bid, ask, last, volume, unrealized P&L)
2. **Re-run attention model** with updated scanner tensor:
   - If predicted return drops below 0.5% → flag for early exit
   - If attention entropy rises above 2.5 → flag for tightened stop
   - If top-2 attention scanners change → log shift, review if thesis still holds
3. **Update position extremes:** peak, trough, MFE, MAE, current drawdown
4. **Scanner presence check:**
   - If symbol drops off ALL scanners → tighten stop to 1.5%
   - If symbol appears on a Loser scanner → flag for immediate exit in Phase 7
5. **Time-based check:** If position held > 30 min and predicted return was for 15-min window, consider exit on next run

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

| Trigger | Action | Exit Reason |
|---------|--------|-------------|
| Symbol appears on LossSinceOpen/TopLosers | Immediate MKT SELL | `thesis_broken_loser_scanner` |
| P&L <= -3.0% | Automatic (STP fills) | `stop_loss_3pct` |
| Target price hit (predicted return) | Automatic (LMT fills) | `take_profit_predicted` |
| Predicted return drops below 0.5% on re-inference | MKT SELL | `model_signal_degraded` |
| Attention entropy rises above 2.5 on re-inference | MKT SELL | `attention_entropy_spike` |
| Held > 30 min without hitting target | MKT SELL | `time_stop_30min` |
| End of day (3:45 PM) | MKT SELL | `eod_close` |

### For Each Exit

1. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")` if not already filled
2. Cancel remaining open orders via `cancel_order(order_id)`
3. Close position in `strategy_positions`: exit_price, exit_reason, pnl, pnl_pct, hold_duration_minutes
4. Log to `lessons` table with attention-specific details:
   - Top-2 attention scanners at entry vs at exit
   - Whether attention entropy increased/decreased during hold
   - Whether the attention model correctly identified the important scanner
   - Predicted return vs actual return
   - Lesson text examples:
     - "Attention model on {symbol} (biotech) correctly weighted HotByVolume highest ({weight:.2f}). Predicted {pred}%, actual {actual}%."
     - "Attention entropy spiked from {entry_entropy:.2f} to {exit_entropy:.2f} on {symbol} — model lost confidence. Exited at {pnl_pct}%."
     - "Top attention scanner shifted from HotByVolume to TopLosers during hold — early warning of reversal. Lesson: monitor attention shifts as dynamic stop signal."
5. Compute KPIs via `get_strategy_kpis_report(strategy_id="attention_scanner_wt")`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

1. Log `scan_runs`: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="attention_scanner_wt" with:
   - Average predicted return for candidates this cycle
   - Average attention entropy
   - Most commonly weighted scanners (distribution across candidates)
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="attention_scanner_wt")`:
   - Win rate (target: >55%)
   - Avg predicted return vs avg actual return (calibration metric)
   - Return by attention entropy bucket: low (<1.5), medium (1.5–2.0), high (>2.0)
   - Return by top attention scanner type
   - Sector-scanner affinity map (which sectors weight which scanners)
4. Call `complete_job_execution(exec_id, summary)` with:
   - Scanner snapshots available, candidates screened, signals generated
   - Attention model health (avg entropy, calibration)
   - Open S34 positions and unrealized P&L

---

## Model Training / Retraining Schedule

### Training Protocol

| Parameter | Value |
|-----------|-------|
| Retrain frequency | Weekly (Sunday) |
| Training data | Rolling 40 trading days of scanner snapshots + 1-min bar returns |
| Validation | Walk-forward: train on days 1–30, validate on 31–35, test on 36–40 |
| Architecture | 4-head self-attention, d_model=11, d_k=3, d_v=3 |
| Loss function | MSE on 15-min forward return |
| Optimizer | AdamW, lr=1e-4, weight_decay=1e-5 |
| Epochs | 100, early stopping (patience=15) on validation MSE |
| Batch size | 64 candidates per batch |

### Label Construction

1. For each candidate at each scanner snapshot time t:
   - Label = price at t+15min / price at t - 1.0 (15-min forward return)
   - Source: `get_historical_bars(symbol, duration="1 D", bar_size="1 min")`
2. Filter: only include candidates that appeared on >= 2 scanners at time t (avoid noise)

### Attention Regularization

- Add entropy regularization term to loss: `loss += 0.1 * mean(entropy(attention_weights))`
- This encourages the model to focus on fewer scanners rather than spreading attention uniformly
- Monitor: if avg attention entropy > 2.5 on validation set, increase regularization coefficient

### Shadow Mode After Retraining

1. Deploy new model in shadow mode for 3 trading days
2. Log shadow predictions alongside live model predictions
3. Compare: predicted return MAE, attention entropy distribution, win rate on hypothetical trades
4. Promote to live if shadow MAE <= live MAE + 0.1%

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with attention weights (accepted & rejected) | Phase 4, 5 |
| `orders` | Every entry/exit order | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle + attention metadata | Phase 5, 6, 7 |
| `price_snapshots` | Price + re-inference results per position per cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary with attention model stats | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with attention analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, calibration, entropy-bucketed returns | Phase 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_results` | 3, 6 | Read all 11 scanner types for tensor construction |
| `get_scanner_dates` | 1 | Verify scanner data available, count snapshots |
| `get_quote` | 3, 5, 6, 7 | Current price for features, execution, monitoring |
| `get_historical_bars` | 3 | Volume ratio, historical return for labels |
| `calculate_indicators` | 3 | RSI, VWAP for supplementary features |
| `get_contract_details` | 3, 5 | Sector/industry classification, security validation |
| `get_positions` | 1, 5 | Current portfolio positions |
| `get_portfolio_pnl` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders` | 1, 2, 5 | Duplicate/existing order check |
| `get_closed_trades` | 2 | Reconcile IB executions with DB |
| `place_order` | 2, 5, 7 | Entry, stop, target, and exit orders |
| `cancel_order` | 7 | Cancel remaining orders after exit |
| `get_strategy_positions` | 1, 2 | Count open S34 positions, enforce max 4 |
| `get_strategy_kpis_report` | 2, 8 | Compute and review strategy KPIs |
| `get_trading_picks` | 1 | Review recent picks for dedup |
| `get_trading_lessons` | 1 | Load lessons for rule application |
| `get_scan_runs` | 3, 8 | Scanner snapshot count, log cycle summary |
| `get_job_executions` | 0 | Track job execution lifecycle |
| `get_daily_kpis` | 8 | Daily aggregate performance |
| `get_position_price_history` | 6 | Review price trajectory during hold |
