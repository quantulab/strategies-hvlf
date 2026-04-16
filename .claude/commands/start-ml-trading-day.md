---
noteId: "start_ml_trading_day_01"
tags: [cron, trading, ml, rotation, setup, start-of-day]

---

Start the full ML-enhanced trading day. This initializes both the standard 8-phase trading engine AND the ML rotation strategies, sets up cron jobs for both, and performs pre-market checks.

## 1. Pre-Market Setup

### Load Context — All Three Engines
- Read `data/instructions/scanner_cron_job.md` for the core engine instructions (includes parallel coordination rules)
- Read `data/instructions/ml_strategies_engine.md` for the ML engine instructions
- Read `data/instructions/rotation_strategies_engine.md` for the rotation engine instructions
- Read `data/instructions/system_architecture.md` for system context
- Read ALL files in `data/lessons/` to load hard rules from past trades
- Read ALL files in `data/strategies/` (core), `data/strategies/ml/` (ML), `data/strategies/rotation/` (rotation)

### Verify Infrastructure
- Call `ensure_connected()` to verify IB connection
- Call `get_positions()` to see any positions held overnight
- Call `get_portfolio_pnl()` to assess current P&L
- Call `get_open_orders()` to check for pending orders
- Verify Station001 scanner data: call `get_scanner_dates(path="//Station001/DATA/hvlf/rotating")` — confirm today's date folder exists
- Call `list_models()` to verify ML model registry is accessible

### Test ML Tools (first run of day)
- Call `classify_market_regime(method="hmm", breadth=2000, gl_ratio=1.0, volume_level=0.5)` — verify HMM regime detection works
- If any ML tool fails, log warning but continue — ML tools are optional enhancements

## 2. Overnight State Check

### Standard Positions
- For each position, check if stop orders survived overnight (may have expired as DAY orders)
- If ANY stop is missing, re-place immediately at -5% from entry
- Apply Strategy 10 (Overnight Gap Risk):
  - Position gapped down >10% → place MKT SELL at open
  - Position moved >20% intraday yesterday → tighten stop to -3%

### Rotation Positions
- For S33 streak positions: check if streaks are still active on today's scanners
- For S36 capsize positions: check if still on upgraded cap tier
- For S37 elite positions: check if still top-5 on gain scanners
- For S34 whipsaw shorts: should have been closed EOD — if any remain, close immediately

### ML Pre-Market Signals
- For each held position, call `get_sentiment_gate(symbol)` — if reject + position underwater, flag for early exit
- Call `compute_hurst_exponent(symbol)` for streak/momentum positions — if H < 0.45, flag for exit at open

## 3. Start Cron Jobs

Set up TWO recurring loops that run in parallel:

### Core + ML Trading Engine (11 core strategies + ML strategies S12-S30)
```
/loop 10m /run-trading-engine
```
- Instructions: `data/instructions/scanner_cron_job.md` + `data/instructions/ml_strategies_engine.md`
- Database: `trading.db`
- Scanner path: `//Station001/DATA/hvlf/scanner-monitor` (10 legacy scanners)
- **Max 5 positions** in parallel mode

### Rotation Strategies Engine (S31-S37 with ML enhancements)
```
/loop 10m /run-rotation-strategies
```
- Instructions: `data/instructions/rotation_strategies_engine.md`
- Database: `rotation_scanner.db`
- Scanner path: `//Station001/DATA/hvlf/rotating` (33 feeds)
- **Max 5 positions** in parallel mode

Both run every 10 minutes on offset cycles. The core engine handles momentum, gap-and-go, volume breakout, and ML-enhanced strategies. The rotation engine handles the 6 scanner pattern sub-strategies with HMM regime detection.

## 4. Confirm Startup

Report:
- IB connection status and account
- Scanner data availability (both paths — scanner-monitor and rotating)
- ML model registry status (loaded vs available)
- Overnight positions, P&L, and stop verification
- HMM regime classification for the open
- Cron jobs scheduled (both engines)
- Pre-market sentiment signals for held positions
- Today's watchlist priorities based on regime

## 5. Trading Day Rules

### Parallel Engine Architecture
```
+---------------------------+    +---------------------------+
| Core + ML Engine          |    | Rotation Engine           |
| /loop 10m /run-trading-   |    | /loop 10m /run-rotation-  |
|   engine                  |    |   strategies              |
|                           |    |                           |
| DB: trading.db            |    | DB: rotation_scanner.db   |
| Scanners: scanner-monitor |    | Scanners: rotating (33)   |
| Max positions: 5          |    | Max positions: 5          |
| Strategies: S01-S12,      |    | Strategies: S31-S37       |
|   S14-S30 (ML)            |    | (6 rotation sub-strats)   |
+---------------------------+    +---------------------------+
             |                                |
             +----------- IB Account ---------+
             |      (shared, max 10 total)    |
             +--------------------------------+
```

### Position Limits (combined)
- **Max 10 total positions** across all engines
- Max 5 core/ML positions (enforced by core engine)
- Max 5 rotation positions (enforced by rotation engine)
- Max 2 new entries per cycle per engine

### Symbol Lock (prevents overlap)
- BEFORE every BUY: call `get_positions()` from IB
- If symbol already held by ANY engine, SKIP
- IB is the single source of truth — both engines check it before every entry

### Position Ownership
- Core engine only manages positions in `trading.db.strategy_positions`
- Rotation engine only manages positions in `rotation_scanner.db.strategy_positions`
- Neither engine closes the other's positions

### Risk Management Priority
- -5% hard stop applies to ALL positions (each engine manages its own)
- Profit protection ratchets apply to ALL positions (same tiers across engines)
- Strategy 10 overnight gap risk applies at open
- No accidental shorts — check open orders before EVERY sell

### Scanner Paths
- Core engine: `//Station001/DATA/hvlf/scanner-monitor` (10 legacy scanners)
- Rotation engine: `//Station001/DATA/hvlf/rotating` (33 feeds, 3 cap tiers)
