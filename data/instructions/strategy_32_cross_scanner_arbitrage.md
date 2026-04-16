---
noteId: "s32_cross_scanner_arb_01"
tags: [strategy, cron, scanner, arbitrage, volume, information-asymmetry]

---

# Strategy 32: Cross-Scanner Arbitrage Detector — Operating Instructions

## Schedule

Runs every 10 minutes during market hours (9:35 AM – 3:40 PM ET) via Claude Code CronCreate.
Primary scan window: 9:35 AM – 11:30 AM (volume/price divergence most common in first 2 hours).
Secondary window: 1:00 PM – 2:30 PM (post-lunch volume spikes with delayed price action).

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Relevant scanner types: HotByVolume, GainSinceOpen, TopGainers, HotByPrice, HotByPriceRange, LossSinceOpen, TopLosers, TopVolumeRate
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every cron run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_32_cross_scanner_arb")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1–8)
   - Operation counts: `positions_checked`, `losers_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply rules learned (especially volume-without-direction vetoes)
2. **Load strategy files** — this strategy (S32) plus S07 (conflict filter), S04 (cut losers), S09 (multi-scanner conviction)
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check open orders** via `get_open_orders()` — verify no pending orders conflict with new signals
5. **Count active S32 positions** via `get_strategy_positions(strategy_id="cross_scanner_arb", status="open")` — enforce max 3 concurrent
6. **Verify IB connection** — if `get_positions()` fails, call `fail_job_execution(exec_id, "IB disconnected")` and abort
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs BEFORE any new trades)

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each S32 position with `pnl_pct <= -2.5%` (strategy-specific stop):
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol, action="SELL", quantity=shares_held, order_type="MKT")`
   c. Log to `orders` table with `strategy_id = "cross_scanner_arb"`, exit details
   d. Close in `strategy_positions` with `exit_reason = "stop_loss_2.5pct"`
   e. Log to `lessons` table: symbol, entry/exit prices, P&L, scanner, lesson text
   f. Compute KPIs via `get_strategy_kpis_report(strategy_id="cross_scanner_arb")`
3. For S32 positions open > 20 minutes (time stop):
   a. Calculate elapsed time since entry (from `strategy_positions.entry_time`)
   b. If elapsed > 20 min and the symbol has NOT appeared on GainSinceOpen or HotByPrice:
      - Call `place_order(symbol, action="SELL", quantity=shares_held, order_type="MKT")`
      - Close with `exit_reason = "time_stop_20min"`
      - Log lesson: "Gap did not close within 20 min — volume surge was not a price precursor"
4. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### Step 1: Identify HotByVolume Candidates

1. Call `get_scanner_results(scanner="HotByVolume", date="today", top_n=20)` for each cap tier (SmallCap, MidCap, LargeCap)
2. Filter to symbols with **rank <= 15** on HotByVolume
3. Record each symbol's HotByVolume rank and first-seen timestamp

### Step 2: Cross-Scanner Exclusion Check

For each HotByVolume candidate, check presence on these scanners:

| Scanner | Check | If Present |
|---------|-------|------------|
| GainSinceOpen | `get_scanner_results(scanner="GainSinceOpen", date="today", top_n=30)` | EXCLUDE — price has already moved |
| TopGainers | `get_scanner_results(scanner="TopGainers", date="today", top_n=30)` | EXCLUDE — price has already moved |
| HotByPrice | `get_scanner_results(scanner="HotByPrice", date="today", top_n=30)` | EXCLUDE — price has already moved |
| LossSinceOpen | `get_scanner_results(scanner="LossSinceOpen", date="today", top_n=30)` | HARD VETO — volume on losing stock |
| TopLosers | `get_scanner_results(scanner="TopLosers", date="today", top_n=30)` | HARD VETO — volume on losing stock |

**Valid candidate**: on HotByVolume rank <= 15 AND NOT on any of the 5 scanners above.

### Step 3: Freshness & TopVolumeRate Confirmation

1. Time since first appearance on HotByVolume must be **<= 5 minutes** — reject stale signals
   - Compare current time to `first_seen_time` from scanner tracking
   - If > 5 min, log rejection: `reject_reason = "stale_volume_signal"`
2. Check `get_scanner_results(scanner="TopVolumeRate", date="today", top_n=30)`:
   - Symbol MUST be present on TopVolumeRate (volume acceleration, not just level)
   - TopVolumeRate rank should be **improving** (lower rank = better) over last 2 snapshots

### Step 4: Feature Vector

For each surviving candidate, build this feature set:

| Feature | Source | Calculation |
|---------|--------|-------------|
| `hotbyvol_rank` | HotByVolume scanner | Current rank (1–15) |
| `hotbyvol_time_on` | Scanner tracking | Minutes since first seen on HotByVolume |
| `topvolrate_rank` | TopVolumeRate scanner | Current rank |
| `topvolrate_improving` | TopVolumeRate scanner | Boolean: rank decreased vs prior snapshot |
| `price_change_pct` | `get_quote(symbol)` | (last - open) / open × 100 |
| `spread_pct` | `get_quote(symbol)` | (ask - bid) / last × 100 |
| `volume_ratio` | `get_historical_bars(symbol, duration="1 D", bar_size="1 min")` | Current 5-min volume / avg 5-min volume |
| `scanner_count` | All scanners | Number of distinct scanners symbol appears on |
| `rsi_5` | `calculate_indicators(symbol, indicators=["RSI"], duration="1 D", bar_size="1 min", tail=20)` | 5-period RSI on 1-min bars |

5. Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

This strategy uses a **rule-based arbitrage detector**, not a trained model. The "information asymmetry" is the gap between volume surge and price movement.

### Signal Scoring

For each candidate passing Phase 3:

| Condition | Points |
|-----------|--------|
| HotByVolume rank <= 5 | +3 |
| HotByVolume rank 6–10 | +2 |
| HotByVolume rank 11–15 | +1 |
| TopVolumeRate improving | +2 |
| TopVolumeRate rank <= 10 | +1 |
| Volume ratio > 5x | +2 |
| Volume ratio 3x–5x | +1 |
| Price change < +0.5% (price hasn't moved yet) | +3 |
| Price change +0.5% to +1.0% | +1 |
| Price change > +1.0% | -2 (gap partially closed already) |
| Spread > 2% | -3 (illiquid, will eat profit) |
| RSI > 70 | -1 (already overbought on short timeframe) |

**Minimum score to trade: 6 points.**

### Ranking

Rank all candidates by score descending. Select top 3 minus current open S32 positions.

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, run these checks via `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Check `get_historical_bars(symbol, duration="1 D", bar_size="1 day")` — avg daily volume >= 50,000
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Contract validation:** Call `get_contract_details(symbol)` — must be a common stock (STK), not ADR/warrant
6. **Position limit:** Current open S32 positions < 3
7. **No duplicate:** Symbol not already in `get_positions()` or `get_open_orders()`
8. **Account exposure:** Total S32 exposure < 4.5% of account (3 positions × 1.5%)

Log any rejection to `scanner_picks` with `rejected = 1` and `reject_reason`.

### Position Sizing

- **Size:** 1.5% of account value per position
- Calculate shares: `floor(account_value * 0.015 / ask_price)`
- Minimum 1 share, cap at available buying power

### Order Placement

For each approved candidate:

1. **Entry order:** `place_order(symbol, action="BUY", quantity=shares, order_type="MKT")`
2. **Stop loss:** `place_order(symbol, action="SELL", quantity=shares, order_type="STP", stop_price=round(ask * 0.975, 2))`
   - 2.5% below entry (tight stop — this is a short-duration arbitrage)
3. Record entry time for the 20-minute time stop

### Database Logging (MANDATORY for every order)

1. **`scanner_picks`**: symbol, scanner="HotByVolume", rank, score, action="BUY", rejected=0, scanners_present (list which scanners the symbol is on)
2. **`orders`**: symbol, action="BUY", quantity, order_type, order_id, entry_price (ask at time of order), strategy_id="cross_scanner_arb"
3. **`strategy_positions`**: strategy_id="cross_scanner_arb", symbol, action="BUY", quantity, entry_price, stop_price, target_price=NULL (target is scanner-based, not price-based), entry_time, scanners_at_entry

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open S32 position every run:

1. **Price snapshot:** Call `get_quote(symbol)` — log to `price_snapshots` with bid, ask, last, volume, unrealized P&L
2. **Gap-closing check:** The core exit signal for this strategy:
   a. Call `get_scanner_results(scanner="GainSinceOpen", date="today", top_n=30)`
   b. Call `get_scanner_results(scanner="HotByPrice", date="today", top_n=30)`
   c. If the symbol NOW appears on GainSinceOpen OR HotByPrice → **the gap has closed**, mark for exit in Phase 7
3. **Time check:** Calculate minutes since entry — if > 20 min without gap closing, mark for time stop exit
4. **Adverse check:** Call `get_scanner_results(scanner="LossSinceOpen", date="today", top_n=30)` and TopLosers:
   - If symbol appears on ANY loser scanner → **immediate exit**, the thesis is broken
5. **Update position extremes:** track peak price, trough price, max favorable excursion (MFE), max adverse excursion (MAE)

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
| Symbol appears on LossSinceOpen/TopLosers | Immediate MKT SELL | `thesis_broken_loser` |
| P&L <= -2.5% | Immediate MKT SELL (stop should have filled) | `stop_loss_2.5pct` |
| Symbol appears on GainSinceOpen or HotByPrice | MKT SELL — gap closed, profit captured | `gap_closed_target` |
| Time > 20 min since entry without gap closing | MKT SELL | `time_stop_20min` |

### For Each Exit

1. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")`
2. Cancel any remaining open stop orders for this symbol via `cancel_order(order_id)`
3. Close position in `strategy_positions`:
   - `exit_price`: last price from `get_quote(symbol)`
   - `exit_reason`: from table above
   - `pnl` and `pnl_pct`: calculated from entry/exit
   - `hold_duration_minutes`: time since entry
4. Log to `lessons` table:
   - symbol, strategy_id="cross_scanner_arb", entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner_at_entry="HotByVolume", exit_reason
   - lesson text — e.g., "Volume surge on {symbol} with rank {rank} led to {pnl_pct}% in {minutes} min. Gap {'closed' if exit='gap_closed_target' else 'did not close'}."
5. If exit_reason = "gap_closed_target", note: "Arbitrage window from volume-to-price was {minutes} min. Consider adjusting time stop."
6. If exit_reason = "time_stop_20min", note: "Volume surge did not translate to price movement within 20 min. Check if volume was institutional accumulation or retail churn."

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="cross_scanner_arb" with cycle details
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="cross_scanner_arb")`:
   - Win rate (target: >55%)
   - Avg win vs avg loss
   - Avg hold duration (target: <15 min)
   - Gap-close rate (% of trades where target was hit vs time stop)
   - Avg time to gap close
4. Call `complete_job_execution(exec_id, summary)` with:
   - Candidates screened, rejected, traded
   - Current open S32 positions
   - P&L for closed S32 positions this session
   - Gap-close rate this session

---

## Model Training / Retraining Schedule

This strategy is rule-based. No model training required.

**Parameter review (weekly, Friday EOD):**
- Review gap-close rate — if < 40%, tighten HotByVolume rank threshold from 15 to 10
- Review avg hold duration — if > 12 min avg, the market is slower; consider extending time stop to 25 min
- Review spread impact — if avg spread at entry > 1.5%, add stricter spread filter
- Review by cap tier — if SmallCap win rate < 40%, restrict to MidCap/LargeCap only
- Review by time of day — if afternoon signals underperform, restrict to morning window only

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each cron run | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every HotByVolume candidate (accepted & rejected) | Phase 4, 5 |
| `orders` | Every entry/exit order placed | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle (open → monitor → close) | Phase 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with P&L and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, hold duration, gap-close rate | Phase 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_results` | 3, 6 | Read HotByVolume, GainSinceOpen, TopGainers, HotByPrice, LossSinceOpen, TopLosers, TopVolumeRate |
| `get_scanner_dates` | 3 | Verify scanner data available for today |
| `get_quote` | 3, 5, 6, 7 | Current bid/ask/last/volume for candidates and positions |
| `get_historical_bars` | 3, 5 | Volume ratio calculation, avg daily volume check |
| `calculate_indicators` | 3 | RSI for overbought filter |
| `get_contract_details` | 5 | Validate security type (common stock only) |
| `get_positions` | 1, 5 | Current portfolio positions |
| `get_portfolio_pnl` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders` | 1, 2, 5 | Check for duplicate/existing orders |
| `get_closed_trades` | 2 | Reconcile IB executions with DB |
| `place_order` | 2, 5, 7 | Entry, stop-loss, and exit orders |
| `cancel_order` | 7 | Cancel remaining stops after exit |
| `get_strategy_positions` | 1, 2 | Count open S32 positions, enforce max 3 |
| `get_strategy_kpis_report` | 2, 8 | Compute and review strategy KPIs |
| `get_trading_picks` | 1 | Review recent picks for dedup |
| `get_trading_orders` | 1 | Review recent orders |
| `get_trading_lessons` | 1 | Load lessons for rule application |
| `get_scan_runs` | 8 | Log scan cycle summary |
| `get_job_executions` | 0 | Track job execution lifecycle |
| `get_daily_kpis` | 8 | Daily aggregate performance |
