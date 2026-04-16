---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, volume-surge, scanner-patterns]

---

# 32-Rotation-Volume Surge Entry — Operating Instructions

## Overview
Exploits the statistically validated phenomenon that volume scanner appearances PRECEDE gain scanner appearances by an average of 120 minutes. By entering when volume spikes — before the price move is visible on gain scanners — this strategy captures the accumulation phase.

**Data Backing (Report §3):** 10,102 volume-leads-price events across 53 trading days (191/day). 25 tickers with highly predictable volume→gain lead patterns identified.

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 3:50 PM ET) via Claude Code CronCreate.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`**

## Strategy ID
`rotation_volume_surge`

---

## Known Predictable Tickers (from Report §3)

These tickers have historically shown consistent volume→gain scanner lead patterns. They receive a conviction bonus.

| Ticker | Signals | Avg Lead (min) | Min Lead | Max Lead |
|--------|---------|----------------|----------|----------|
| SOXL | 42 | 119 | 5 | 271 |
| SQQQ | 40 | 121 | 5 | 302 |
| SNXX | 37 | 126 | 5 | 295 |
| MSTZ | 36 | 153 | 7 | 901 |
| SLV | 34 | 91 | 5 | 309 |
| TSLL | 33 | 142 | 5 | 386 |
| AMDL | 32 | 108 | 5 | 269 |
| KOLD | 31 | 104 | 7 | 566 |
| TQQQ | 31 | 127 | 10 | 386 |
| CRWV | 30 | 75 | 3 | 355 |
| NVDA | 30 | 103 | 5 | 277 |
| USO | 30 | 116 | 7 | 394 |
| NVDL | 29 | 70 | 5 | 273 |
| ZSL | 29 | 181 | 9 | 341 |
| PLTR | 28 | 102 | 5 | 358 |
| RDW | 27 | 126 | 18 | 315 |
| INTC | 27 | 149 | 5 | 386 |
| RKLB | 27 | 89 | 5 | 434 |
| LITX | 27 | 63 | 2 | 238 |
| ONDS | 26 | 89 | 4 | 269 |
| TSLQ | 26 | 125 | 11 | 362 |
| BOIL | 26 | 110 | 1 | 400 |
| BITX | 26 | 146 | 3 | 798 |
| EWY | 26 | 103 | 1 | 336 |
| HOOD | 26 | 99 | 2 | 533 |

### Lead Time Distribution
```
     <5min: 1276 (13%) — fast movers, best for scalping
   5-15min:  901  (9%) — actionable window
  15-30min: 1081 (11%) — standard entry window
  30-60min: 1382 (14%) — requires patience
    >60min: 5462 (54%) — majority; set time stop at 180 min
```

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

1. Open `rotation_scanner.db` — ensure tables exist (see strategy_31 master schema)
2. INSERT into `job_executions` with `job_id="rotation_volume_surge"` — capture `exec_id`
3. After each phase, UPDATE with `phase_completed`, operation counts
4. On success: `status="completed"`, `completed_at`, `summary`
5. On error: `status="failed"`, `error_message`

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` AND `rotation_scanner.db` → `lessons` WHERE `sub_strategy="rotation_volume_surge"`
2. **Check positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count open positions: `rotation_scanner.db` → `strategy_positions` WHERE `sub_strategy="rotation_volume_surge" AND status="open"`
   - Max 2 concurrent positions for this sub-strategy — if at limit, skip to Phase 6
3. **Check open orders** via `get_open_orders()`
4. **Verify IB connection** — if disconnected, log error, attempt reconnect
5. **Load whipsaw watchlist** from `rotation_scanner.db` → `whipsaw_watchlist` — these get special filtering
6. **Load today's volume_lead_signals** from DB — track which symbols already had volume signals today
7. UPDATE `job_executions` with `phase_completed=1`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for current P&L
2. Query `strategy_positions` WHERE `sub_strategy="rotation_volume_surge" AND status="open"`
3. For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if SELL order exists
   b. Place MKT SELL to liquidate
   c. Log to `orders`, close in `strategy_positions` with `exit_reason="stop_loss_5pct"`
   d. INSERT into `lessons`
4. **Time stop enforcement:** For each open position where `minutes_held >= 180`:
   - If symbol has NOT appeared on any gain scanner since entry → close with `exit_reason="time_stop_180min_no_gain"`
   - If symbol HAS appeared on gain scanner → convert to trailing stop (2% below current price), extend hold
5. **Reconcile closed trades:** Call `get_closed_trades(save_to_db=True)`, match against DB positions
6. UPDATE `job_executions` with `phase_completed=2`

---

## PHASE 3: Signal Detection

### Step 1: Collect Scanner Data
For each cap tier (SmallCap, MidCap, LargeCap):
- Call `get_scanner_results` for volume scanners: HotByVolume, MostActive, TopVolumeRate (top 50)
- Call `get_scanner_results` for gain scanners: TopGainers, GainSinceOpen (top 50)
- Call `get_scanner_results` for loss scanners: TopLosers, LossSinceOpen (top 50)

### Step 2: Identify Volume-Only Symbols
For each symbol on ANY volume scanner:
1. Check if symbol is on ANY gain scanner right now → if YES, skip (price move already visible)
2. Check if symbol is on ANY loss scanner right now → if YES, skip (volume without direction — Lesson 4)
3. Symbol is on volume scanner BUT NOT on gain or loss scanner → **VOLUME SURGE CANDIDATE**

### Step 3: Log Signals
For each candidate, INSERT into `rotation_scanner.db` → `volume_lead_signals`:
- symbol, volume_scanner, volume_first_seen timestamp, price_at_volume_signal (via `get_quote`)
- `traded=0` (not yet traded)

### Step 4: Cross-Reference Known Predictable Tickers
- If candidate is in the top-25 predictable tickers list → flag as HIGH PRIORITY
- Record the ticker's historical avg lead time for position management

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring

For each volume surge candidate:

| Factor | Points | Check |
|--------|--------|-------|
| Known predictable ticker (top 25 list) | +3 | Symbol in list above |
| On 2+ volume scanners simultaneously | +2 | Count distinct volume scanner appearances |
| NOT on any loss scanner | +2 | Cross-reference loss scanners |
| Lead time < 60 min historically (fast mover) | +1 | From known ticker table |
| Price > $5 | +1 | From `get_quote` |
| On whipsaw watchlist (EXTREME danger) | -3 | Cross-reference `whipsaw_watchlist` |
| Already had a volume signal today (stale) | -2 | Check `volume_lead_signals` for today |
| On loss scanner in last 30 min | -3 | Recent loss scanner check |

### Tier Classification
- **Tier 1 (score 5+):** TRADE — proceed to Phase 5
- **Tier 2 (score 3-4):** REJECT — log as `rejected=1` with reason
- **Tier 3 (score 1-2):** WATCH only — log as `rejected=1`
- **Negative:** BLACKLIST — log as `rejected=1`

Log ALL candidates to `rotation_scanner.db` → `scanner_picks` with:
- `sub_strategy="rotation_volume_surge"`
- `conviction_score`, `conviction_tier`
- `signal_metadata` JSON: `{"volume_scanners": [...], "avg_lead_min": N, "is_known_predictable": true/false}`

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate (MANDATORY)
Before placing ANY order, call `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $2.00
2. **Minimum volume:** Avg daily volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject R, W, WS, U suffixes
5. **$5-$10 confirmation:** Require 2+ consecutive volume scanner appearances
6. **Not already held:** Check `get_positions()` + `strategy_positions`
7. **Not already ordered:** Check `get_open_orders()`
8. **Whipsaw veto:** If on whipsaw watchlist with EXTREME danger → REJECT

### Position Limits
- Max **2** concurrent positions for `rotation_volume_surge`
- Max **1** new entry per 10-minute cycle
- 1 share per ticker

### Order Structure
1. **Entry:** `place_order(symbol, action="BUY", quantity=1, order_type="MKT")`
2. **Stop Loss:** `place_order(symbol, action="SELL", quantity=1, order_type="STP", stop_price=entry * 0.95)` — 5% stop, or 1.5x ATR if tighter
3. **No limit target** — this strategy exits when gain scanner fires or time stop hits

### Post-Order Protection
- Immediately place protective GTC STP SELL
- Verify via `get_open_orders()`
- Log all orders to `rotation_scanner.db` → `orders`

### Log to Database
1. `scanner_picks`: symbol, sub_strategy, scanner, rank, conviction_score, conviction_tier, action="BUY"
2. `orders`: symbol, sub_strategy, action, quantity, order_type, ib_order_id, stop_price, entry_price
3. `strategy_positions`: sub_strategy="rotation_volume_surge", symbol, entry_price, stop_price, signal_metadata
4. `volume_lead_signals`: UPDATE `traded=1` for this signal

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring

For each open `rotation_volume_surge` position:

1. Call `get_quote(symbol)` for current price
2. INSERT `price_snapshots` with bid, ask, last, volume, unrealized P&L, distances
3. Update position extremes: peak, trough, MFE, MAE, drawdown

### Volume→Gain Transition Check (KEY MONITORING)
- Check if symbol has now appeared on ANY gain scanner (TopGainers, GainSinceOpen)
- If YES:
  - Log lead time to `volume_lead_signals`: `gain_first_seen`, `lead_time_minutes`, `price_at_gain_signal`
  - Switch exit mode: set trailing stop at 3% below current high (momentum confirmed)
  - UPDATE `strategy_positions` signal_metadata with `{"gain_scanner_confirmed": true, "lead_time_min": N}`
- If NO and minutes_held > 180:
  - Prepare exit in Phase 7 with `exit_reason="time_stop_180min_no_gain"`

### Loss Scanner Veto
- If symbol appears on ANY loss scanner while held → prepare immediate exit
- `exit_reason="loss_scanner_veto"`

### Profit Protection — Trailing Stop Ratchet (MANDATORY)

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +10% to +20% | Breakeven (entry price) |
| +20% to +50% | +10% above entry |
| +50% to +100% | MAX(+25% above entry, peak × 0.80) |
| >+100% | Trail at peak × 0.75 |

- Stops only ratchet UP
- Use `modify_order` to raise existing stops
- Log adjustments to `orders`

UPDATE `job_executions` with `phase_completed=6, positions_monitored=N, snapshots_logged=N`

---

## PHASE 7: Exit Handling & Lessons

### Exit Triggers
| Trigger | Exit Reason | Action |
|---------|-------------|--------|
| Stop loss hit (-5%) | `stop_loss_5pct` | Auto via STP order |
| Time stop (180 min, no gain scanner) | `time_stop_180min_no_gain` | MKT SELL |
| Loss scanner appearance | `loss_scanner_veto` | MKT SELL |
| Trailing stop hit (after gain confirmed) | `trailing_stop_gain_confirmed` | Auto via modified STP |
| EOD forced close (3:50 PM) | `eod_close` | MKT SELL |

### On Exit
1. UPDATE `strategy_positions`: status="closed", exit_price, exit_time, exit_reason, compute pnl/pnl_pct/hold_duration
2. INSERT into `lessons`:
   - symbol, sub_strategy="rotation_volume_surge", entry/exit prices, pnl
   - signal_metadata: volume scanners at entry, was gain scanner confirmed?, lead time if confirmed
   - lesson_text: "Volume signal on [scanners] at [time]. Gain scanner [confirmed/not confirmed] after [N] min. P&L: [X]%"
3. UPDATE `volume_lead_signals` with price_change_pct (actual outcome)
4. Compute KPIs if needed

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N`

---

## PHASE 8: Run Summary & KPIs

### Per-Cycle Summary
INSERT into `scan_runs` with candidates_found, rejected, orders_placed, positions_held, summary.

### KPIs (computed on closed trades)

| KPI | Formula | Target |
|-----|---------|--------|
| Win Rate | wins / total | > 45% |
| Avg Win | mean(pnl where pnl > 0) | > 2% |
| Avg Loss | mean(pnl where pnl < 0) | < -4% |
| Profit Factor | sum(wins) / abs(sum(losses)) | > 1.3 |
| Expectancy | (WR × avg_win) - ((1-WR) × abs(avg_loss)) | > 0.3% |
| Gain Confirmation Rate | % of entries where gain scanner eventually fired | > 50% |
| Avg Lead Time (actual) | mean(lead_time_minutes) for confirmed signals | Track trend |
| Signal Hit Rate | % of Tier 1 signals producing > 1% gain | > 55% |
| Time Stop Rate | % of exits via time_stop_180min | < 30% (if higher, lead time model is off) |
| MFE/MAE Ratio | avg_mfe / avg_mae | > 1.5 |

### Circuit Breakers
- 5 consecutive losses → disable for rest of day
- Gain confirmation rate < 30% over last 20 trades → review signal detection logic
- Time stop rate > 50% → increase time stop to 240 min or tighten entry criteria

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`

---

## Lessons Pre-Loaded

### VS-1: 54% of Leads are >60 Minutes
Most volume→gain transitions take over an hour. Do NOT exit prematurely at 30-60 min. The 180 min time stop accounts for the long tail of the lead distribution.

### VS-2: Leveraged ETFs Have Volume Signals but Whipsaw
SOXL, SQQQ, TQQQ dominate the known predictable list but also have EXTREME whipsaw danger. Only trade these if NOT on whipsaw watchlist AND conviction score is 6+.

### VS-3: Loss Scanner Appearance is a Hard Veto
If a ticker moves from volume scanner to loss scanner (instead of gain), the thesis is broken. Exit immediately — do not wait for time stop.

### VS-4: Fast Movers (<15 min lead) are the Best Trades
Signals where gain scanner fires within 15 min of volume signal capture the sharpest moves. Track and report these separately — they should have the highest win rate.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect volume and gain scanner data |
| `get_quote(symbol)` | Phase 3 (signal price), Phase 5 (quality gate), Phase 6 (monitoring) |
| `calculate_indicators(symbol, indicators=["ATR"], duration, bar_size, tail)` | Phase 5 — ATR for stop calculation |
| `get_positions()` | Phase 1, Phase 5 |
| `get_portfolio_pnl()` | Phase 1, Phase 2 |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 |
| `get_closed_trades(save_to_db=True)` | Phase 2 |
| `place_order(symbol, action, quantity, order_type, stop_price)` | Phase 2, Phase 5 |
| `modify_order(order_id, ...)` | Phase 6 — ratchet stops |
| `get_scanner_dates()` | Phase 3 — confirm today's data |
