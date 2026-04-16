---
noteId: "a31f3c9038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy-31, diffusion-model, ddpm, generative, scanner-prediction]

---

# Strategy 31: Diffusion Model — Scanner State Prediction — Operating Instructions

## Schedule

- **Model training:** Sunday 8 PM ET via Claude Code CronCreate (`job_id = "diffusion_train"`)
- **Live trading:** Every 10 minutes during market hours 10:00 AM - 3:15 PM ET (`job_id = "diffusion_scanner"`)
- **End-of-day summary:** 4:05 PM ET

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types modeled: GainSinceOpen, HotByVolume, HotByPrice, TopGainers, TopVolumeRate, MostActive
- Cap tiers: SmallCap, MidCap, LargeCap
- Minute bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Database: `D:\src\ai\mcp\ib\trading.db`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="diffusion_scanner")` to create a new execution record -- returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - Diffusion-specific: `futures_generated`, `consensus_scores_computed`, `denoising_steps`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` -- apply rules learned
2. **Load trained DDPM model** (from latest Sunday training, stored in `strategy_runs`):
   - U-Net architecture weights and configuration
   - Noise schedule (linear beta schedule, 50 timesteps)
   - Symbol embedding table (maps symbols to vector space)
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Confirm no more than 3 open positions for this strategy
4. **Check current open orders** via `get_open_orders()`
5. **Verify IB connection** -- if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Time gate:** Do not open new positions after 2:30 PM ET (need 45 min for time stop)
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY, runs FIRST)

**Before any new trades, enforce stops on ALL strategy-31 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="diffusion_scanner", status="open")` to identify this strategy's positions
3. For each position with `pnl_pct <= -3.5%`:
   a. Check `get_open_orders()` -- skip if SELL order already exists
   b. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   c. Log with `exit_reason = "stop_loss_3_5pct"`
4. **Time stop (45 min):** For each position held > 45 minutes:
   a. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
   b. Log with `exit_reason = "time_stop_45min"`
5. **Prediction fulfilled:** Check if symbol has entered top-10 GainSinceOpen (the predicted outcome):
   - Call `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=10)` (all tiers)
   - If held symbol now appears in top-10 GainSinceOpen, this is the target exit (see Phase 7)
6. Call `get_closed_trades(save_to_db=True)` to reconcile with IB
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3A: DDPM Model Training (Sunday 8 PM -- weekly)

**Architecture: U-Net for scanner state generation**

```
Scanner State Representation:
- Matrix S(t) of shape [num_scanners x top_k] where each entry is a symbol embedding
- num_scanners = 6 (GainSinceOpen, HotByVolume, HotByPrice, TopGainers, TopVolumeRate, MostActive)
- top_k = 20 (top 20 symbols per scanner)
- Symbol embedding dimension = 64
- Conditioning input: current scanner state S(t_now), time of day, market-wide features
```

**DDPM Training Procedure:**

1. Collect 40 trading days via `get_scanner_dates()`
2. For each day, collect scanner snapshots at 10-minute intervals:
   - For each snapshot time t, record current state S(t) and future state S(t+30min)
   - This creates (input, target) pairs: predict S(t+30) given S(t)
3. **Forward diffusion process (training):**
   - Take target state S(t+30) as x_0
   - Linear beta schedule: beta_1 = 0.0001, beta_T = 0.02, T = 50 steps
   - Add noise: x_t = sqrt(alpha_bar_t) * x_0 + sqrt(1 - alpha_bar_t) * epsilon
4. **U-Net learns to predict noise epsilon given (x_t, t, S(t_now)):**
   - Encoder: 3 downsampling blocks with residual connections
   - Bottleneck: self-attention over scanner positions
   - Decoder: 3 upsampling blocks with skip connections
   - Time embedding: sinusoidal positional encoding of diffusion step t
   - Conditioning: current scanner state S(t_now) concatenated at bottleneck
5. Loss: MSE between predicted noise and actual noise
6. Train for 200 epochs, learning rate 1e-4, AdamW optimizer
7. Store model weights in `strategy_runs` with `run_type = "ddpm_train"`

### 3B: Current Scanner State Collection (every 10-min run)

1. Pull ALL scanner types to build current state matrix S(t_now):
   - `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="HotByVolume", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="HotByPrice", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="TopGainers", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="TopVolumeRate", date="YYYY-MM-DD", top_n=20)` (all tiers)
   - `get_scanner_results(scanner="MostActive", date="YYYY-MM-DD", top_n=20)` (all tiers)
2. Build current state matrix S(t_now) using symbol embeddings
3. Record which symbols are currently in top-10 GainSinceOpen (baseline for prediction)
4. Collect market-wide features:
   - Call `get_quote(symbol="SPY")` for broad market direction
   - Call `calculate_indicators(symbol="SPY", indicators=["RSI", "VWAP"], duration="1 D", bar_size="1 min", tail=10)`

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### Diffusion Sampling: Generate 20 Future Scanner States

1. **Initialize:** Sample 20 independent noise vectors x_T ~ N(0, I) for the scanner state space
2. **Reverse diffusion (50 denoising steps per sample):**
   - For t = 50, 49, ..., 1:
     - Predict noise: epsilon_hat = UNet(x_t, t, S(t_now))
     - Compute x_{t-1} using DDPM update rule with predicted noise
   - Result: 20 denoised samples x_0^{(1)}, ..., x_0^{(20)} representing predicted S(t+30min)
3. **Decode each sample** to extract predicted top-10 GainSinceOpen symbols:
   - For each sample, find nearest-neighbor symbols in embedding space for the GainSinceOpen scanner rows
   - Extract predicted top-10 symbols

### Consensus Scoring

For each unique symbol that appears in ANY of the 20 generated futures:

```
consensus_score = (number of futures where symbol appears in top-10 GainSinceOpen) / 20
```

### Entry Criteria (ALL must be met)

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Consensus score | >= 0.70 | Symbol predicted to enter top-10 in 14+ of 20 futures |
| Currently NOT in top-10 GainSinceOpen | Required | Prediction value: symbol hasn't moved yet |
| Currently on HotByVolume | Required | Volume precedes price -- symbol is accumulating |
| Not on any loss scanner | Required | Contradictory signal veto |
| Consensus consistency | Std dev across futures < 0.3 | Model is confident, not noisy |

### Candidate Output

For each qualifying symbol, record:
- `consensus_score`: fraction of futures predicting top-10 GainSinceOpen
- `current_scanners`: which scanners the symbol currently appears on
- `predicted_rank_mean`: average predicted rank across futures
- `predicted_rank_std`: standard deviation of predicted rank
- `futures_generated`: 20 (fixed)
- `denoising_steps`: 50 (fixed)

### Candidate Ranking

Rank by `consensus_score` descending. Enter highest consensus first, up to max 3 positions.

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Pre-Order Quality Checks (MANDATORY)

For each qualifying candidate, run via `get_quote(symbol=SYM)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Volume today >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Max positions:** 3 open positions maximum for this strategy
6. **Not already held:** Check `get_positions()` for existing position
7. **Time gate:** Current time before 2:30 PM ET (need 45 min window)
8. **$5-$10 bracket check:** If price $5-$10, require 2+ consecutive scanner appearances before entry
9. **Confirm HotByVolume presence:** Re-verify symbol is currently on HotByVolume scanner

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing

- **Fixed allocation:** 1% of account per position
- Calculate quantity: `qty = floor(account_value * 0.01 / last_price)`

### Order Placement

1. Call `get_quote(symbol=SYM)` for current price
2. Entry order: `place_order(symbol=SYM, action="BUY", quantity=qty, order_type="MKT")`
3. Stop loss (3.5% below entry): `place_order(symbol=SYM, action="SELL", quantity=qty, order_type="STP", stop_price=round(last_price * 0.965, 2))`
4. No fixed take-profit limit order -- exit is prediction-driven (when symbol enters top-10 GainSinceOpen)
5. Time stop: record `max_hold_time = entry_time + 45 minutes` in `strategy_positions`

### Database Logging

For EVERY order placed, log to:
1. **`scanner_picks`:** symbol, consensus_score, predicted_rank_mean, predicted_rank_std, current_scanners, futures_generated=20, strategy_id="diffusion_scanner"
2. **`orders`:** symbol, action, quantity, order_type, order_id, stop_price, strategy_id="diffusion_scanner"
3. **`strategy_positions`:** strategy_id="diffusion_scanner", symbol, entry_price, stop_price, consensus_score, predicted_rank, current_scanners, entry_time, max_hold_time

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open strategy-31 position, every 10-min cycle:

1. Call `get_quote(symbol=SYM)` for current bid/ask/last/volume
2. Log to `price_snapshots`: bid, ask, last, volume, unrealized P&L, distance to stop
3. **Check prediction fulfillment:**
   - Call `get_scanner_results(scanner="GainSinceOpen", date="YYYY-MM-DD", top_n=10)` (all tiers)
   - If symbol NOW appears in top-10 GainSinceOpen: `prediction_fulfilled = true`
   - This is the primary exit signal (see Phase 7)
4. **Re-run diffusion model (lightweight check):**
   - Generate 5 quick futures (instead of 20) to check if consensus is holding
   - Updated `consensus_score_live` stored in `price_snapshots`
   - If live consensus drops below 0.30, consider early exit (model no longer predicts the move)
5. **Time stop check:** If `current_time > entry_time + 45 minutes`, flag for exit
6. **Dynamic stop management:**
   - If unrealized P&L > 2%, trail stop to breakeven: `modify_order(order_id=STOP_ID, stop_price=entry_price)`
   - If unrealized P&L > 3%, trail stop to +1%: `modify_order(order_id=STOP_ID, stop_price=round(entry_price * 1.01, 2))`
7. **Scanner progression tracking:**
   - Track which scanners the symbol is moving through (e.g., HotByVolume -> HotByPrice -> GainSinceOpen)
   - Record scanner progression in `price_snapshots` metadata
   - Progression toward GainSinceOpen = positive signal, regression = negative

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

1. **Stop loss hit (3.5%):** Automatic via STP order
2. **Prediction fulfilled:** Symbol enters top-10 GainSinceOpen -- market sell within current cycle
3. **Time stop (45 min):** Market sell -- prediction window expired
4. **Live consensus collapse (<0.30):** Model no longer predicts the move -- market sell
5. **End of day (3:15 PM):** Close all remaining positions

### Exit Execution

1. Call `place_order(symbol=SYM, action="SELL", quantity=QTY, order_type="MKT")`
2. Cancel any open stop orders: `cancel_order(order_id=STOP_ORDER_ID)`
3. Close position in `strategy_positions`:
   - `exit_price`, `exit_reason` (stop_loss / prediction_fulfilled / time_stop / consensus_collapse / eod_close)
   - `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `prediction_fulfilled` (boolean), `time_to_fulfillment_minutes` (if fulfilled)
   - `exit_consensus_score` (live consensus at exit)
4. Log to `lessons` table:
   - Was the diffusion prediction correct? Did the symbol actually enter top-10 GainSinceOpen?
   - Time to fulfillment vs expected 30 minutes
   - Consensus score at entry vs exit
   - Scanner progression path: which scanners did the symbol traverse?
   - P&L at moment of prediction fulfillment vs actual exit P&L
   - Lesson text: model accuracy, prediction quality, timing analysis
5. Compute KPIs via `compute_and_log_kpis(strategy_id="diffusion_scanner")`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="diffusion_scanner" with:
   - Futures generated (count), denoising steps, consensus scores computed
   - Prediction accuracy: % of high-consensus predictions that actually entered top-10 GainSinceOpen
   - Scanner state similarity: cosine similarity between predicted and actual S(t+30)
3. Compute `strategy_kpis` for any closed positions:
   - Win rate, avg P&L, max drawdown, Sharpe ratio, avg hold time
   - **Diffusion-specific KPIs:**
     - Prediction fulfillment rate: % of trades where symbol actually entered top-10 GainSinceOpen
     - Mean time to fulfillment (minutes)
     - Consensus-P&L correlation: do higher consensus scores produce higher returns?
     - Scanner progression accuracy: did symbols follow the predicted scanner path?
     - Generation diversity: average pairwise distance between 20 generated futures
     - Denoising quality: MSE between predicted and actual future scanner states
4. Call `complete_job_execution(exec_id, summary)` with full run summary
5. Call `get_daily_kpis()` to compare against other strategies

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| DDPM full training | Weekly (Sunday 8 PM) | 200 epochs on 40-day scanner state history, U-Net with attention |
| Noise schedule tuning | Weekly | Validate linear beta schedule vs cosine schedule on holdout data |
| Symbol embedding update | Weekly | Re-learn embeddings for new symbols appearing in scanners |
| Generation quality audit | Daily | Compare yesterday's predictions vs actual outcomes, log accuracy |
| Architecture review | Monthly | Evaluate deeper U-Net, different attention mechanisms, classifier-free guidance |
| Denoising step count experiment | Monthly | Test 25, 50, 100 steps for quality vs latency tradeoff |

### DDPM Training Details (Sunday)

1. Collect 40 trading days via `get_scanner_dates()`
2. For each day, build scanner state matrices at 10-min intervals (approx 39 snapshots per day)
3. Create (S(t), S(t+30min)) pairs -- approx 36 pairs per day x 40 days = 1,440 training pairs
4. Symbol embedding table: initialize with random vectors for all symbols seen in 40 days
5. Hyperparameters:
   - Beta schedule: linear from 0.0001 to 0.02 over T=50 steps
   - U-Net channels: [64, 128, 256]
   - Attention: multi-head self-attention at 128-channel resolution
   - Optimizer: AdamW, lr=1e-4, weight_decay=0.01
   - Batch size: 32
   - Epochs: 200 with early stopping (patience=20)
6. Validation: hold out last 5 days, evaluate prediction accuracy and MSE
7. Save best model by validation loss
8. Store in `strategy_runs` with training metrics, validation scores, symbol embedding table size

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Candidates with consensus scores and prediction details | Phase 4, 5 |
| `orders` | Entry/exit orders with full details | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle with diffusion metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + live consensus + scanner progression each cycle | Phase 6 |
| `strategy_runs` | DDPM model weights, generation metrics, prediction accuracy | Phase 8, weekly train |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with prediction fulfillment analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, fulfillment rate, consensus correlation | Phase 2, 8 |

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` -- collect scanner states for training data and live state matrix
- `get_scanner_dates()` -- enumerate available dates for 40-day training window
- `get_quote(symbol)` -- current price for quality gate, monitoring, and market-wide features (SPY)
- `get_historical_bars(symbol, duration, bar_size)` -- price data for symbol embedding context
- `calculate_indicators(symbol, indicators=["RSI", "VWAP"], duration="1 D", bar_size="1 min", tail=10)` -- market context features
- `get_positions()` -- check current portfolio
- `get_portfolio_pnl()` -- P&L monitoring and stop enforcement
- `get_open_orders()` -- prevent duplicates, verify stop orders
- `get_closed_trades(save_to_db=True)` -- reconcile IB executions
- `place_order(symbol, action, quantity, order_type, stop_price)` -- entry and exit execution
- `cancel_order(order_id)` -- cancel stops on exit
- `modify_order(order_id, quantity, limit_price, stop_price)` -- trail stops dynamically
- `get_strategy_positions(strategy_id="diffusion_scanner", status, limit)` -- query positions
- `get_strategy_kpis_report(strategy_id="diffusion_scanner")` -- performance review
- `get_job_executions(job_id="diffusion_scanner", limit)` -- execution history
- `get_daily_kpis()` -- cross-strategy comparison
- `get_position_price_history(position_id)` -- detailed price path for prediction accuracy analysis
