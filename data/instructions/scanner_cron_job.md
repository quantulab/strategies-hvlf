---
noteId: "60f37c9038d711f1aa17e506bb81f996"
tags: [cron, trading, strategies, risk-management]

---

# Scanner Cron Job — Operating Instructions

## Schedule
Runs every 10 minutes during market hours via Claude Code CronCreate.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\scanner-monitor\{YYYYMMDD}\`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\` (11 strategy files)
- Lessons: `D:\src\ai\mcp\ib\data\lessons\` (post-trade analysis)
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id)` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned (see Lesson Application Rules below)
2. **Load all 11 strategy files** from `data/strategies/` — match current market conditions to applicable strategies
3. **Check current positions** via `get_positions` and `get_portfolio_pnl`
4. **Check current open orders** via `get_open_orders`
5. **Verify IB connection** — if disconnected, log error via `fail_job_execution` and attempt reconnect before proceeding (Lesson: gateway disconnect)
6. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the -5% stop-loss rule on ALL positions.**

1. Call `get_portfolio_pnl` to get current P&L for every position
2. For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders` — skip if a SELL order already exists for this symbol (prevents accidental shorts)
   b. Place MKT SELL order to liquidate
   c. Log to `orders` table with `strategy_id = "cut_losers"`, full order details
   d. Log to `strategy_positions` — close the position with `exit_reason = "stop_loss_5pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, scanner, and lesson text
   f. Compute and log KPIs for the strategy that opened this position via `compute_and_log_kpis`
3. For short positions (quantity < 0) that were created accidentally:
   a. Place MKT BUY order to close the short
   b. Log with `exit_reason = "close_accidental_short"`
4. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. Compare current positions against positions held in the previous cycle
   c. For every position that disappeared (closed externally by stop/limit/manual):
      - Call `close_position(position_id, exit_price, exit_reason)` in `strategy_positions` — this computes P&L and hold duration automatically
      - Log to `lessons` table with symbol, entry/exit prices, P&L, exit_reason (stop_loss/take_profit/manual), strategy_id, and lesson text
      - Log to `orders` table with exit order details
   d. Also check `get_open_positions()` from DB and compare against current IB positions — close any DB positions whose symbol is no longer in IB
   e. This ensures NO closed trade goes unrecorded — IB is the source of truth, `strategy_positions` must match
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Scanner Analysis

1. Call `get_scanner_results` to read latest scanner data
2. Find tickers trending into top 10 (rank improving over time)
3. Categorize each scanner:
   - **Gain scanners**: GainSinceOpenLarge/Small, PctGainLarge/Small → LONG bias
   - **Loss scanners**: LossSinceOpenLarge/Small, PctLossLarge/Small → SHORT bias / veto
   - **Volume scanners**: HotByVolumeLarge/Small → Direction from cross-reference

### Direction Logic
- Gain scanner hit → BUY (long)
- Volume scanner + NOT in any loss scanner → BUY (long)
- Volume scanner + IN a loss scanner → SKIP (Lesson 4: volume without direction is meaningless)
- Loss scanner only → ignored

---

## PHASE 4: Strategy Matching & Conviction Scoring

### Strategy Selection
For each scanner candidate, determine which strategy applies:

| Strategy | ID | Trigger Condition |
|----------|-----|-------------------|
| Momentum Surfing | `momentum_surfing` | On 2+ gain scanners, price above prior day high |
| Gap-and-Go | `gap_and_go` | Gap up >50% premarket, >1M premarket volume |
| Fade Euphoria | `fade_euphoria` | Up >100% intraday with topping signals |
| Cut Losers | `cut_losers` | Position losing >5% (handled in Phase 2) |
| Pairs Trade | `pairs_trade` | Two correlated stocks, ratio at 1-std-dev extreme |
| Volume Breakout | `volume_breakout` | First appearance on HotByVolume, positive price action |
| Scanner Conflict | `conflict_filter` | Cross-scanner conflict detected (overlay, not standalone) |
| Oversold Bounce | `oversold_bounce` | Down >40% from 20-day high, bottoming pattern |
| Multi-Scanner Conviction | `multi_scanner` | 3+ scanner appearances simultaneously |
| Overnight Gap Risk | `overnight_gap_risk` | Any position up/down >20% intraday (end-of-day) |
| Quantum Catalyst | `quantum_catalyst` | Quantum sector catalyst with leveraged ETF exposure |

### Conviction Scoring (Strategy 9)
- +2 points: PctGain scanner
- +2 points: HotByVolume scanner
- +1 point: GainSinceOpen scanner
- -2 points: Any loss scanner
- -1 point: Conflicting gain + loss scanners

#### Tiers
- **Tier 1 (score 5+):** Trade with full size — log as `conviction_tier = "tier1"`
- **Tier 2 (score 3-4):** **REJECT** — insufficient conviction, log pick as `rejected = 1`
- **Tier 3 (score 1-2):** Watchlist only, do NOT trade — log pick as `rejected = 1`
- **Negative:** Blacklist, do NOT trade — log pick as `rejected = 1`

> **Only Tier 1 picks are tradeable.** This was changed on 2026-04-15 to improve win rate (40% → 60% target). Tier 2 picks had too many false signals.

### Stale Signal Override — Catalyst Confirmation Rule

Lesson 1 rejects stocks on scanners >10 minutes. However, **multi-day catalyst plays** should NOT be auto-rejected if they meet ALL of the following:

1. **Tier 1 conviction** (score 5+, on 3+ scanners)
2. **Real catalyst confirmed** — check news via `get_news_headlines`. Must have a fundamental event (pivot, M&A, FDA, financing, partnership), NOT just momentum/squeeze
3. **Volume >1000x 20-day average** — institutional-scale participation, not retail pump
4. **Price holding >50% of intraday high** — consolidating, not crashing back. Calculate: `(current - low) / (high - low) > 0.50`
5. **Spread < 1%** — tight liquidity confirms real two-sided market
6. **Price > $2** — quality gate still applies

If all 6 conditions are met, the stock is upgraded from "stale reject" to **"catalyst hold"** and is eligible for entry with:
- **Entry**: on first pullback to consolidation support (not market chasing the high)
- **Stop**: below the intraday consolidation low or 1.5x ATR, whichever is tighter
- **Target**: trailing stop at 15% below intraday high (these are volatile multi-day names)
- **Max hold**: 2 days for catalyst plays (decay risk on extended moves)

Log the override reason in `scanner_picks` as: `"Stale signal overridden: catalyst confirmation [catalyst description]"`

### Conflict Filter (Strategy 7) — Applied BEFORE entry
- Level 1 (Yellow): Gain + Volume → proceed with caution, tighter stops
- Level 2 (Orange): Gain + Loss same day → half size, tighter stops
- Level 3 (Red): PctGain + PctLoss + HotByVolume → **NO TRADE**, log rejection

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, run these checks via `get_quote`. Reject if any fail:

1. **Minimum price:** Last price >= $2.00 — reject sub-$2 stocks (25% win rate historically)
2. **Minimum volume:** Avg daily volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** (ask - bid) / last <= 3% — reject wide-spread penny stocks
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **$5-$10 confirmation:** For stocks priced $5-$10, require the symbol to have appeared on a scanner in 2+ consecutive runs before entry (prevents FOMO on initial pop — this bracket was 0% win rate on 2026-04-15)

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **10** open positions at any time (reduced from 15 on 2026-04-15 — forces selectivity)
- Maximum **2 new entries per 10-minute cron cycle** (added 2026-04-15 EOD — prevents batch-entry loss streaks; 10 consecutive losses occurred from entering too many positions simultaneously)
- 1 share per ticker
- Re-entry allowed if ticker exits and reappears on scanner
- Check for existing position/order AND current IB positions before placing new ones (prevents duplicates AND accidental shorts)

### Order Structure
- Entry: MKT BUY or MKT SELL
- Stop Loss: ATR-based when available, otherwise 5% from entry (STP order)
- Take Profit: **NO fixed take-profit LMT order** — profit is protected by the trailing stop ratchet in Phase 6

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Verify stop was placed by checking `get_open_orders` for the symbol
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

### For EVERY order placed, log to database:
1. **`scanner_picks` table:** symbol, scanner, rank, rank_trend, conviction_score, conviction_tier, scanners_present, action, rejected flag, reject_reason
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status, pick_id, strategy_id
3. **`strategy_positions` table:** strategy_id, symbol, action, quantity, entry_price, entry_order_id, stop_price, target_price, stop/target_order_ids, scanners_at_entry, conviction_score, pick_id

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position every run:
1. Get current quote via `get_quote`
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distances to stop/target
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown)
4. Check overnight gap risk rules (Strategy 10) near market close
5. **Profit Protection — Trailing Stop Ratchet (MANDATORY)**

### Profit Protection Tiers (updated 2026-04-16 — replaced fixed 10% LMT take-profit with trailing ratchet to let winners run)

After getting the quote, compute `unrealized_pnl_pct` from entry price. Apply the highest matching tier:

| Unrealized Gain | Required Stop Level | Action |
|-----------------|---------------------|--------|
| **+5% to +10%** | Breakeven (entry price) | Move stop to entry. Lock in zero-loss. |
| **+10% to +20%** | Trail 2% below current price | Stop = current_price × 0.98. Tight trail lets winners run while locking ~8%+ gain. |
| **+20% to +50%** | MAX(trail 2% below current, +10% above entry) | Stop = MAX(current_price × 0.98, entry × 1.10). Never give back below +10%. |
| **+50%+** | Trail 3% below peak | Stop = peak_price × 0.97. Slightly wider trail for big runners to avoid noise exits. |

**Rules:**
- Stops only ratchet UP, never down — if current stop is already above the tier level, keep it
- Check `get_open_orders` first — if a STP SELL order exists for this symbol, use `modify_order` to raise the stop price
- If no stop order exists, place a new GTC STP SELL order
- Log every stop adjustment to `orders` table with `strategy_id = "profit_protection"`
- This applies to ALL positions regardless of strategy — profit protection overrides strategy-specific stops when it produces a tighter (higher) stop

**Example (AGAE failure this rule prevents):**
- Entry $0.50, position reaches +10% ($0.55) → stop moves to $0.539 (trail 2% below $0.55)
- Position keeps running to +26% ($0.63) → stop moves to $0.617 (trail 2% below $0.63)
- Position keeps running to +50% ($0.75) → stop moves to $0.728 (trail 3% below peak $0.75)
- Reversal to $0.728 hits the ratcheted stop → exit at +45.5% instead of -7%
- If it reversed at +12% instead ($0.56) → stop at $0.549, exit at ~+9.8% instead of riding it down

Call `update_job_execution(exec_id, phase_completed=6, positions_monitored=N, snapshots_logged=N)`

---

## PHASE 7: Exit Handling & Lessons

### On Exit (stop hit, target hit, or manual close)
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id, action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - lesson text (what was learned)
3. Compute and log KPIs for the strategy via `compute_and_log_kpis`
4. If significant lesson, write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:
1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for each strategy that was active this cycle
3. Compute `strategy_kpis` for any strategy that had closed positions
4. Call `complete_job_execution(exec_id, summary)` with a full summary of all operations performed

---

## Lesson Application Rules

Before each run, read ALL lessons from `data/lessons/` and apply:

| Lesson | Rule | How to Apply |
|--------|------|-------------|
| Cut Losers Early | Hard stop at -5% | Phase 2 — mandatory before any new trades |
| Scanners Show Past | Signal freshness <10 min | Reject if `first_seen_time > 10 min` ago |
| Wrong Stop/Target | ATR-based brackets | Calculate ATR, set stop = 1.5x ATR, target = 2.5x ATR |
| Volume Without Direction | Veto volume + loss conflict | Hard reject if on volume AND loss scanner |
| Too Many Positions | Max 15 positions | Check position count before entry |
| No Conflict Check | Cross-scanner filter mandatory | Run Strategy 7 on every candidate |
| Rank Not Enough | Top 5 for 3+ snapshots | Track `consecutive_top5_count` |
| Same Order Structure | ATR-based scaling | No fixed % for all stocks |
| Gateway Disconnect | Verify connection each cycle | Ping IB before scan, auto-reconnect |
| Accidental Shorts | Check orders before selling | Query open orders for symbol before SELL |
| Unprotected Gains (AGAE) | Trailing stop ratchet on all positions | Phase 6 — apply profit protection tiers every cycle. Stops only move UP. |
| Batch Entry Losses | Max 2 new entries per cron cycle | Phase 5 — prevent 10-loss streaks from simultaneous entries |

---

## Database Tables Used (all in trading.db)

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each cron run with all operation counts | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate found (accepted & rejected) | Phase 4 |
| `orders` | Every order placed with full details | Phase 2, 5 |
| `strategy_positions` | Position lifecycle (open → monitor → close) | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with P&L and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, drawdown, expectancy per strategy | Phase 2, 8 |

### Database Functions for Job Tracking
```python
from ib_mcp.db import (
    start_job_execution,      # Returns exec_id
    update_job_execution,     # Incremental progress after each phase
    complete_job_execution,   # Mark as completed with summary
    fail_job_execution,       # Mark as failed with error
    get_recent_job_executions # Query execution history
)
```

### MCP Tool
- `get_job_executions(job_id, limit)` — query execution history via MCP
