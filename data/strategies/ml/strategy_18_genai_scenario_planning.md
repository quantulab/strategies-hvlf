---
noteId: "s18_genai_scenario_planning"
tags: [strategy, genai, scenario-planning, what-if, robust-winners]

---

# Strategy 18: Generative AI Scenario Planning — Operating Instructions

## Schedule
- **Evening job** (7:00 PM ET): Generate 10 what-if scenarios for next trading day
- **Pre-market job** (8:00 AM ET): Compare pre-market against scenarios, identify trades
- **Intraday monitoring** (every 10 minutes, 9:40 AM–3:55 PM ET): Monitor positions, EOD exit

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner types: GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- Cap tiers: LargeCap, MidCap, SmallCap
- Historical scanner CSVs: last 60 trading days of scanner data for model fine-tuning
- News: via `get_news_headlines` and `get_news_article` for macro context
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_18_scenario")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules (cut losers, gateway disconnect, accidental shorts)
2. **Load strategy file** from `data/strategies/` — verify Strategy 18 parameters
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions tagged with `strategy_id = "scenario_planning"`
   - If already at max 6 positions, skip to Phase 6 (monitoring only)
4. **Check open orders** via `get_open_orders()` — avoid duplicate entries
5. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
6. **Check scenario availability** — verify evening scenario generation completed for today (query `job_executions` for last evening run)
7. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs FIRST)

**Before any new trades, enforce the 5% stop-loss rule on ALL Strategy 18 positions.**

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. For each Strategy 18 position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if a SELL order already exists for this symbol
   b. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")`
   c. Log to `orders` table with `strategy_id = "scenario_planning"`, full order details
   d. Log to `strategy_positions` — close the position with `exit_reason = "stop_loss_5pct"`
   e. Log to `lessons` table with symbol, entry/exit prices, P&L, scenario context, lesson text
   f. Compute and log KPIs via `compute_and_log_kpis(strategy_id="scenario_planning")`
3. For short positions (quantity < 0) created accidentally:
   a. Call `place_order(symbol=SYMBOL, action="BUY", quantity=ABS_SHARES, order_type="MKT")`
   b. Log with `exit_reason = "close_accidental_short"`
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)` to sync IB executions
   b. For every Strategy 18 position that closed externally:
      - Log to `lessons`, `strategy_positions`, and `orders` tables with actual exit details
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 Evening Scenario Generation (7:00 PM ET run)

1. Collect today's scanner data across all 11 scanner types:
   - Call `get_scanner_results(scanner=SCANNER_TYPE, date=TODAY, top_n=50)` for each type
2. Collect market context:
   - Call `get_news_headlines(symbol="SPY", provider_codes="DJ-N", start=TODAY, end=TODAY, max_results=20)` for macro news
   - Call `get_news_headlines(symbol="QQQ", provider_codes="DJ-N", start=TODAY, end=TODAY, max_results=10)` for tech sector
   - For key articles, call `get_news_article(provider_code="DJ-N", article_id=ARTICLE_ID)` for full text
3. Call `calculate_indicators(symbol="SPY", indicators=["RSI", "SMA", "MACD"], duration="20 D", bar_size="1 day", tail=5)` for macro trend
4. Call `calculate_indicators(symbol="VIX", indicators=["SMA"], duration="20 D", bar_size="1 day", tail=5)` for volatility regime

### 3.2 Generate 10 What-If Scenarios

Using historical scanner patterns and today's context, generate:

| Scenario # | Type | Description |
|------------|------|-------------|
| 1 | Bull continuation | Today's gainers extend, volume confirms |
| 2 | Bull rotation | New sector leads, yesterday's leaders cool |
| 3 | Bear reversal | Gainers flip to losers, VIX spike |
| 4 | Bear continuation | Today's losers deepen, broad selling |
| 5 | Macro shock (positive) | Fed dovish/earnings beat, broad rally |
| 6 | Macro shock (negative) | Geopolitical/data miss, broad selloff |
| 7 | Sector earnings | Earnings catalyst drives specific names |
| 8 | Low volatility drift | Narrow range, volume dries up |
| 9 | Short squeeze | High-short-interest names spike |
| 10 | Gap and reversal | Gap up/down reverses by midday |

For each scenario, predict:
- Expected scanner composition: which symbols appear on which scanners
- Predicted Top-5 on each Gainer scanner
- Predicted entrants on Loser scanners
- Confidence level (low/medium/high) for each scenario

### 3.3 Identify Robust Winners

5. A "robust winner" appears in the **bullish column** (Gainer/Volume scanners) in **7 or more** of the 10 scenarios
6. Store robust winners list with scenario count and average predicted rank
7. Log scenario generation to `scan_runs` table with summary of all 10 scenarios

### 3.4 Pre-Market Validation (8:00 AM ET run)

8. At 8:00 AM, call `get_quote(symbol=SYMBOL)` for each robust winner to check pre-market price
9. Call `get_scanner_results(scanner="HighOpenGap", date=TODAY, top_n=20)` for pre-market gap data
10. Compute **Jaccard similarity** between actual pre-market scanner composition and each scenario:
    - `J(A, B) = |A ∩ B| / |A ∪ B|` where A = predicted scanner symbols, B = actual pre-market symbols
11. If **best-matching scenario has Jaccard similarity > 0.60**, activate trades for that scenario's robust winners
12. If no scenario matches (all J < 0.60), skip trading — log `reject_reason = "no_scenario_match"`

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 Scenario-Driven Signal Selection

1. From the best-matching scenario (J > 0.60), extract the predicted robust winners
2. For each robust winner, compute a conviction score:
   - `scenario_count / 10` (fraction of scenarios where symbol appears bullish)
   - Weight by matched scenario's confidence level
   - Final score = `scenario_count_score * scenario_confidence * jaccard_similarity`
3. Rank candidates by conviction score descending

### 4.2 Cross-Validation with Live Data

4. For each candidate, call `get_quote(symbol=SYMBOL)` — verify price is moving in predicted direction
5. Call `calculate_indicators(symbol=SYMBOL, indicators=["RSI", "MACD", "ATR"], duration="5 D", bar_size="15 mins", tail=10)` for trend confirmation
6. **Veto rules:**
   - If symbol appears on any Loser scanner in current data → reject, log `reject_reason = "loser_scanner_present"`
   - If RSI > 80 → reject, log `reject_reason = "overbought_rsi"`
   - If ATR < 0.5% of price → reject, log `reject_reason = "insufficient_volatility"`
7. Log all candidates to `scanner_picks` table with scenario context

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, call `get_quote(symbol=SYMBOL)` and verify:

1. **Minimum price:** `last >= $2.00` — reject sub-$2 stocks
2. **Minimum volume:** avg daily volume >= 50,000 shares — reject illiquid names
3. **Maximum spread:** `(ask - bid) / last <= 3%` — reject wide-spread stocks
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Scenario freshness:** Scenarios must be from last evening (< 16 hours old) — reject if stale

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **6** open positions for Strategy 18 at any time
- Position size: **0.5% of account** per position
- Calculate shares: `quantity = floor(account_value * 0.005 / last_price)`
- Check for existing position/order via `get_positions()` and `get_open_orders()` before placing

### Order Structure

For each accepted candidate:

1. **Entry order:** `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
2. **Stop loss (5%):** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=ENTRY * 0.95)`
3. No take-profit limit — hold until EOD per strategy rules

### Database Logging (for EVERY order):

1. **`scanner_picks` table:** symbol, scanner, rank, conviction_score, scenario_count, jaccard_similarity, best_scenario_id, action="BUY", rejected=0
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, stop_price, entry_price, status, pick_id, strategy_id="scenario_planning"
3. **`strategy_positions` table:** strategy_id="scenario_planning", symbol, action="BUY", quantity, entry_price, entry_order_id, stop_price, target_price=NULL, scanners_at_entry, conviction_score, pick_id

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open Strategy 18 position every run:

1. Call `get_quote(symbol=SYMBOL)` for current price
2. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, distance to stop
3. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown)
4. Call `get_position_price_history(position_id=POS_ID)` to review trajectory
5. **Scenario drift check**: Compare current scanner state against the matched scenario
   - If actual market diverges significantly (Jaccard drops below 0.30), consider early exit
   - Log drift observation to `lessons` table
6. **EOD exit** (3:45 PM ET or later):
   a. Call `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="MKT")`
   b. Cancel open stop orders via `cancel_order(order_id=STOP_ORDER_ID)`
   c. Log exit with `exit_reason = "eod_close"`

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

### On Exit (stop hit, EOD close, scenario drift, or manual close)

1. Close position in `strategy_positions` with exit_price, exit_reason, P&L
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="scenario_planning", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - matched_scenario_id, jaccard_similarity_at_entry, scenario_count
   - whether the matched scenario played out correctly
   - lesson text: scenario accuracy assessment, what was predicted vs what happened
3. Compute and log KPIs via `compute_and_log_kpis(strategy_id="scenario_planning")`
4. **Scenario accuracy tracking**: Log whether each scenario's predictions were correct:
   - Did robust winners actually appear on Gainer scanners?
   - Did the matched scenario's predicted Losers actually lose?
   - Feed accuracy back into scenario generation quality metrics
5. If significant lesson, write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: scenarios_generated, scenario_match_quality, candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for strategy_id="scenario_planning" with this cycle's metrics
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="scenario_planning")`:
   - Win rate, avg P&L per trade, max drawdown, expectancy
   - Scenario accuracy: % of matched scenarios that played out correctly
   - Jaccard similarity distribution across trading days
4. Call `complete_job_execution(exec_id, summary)` with full summary

---

## Model Training / Retraining Schedule

### Ongoing Scenario Quality Improvement
1. After each trading day, compare all 10 scenarios against actual scanner data
2. Track per-scenario-type accuracy over trailing 20 days
3. Prune scenario types with < 20% accuracy, add new scenario types based on observed patterns
4. Update prompt/fine-tuning data with last 60 days of scanner CSVs monthly

### Monthly Review
- Review scenario accuracy via `get_strategy_kpis_report(strategy_id="scenario_planning")`
- Adjust Jaccard similarity threshold (currently 0.60) based on trade-off between signal frequency and accuracy
- Review robust winner threshold (currently 7/10 scenarios) — lower if too few trades, raise if win rate drops
- Analyze which scenario types (bull/bear/macro) produce the best trades

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each run (evening + pre-market + intraday) | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with scenario context & rejection reasons | Phase 4, 5 |
| `orders` | Every order placed (entry, stop, exit) | Phase 2, 5, 6 |
| `strategy_positions` | Position lifecycle (open → monitor → close) | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price history for each position each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary each cycle | Phase 8 |
| `scan_runs` | Scan cycle summary with scenario metadata | Phase 3, 8 |
| `lessons` | Exit lessons with scenario accuracy and learnings | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, scenario accuracy per strategy | Phase 2, 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_dates()` | 3 | Verify available scanner data dates |
| `get_scanner_results(scanner, date, top_n)` | 3 | Fetch scanner data for scenario generation and validation |
| `get_quote(symbol)` | 3, 5, 6 | Pre-market price, quality gate, position monitoring |
| `get_historical_bars(symbol, duration, bar_size)` | 3 | Historical price data for scenario context |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | 3, 4 | RSI, MACD, ATR, SMA for trend confirmation |
| `get_news_headlines(symbol, provider_codes, start, end, max_results)` | 3 | Macro/sector news for scenario generation |
| `get_news_article(provider_code, article_id)` | 3 | Full article text for scenario context |
| `get_positions()` | 1, 5 | Check current positions and slot availability |
| `get_portfolio_pnl()` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders()` | 1, 2, 5 | Prevent duplicate orders and accidental shorts |
| `get_closed_trades(save_to_db=True)` | 2 | Reconcile externally closed trades |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | 2, 5, 6 | Execute entries, stops, exits |
| `cancel_order(order_id)` | 6 | Cancel orphaned stop orders on EOD exit |
| `get_position_price_history(position_id)` | 6 | Review position trajectory |
| `get_strategy_positions(strategy_id="scenario_planning", status, limit)` | 1, 6 | Query strategy-specific positions |
| `get_strategy_kpis_report(strategy_id="scenario_planning")` | 8 | Compute and review strategy KPIs |
| `get_job_executions(job_id="strategy_18_scenario", limit)` | 0, 1 | Query execution history, verify evening run |
