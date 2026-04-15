# ib-mcp

MCP (Model Context Protocol) server for Interactive Brokers — a full-stack algorithmic trading research platform that connects Claude to live markets, scanner data, ML models, and a backtesting engine.

Built on [FastMCP](https://github.com/jlowin/fastmcp) + [ib_insync](https://github.com/erdewit/ib_insync), with 53 MCP tools, 41 trading strategies, 15 HuggingFace model integrations, and a 52-day backtesting framework.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [Project Structure](#project-structure)
- [MCP Tools Reference](#mcp-tools-reference)
- [Trading Strategies](#trading-strategies)
- [HuggingFace Model Integration](#huggingface-model-integration)
- [Scanner Data Pipeline](#scanner-data-pipeline)
- [Backtesting Framework](#backtesting-framework)
- [Database Schema](#database-schema)
- [Cron Job System](#cron-job-system)
- [Technical Papers](#technical-papers)
- [Example Usage](#example-usage)
- [Dependencies](#dependencies)
- [License](#license)

---

## Architecture Overview

```
                         Claude Code / Claude Desktop
                                    |
                              MCP Protocol
                                    |
                    +---------------+---------------+
                    |         ib-mcp server          |
                    |        (53 MCP tools)          |
                    +------+--------+-------+-------+
                           |        |       |       |
              +------------+   +----+---+   |   +---+--------+
              |  IB Gateway |   | SQLite |   |   | HuggingFace|
              | TWS / IBKR  |   |  DB    |   |   |   Models   |
              +------+------+   +--------+   |   +------------+
                     |                       |
          +----------+----------+    +-------+--------+
          |  Live Market Data   |    | Scanner CSVs   |
          |  Orders / Fills     |    | (Station001)   |
          |  News / Options     |    | 31 scanners    |
          +---------------------+    | 52+ days       |
                                     +-------+--------+
                                             |
                                     +-------+--------+
                                     | MinuteBars_SB  |
                                     | 6,147 symbols  |
                                     | 1-min OHLCV    |
                                     +----------------+
```

---

## Features

### Market Data (8 tools)
- **get_quote** — Real-time price snapshot (bid, ask, last, volume) for any contract
- **get_historical_bars** — OHLCV data with configurable duration and bar size (1 sec to 1 month)
- **get_option_chain** — Available expirations and strikes for an underlying
- **get_option_quotes** — Price, Greeks, and IV for specific option contracts
- **get_market_depth** — Level 2 order book data
- **get_head_timestamp** — First available data point for any contract
- **get_histogram** — Price distribution histogram
- **set_market_data_type** — Switch between live, delayed, and frozen data

### Account & Portfolio (6 tools)
- **get_account_summary** — Net liquidation, cash, buying power, margin, daily P&L
- **get_positions** — Current holdings with quantity, average cost, and market value
- **get_portfolio_pnl** — Per-position unrealized P&L with portfolio totals
- **get_open_orders** — All pending orders with status
- **get_closed_trades** — Completed round-trip trades with P&L computation
- **get_executions** — Full execution history with filtering

### Order Management (6 tools)
- **place_order** — Market, limit, or stop orders
- **cancel_order** — Cancel by order ID
- **modify_order** — Change quantity or price on existing orders
- **place_bracket_order** — Entry + stop loss + take profit in one call
- **place_trailing_stop_order** — Trailing stop with configurable distance
- **place_adaptive_order** — IB adaptive algo routing

> Orders are disabled by default. Set `IB_READONLY=false` to enable.

### Research & Analysis (5 tools)
- **calculate_indicators** — SMA, EMA, RSI, MACD, Bollinger Bands, ATR on any timeframe
- **get_contract_details** — Full contract info (name, sector, tick size, trading hours)
- **search_symbols** — Search contracts by partial name
- **check_margin_impact** — Calculate margin requirements before trading
- **get_fundamental_events** — Earnings dates, dividends, corporate actions

### News (3 tools)
- **get_news_providers** — List available IB news sources
- **get_news_headlines** — Recent headlines filtered by symbol or provider
- **get_news_article** — Full article text by ID

### Scanner Data (2 tools)
- **get_scanner_results** — Latest scanner rankings (gainers, losers, volume, gaps)
- **get_scanner_dates** — Available historical scanner date folders

### Trading Log & KPIs (10 tools)
- **get_trading_picks** — Scanner candidate decisions with conviction scoring
- **get_trading_orders** — Order placement history
- **get_trading_lessons** — Lessons logged after position exits
- **get_scan_runs** — Scan cycle summaries
- **get_strategy_positions** — Open/closed positions per strategy
- **get_strategy_kpis_report** — Win rate, profit factor, Sharpe, expectancy per strategy
- **get_position_price_history** — Price snapshots over time for any position
- **get_job_executions** — Cron job execution history
- **get_closed_pnl** — P&L aggregated by date/strategy
- **get_daily_kpis** — Comprehensive daily session metrics

### ML Model Inference (10 tools)
- **analyze_news_sentiment** — FinBERT/DistilRoBERTa sentiment on headlines
- **detect_news_burst** — Rapid headline velocity detection
- **forecast_scanner_rank** — Chronos time series rank prediction
- **forecast_price_monte_carlo** — Probabilistic price distribution with Kelly sizing
- **classify_market_regime** — Zero-shot regime classification (rally/chop/selloff)
- **classify_news_catalyst** — Catalyst type identification (earnings, FDA, etc.)
- **extract_ticker_entities** — NER-based company name to ticker mapping
- **find_similar_trading_days** — Vector similarity search on historical scanner patterns
- **index_scanner_day** — Build RAG index of historical trading days
- **list_models** — Show available models and loading status

### System (3 tools)
- **get_connection_status** — IB connection state
- **reconnect** — Manual reconnection trigger
- **ensure_connected** — Verify or establish connection

---

## Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Interactive Brokers TWS or IB Gateway** — running with API enabled

### IB API Setup

1. Open TWS or IB Gateway
2. Go to **Edit > Global Configuration > API > Settings**
3. Check **Enable ActiveX and Socket Clients**
4. Note the **Socket port** (TWS paper: 7497, TWS live: 7496, Gateway paper: 4002, Gateway live: 4001)
5. Add your machine's IP to **Trusted IPs**

---

## Installation

```bash
git clone <repo-url>
cd ib
uv sync
```

### With ML model support

```bash
uv sync --extra models
```

This installs PyTorch, Transformers, Sentence-Transformers, and Chronos for the HuggingFace model tools. Models are downloaded on first use to `.model_cache/`.

---

## Configuration

Create or edit `.env` in the project root:

```env
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_READONLY=true
```

| Variable | Default | Description |
|---|---|---|
| `IB_HOST` | `127.0.0.1` | TWS/Gateway hostname or IP |
| `IB_PORT` | `7497` | API port (TWS paper: 7497, live: 7496, GW paper: 4002, live: 4001) |
| `IB_CLIENT_ID` | auto | Numeric client ID (1-999), must be unique per connection |
| `IB_READONLY` | `true` | Set to `false` to enable order placement |

---

## Running

### Direct

```bash
uv run python main.py
```

### Windows batch file

```bash
run.bat
```

### As MCP server in Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ib": {
      "command": "uv",
      "args": ["run", "--directory", "D:/src/ai/mcp/ib", "python", "main.py"]
    }
  }
}
```

### As MCP server in Claude Code

```bash
claude mcp add ib -- uv run --directory D:/src/ai/mcp/ib python main.py
```

---

## Project Structure

```
ib/
├── .env                              # Connection settings
├── main.py                           # Entry point
├── pyproject.toml                    # Dependencies and metadata
├── run.bat                           # Windows launcher
├── run_scan.py                       # Multi-strategy scanner cycle
├── trading.db                        # SQLite trading database
│
├── ib_mcp/                           # MCP Server
│   ├── server.py                     # FastMCP instance, tool registration
│   ├── connection.py                 # IB connection lifecycle, auto-reconnect
│   ├── config.py                     # IBConfig via pydantic-settings
│   ├── db.py                         # SQLite ORM (10 tables, 738 lines)
│   ├── indicators.py                 # Technical indicator implementations
│   ├── scanner_data.py               # HVLF rotating scanner CSV parser
│   │
│   ├── models/                       # HuggingFace model integrations
│   │   ├── __init__.py               # ModelRegistry singleton, lazy loading
│   │   ├── config.py                 # Strategy-to-model mapping
│   │   ├── sentiment.py              # FinBERT, DistilRoBERTa, Twitter, DeBERTa
│   │   ├── timeseries.py             # Chronos, TimesFM, TTM forecasting
│   │   ├── embeddings.py             # BGE, MiniLM, vector index
│   │   └── classifiers.py            # BART-MNLI zero-shot, BERT NER
│   │
│   └── tools/                        # MCP tool endpoints (53 total)
│       ├── account.py                # 6 tools — account, positions, P&L
│       ├── market_data.py            # 8 tools — quotes, bars, options, depth
│       ├── orders.py                 # 6 tools — place, cancel, modify, bracket
│       ├── research.py               # 5 tools — indicators, contracts, margin
│       ├── news.py                   # 3 tools — providers, headlines, articles
│       ├── scanners.py               # 2 tools — scanner results, dates
│       ├── trading_log.py            # 10 tools — picks, orders, KPIs, lessons
│       ├── system.py                 # 3 tools — connection management
│       └── models.py                 # 10 tools — ML model inference
│
├── backtest/                         # Backtesting framework
│   ├── engine.py                     # Core engine (PriceCache, trade simulation)
│   ├── strategies.py                 # 14 strategy signal generators
│   ├── run_backtest.py               # CLI runner with full reporting
│   └── backtest_results.db           # Results database
│
├── data/
│   ├── strategies/                   # 11 core + 30 advanced strategy specs
│   │   ├── 01_momentum_surfing.md
│   │   ├── ...
│   │   ├── 11_nvidia_quantum_catalyst.md
│   │   └── 30_advanced_strategies.md # 30 ML/RL/GenAI strategies
│   │
│   ├── instructions/                 # Operational instructions per strategy
│   │   ├── scanner_cron_job.md       # 8-phase cron job specification
│   │   ├── system_architecture.md
│   │   └── strategy_12..41.md        # 30 individual strategy instructions
│   │
│   ├── lessons/                      # Post-trade analysis
│   │   └── 20260415_*.md             # Lessons from closed positions
│   │
│   └── historical/                   # Cached bar data (JSON)
│       └── *.json                    # 16 symbol files
│
└── docs/                             # Technical papers
    ├── 00_Strategy_Overview_and_Comparative_Analysis.md
    ├── S12_ML_Rank_Velocity.md
    ├── S15_HMM_Regime_Detector.md
    ├── S20_Anomaly_Detection.md
    ├── S23_LSTM_Rank_Forecast.md
    └── S30_MAML_Few_Shot.md
```

---

## MCP Tools Reference

### Quick Reference (53 tools)

| Category | Tools | Description |
|----------|-------|-------------|
| Market Data | 8 | Quotes, bars, options, depth, histograms |
| Account | 6 | Positions, P&L, orders, executions |
| Orders | 6 | Place, cancel, modify, bracket, trailing, adaptive |
| Research | 5 | Indicators, contracts, margin, fundamentals |
| News | 3 | Providers, headlines, full articles |
| Scanners | 2 | Scanner results and date listing |
| Trading Log | 10 | Picks, orders, lessons, KPIs, price history |
| ML Models | 10 | Sentiment, forecasting, regime, NER, RAG |
| System | 3 | Connection status, reconnect |

### Key Tool Examples

```
# Get a real-time quote
get_quote(symbol="NVDA")

# Fetch 1-min bars for the last trading day
get_historical_bars(symbol="AAPL", duration="1 D", bar_size="1 min")

# Place a bracket order (entry + stop + target)
place_bracket_order(symbol="TSLA", action="BUY", quantity=10,
                    limit_price=250.00, stop_loss=245.00, take_profit=260.00)

# Analyze news sentiment with FinBERT
analyze_news_sentiment(symbol="NVDA", model="finbert")

# Forecast scanner rank trajectory
forecast_scanner_rank(symbol="HOOD", scanner="GainSinceOpenLarge",
                      prediction_steps=60, model="chronos_small")

# Monte Carlo price forecast with Kelly sizing
forecast_price_monte_carlo(symbol="IONQ", prediction_length=30, num_samples=1000)

# Classify current market regime
classify_market_regime(scanner_summary="Gainers: NVDA, AMD. Bull/bear ratio 3.2")

# Find historically similar trading days (RAG)
find_similar_trading_days(top_k=3)
```

---

## Trading Strategies

### Core Strategies (1-11)

| # | Strategy | Signal | Risk |
|---|----------|--------|------|
| 1 | Momentum Surfing | 2+ gain scanners, above prior day high | 10% stop, 15% trailing, basket stop |
| 2 | Gap-and-Go | >50% premarket gap, >1M volume | 2% account, close by EOD |
| 3 | Fade Euphoria | >100% intraday with topping signals | Short with 15% stop |
| 4 | Cut Losers | Position at -5% | Mandatory stop-loss |
| 5 | Pairs Trade | Correlated stocks, 1-std-dev divergence | Dollar-neutral |
| 6 | Volume Breakout | First HotByVolume appearance + positive price | 1.5% account, 8% max stop |
| 7 | Scanner Conflict Filter | Cross-scanner conflict detection | Overlay: yellow/orange/red |
| 8 | Oversold Bounce | Down >40% from 20-day high, bottoming | 1% account, 5% stop |
| 9 | Multi-Scanner Conviction | 3+ scanner appearances | Tiered sizing by score |
| 10 | Overnight Gap Risk | Position up/down >20% intraday | EOD position review |
| 11 | Quantum Catalyst | Quantum sector + leveraged ETF | Sector-specific |

### Advanced Strategies (12-41)

30 strategies spanning ML, RL, generative AI, and statistical methods:

| Category | Strategies | Models Used |
|----------|-----------|-------------|
| **Machine Learning** | S12 XGBoost, S22 CNN, S23 LSTM, S25 VAE, S34 Attention, S36 SimCLR | LightGBM, ResNet-18, BiLSTM |
| **Reinforcement Learning** | S13 PPO, S35 DQN, S39 World Model, S41 Multi-Agent | PPO, DQN, Dreamer/MuZero |
| **Generative AI / LLM** | S14 Sentiment, S18 Scenarios, S31 Diffusion, S40 RAG | Claude API, DDPM, ChromaDB |
| **News & Sentiment** | S24 News Velocity, S28 Composite Score | FinBERT, DistilRoBERTa |
| **Statistical** | S15 HMM, S20 Anomaly, S27 Granger, S29 Monte Carlo, S37 Bayesian | HMM, IsolationForest, KDE |
| **Graph / Network** | S16 GNN Co-occurrence | GAT |
| **Ensemble / Meta** | S19 Bandit, S26 Federated, S30 MAML, S33 Voting, S38 Distillation | Thompson Sampling, MAML |

### Backtest-Verified Winners

From a 52-day backtest (2026-01-28 to 2026-04-15):

| Strategy | Win Rate | Expectancy | Sharpe | Key Edge |
|----------|----------|------------|--------|----------|
| **S23 LSTM Rank Forecast** | 60% | +1.12% | 11.4 | Catches rank climbers before top-5 |
| **S30 MAML Few-Shot** | 71% | +1.00% | 5.0 | New-to-scanner momentum |
| **S20 Anomaly Detection** | 67% | +0.67% | 3.2 | +14.2% avg forward return at 60 min |
| **S12 Rank Velocity** | 71% | +0.57% | 4.0 | 7-min avg hold scalper |
| **S15 HMM Regime** | 100% | +3.00% | -- | Highest per-trade expectancy |

---

## HuggingFace Model Integration

15 models with lazy loading via `ModelRegistry`. Models download to `.model_cache/` on first use.

### Sentiment Models

| Model | HF ID | Downloads | Use Case |
|-------|-------|-----------|----------|
| FinBERT | `ProsusAI/finbert` | 85.8M | Financial news sentiment (S14, S28) |
| DistilRoBERTa | `mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis` | 145M | Fast batch sentiment (S24) |
| Twitter RoBERTa | `cardiffnlp/twitter-roberta-base-sentiment-latest` | 310M | Social media buzz (S28) |
| DeBERTa Finance | `nickmuchi/deberta-v3-base-finetuned-finance-text-classification` | 45K | High-accuracy sentiment (S28) |
| CryptoBERT | `ElKulako/cryptobert` | 3.8M | Crypto-adjacent names (S28) |
| FOMC RoBERTa | `gtfintechlab/FOMC-RoBERTa` | 74K | Hawkish/dovish Fed text (S15) |

### Time Series Models

| Model | HF ID | Params | Use Case |
|-------|-------|--------|----------|
| Chronos Small | `amazon/chronos-t5-small` | 46M | Zero-shot rank forecasting (S23, S30) |
| Chronos Bolt | `amazon/chronos-bolt-base` | 205M | Monte Carlo price distributions (S29) |
| Chronos Large | `amazon/chronos-t5-large` | 709M | Fine-tuned rank trajectory (S17) |
| TimesFM 2.0 | `google/timesfm-2.0-500m-pytorch` | 499M | Multi-step scanner prediction (S31) |
| TTM | `ibm-granite/granite-timeseries-ttm-r2` | 805K | Ultra-fast student model (S38) |

### Embedding & Classification Models

| Model | HF ID | Use Case |
|-------|-------|----------|
| BGE Large | `BAAI/bge-large-en-v1.5` | RAG vector index (S40) |
| MiniLM | `sentence-transformers/all-MiniLM-L6-v2` | Day fingerprinting (S36) |
| BART MNLI | `facebook/bart-large-mnli` | Zero-shot regime classification (S15, S18, S25) |
| BERT NER | `dslim/bert-base-NER` | Entity extraction, ticker mapping (S14, S24, S40) |

### Usage

```python
from ib_mcp.models import registry

# Models load on first use
model = registry.get_model("finbert")
tokenizer = registry.get_tokenizer("finbert")

# Or use the high-level API
from ib_mcp.models.sentiment import analyze_sentiment
results = analyze_sentiment(["NVDA beats earnings expectations"], model_key="finbert")

# Time series forecasting
from ib_mcp.models.timeseries import forecast_rank_trajectory
forecast = forecast_rank_trajectory(rank_history=[25, 20, 15, 12, 10], prediction_steps=30)

# Regime classification
from ib_mcp.models.classifiers import classify_market_regime
regime = classify_market_regime("Gainers dominated by tech. Bull/bear ratio 3.5.")
```

Install model dependencies:

```bash
uv sync --extra models
```

---

## Scanner Data Pipeline

### Data Sources

| Source | Path | Content |
|--------|------|---------|
| HVLF Rotating Scanners | `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` | 31 CSV files per day, ~30s refresh |
| Minute Bars | `D:\Data\Strategies\HVLF\MinuteBars_SB\` | 6,147 symbol files, 1-min OHLCV |

### Scanner Types (11)

| Scanner | Signal | Category |
|---------|--------|----------|
| GainSinceOpen | Stocks up most since open | Gainer |
| TopGainers | Highest % gainers | Gainer |
| HighOpenGap | Biggest gap-up at open | Gainer |
| LossSinceOpen | Stocks down most since open | Loser |
| TopLosers | Highest % losers | Loser |
| LowOpenGap | Biggest gap-down at open | Loser |
| HotByVolume | Highest relative volume | Volume |
| TopVolumeRate | Fastest volume acceleration | Volume |
| MostActive | Highest absolute volume | Volume |
| HotByPrice | Most price movement | Price |
| HotByPriceRange | Widest price range | Price |

### Cap Tiers (3)

Each scanner type runs separately for LargeCap, MidCap, and SmallCap — giving **33 scanner feeds** total (31 CSV files as some cap tiers lack certain scanners).

### CSV Format

```
20260415 12:40:12.993,0:TEM_STK,1:WIX_STK,2:OKLO_STK,3:HOOD_STK,...
```

Each line: `timestamp,rank:SYMBOL_STK,...` with up to 50 ranked symbols.

### Scanner Data Parser

```python
from ib_mcp.scanner_data import (
    load_scanner_snapshot,           # All scanners, latest snapshot
    load_scanner_file,               # Specific scanner, all lines
    get_symbol_rank_history,         # Symbol's rank over time
    get_symbol_cross_scanner_presence,  # Which scanners a symbol is on
    generate_scanner_summary,        # Natural language summary
)
```

---

## Backtesting Framework

### Architecture

```
backtest/
├── engine.py         # PriceCache, Signal, Trade, StrategyResult, trade simulation
├── strategies.py     # 14 strategy signal generators + STRATEGY_REGISTRY
├── run_backtest.py   # CLI runner, results tables, DB persistence
└── backtest_results.db
```

### Running a Backtest

```bash
# Full backtest — all strategies, all 52 days
python -m backtest.run_backtest

# Specific strategies
python -m backtest.run_backtest --strategies S12,S23,S30

# Specific dates
python -m backtest.run_backtest --dates 20260303,20260304,20260305

# Without IB connection (local CSV bars only)
python -m backtest.run_backtest --no-ib

# Custom sampling interval
python -m backtest.run_backtest --interval 5 --max-signals 30
```

### Price Data Fallback

The `PriceCache` loads data using a cascading fallback:

1. **Local CSV** — `D:\Data\Strategies\HVLF\MinuteBars_SB\{SYMBOL}_STK_M.csv`
2. **IB TWS** — connects to `127.0.0.1:7497` and fetches via `reqHistoricalData`
3. **IB Gateway** — falls back to `127.0.0.1:4002`
4. **Skip** — if all sources fail, the signal is not evaluated

### Output

The backtest produces four report tables:

1. **Strategy Rankings** — signals, trades, win rate, expectancy, Sharpe, profit factor, max drawdown
2. **Exit Breakdown** — stop-loss vs take-profit vs time-stop counts
3. **Forward Returns** — average returns at 15, 30, 60 min horizons
4. **Top/Bottom Trades** — best and worst 10 individual trades

Results are saved to `backtest/backtest_results.db` with two tables: `backtest_results` (strategy-level) and `backtest_trades` (trade-level).

---

## Database Schema

`trading.db` contains 10 tables tracking all trading activity:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `scanner_picks` | Every candidate found by scanners | symbol, scanner, rank, conviction_score, rejected, reject_reason |
| `orders` | Every order placed | symbol, action, order_type, order_id, strategy_id |
| `strategy_positions` | Position lifecycle (open to close) | entry_price, stop_price, target_price, exit_price, pnl, pnl_pct |
| `price_snapshots` | Periodic price logging for open positions | bid, ask, last, volume, unrealized_pnl, distance_to_stop |
| `strategy_runs` | Per-strategy summary each cycle | candidates_found, orders_placed, realized/unrealized P&L |
| `scan_runs` | Overall scan cycle summary | candidates_found, rejected, orders_placed |
| `lessons` | Trade exit analysis | entry/exit prices, P&L, hold_duration, lesson text |
| `strategy_kpis` | Computed performance metrics | win_rate, profit_factor, expectancy, Sharpe, max_drawdown |
| `job_executions` | Cron job tracking | phase_completed, operation counts, portfolio P&L |
| `errors` | Error logging | strategy_id, error_type, error_message, context |

### Database API

```python
from ib_mcp.db import (
    log_pick, log_order, open_position, close_position,
    update_position_extremes, log_price_snapshot,
    log_lesson, log_strategy_run, log_scan_run,
    compute_and_log_kpis,
    start_job_execution, update_job_execution,
    complete_job_execution, fail_job_execution,
    get_open_positions, get_closed_positions,
    get_recent_picks, get_recent_orders, get_recent_lessons,
)
```

---

## Cron Job System

The scanner cron job (`data/instructions/scanner_cron_job.md`) runs every 10 minutes during market hours with 8 phases:

| Phase | Action | Key Operations |
|-------|--------|----------------|
| 0 | Job Tracking | `start_job_execution` → returns `exec_id` |
| 1 | Pre-Trade Checklist | Load strategies, lessons, check positions and connection |
| 2 | Risk Management | Cut losers at -5%, close accidental shorts, reconcile trades |
| 3 | Scanner Analysis | Parse scanner data, categorize gain/loss/volume signals |
| 4 | Strategy Matching | Conviction scoring, conflict filtering, tier classification |
| 5 | Order Execution | Quality gates (price, volume, spread), place orders, log to DB |
| 6 | Position Monitoring | Price snapshots, extremes tracking, overnight gap check |
| 7 | Exit Handling | Close positions, log lessons, compute KPIs |
| 8 | Run Summary | Log scan_runs, strategy_runs, `complete_job_execution` |

### Quality Gates (Phase 5)

Before any order is placed:

- Minimum price: >= $2.00
- Minimum volume: >= 50,000 shares/day
- Maximum spread: <= 3% of last price
- No warrants/units (R, W, WS, U suffixes rejected)
- $5-$10 stocks require 2+ consecutive scanner appearances
- Maximum 10 open positions

### Conviction Scoring

| Scanner | Points |
|---------|--------|
| PctGain | +2 |
| HotByVolume | +2 |
| GainSinceOpen | +1 |
| Any Loss scanner | -2 |
| Gain + Loss conflict | -1 |

- **Tier 1 (5+)**: Trade with full size
- **Tier 2 (3-4)**: Reject — insufficient conviction
- **Tier 3 (1-2)**: Watchlist only
- **Negative**: Blacklisted

---

## Technical Papers

Published in `docs/`:

| Paper | Strategy | Key Finding |
|-------|----------|-------------|
| `00_Strategy_Overview_and_Comparative_Analysis.md` | All 14 | Comparative ranking, forward return analysis, architecture |
| `S12_ML_Rank_Velocity.md` | XGBoost Rank Velocity | 7-min scalper: negative forward returns confirm fast exit is correct |
| `S15_HMM_Regime_Detector.md` | HMM Regime | Knowing WHEN to trade matters more than WHAT to trade |
| `S20_Anomaly_Detection.md` | Isolation Forest | +14.2% avg forward return at 60 min — scanner shocks predict sustained moves |
| `S23_LSTM_Rank_Forecast.md` | BiLSTM Rank Forecast | Sharpe 11.4, profit factor 17.5x — best risk-adjusted strategy |
| `S30_MAML_Few_Shot.md` | MAML Meta-Learning | New-to-scanner symbols as few-shot adaptation proxy |

---

## Example Usage

Once connected through Claude, you can interact naturally:

### Market Data
```
"Show me my account summary and open positions"
"Get 6 months of daily bars for AAPL with RSI and MACD"
"What's the current bid/ask spread on SPY?"
"Show me the NVDA option chain for next month"
```

### Trading
```
"Buy 100 shares of TSLA at market"
"Place a bracket order on AAPL: buy at 190, stop at 185, target at 200"
"What are my open orders? Cancel order 12345"
```

### Scanner & Strategy
```
"Show me today's scanner results"
"What stocks are on both the gainer and volume scanners?"
"Run the sentiment analysis on NVDA's latest headlines"
"Classify the current market regime from scanner data"
```

### Analysis & Research
```
"What's my win rate on the momentum_surfing strategy?"
"Show me all lessons from today's trades"
"Find trading days similar to today's scanner pattern"
"Run a Monte Carlo forecast on IONQ with 1000 simulations"
```

### Backtesting
```
"Run a backtest of S12 and S23 over the last 10 trading days"
"Show me the backtest results sorted by Sharpe ratio"
```

---

## Dependencies

### Core

| Package | Purpose |
|---|---|
| `mcp[cli]` | MCP server framework (FastMCP) |
| `ib_insync` | Interactive Brokers TWS/Gateway API |
| `pandas` | Data manipulation, bar data processing |
| `numpy` | Numerical computation |
| `pydantic-settings` | Configuration management with `.env` |

### Models (optional)

| Package | Purpose |
|---|---|
| `torch` | PyTorch for model inference |
| `transformers` | HuggingFace model loading |
| `sentence-transformers` | Embedding models (BGE, MiniLM) |
| `chronos-forecasting` | Amazon Chronos time series |
| `safetensors` | Efficient model weight loading |

---

## External Data Paths

| Path | Content |
|------|---------|
| `\\Station001\DATA\hvlf\rotating\` | Scanner CSVs (31 files/day, 52+ days) |
| `\\Station001\DATA\hvlf\scanner-monitor\` | Legacy scanner monitor path |
| `D:\Data\Strategies\HVLF\MinuteBars_SB\` | 6,147 symbol minute bar files |

---

## License

Private research project. Not for redistribution.
