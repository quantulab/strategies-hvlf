---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, scanner-patterns, multi-strategy]

---

# 31-Rotation-Scanner-Patterns — Operating Instructions

## Overview
Six rotation sub-strategies derived from the HVLF Scanner Pattern Analysis (53 trading days, 9,820 tickers, 33 scanner feeds). Each sub-strategy exploits a distinct statistical edge discovered in scanner data. The strategies rotate capital based on which pattern is currently firing, concentrating risk on the highest-conviction signal.

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 3:50 PM ET) via Claude Code CronCreate.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner Pattern Report: `D:\src\ai\mcp\ib\scanner_pattern_report.md`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`** (separate from trading.db)

## Sub-Strategy Registry

| ID | Name | Report Section | Signal Type |
|----|------|---------------|-------------|
| `rotation_volume_surge` | Volume Surge Entry | §3, §8, Strategy 1 | Volume leads price by ~120 min |
| `rotation_streak_continuation` | Streak Continuation | §4, §11, Strategy 2 | Multi-day momentum on same scanner 3+ days |
| `rotation_whipsaw_fade` | Whipsaw Fade | §2, Strategy 3 | Mean-reversion on chronic whipsaw names |
| `rotation_premarket_persist` | Pre-Market Persistence | §7, Strategy 4 | Pre-market movers that persist into regular hours (96% rate) |
| `rotation_capsize_breakout` | Cap-Size Breakout | §5, Strategy 5 | Small→Mid or Mid→Large crossover events |
| `rotation_elite_accumulation` | Elite Accumulation | §11, §1, Strategy 6 | Top-5 rank holders on gain scanners for 3+ days |

---

## SEPARATE DATABASE: `rotation_scanner.db`

**All data for this strategy family is stored in `rotation_scanner.db`, NOT `trading.db`.**

### Schema — Create on First Run

```sql
-- Master execution log
CREATE TABLE IF NOT EXISTS job_executions (
    exec_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL DEFAULT 'strategy_31_rotation',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running', -- running, completed, failed
    phase_completed INTEGER DEFAULT 0,
    positions_checked INTEGER DEFAULT 0,
    losers_closed INTEGER DEFAULT 0,
    shorts_closed INTEGER DEFAULT 0,
    candidates_found INTEGER DEFAULT 0,
    candidates_rejected INTEGER DEFAULT 0,
    orders_placed INTEGER DEFAULT 0,
    positions_monitored INTEGER DEFAULT 0,
    snapshots_logged INTEGER DEFAULT 0,
    lessons_logged INTEGER DEFAULT 0,
    kpis_computed INTEGER DEFAULT 0,
    portfolio_pnl REAL,
    portfolio_pnl_pct REAL,
    active_sub_strategy TEXT, -- which rotation sub-strategy fired
    summary TEXT,
    error_message TEXT
);

-- Scanner picks (all candidates scored, accepted & rejected)
CREATE TABLE IF NOT EXISTS scanner_picks (
    pick_id INTEGER PRIMARY KEY AUTOINCREMENT,
    exec_id INTEGER,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    sub_strategy TEXT NOT NULL, -- rotation_volume_surge, etc.
    scanner TEXT,
    rank INTEGER,
    rank_trend REAL,
    conviction_score REAL,
    conviction_tier TEXT, -- tier1, rejected
    scanners_present TEXT, -- comma-separated
    action TEXT, -- BUY, SELL, WATCH
    rejected INTEGER DEFAULT 0,
    reject_reason TEXT,
    signal_metadata TEXT, -- JSON: sub-strategy-specific signal details
    FOREIGN KEY (exec_id) REFERENCES job_executions(exec_id)
);

-- Orders placed
CREATE TABLE IF NOT EXISTS orders (
    order_id_local INTEGER PRIMARY KEY AUTOINCREMENT,
    exec_id INTEGER,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    sub_strategy TEXT NOT NULL,
    scanner TEXT,
    action TEXT NOT NULL, -- BUY, SELL
    quantity INTEGER NOT NULL,
    order_type TEXT NOT NULL, -- MKT, LMT, STP
    ib_order_id INTEGER,
    limit_price REAL,
    stop_price REAL,
    entry_price REAL,
    status TEXT DEFAULT 'submitted',
    pick_id INTEGER,
    notes TEXT,
    FOREIGN KEY (exec_id) REFERENCES job_executions(exec_id),
    FOREIGN KEY (pick_id) REFERENCES scanner_picks(pick_id)
);

-- Position lifecycle
CREATE TABLE IF NOT EXISTS strategy_positions (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL DEFAULT (datetime('now')),
    entry_order_id INTEGER,
    stop_price REAL,
    target_price REAL,
    stop_order_id INTEGER,
    target_order_id INTEGER,
    exit_price REAL,
    exit_time TEXT,
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    hold_duration_minutes INTEGER,
    peak_price REAL,
    trough_price REAL,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    max_drawdown_pct REAL,
    scanners_at_entry TEXT,
    conviction_score REAL,
    pick_id INTEGER,
    signal_metadata TEXT, -- JSON
    status TEXT DEFAULT 'open', -- open, closed
    FOREIGN KEY (pick_id) REFERENCES scanner_picks(pick_id)
);

-- Price snapshots per position per cycle
CREATE TABLE IF NOT EXISTS price_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    exec_id INTEGER,
    position_id INTEGER,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    bid REAL,
    ask REAL,
    last_price REAL,
    volume INTEGER,
    unrealized_pnl REAL,
    unrealized_pnl_pct REAL,
    distance_to_stop_pct REAL,
    distance_to_target_pct REAL,
    FOREIGN KEY (exec_id) REFERENCES job_executions(exec_id),
    FOREIGN KEY (position_id) REFERENCES strategy_positions(position_id)
);

-- Per-sub-strategy KPIs
CREATE TABLE IF NOT EXISTS strategy_kpis (
    kpi_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    sub_strategy TEXT NOT NULL,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    win_rate REAL,
    avg_win REAL,
    avg_loss REAL,
    profit_factor REAL,
    expectancy REAL,
    avg_hold_duration_min REAL,
    max_drawdown_pct REAL,
    total_pnl REAL,
    sharpe_ratio REAL,
    avg_conviction_score REAL,
    best_trade_pnl REAL,
    worst_trade_pnl REAL,
    consecutive_wins INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    avg_mfe REAL,
    avg_mae REAL,
    mfe_mae_ratio REAL -- edge efficiency
);

-- Lessons learned per trade
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    sub_strategy TEXT NOT NULL,
    action TEXT,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    hold_duration_minutes INTEGER,
    max_drawdown_pct REAL,
    max_favorable_excursion REAL,
    scanner TEXT,
    exit_reason TEXT,
    lesson_text TEXT,
    signal_metadata TEXT
);

-- Per-cycle summary
CREATE TABLE IF NOT EXISTS scan_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    exec_id INTEGER,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    candidates_found INTEGER DEFAULT 0,
    candidates_rejected INTEGER DEFAULT 0,
    orders_placed INTEGER DEFAULT 0,
    positions_held INTEGER DEFAULT 0,
    active_sub_strategies TEXT,
    summary TEXT,
    FOREIGN KEY (exec_id) REFERENCES job_executions(exec_id)
);

-- Rotation state tracking (which sub-strategy is active)
CREATE TABLE IF NOT EXISTS rotation_state (
    state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    active_sub_strategy TEXT NOT NULL,
    rotation_reason TEXT,
    market_breadth INTEGER,
    gl_ratio REAL,
    breadth_trend TEXT, -- expanding, contracting, stable
    volume_regime TEXT, -- high, normal, low
    prior_sub_strategy TEXT
);

-- Whipsaw watchlist (persistent tracker from report §2)
CREATE TABLE IF NOT EXISTS whipsaw_watchlist (
    symbol TEXT PRIMARY KEY,
    whipsaw_days INTEGER DEFAULT 0,
    danger_level TEXT, -- EXTREME, HIGH, MODERATE
    last_whipsaw_date TEXT,
    last_updated TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Volume-leads-price signal log (from report §3)
CREATE TABLE IF NOT EXISTS volume_lead_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    volume_scanner TEXT,
    volume_first_seen TEXT,
    gain_scanner TEXT,
    gain_first_seen TEXT,
    lead_time_minutes REAL,
    price_at_volume_signal REAL,
    price_at_gain_signal REAL,
    price_change_pct REAL,
    traded INTEGER DEFAULT 0
);

-- Multi-day streak tracker (from report §4)
CREATE TABLE IF NOT EXISTS streak_tracker (
    tracker_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    scanner_type TEXT NOT NULL,
    streak_start TEXT NOT NULL,
    streak_end TEXT,
    streak_days INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active', -- active, broken
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(symbol, scanner_type, streak_start)
);

-- Cap-size crossover events (from report §5)
CREATE TABLE IF NOT EXISTS capsize_crossovers (
    crossover_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL, -- Small->Mid, Mid->Large, Large->Mid, Mid->Small
    source_cap TEXT NOT NULL,
    target_cap TEXT NOT NULL,
    scanner_type TEXT,
    crossover_day_count INTEGER DEFAULT 1,
    first_crossover_date TEXT,
    traded INTEGER DEFAULT 0
);
```

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in `rotation_scanner.db` → `job_executions` table.**

1. Open/create `rotation_scanner.db` — run CREATE TABLE IF NOT EXISTS for all tables above on first run
2. Insert new row into `job_executions` with `job_id="strategy_31_rotation"` — returns `exec_id`
3. After each phase completes, UPDATE the row with `phase_completed`, operation counts, portfolio state
4. On success, UPDATE with `status="completed"`, `completed_at`, `summary`
5. On error, UPDATE with `status="failed"`, `error_message`

**Also call `start_job_execution(job_id="strategy_31_rotation")` in trading.db for cross-strategy visibility.**

### ML Schema Migration (run once)

On first run with ML enhancements, execute these ALTER TABLE statements against `rotation_scanner.db`. Ignore "duplicate column name" errors:

```sql
ALTER TABLE scanner_picks ADD COLUMN hurst_exponent REAL;
ALTER TABLE scanner_picks ADD COLUMN autocorrelation REAL;
ALTER TABLE scanner_picks ADD COLUMN sentiment_score REAL;
ALTER TABLE scanner_picks ADD COLUMN sentiment_gate TEXT;
ALTER TABLE scanner_picks ADD COLUMN catalyst_topic TEXT;
ALTER TABLE scanner_picks ADD COLUMN volume_forecast_trend TEXT;
ALTER TABLE rotation_state ADD COLUMN regime_hmm TEXT;
ALTER TABLE rotation_state ADD COLUMN regime_hmm_confidence REAL;
ALTER TABLE strategy_positions ADD COLUMN ml_signals TEXT;
```

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` AND from `rotation_scanner.db` → `lessons` table
2. **Load strategy files** from `data/strategies/` — confirm strategy parameters are current
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions with any `rotation_*` sub-strategy in `rotation_scanner.db` → `strategy_positions` WHERE `status='open'`
   - If already at 6 concurrent rotation positions, skip to Phase 6 (monitoring only)
4. **Check current open orders** via `get_open_orders()` — note any pending orders
5. **Verify IB connection** — if disconnected, log error and attempt reconnect
6. **Load whipsaw watchlist** from `rotation_scanner.db` → `whipsaw_watchlist` — these symbols get special handling
7. **Load active streaks** from `rotation_scanner.db` → `streak_tracker` WHERE `status='active'`
8. **Compute market regime** (enhanced with HMM):
   - Call `get_scanner_results` for today — count unique tickers (market breadth)
   - Compute gain/loss ratio from gain vs loss scanner counts
   - Call `classify_market_regime(method="hmm", breadth=N, gl_ratio=X, volume_level=Y)` for HMM-based regime detection
   - The HMM returns one of: `bull_momentum`, `bear_mean_reversion`, `range_bound`
   - Also call `classify_market_regime()` (zero-shot) as a secondary signal for logging
   - If HMM and zero-shot disagree, use HMM for routing but log the disagreement
9. **Select rotation priority** based on HMM regime routing:
   - `bull_momentum` → prioritize: `rotation_streak_continuation`, `rotation_volume_surge`, `rotation_elite_accumulation`
   - `bear_mean_reversion` → prioritize: `rotation_whipsaw_fade`, `rotation_premarket_persist`
   - `range_bound` → all sub-strategies eligible, prioritize: `rotation_whipsaw_fade`, `rotation_premarket_persist`, `rotation_volume_surge`
10. Log rotation state to `rotation_scanner.db` → `rotation_state`
11. UPDATE `job_executions` with `phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

**Before any new trades, enforce stop-loss rules on ALL rotation positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Query `rotation_scanner.db` → `strategy_positions` WHERE `status='open'` to identify rotation positions
3. For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists (prevents accidental shorts)
   b. Call `place_order(symbol, action="SELL", quantity, order_type="MKT")` to liquidate
   c. Log to `rotation_scanner.db` → `orders` with sub_strategy, full order details
   d. UPDATE `strategy_positions` — set `status='closed'`, `exit_reason="stop_loss_5pct"`, compute P&L
   e. INSERT into `rotation_scanner.db` → `lessons` with full trade details
4. For short positions (quantity < 0) created accidentally:
   a. Place MKT BUY to close
   b. Log with `exit_reason="close_accidental_short"`
5. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` for IB reconciliation
   b. Compare current IB positions against `strategy_positions` WHERE `status='open'`
   c. For every position in DB that no longer exists in IB:
      - UPDATE `strategy_positions` with exit details, compute P&L
      - INSERT into `lessons` with full trade analysis
      - INSERT into `orders` with exit order details
6. **Sub-strategy-specific time stops:**
   - `rotation_volume_surge`: close after 180 min if no gain scanner appearance
   - `rotation_whipsaw_fade`: close after 60 min (mean-reversion window)
   - `rotation_premarket_persist`: close after 90 min (morning momentum window)
   - `rotation_capsize_breakout`: no time stop (multi-day hold)
   - `rotation_streak_continuation`: no time stop (hold until streak breaks)
   - `rotation_elite_accumulation`: no time stop (hold until rank drops out of top-5)
7. UPDATE `job_executions` with `phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N`

---

## PHASE 3: Scanner Analysis & Signal Detection

### 3A: Collect Scanner Data

1. Call `get_scanner_dates()` to confirm today is available
2. For each scanner type × cap tier (33 feeds):
   - Call `get_scanner_results(scanner="{CapTier}-{ScannerType}", date=TODAY, top_n=50)`
   - Store results with timestamp

### 3B: Detect Sub-Strategy Signals

**Signal 1 — Volume Surge Entry (`rotation_volume_surge`)**
- Scan HotByVolume, MostActive, TopVolumeRate results for symbols NOT YET on TopGainers or GainSinceOpen
- Cross-reference against report §3 top predictable tickers (SOXL, SQQQ, SNXX, MSTZ, SLV, TSLL, AMDL, KOLD, TQQQ, CRWV, NVDA, USO, NVDL, ZSL, PLTR, etc.)
- For known predictable tickers: avg lead time is 120 min — flag as SIGNAL
- For unknown tickers on volume scanner but not gain scanner: flag as WATCH
- Log to `rotation_scanner.db` → `volume_lead_signals`

**Signal 2 — Streak Continuation (`rotation_streak_continuation`)**
- Query `streak_tracker` for active streaks
- For each active streak, check if symbol still appears on same scanner today
  - YES → increment `streak_days`, update `streak_end`
  - NO → set `status='broken'`, log break
- New streaks: any symbol on same scanner type for 2+ consecutive days → create tracker entry
- Signal fires on day 2-3 with improving rank (rank_delta < 0)

**Signal 3 — Whipsaw Fade (`rotation_whipsaw_fade`)**
- Check today's scanner results: find symbols on BOTH gain AND loss scanners same day
- Cross-reference against `whipsaw_watchlist` (symbols with 5+ historical whipsaw days)
- Known whipsaw names on TopGainers at open → SHORT/FADE signal
- Update `whipsaw_watchlist` with today's events

**Signal 4 — Pre-Market Persistence (`rotation_premarket_persist`)**
- Identify symbols on scanners before 9:30 AM (pre-market)
- At 9:35 AM: check if still on gain scanner → SIGNAL (96% historical persist rate)
- Cross-reference against whipsaw watchlist → SKIP if known whipsaw name
- Priority to report §7 reliable persisters: SGOV, BMNR, SCHD, JOBY, EXK, DUST, CPNG, SOUN

**Signal 5 — Cap-Size Breakout (`rotation_capsize_breakout`)**
- Compare symbol's presence across SmallCap, MidCap, LargeCap scanner variants
- If symbol appears on higher cap tier than yesterday → crossover event
- Log to `rotation_scanner.db` → `capsize_crossovers`
- Signal fires on 2+ consecutive crossover days with volume confirmation
- Priority to report §5 frequent crossovers: CLSK, JOBY, ONDS, TQQQ, LCID, ASTX

**Signal 6 — Elite Accumulation (`rotation_elite_accumulation`)**
- Check which symbols hold top-5 rank on any gain scanner
- Cross-reference against report §11 elite holders and §1 persistent tickers
- Signal fires when top-5 for 3+ consecutive days AND rank is improving
- Pullback entry: signal when price pulls back to VWAP on day 3+

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring & Rotation Selection

### Conviction Scoring (per signal)

Each sub-strategy has its own scoring model:

**Volume Surge Conviction:**
| Factor | Points |
|--------|--------|
| Known predictable ticker (report §3 top 25) | +3 |
| On 2+ volume scanners simultaneously | +2 |
| NOT on any loss scanner | +2 |
| Lead time < 60 min (fast mover) | +1 |
| Price > $5 | +1 |
| On whipsaw watchlist | -3 |
| **Tier 1 threshold** | **5+** |

**Streak Continuation Conviction:**
| Factor | Points |
|--------|--------|
| Streak >= 5 days | +3 |
| Rank improving (delta < -5 over 3 snapshots) | +2 |
| On 2+ scanner types simultaneously | +2 |
| Elite holder (top-5 for 3+ days) | +2 |
| On whipsaw watchlist | -2 |
| Streak just started (day 2) | -1 |
| **Tier 1 threshold** | **5+** |

**Whipsaw Fade Conviction:**
| Factor | Points |
|--------|--------|
| 10+ historical whipsaw days (EXTREME danger) | +3 |
| On BOTH gain AND loss scanner today | +3 |
| Up >5% from open (overextended for fade) | +2 |
| Known leveraged ETF (UVIX, SQQQ, SOXL, etc.) | +1 |
| Spread > 2% (poor liquidity for fade) | -3 |
| **Tier 1 threshold** | **5+** |

**Pre-Market Persistence Conviction:**
| Factor | Points |
|--------|--------|
| Known reliable persister (report §7 top 15) | +3 |
| Still on gain scanner at 9:35 AM | +3 |
| Pre-market volume > 100K shares | +2 |
| NOT on whipsaw watchlist | +1 |
| Gap > 10% (overextended, fade risk) | -2 |
| **Tier 1 threshold** | **5+** |

**Cap-Size Breakout Conviction:**
| Factor | Points |
|--------|--------|
| Small→Mid or Mid→Large direction | +3 |
| 3+ consecutive crossover days | +3 |
| Volume > 2x 20-day average | +2 |
| On gain scanner in new cap tier | +1 |
| Large→Mid or Mid→Small (downgrade) | -3 |
| **Tier 1 threshold** | **5+** |

**Elite Accumulation Conviction:**
| Factor | Points |
|--------|--------|
| Top-5 rank for 5+ consecutive days | +3 |
| Appears all 53 days in report (persistent) | +2 |
| On 3+ scanner types simultaneously | +2 |
| Avg rank < 10 (dominant position) | +2 |
| On whipsaw watchlist with EXTREME danger | -3 |
| **Tier 1 threshold** | **5+** |

### Universal ML Conviction Modifiers (apply to ALL sub-strategies)

Before computing sub-strategy-specific scores, apply these ML modifiers to every candidate:

| Factor | Points | Tool Call |
|--------|--------|-----------|
| Sentiment gate approves | +2 | `get_sentiment_gate(symbol)` returns `gate="approve"` |
| Sentiment gate rejects (avg < -0.3) | -1 | `get_sentiment_gate(symbol)` returns `gate="reject"` |
| Catalyst topic is fundamental (earnings, M&A, FDA) | +1 | `classify_catalyst_topic(headline)` returns `is_fundamental_catalyst=true` |
| HMM regime matches sub-strategy priority | +1 | Sub-strategy is in HMM routing's `prioritize` list |
| HMM regime deprioritizes sub-strategy | -2 | Sub-strategy is in HMM routing's `deprioritize` list |

**Sentiment gate handling:** If `get_sentiment_gate` fails (no headlines, model error), score is unchanged (0 points). The gate is a modifier, not a hard requirement.

### Tier Classification
- **Tier 1 (score 5+):** Trade with full size
- **Tier 2 (score 3-4):** REJECT — log as `rejected=1`
- **Tier 3 (score 1-2):** Watchlist only — log as `rejected=1`
- **Negative:** Blacklist — log as `rejected=1`

### Rotation Priority
When multiple sub-strategies fire simultaneously:
1. Rank all Tier 1 signals by conviction score descending
2. Apply regime filter from Phase 1 — only signals from prioritized sub-strategies
3. Max 2 entries per cycle (batch entry protection)
4. Max 1 entry per sub-strategy per cycle (diversification)
5. If tied: prefer sub-strategy with highest historical win rate (from `strategy_kpis`)

### Conflict Detection
- If same symbol appears in BOTH `rotation_volume_surge` AND `rotation_whipsaw_fade` → take whipsaw_fade (conservative)
- If same symbol in `rotation_streak_continuation` AND `rotation_whipsaw_fade` → SKIP (contradictory signals)
- If same symbol in `rotation_premarket_persist` AND whipsaw watchlist → SKIP

Log all candidates to `rotation_scanner.db` → `scanner_picks` with signal_metadata JSON.

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, run via `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $2.00 (sub-$2 had 25% win rate)
2. **Minimum volume:** Avg daily volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **$5-$10 confirmation:** Require 2+ consecutive scanner appearances before entry
6. **Not already held:** Check `get_positions()` + `rotation_scanner.db` → `strategy_positions` WHERE `status='open'`
7. **Not already ordered:** Check `get_open_orders()`
8. **Whipsaw gate (non-fade strategies):** If symbol on whipsaw watchlist with EXTREME danger AND sub-strategy is NOT `rotation_whipsaw_fade` → REJECT

Log rejection reason to `rotation_scanner.db` → `scanner_picks`.

### Position Limits
- Maximum **6** concurrent rotation positions (1 per sub-strategy max)
- Maximum **2 new entries per 10-minute cycle** (batch entry protection)
- **1 share per ticker** (same as main engine)
- Re-entry allowed if ticker exits and reappears with fresh signal

### Order Structure by Sub-Strategy

**Volume Surge Entry:**
- Entry: MKT BUY
- Stop: 5% below entry or 1.5x ATR (whichever tighter)
- Target: hold until gain scanner appearance, then trail 3% below high
- Time stop: 180 min

**Streak Continuation:**
- Entry: MKT BUY on day 2-3 pullback
- Stop: below prior day's low
- Target: trailing stop — exit when streak breaks (symbol disappears from scanner)
- No time stop

**Whipsaw Fade:**
- Entry: MKT SELL (short) or BUY puts at open on gap-up
- Stop: new high of day +2%
- Target: mean reversion to prior close
- Time stop: 60 min

**Pre-Market Persistence:**
- Entry: MKT BUY at 9:35 if still on gain scanner
- Stop: below VWAP or 5% below entry
- Target: ride 30-60 min momentum, trail 2% below high
- Time stop: 90 min

**Cap-Size Breakout:**
- Entry: MKT BUY on first crossover day with volume confirmation
- Stop: 7% below entry (wider stop for multi-day hold)
- Target: trail 10% below peak (multi-day run)
- No time stop (hold until returns to original cap tier)

**Elite Accumulation:**
- Entry: LMT BUY at VWAP pullback on day 3+ of top-5 streak
- Stop: below prior day's low
- Target: new multi-day high, then trail 5% below peak
- No time stop (hold while in top-5)

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order:
1. Immediately place protective GTC STP SELL at stop price
2. Verify via `get_open_orders()`
3. Log stop order to `rotation_scanner.db` → `orders` with `sub_strategy + "_protection"`

### For EVERY order placed, log to `rotation_scanner.db`:
1. **`scanner_picks`:** symbol, sub_strategy, scanner, rank, conviction_score, conviction_tier, scanners_present, action, rejected flag, signal_metadata
2. **`orders`:** symbol, sub_strategy, action, quantity, order_type, ib_order_id, limit_price, stop_price, entry_price, status, pick_id
3. **`strategy_positions`:** sub_strategy, symbol, action, quantity, entry_price, stop_price, target_price, order IDs, scanners_at_entry, conviction_score, pick_id, signal_metadata

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position in `rotation_scanner.db` → `strategy_positions` WHERE `status='open'`:

1. Call `get_quote(symbol)` for current price
2. INSERT into `rotation_scanner.db` → `price_snapshots` with bid, ask, last, volume, unrealized P&L, distances
3. Update position extremes: peak_price, trough_price, MFE, MAE, max_drawdown_pct
4. **Sub-strategy-specific monitoring:**
   - Volume Surge: check if symbol now on gain scanner → log lead time, adjust target
   - Streak: check if symbol still on same scanner → if missing, prepare exit
   - Whipsaw Fade: check if reverting to mean → tighten stop on profit
   - Pre-Market: check if still on scanner after 30 min → if faded, prepare exit
   - Cap-Size Breakout: check cap tier presence → if returned to original tier, prepare exit
   - Elite: check if still top-5 → if rank > 5, prepare exit
5. **Time stop enforcement** (per sub-strategy limits in Phase 2)

### Profit Protection — Trailing Stop Ratchet (MANDATORY, every cycle)

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +5% to +10% | Breakeven (entry price) |
| +20% to +50% | +10% above entry (entry × 1.10) |
| +50% to +100% | MAX(entry × 1.25, peak × 0.80) |
| >+100% | Trail at peak × 0.75 |

**Implementation:**
1. Compute unrealized P&L % from entry price
2. Determine tier-required stop from table
3. Check `get_open_orders()` for existing STP SELL
4. If existing stop < tier level → `modify_order` to raise it
5. If no stop exists → place new GTC STP SELL
6. Stops only ratchet UP, never down
7. Log to `rotation_scanner.db` → `orders`

UPDATE `job_executions` with `phase_completed=6, positions_monitored=N, snapshots_logged=N`

---

## PHASE 7: Exit Handling & Lessons

### On Exit (stop hit, target hit, time stop, streak break, or manual)
1. UPDATE `rotation_scanner.db` → `strategy_positions`:
   - `status='closed'`, `exit_price`, `exit_time`, `exit_reason`
   - Compute: `pnl = (exit_price - entry_price) * quantity`, `pnl_pct`, `hold_duration_minutes`
   - Exit reasons: `stop_loss_5pct`, `time_stop`, `streak_broken`, `rank_dropped`, `capsize_reverted`, `scanner_faded`, `mean_reverted`, `take_profit`, `trailing_stop`, `eod_close`, `manual`
2. INSERT into `rotation_scanner.db` → `lessons`:
   - symbol, sub_strategy, action, entry/exit prices, pnl, pnl_pct, hold_duration
   - max_drawdown_pct, max_favorable_excursion
   - scanner, exit_reason, signal_metadata
   - lesson_text: what worked/failed for this sub-strategy signal
3. Compute sub-strategy KPIs (see Phase 8)
4. If significant lesson (loss > 3% or unexpected exit), write markdown to `data/lessons/`
5. **End-of-day forced close (3:50 PM ET):** Close ALL remaining rotation positions with `exit_reason="eod_close"`
   - Exception: `rotation_streak_continuation` and `rotation_capsize_breakout` may hold overnight if:
     - Position is profitable (pnl_pct > 0)
     - Streak/crossover is still active
     - NOT on whipsaw watchlist
     - Log overnight hold decision to `rotation_state`

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N, kpis_computed=N`

---

## PHASE 8: Run Summary & KPIs

### Per-Cycle Summary
1. INSERT into `rotation_scanner.db` → `scan_runs`:
   - candidates_found, candidates_rejected, orders_placed, positions_held
   - active_sub_strategies (comma-separated list of sub-strategies that fired)
   - summary text

### KPI Computation (per sub-strategy)
For each sub-strategy with closed trades, compute and INSERT/UPDATE `rotation_scanner.db` → `strategy_kpis`:

| KPI | Formula | Target |
|-----|---------|--------|
| Win Rate | wins / total_trades | > 50% |
| Avg Win | mean(pnl where pnl > 0) | > 2% |
| Avg Loss | mean(pnl where pnl < 0) | < -3% |
| Profit Factor | sum(wins) / abs(sum(losses)) | > 1.5 |
| Expectancy | (win_rate × avg_win) - ((1-win_rate) × abs(avg_loss)) | > 0.5% |
| Avg Hold Duration | mean(hold_duration_minutes) | varies by sub-strategy |
| Max Drawdown | max(max_drawdown_pct across positions) | < -10% |
| Sharpe Ratio | mean(daily_returns) / std(daily_returns) × sqrt(252) | > 1.0 |
| MFE/MAE Ratio | avg_mfe / avg_mae | > 2.0 (edge efficiency) |
| Consecutive Wins | max streak of wins | tracking |
| Consecutive Losses | max streak of losses | < 5 (circuit breaker) |

### Circuit Breakers
- If any sub-strategy hits **5 consecutive losses**: DISABLE that sub-strategy for rest of day
  - Log to `rotation_state` with `rotation_reason="circuit_breaker_5_losses"`
  - Re-enable next trading day
- If overall rotation P&L for the day < **-3%**: DISABLE all rotation trading for rest of day
  - Log and alert
- If win rate over last 20 trades < **30%**: flag for review, reduce to Tier 1 only (already default)

### Cross-Strategy Comparison
Query all sub-strategies from `strategy_kpis` and rank by expectancy:
- Top 3 sub-strategies get priority in next day's rotation
- Bottom sub-strategy gets demoted (requires score 6+ instead of 5+)
- Log ranking to `rotation_state`

### Aggregate KPIs (rotation family)
Compute combined metrics across all 6 sub-strategies:
- Total rotation P&L (day, week, month)
- Best/worst performing sub-strategy
- Rotation efficiency: % of capital deployed vs idle
- Signal quality: % of Tier 1 signals that were profitable

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`
Call `complete_job_execution(exec_id, summary)` in trading.db for cross-strategy visibility.

---

## Major KPIs Dashboard

### Strategy-Level KPIs (tracked per sub-strategy in `strategy_kpis`)

| KPI | Description | Target | Alert Threshold |
|-----|-------------|--------|-----------------|
| **Win Rate** | % of trades profitable | > 50% | < 35% → circuit breaker review |
| **Profit Factor** | Gross profit / Gross loss | > 1.5 | < 1.0 → disable sub-strategy |
| **Expectancy** | Expected $ per trade | > $0.50 | < $0 → disable sub-strategy |
| **Sharpe Ratio** | Risk-adjusted return (annualized) | > 1.0 | < 0.5 → reduce position size |
| **Max Drawdown** | Worst peak-to-trough | < -10% | > -15% → halt all rotation |
| **MFE/MAE Ratio** | Edge efficiency (profit capture vs adverse move) | > 2.0 | < 1.0 → exits too early or entries too late |
| **Avg Hold Duration** | Minutes in position | Varies | Outliers → review time stops |
| **Signal Hit Rate** | % of Tier 1 signals producing > 1% gain | > 60% | < 40% → recalibrate scoring |
| **Consecutive Loss Streak** | Max back-to-back losses | < 5 | = 5 → circuit breaker |

### Portfolio-Level KPIs (aggregated across all 6 sub-strategies)

| KPI | Description | Target |
|-----|-------------|--------|
| **Daily Rotation P&L** | Net P&L from all rotation trades today | > $0 |
| **Weekly Rotation P&L** | Rolling 5-day P&L | > $0 |
| **Capital Utilization** | % of available rotation slots filled | 50-80% |
| **Sub-Strategy Diversity** | # of distinct sub-strategies active today | >= 3 |
| **Rotation Frequency** | # of sub-strategy switches per day | 2-4 (not too static, not churning) |
| **Best Sub-Strategy (7d)** | Highest expectancy over trailing 7 days | Track for priority weighting |
| **Worst Sub-Strategy (7d)** | Lowest expectancy over trailing 7 days | Track for demotion |

---

## Lessons Learned (Pre-Loaded from Scanner Pattern Analysis)

These lessons are derived from the 53-day scanner pattern report and must be applied from day 1:

### Lesson R1: Leveraged ETFs Dominate but Whipsaw
- **Observation:** SOXL, SQQQ, UVIX, MSTU, TZA appear on every single day (53/53) but also have EXTREME whipsaw danger (35+ whipsaw days)
- **Rule:** Leveraged ETFs are ONLY eligible for `rotation_whipsaw_fade` (short/fade). Never long via other sub-strategies.
- **Why:** 70%+ of their days show gain AND loss scanner appearances — directional bets fail.

### Lesson R2: Volume Lead Time is Real but Variable
- **Observation:** Average 120-minute lead from volume → gain scanner, but 54% of signals have >60 min lead
- **Rule:** For `rotation_volume_surge`, set time stop at 180 min (1.5x avg lead). If gain scanner hasn't fired by then, the signal failed.
- **Why:** Short lead times (<15 min) are 22% of signals — these are the actionable ones. Long leads dilute returns.

### Lesson R3: Streaks are Binary — Persistent or Worthless
- **Observation:** Streak distribution is bimodal: 44 streaks lasted all 53 days, most others lasted ~39-44 days. Few short streaks survive.
- **Rule:** For `rotation_streak_continuation`, only enter on day 3+ (not day 2). Day-2 entries have higher break rate.
- **Why:** If a streak survives to day 3, it likely survives much longer. Day-2 breaks are noise.

### Lesson R4: Pre-Market Persistence is Extremely Reliable
- **Observation:** 95.7% of pre-market movers persist into regular hours
- **Rule:** Pre-market persistence signals are high-conviction but MUST be filtered against whipsaw watchlist
- **Why:** The 4.3% that fade are disproportionately whipsaw names — one bad fade can wipe multiple good persists.

### Lesson R5: Cap-Size Crossovers Need Volume Confirmation
- **Observation:** CLSK had 23 crossover days, JOBY 22, ONDS 20 — but not all crossovers are bullish
- **Rule:** Only trade Small→Mid or Mid→Large crossovers (upgrades). Ignore downgrades. Require 2x avg volume on crossover day.
- **Why:** Downgrades (Large→Mid) often signal deterioration, not opportunity.

### Lesson R6: Breadth Contraction = Concentrate Capital
- **Observation:** Recent 10d avg breadth (1,914 tickers) is 20% below prior 10d (2,398). Market is contracting.
- **Rule:** During contracting breadth, only trade Tier 1 signals from top-3 sub-strategies by recent win rate. Reduce from 6 max positions to 4.
- **Why:** Fewer movers = fewer real opportunities. Spreading capital thin in low-breadth environments produces more losers.

### Lesson R7: Tuesday has Highest Breadth, Wednesday Lowest
- **Observation:** Tuesday avg 2,677 unique tickers vs Wednesday 2,298 (14% more opportunities on Tuesday)
- **Rule:** On Tuesdays, allow up to 3 entries per cycle (instead of 2). On Wednesdays, reduce to 1 entry per cycle.
- **Why:** More breadth = more real signals. Less breadth = more noise in the same signal count.

### Lesson R8: HighOpenGap → LossSinceOpen is the Trap Flow
- **Observation:** Scanner migration shows 311,303 transitions from HighOpenGap → LossSinceOpen
- **Rule:** Never enter a position solely because it appears on HighOpenGap. Require gain scanner confirmation AFTER open.
- **Why:** Gap-up stocks that don't hold often cascade directly into loss scanners. The gap is the trap.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_dates()` | Phase 3 — confirm today's data |
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect all 33 scanner feeds |
| `get_quote(symbol)` | Phase 5 (quality gate), Phase 6 (monitoring) |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | Phase 5 — ATR for stops |
| `get_positions()` | Phase 1, Phase 5 — check current holdings |
| `get_portfolio_pnl()` | Phase 1, Phase 2 — P&L for risk management |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 — prevent duplicates, manage stops |
| `get_closed_trades(save_to_db=True)` | Phase 2 — reconcile trades closed by IB |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | Phase 2, Phase 5 |
| `modify_order(order_id, ...)` | Phase 6 — ratchet trailing stops |
| `get_strategy_positions(strategy_id, status, limit)` | Phase 2, Phase 5 — check rotation positions |
| `get_news_headlines(symbol)` | Phase 4 — catalyst confirmation for stale signal override |
| `classify_market_regime()` | Phase 1 — market context for rotation priority |
| `get_job_executions(job_id, limit)` | Phase 1 — check for repeated failures |
| `get_sentiment_gate(symbol)` | Phase 4 — universal sentiment conviction modifier |
| `classify_catalyst_topic(headline)` | Phase 4 — catalyst type classification |
| `classify_market_regime(method="hmm", breadth, gl_ratio, volume_level)` | Phase 1 — HMM regime detection |
| `detect_regime_hmm(breadth, gl_ratio, volume_level)` | Phase 1 — alternative HMM regime detection |
| `compute_hurst_exponent(symbol)` | Phase 4 — streak persistence validation (delegated to sub-strategies) |
| `compute_return_autocorrelation(symbol)` | Phase 1 — whipsaw fade regime filter (delegated) |
| `forecast_volume_trajectory(symbol)` | Phase 3 — volume surge sustainability (delegated) |
| `forecast_scanner_rank(symbol, scanner, multi_day=True)` | Phase 4 — multi-day rank trajectory (delegated) |

---

## Database Initialization Command

On first run, execute all CREATE TABLE statements above against `D:\src\ai\mcp\ib\rotation_scanner.db`. The database file will be created automatically by SQLite on first connection.

---

## ML/AI Enhancement Opportunities (Cross-Strategy)

### Research Papers Applicable to ALL Sub-Strategies

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **HMM + LSTM for Stock Trends** | [2104.09700](https://arxiv.org/abs/2104.09700) | Replace Phase 1 regime classification (simple G/L ratio) with HMM-based regime detector combining scanner breadth, VIX, and sector rotation signals |
| **When Alpha Breaks: Safe Stock Rankers** | [2603.13252](https://arxiv.org/abs/2603.13252) | Two-level uncertainty framework — detect when ANY sub-strategy's scoring model is unreliable during regime shifts. Auto-tighten thresholds |
| **Adaptive Market Intelligence: Mixture of Experts** | [2508.02686](https://hf.co/papers/2508.02686) | Route capital allocation across sub-strategies using a volatility-aware gating mechanism instead of fixed regime→priority mapping |
| **Proactive Model Adaptation Against Concept Drift** | [2412.08435](https://hf.co/papers/2412.08435) | Detect when scanner pattern statistical properties have shifted — auto-recalibrate conviction scoring thresholds |
| **TradeFM: Generative Foundation Model for Trade-Flow** | [2602.23784](https://hf.co/papers/2602.23784) | 524M-param transformer for cross-asset trade flow analysis — detect macro regime shifts from aggregate order flow |
| **Alpha-R1: Alpha Screening with LLM Reasoning** | [2512.23515](https://hf.co/papers/2512.23515) | RL-trained LLM for context-aware alpha screening — could serve as a meta-strategy selector across all 6 sub-strategies |

### Hugging Face Models for Cross-Strategy Use

| Model | Downloads | Use Case |
|-------|-----------|----------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) | 252K | News sentiment scoring for ALL candidates — add as universal conviction factor |
| [mrm8488/deberta-v3-ft-financial-news-sentiment-analysis](https://hf.co/mrm8488/deberta-v3-ft-financial-news-sentiment-analysis) | 87K | Higher-accuracy DeBERTa-v3 sentiment for Tier 1 signal validation |
| [ahmedrachid/FinancialBERT-Sentiment-Analysis](https://hf.co/ahmedrachid/FinancialBERT-Sentiment-Analysis) | 22K | Financial-domain BERT for earnings/guidance news |
| [soleimanian/financial-roberta-large-sentiment](https://hf.co/soleimanian/financial-roberta-large-sentiment) | 3.4K | Large RoBERTa for deep analysis of corporate filings, ESG reports |
| [nickmuchi/finbert-tone-finetuned-finance-topic-classification](https://hf.co/nickmuchi/finbert-tone-finetuned-finance-topic-classification) | 694 | Topic classification — route signals by catalyst type (earnings, M&A, macro, technical) |
| [keras-io/timeseries-anomaly-detection](https://hf.co/keras-io/timeseries-anomaly-detection) | 30 | Detect anomalous volume/price patterns that deviate from historical scanner norms |

### Cross-Strategy Enhancement Architecture

1. **Regime Detection Layer (Phase 1 Enhancement):**
   - Replace fixed BULL/BEAR/NEUTRAL classification with HMM (paper 2104.09700) trained on: scanner breadth, G/L ratio, VIX, sector rotation scores, volume regime
   - Output: regime probabilities + transition probabilities → feed into sub-strategy priority weighting
   - Add concept drift detection (paper 2412.08435) to alert when scanner patterns are non-stationary

2. **Intelligent Rotation Selector (Phase 4 Enhancement):**
   - Replace fixed regime→priority mapping with Mixture of Experts (paper 2508.02686)
   - Each sub-strategy is an "expert" — a volatility-aware gate learns which expert(s) to allocate capital to in current conditions
   - Gate features: regime state, recent KPIs per sub-strategy, sector momentum, VIX level, time of day
   - Output: capital allocation weights across sub-strategies (replacing binary priority list)

3. **Universal News Sentiment Layer (Phase 3-4 Enhancement):**
   - For every candidate across all sub-strategies, fetch headlines via `get_news_headlines(symbol)`
   - Score with distilroberta financial sentiment model → add ±1 conviction based on sentiment polarity
   - Classify catalyst type with finbert topic classifier → route to appropriate sub-strategy (earnings→elite accumulation, gap→premarket persist, sector rotation→capsize breakout)

4. **Anomaly Detection Guard (Phase 5 Enhancement):**
   - Use time series anomaly detection model to flag unusual scanner behavior (sudden spike in candidates, volume patterns deviating from historical norms)
   - On detected anomaly: reduce max entries per cycle from 2 to 1, require score 6+ for Tier 1

5. **Meta-Learning KPI Optimizer (Phase 8 Enhancement):**
   - Track per-sub-strategy KPIs over rolling 20-trade windows
   - Use the "When Alpha Breaks" uncertainty framework to detect when a sub-strategy's edge has degraded
   - Auto-adjust conviction thresholds: degraded sub-strategy requires score 7+ instead of 5+
   - Auto-promote outperforming sub-strategy: lower threshold to score 4+ for Tier 1

### Per-Sub-Strategy Enhancement Details
See the ML/AI Enhancement sections in each sub-strategy's instruction file:
- `strategy_32-rotation-volume_surge.md` — Lead-lag ML, order-flow entropy, volume conversion classifier
- `strategy_33-rotation-streak_continuation.md` — Streak survival classifier, temporal pattern matching, factor momentum overlay
- `strategy_34-rotation-whipsaw_fade.md` — HMM regime classifier, autocorrelation factor, LETF rebalancing timer, MoE routing
- `strategy_35-rotation-premarket_persist.md` — Dynamic persistence model, concept drift detector, news catalyst scoring
- `strategy_36-rotation-capsize_breakout.md` — Markov transition model, peer crossover detection, fundamental catalyst filter
- `strategy_37-rotation-elite_accumulation.md` — RL VWAP entry optimization, LOB bounce predictor, institutional flow asymmetry
