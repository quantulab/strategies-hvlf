# ib-mcp

MCP (Model Context Protocol) server for Interactive Brokers. Connects Claude to your IB account for algorithmic trading research and development.

## Features

### Market Data
- **get_quote** — Real-time price snapshot (bid, ask, last, volume) for any contract
- **get_historical_bars** — OHLCV historical bar data for backtesting (configurable duration and bar size)
- **get_option_chain** — Available option expirations and strikes for an underlying
- **get_option_quotes** — Price and Greeks for a specific option contract

### Account & Portfolio
- **get_account_summary** — Net liquidation, cash, buying power, margin, P&L
- **get_positions** — Current holdings with quantity and average cost
- **get_open_orders** — All pending orders with status

### Order Management
- **place_order** — Place market, limit, or stop orders
- **cancel_order** — Cancel an open order by ID
- **modify_order** — Change quantity or price on an existing order

> Orders are disabled by default. Set `IB_READONLY=false` to enable.

### Strategy R&D
- **calculate_indicators** — Compute technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR) from historical data
- **get_contract_details** — Full contract info (name, industry, tick size, trading hours)

## Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Interactive Brokers TWS or IB Gateway** — running and accepting API connections

### IB API Setup

1. Open TWS or IB Gateway
2. Go to **Edit > Global Configuration > API > Settings**
3. Check **Enable ActiveX and Socket Clients**
4. Note the **Socket port** (default: 7497 for TWS paper, 4002 for Gateway paper)
5. Add `127.0.0.1` to **Trusted IPs** (or your machine's IP if running remotely)

## Installation

```bash
git clone <repo-url>
cd ib
uv sync
```

## Configuration

Copy and edit the `.env` file in the project root:

```env
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_READONLY=true
```

| Variable | Default | Description |
|---|---|---|
| `IB_HOST` | `127.0.0.1` | TWS/Gateway hostname or IP |
| `IB_PORT` | `7497` | API port. TWS paper: 7497, TWS live: 7496, Gateway paper: 4002, Gateway live: 4001 |
| `IB_CLIENT_ID` | `1` | Numeric client ID (1-999). Must be unique per simultaneous connection |
| `IB_READONLY` | `true` | Set to `false` to enable order placement |

## Running

### Directly

```bash
uv run python main.py
```

### Windows batch file

```bash
run.bat
```

### As an MCP server in Claude Desktop

Add to your `claude_desktop_config.json`:

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

The server reads configuration from the `.env` file automatically. You can also pass env vars in the config if needed:

```json
{
  "mcpServers": {
    "ib": {
      "command": "uv",
      "args": ["run", "--directory", "D:/src/ai/mcp/ib", "python", "main.py"],
      "env": {
        "IB_PORT": "7497",
        "IB_READONLY": "true"
      }
    }
  }
}
```

### As an MCP server in Claude Code

Add via CLI:

```bash
claude mcp add ib -- uv run --directory D:/src/ai/mcp/ib python main.py
```

## Project Structure

```
ib/
  .env                         # Connection settings (gitignored)
  main.py                      # Entry point
  pyproject.toml               # Dependencies and metadata
  run.bat                      # Windows launcher
  ib_mcp/
    server.py                  # FastMCP instance and tool registration
    connection.py              # IB connection lifecycle (lifespan)
    config.py                  # Settings via pydantic-settings
    indicators.py              # Technical indicator implementations (SMA, EMA, RSI, MACD, BBANDS, ATR)
    tools/
      market_data.py           # Quotes, historical bars, option chains
      account.py               # Account summary, positions, open orders
      orders.py                # Place, cancel, modify orders
      research.py              # Technical indicators, contract details
```

## Example Usage

Once connected through Claude, you can ask things like:

- "Show me my account summary"
- "Get 6 months of daily bars for AAPL"
- "Calculate RSI and MACD for TSLA"
- "What's the current bid/ask for SPY?"
- "Show me the option chain for NVDA"
- "Get my open positions"

## Dependencies

| Package | Purpose |
|---|---|
| `mcp[cli]` | MCP server framework (FastMCP) |
| `ib_insync` | Interactive Brokers TWS/Gateway API client |
| `pandas` | Data manipulation for indicators and bar data |
| `numpy` | Numerical computation |
| `pydantic-settings` | Configuration management with `.env` support |
