---
noteId: "system_architecture_20260415"
tags: [architecture, documentation, trading-system]

---

# Automated Trading System — Complete Architecture

## Overview

This is a scanner-driven automated trading system built on Interactive Brokers (IB) via the `ib_insync` library, exposed as an MCP (Model Context Protocol) server, and orchestrated by a Claude Code cron job that runs every 10 minutes during market hours.

The system reads real-time scanner data (top gainers, losers, volume leaders), scores each candidate using a multi-strategy conviction framework, places trades for high-conviction signals, monitors positions, enforces risk rules, and logs everything to a SQLite database for post-trade analysis.

---

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Code (Orchestrator)                │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Cron Job   │  │ Strategies   │  │ Lessons              │ │
│  │ (10 min)   │  │ (11 files)   │  │ (post-trade rules)   │ │
│  └─────┬─────┘  └──────┬───────┘  └──────────┬───────────┘ │
│        │               │                      │             │
│        ▼               ▼                      ▼             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              8-Phase Execution Engine                │    │
│  │  Phase 0: Job tracking                              │    │
│  │  Phase 1: Load context (strategies, lessons, state)  │    │
│  │  Phase 2: Risk management (cut losers, reconcile)    │    │
│  │  Phase 3: Scanner analysis                           │    │
│  │  Phase 4: Strategy matching & conviction scoring     │    │
│  │  Phase 5: Order execution                            │    │
│  │  Phase 6: Position monitoring & snapshots            │    │
│  │  Phase 7: Exit handling & lessons                    │    │
│  │  Phase 8: Summary & KPIs                             │    │
│  └─────────────────────┬───────────────────────────────┘    │
│                        │                                     │
└────────────────────────┼─────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ IB Gateway │ │ Scanner    │ │ SQLite DB  │
   │ (TWS/GW)   │ │ CSV Files  │ │ trading.db │
   │ Port 7497  │ │ \\Station001│ │            │
   └────────────┘ └────────────┘ └────────────┘
```

---

## Data Flow

### Input Sources

1. **IB Gateway** (port 7497) — real-time positions, orders, quotes, executions
2. **Scanner CSV files** (`\\Station001\DATA\hvlf\scanner-monitor\{YYYYMMDD}\`) — 10 scanners updated continuously:
   - GainSinceOpenLarge/Small
   - PctGainLarge/Small
   - HotByVolumeLarge/Small
   - LossSinceOpenLarge/Small
   - PctLossLarge/Small
3. **Strategy files** (`data/strategies/`) — 11 trading strategies with entry/exit/sizing rules
4. **Lesson files** (`data/lessons/`) — post-trade analysis with hard rules to apply

### Output/Storage

1. **IB Gateway** — order placement (MKT BUY/SELL, STP, LMT)
2. **SQLite database** (`trading.db`) — every operation logged (see Database Schema below)
3. **Lesson files** — significant learnings written as markdown

---

## The 11 Strategies

| # | Strategy | ID | Type | Trigger |
|---|----------|----|------|---------|
| 01 | Momentum Surfing | `momentum_surfing` | Trend | 2+ gain scanners, price above prior day high |
| 02 | Gap-and-Go | `gap_and_go` | Day trade | Gap up >50% premarket, >1M volume |
| 03 | Fade Euphoria | `fade_euphoria` | Short | Up >100% intraday with topping signals |
| 04 | Cut Losers | `cut_losers` | Risk mgmt | Position losing >5% (auto-enforced Phase 2) |
| 05 | Pairs Trade | `pairs_trade` | Market neutral | Correlated stocks, ratio at 1-std extreme |
| 06 | Volume Breakout | `volume_breakout` | Breakout | First HotByVolume appearance, positive price |
| 07 | Scanner Conflict Filter | `conflict_filter` | Risk overlay | Cross-scanner conflict detected |
| 08 | Oversold Bounce | `oversold_bounce` | Mean reversion | Down >40% from 20-day high, bottoming |
| 09 | Multi-Scanner Conviction | `multi_scanner` | Scoring | 3+ scanner appearances simultaneously |
| 10 | Overnight Gap Risk | `overnight_gap_risk` | Risk mgmt | Position >20% intraday move (end-of-day) |
| 11 | Quantum Catalyst | `quantum_catalyst` | Catalyst | Sector catalyst with leveraged ETF exposure |

---

## Conviction Scoring System (Strategy 9)

Every scanner candidate is scored across all 10 scanners:

| Scanner Type | Points |
|-------------|--------|
| PctGain (Large or Small) | +2 |
| HotByVolume (Large or Small) | +2 |
| GainSinceOpen (Large or Small) | +1 |
| Any Loss scanner | -2 |
| Gain + Loss conflict (same stock) | -1 |

### Conviction Tiers

| Tier | Score | Action | Position Size |
|------|-------|--------|---------------|
| **Tier 1** | 5+ | Trade | Full size |
| **Tier 2** | 3-4 | Trade | Half size |
| **Tier 3** | 1-2 | Watchlist only | No trade |
| **Blacklist** | ≤0 | No trade | Rejected |

### Conflict Filter (Strategy 7) — Pre-Trade Gate

| Level | Condition | Action |
|-------|-----------|--------|
| Yellow | Gain + Volume | Tighter stops, proceed cautiously |
| Orange | Gain + Loss same day | Half size, 2-hour exit window |
| **Red** | PctGain + PctLoss + HotByVolume | **NO TRADE** — auto-reject |

---

## 8-Phase Execution Engine

Each cron cycle (every 10 minutes) runs these phases in order:

### Phase 0: Job Tracking
- Create `job_executions` record with `start_job_execution(job_id)`
- Update after each phase with operation counts
- Complete or fail at end

### Phase 1: Pre-Trade Checklist
- Load all lesson files → extract hard rules
- Load all 11 strategy files → match to market conditions
- Get current positions (`get_positions`, `get_portfolio_pnl`)
- Get open orders (`get_open_orders`)
- Verify IB connection

### Phase 2: Risk Management (MANDATORY FIRST)
- **Cut losers**: Liquidate any position at ≤ -5% P&L
- **Close accidental shorts**: Buy to close any negative-quantity positions
- **Reconcile closed trades**: Call `get_closed_trades(save_to_db=True)` — compare against last cycle's positions, log any externally-closed trades to `lessons`, `strategy_positions`, `orders`
- Check for existing sell orders before placing new ones (prevent duplicates)

### Phase 3: Scanner Analysis
- Pull latest scanner data (10 scanners, top 10-20 per scanner)
- Build cross-scanner map: which symbols appear on which scanners
- Apply direction logic (gain=long, volume+not_loss=long, volume+loss=skip)

### Phase 4: Strategy Matching & Scoring
- Score each candidate using conviction system
- Apply conflict filter (Strategy 7)
- Match to applicable strategy (01-11)
- Log ALL candidates to `scanner_picks` — including rejected ones with reasons

### Phase 5: Order Execution
- Filter to Tier 1/2 candidates only
- Check position count (max 15)
- Check for existing positions/orders (prevent duplicates)
- Place MKT orders
- Log to `orders`, `strategy_positions` with strategy_id, conviction_score, scanners

### Phase 6: Position Monitoring
- Get current quote for each open position
- Log `price_snapshots` (bid, ask, last, volume, P&L, distance to stop/target)
- Update position extremes (peak, trough, MFE, MAE, max drawdown)
- Check overnight gap risk rules near market close

### Phase 7: Exit Handling
- Close positions in `strategy_positions` with exit details
- Log to `lessons` table with full trade data and lesson text
- Compute strategy KPIs
- Write markdown lesson file for significant events

### Phase 8: Run Summary
- Log `scan_runs` summary
- Log `strategy_runs` for each active strategy
- Compute `strategy_kpis` for strategies with closed positions
- Complete job execution record

---

## Database Schema (trading.db)

### 10 Tables

| Table | Records | Purpose |
|-------|---------|---------|
| `job_executions` | 1 per cron cycle | Master record — ties all operations in a cycle together |
| `scanner_picks` | 1 per candidate per cycle | Every ticker scored (accepted + rejected with reasons) |
| `orders` | 1 per order | Every order placed with IB order ID, strategy, prices |
| `strategy_positions` | 1 per position | Full lifecycle: open → monitor → close with P&L |
| `price_snapshots` | 1 per position per cycle | Time-series of bid/ask/last/volume/P&L per position |
| `strategy_runs` | 1 per strategy per cycle | Per-strategy summary each cycle |
| `scan_runs` | 1 per cycle | Overall scan cycle summary |
| `lessons` | 1 per exit | Post-trade lesson with entry/exit/P&L/reason/lesson text |
| `strategy_kpis` | 1 per strategy per computation | Win rate, profit factor, expectancy, Sharpe, MFE/MAE |
| `closed_trades` | 1 per round-trip | IB execution-matched round trips with P&L |

### Key Relationships

```
scanner_picks (candidate) → orders (if accepted) → strategy_positions (lifecycle)
                                                          ↓
                                                   price_snapshots (monitoring)
                                                          ↓
                                                   lessons (on exit)
                                                          ↓
                                                   strategy_kpis (aggregated)

job_executions ← ties together all operations in one cycle
scan_runs ← cycle-level summary
strategy_runs ← per-strategy summary per cycle
```

---

## Lesson System

### How Lessons Work

1. **Post-trade lessons** are logged to the `lessons` DB table after every exit with full trade details
2. **Significant lessons** are also written as markdown files to `data/lessons/`
3. **Every cron cycle** reads all lesson files and applies their rules as pre-trade gates

### Active Lessons (as of 2026-04-15)

| Lesson | Hard Rule |
|--------|-----------|
| Cut Losers Early | -5% hard stop, enforced in Phase 2 |
| Scanners Show Past | Reject if signal on scanner >10 min (stale) |
| Wrong Stop/Target | Use ATR-based brackets, not fixed % |
| Volume Without Direction | Veto if on volume AND loss scanner |
| Too Many Positions | Max 15 positions |
| Cross-Scanner Conflict | Strategy 7 mandatory on every candidate |
| Rank Not Enough | Require top-5 rank for 3+ consecutive snapshots |
| Same Order Structure | ATR-based scaling per stock volatility |
| Gateway Disconnect | Verify IB connection each cycle |
| Accidental Shorts | Check open orders before placing SELL |

---

## MCP Tools

The system exposes these tools via the MCP server:

### Account & Trading
| Tool | Description |
|------|-------------|
| `get_account_summary` | Net liquidation, cash, buying power, margin |
| `get_positions` | Current portfolio with quantity and avg cost |
| `get_portfolio_pnl` | P&L for all positions with market prices |
| `get_open_orders` | Pending orders with status |
| `get_closed_trades` | Today's round-trip trades matched with P&L |
| `place_order` | Place market/limit/stop orders |
| `cancel_order` | Cancel an open order |
| `modify_order` | Modify an existing order |

### Market Data
| Tool | Description |
|------|-------------|
| `get_quote` | Real-time bid/ask/last/volume for a symbol |
| `get_historical_bars` | OHLCV history |
| `get_option_chain` | Options chain for a stock |
| `get_option_quotes` | Option price quotes |
| `get_contract_details` | Contract specifications |
| `get_scanner_results` | Latest scanner data (10 scanners) |
| `get_scanner_dates` | Available scanner date folders |
| `calculate_indicators` | Technical indicators (ATR, RSI, etc.) |

### Trading Log & Analytics
| Tool | Description |
|------|-------------|
| `get_trading_picks` | Scanner pick decisions with reasoning |
| `get_trading_orders` | Order placements from scanner trading |
| `get_trading_lessons` | Lessons logged after exits |
| `get_scan_runs` | Scan cycle summaries |
| `get_strategy_positions` | Positions by strategy (open/closed) |
| `get_strategy_kpis_report` | Win rate, P&L, drawdown, expectancy |
| `get_position_price_history` | Price snapshots for a position |
| `get_job_executions` | Cron job execution history |
| `get_daily_kpis` | Comprehensive daily trading KPIs |

### News
| Tool | Description |
|------|-------------|
| `get_news_providers` | Available news sources |
| `get_news_headlines` | Recent headlines for a symbol |
| `get_news_article` | Full article text |

---

## Risk Management Rules

### Position-Level
- **-5% hard stop**: Any position at ≤ -5% unrealized P&L is immediately liquidated (Phase 2)
- **ATR-based stops**: Stop = entry - 1.5x ATR, target = entry + 2.5x ATR
- **No averaging down**: Never add to a losing position

### Portfolio-Level
- **Max 15 positions**: No new entries beyond this cap
- **Conflict filter**: Strategy 7 (Red level) overrides all buy signals
- **Duplicate prevention**: Check open orders before placing SELL (prevents accidental shorts)
- **Overnight gap risk**: Strategy 10 rules near market close

### Operational
- **IB connection check**: Verify before every scan cycle
- **Closed trade reconciliation**: Every cycle calls `get_closed_trades` to catch externally-closed positions
- **Job execution tracking**: Every cycle recorded with full operation counts

---

## File Structure

```
D:\src\ai\mcp\ib\
├── ib_mcp/
│   ├── server.py              # MCP server (FastMCP, stdio transport)
│   ├── connection.py           # IB Gateway connection management
│   ├── config.py               # Pydantic settings (host, port, client_id)
│   ├── db.py                   # SQLite schema + all DB functions
│   └── tools/
│       ├── account.py          # Account, positions, P&L, orders, closed trades
│       ├── market_data.py      # Quotes, historical bars, indicators
│       ├── orders.py           # Place, cancel, modify orders
│       ├── scanners.py         # Read scanner CSV files
│       ├── research.py         # Contract details, option chains
│       ├── news.py             # News headlines and articles
│       └── trading_log.py      # Trading log queries, KPIs, job executions
├── data/
│   ├── strategies/             # 11 strategy markdown files
│   │   ├── 01_momentum_surfing.md
│   │   ├── 02_gap_and_go.md
│   │   ├── ...
│   │   └── 11_nvidia_quantum_catalyst.md
│   ├── lessons/                # Post-trade lesson markdown files
│   │   ├── 20260415_scanner_bracket_postmortem.md
│   │   ├── 20260415_system_gateway_disconnect.md
│   │   └── 20260415_cut_losers_early.md
│   └── instructions/           # Operating instructions
│       ├── scanner_cron_job.md  # Main cron job playbook (Phases 0-8)
│       └── system_architecture.md  # This document
├── trading.db                  # SQLite database (all trading data)
└── .env                        # IB connection config (IB_HOST, IB_PORT, etc.)
```

---

## Configuration

### IB Connection (`config.py` / `.env`)
| Setting | Default | Notes |
|---------|---------|-------|
| `IB_HOST` | 127.0.0.1 | IB Gateway host |
| `IB_PORT` | 7497 | TWS paper (7496 live, 4002 GW paper, 4001 GW live) |
| `IB_CLIENT_ID` | auto | Hash of nanosecond timestamp mod 2^16 |
| `IB_READONLY` | True | Must be False to place orders |

### Cron Job
| Setting | Value |
|---------|-------|
| Schedule | Every 10 minutes (`*/10 * * * *`) |
| Job ID | Assigned by CronCreate |
| Auto-expire | 7 days |
| Transport | Claude Code session (dies when Claude exits) |

---

## Daily KPIs Tracked

The `get_daily_kpis` tool computes these metrics from the day's trading:

### Trade Performance
- Total trades, winners, losers, win rate
- Average win %, average loss %
- Profit factor (gross wins / gross losses)
- Expectancy (edge per trade)
- Sharpe estimate (annualized)
- Max consecutive wins/losses

### P&L Breakdown
- Gross P&L, commissions, net P&L
- P&L by exit type (stop_loss, take_profit, manual)
- P&L by strategy (momentum_surfing, volume_breakout, etc.)
- P&L by symbol
- Best and worst individual trades

### Operational
- Scanner candidates scanned / rejected / acceptance rate
- Orders placed by strategy and action
- Job execution count (completed, failed)
- Total snapshots logged
