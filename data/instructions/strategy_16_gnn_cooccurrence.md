---
noteId: "TODO"
tags: [cron, trading, strategies, ml, gnn, graph-neural-network, gat]

---

# Strategy 16: GNN Co-occurrence Network — Operating Instructions

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 2:00 PM ET) via Claude Code CronCreate.
**Hard cutoff at 2:00 PM ET — all positions closed, no new trades after 2 PM.**
Model retraining runs weekly on Sundays at 8 PM ET.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Minute bars: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Historical bars via MCP: `get_historical_bars(symbol, duration, bar_size)`
- GAT model weights: `D:\src\ai\mcp\ib\data\models\gnn_cooccurrence_gat.pt`
- Node encoder: `D:\src\ai\mcp\ib\data\models\gnn_node_encoder.pkl`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

**Every cron run MUST be recorded in the `job_executions` table.**

1. Call `start_job_execution(job_id="strategy_16_gnn_cooccurrence")` to create a new execution record — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1-8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
   - Graph-specific: `graph_nodes`, `graph_edges`, `avg_degree_centrality`, `top_node_symbol`, `top_node_predicted_return`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

**All information from the run must be stored in the database — the `job_executions` row is the master record tying together all operations performed in that cycle.**

---

## PHASE 1: Pre-Trade Checklist (every run)

1. **Load all lessons** from `data/lessons/` — apply rules learned (especially co-occurrence and graph-based lessons)
2. **Load strategy file** from `data/strategies/` — confirm parameters
3. **Load GAT model weights** from disk:
   - If model file missing, call `fail_job_execution(exec_id, "GAT model weights not found")` and abort
   - Verify model checkpoint is from current training cycle (within 7 days)
4. **Load node encoder** — maps symbol strings to consistent integer IDs
5. **Check current time:** If after 2:00 PM ET, skip to Phase 6 for position closure only
6. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count positions with `strategy_id = "gnn_cooccurrence"`
   - If already at 3 concurrent positions, skip to Phase 6 (monitoring only)
7. **Check current open orders** via `get_open_orders()`
8. **Verify IB connection** — if disconnected, log error via `fail_job_execution` and attempt reconnect
9. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management (MANDATORY)

**Before any new trades, enforce stop-loss rules on ALL strategy_16 positions.**

Stops are VWAP-based: `stop_price = VWAP - 2 * ATR`

1. Call `get_portfolio_pnl()` to get current P&L for every position
2. Call `get_strategy_positions(strategy_id="gnn_cooccurrence", status="open")` to identify this strategy's positions
3. For each open position:
   a. Call `calculate_indicators(symbol=SYMBOL, indicators=["ATR"], duration="1 D", bar_size="1 min", tail=1)` to get current ATR
   b. Call `get_historical_bars(symbol=SYMBOL, duration="1 D", bar_size="1 min")` to compute intraday VWAP:
      - `VWAP = sum(typical_price * volume) / sum(volume)` where `typical_price = (high + low + close) / 3`
   c. Compute `dynamic_stop = VWAP - 2 * ATR`
   d. If `last_price <= dynamic_stop`:
      - Check `get_open_orders()` — skip if a SELL order already exists
      - Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")`
      - Log to `orders` table with `strategy_id = "gnn_cooccurrence"`
      - Log to `strategy_positions` — close with `exit_reason = "stop_vwap_minus_2atr"`
      - Log to `lessons` table with full details including VWAP, ATR, and graph metrics at entry
      - Compute KPIs via `compute_and_log_kpis`
4. For short positions (quantity < 0) — close immediately with MKT BUY
5. **Reconcile closed trades (MANDATORY):**
   a. Call `get_closed_trades(save_to_db=True)` to get all completed executions from IB
   b. For every position that disappeared: log to `lessons`, `strategy_positions`, and `orders`
6. **Check target hits:** For positions where `last_price >= target_price` (VWAP + 3*ATR):
   - These should be caught by the limit order, but verify and log if filled
7. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Graph Construction

### Scanner Data Collection
1. Call `get_scanner_dates()` to confirm today's date is available
2. For each scanner type in [GainSinceOpen, HotByVolume, HotByPrice, TopGainers, MostActive, TopVolumeRate, HotByPriceRange, HighOpenGap]:
   - For each cap tier in [SmallCap, MidCap, LargeCap]:
     - Call `get_scanner_results(scanner="{CapTier}-{ScannerType}", date=TODAY, top_n=20)`
     - Record: `{symbol, scanner_type, cap_tier, rank, timestamp}`

### Graph Construction

1. **Build node set:**
   - Each unique symbol across all scanners becomes a node
   - If `total_nodes < 20`, log "Insufficient graph density" and skip to Phase 8 — **do not trade**
   - Record `graph_nodes = len(node_set)`

2. **Build edge set (co-occurrence edges):**
   - For each pair of symbols `(A, B)` that appear on the **same scanner** in the current snapshot:
     - Create an undirected edge `(A, B)`
     - Edge weight = number of distinct scanner types where both A and B appear simultaneously
   - Example: if AAPL and MSFT both appear on HotByVolume-LargeCap AND TopGainers-LargeCap, edge weight = 2
   - Record `graph_edges = len(edge_set)`

3. **Compute node features (per node):**

   a. **Rank vector** (11 elements, one per scanner type):
      - Rank of the symbol on each scanner type (0 if not present)
      - Normalized to [0, 1] where 1 = rank 1, 0 = not present
      - `rank_vector = [rank_GainSinceOpen/20, rank_HotByVolume/20, ..., rank_TopVolumeRate/20]`

   b. **Cap tier** (one-hot, 3 elements):
      - `[is_smallcap, is_midcap, is_largecap]`

   c. **Minutes on scanner** (1 element):
      - `minutes_on_any_scanner` = time since symbol first appeared on any scanner today
      - Normalized: `min(minutes / 330, 1.0)` (330 min = full trading day)

   d. **Price features** (4 elements):
      - Call `get_quote(symbol=SYMBOL)` for each node
      - `spread_pct = (ask - bid) / last`
      - `change_pct = (last - prev_close) / prev_close`
      - `volume_ratio = current_volume / avg_volume` (from `get_historical_bars`)
      - `log_price = log(last_price)` (size normalization)

   e. Total node feature vector: 11 + 3 + 1 + 4 = **19 elements per node**

4. **Compute graph-level metrics:**

   a. **Degree centrality** per node: `degree(node) / (total_nodes - 1)`
   b. **80th percentile threshold:** `centrality_threshold = percentile(all_degree_centralities, 80)`
   c. Identify **high-centrality nodes:** nodes with `degree_centrality > centrality_threshold`

5. **Construct PyTorch Geometric Data object:**
   - `x`: node feature matrix [N, 19]
   - `edge_index`: edge list [2, E]
   - `edge_attr`: edge weights [E, 1]

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### GAT Forward Pass
1. **Run 2-layer Graph Attention Network:**
   - Layer 1: GAT(in=19, out=32, heads=4) → concatenate → [N, 128]
   - Layer 2: GAT(in=128, out=1, heads=1) → [N, 1] — predicted 30-min return
   - Apply sigmoid to output for bounded prediction

2. **Extract predictions:**
   - `predicted_returns[i]` = model output for node i (predicted 30-min forward return in %)
   - Rank all nodes by predicted return descending

3. **Apply selection criteria — ALL must be TRUE:**
   - `degree_centrality > 80th percentile` — node must be well-connected in the co-occurrence graph
   - `predicted_return > 0` — model must predict positive return
   - `graph_nodes >= 20` — minimum graph density requirement

4. **Select top-3 nodes** meeting all criteria, ranked by predicted return

5. **Compute conviction score per candidate:**
   - `conviction = predicted_return * 100 * degree_centrality * edge_weight_sum`
   - Normalize to 0-100 range

6. **Log all nodes to `scanner_picks` table:**
   - symbol, scanner (primary scanner by rank), rank, conviction_score, conviction_tier ("tier1" if selected, "rejected" otherwise), scanners_present (comma-separated), action="BUY", rejected flag, reject_reason
   - Additional fields: degree_centrality, predicted_return, edge_count, graph_density

7. Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)
Before placing ANY order, run these checks via `get_quote(symbol=SYMBOL)`:

1. **Minimum price:** Last price >= $2.00
2. **Minimum volume:** Current volume >= 50,000 shares
3. **Maximum spread:** (ask - bid) / last <= 2%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U suffixes
5. **Not already held:** Check `get_positions()` for existing position
6. **Not already ordered:** Check `get_open_orders()` for pending order
7. **Graph density:** Verify `graph_nodes >= 20` (re-check)
8. **Time check:** Verify current time < 2:00 PM ET (must have time for the 30-min prediction horizon)
9. **Degree centrality:** Verify node's `degree_centrality > 80th percentile`

Log rejection reason to `scanner_picks` table if any check fails.

### Position Limits
- Maximum **3** concurrent positions for this strategy
- **1% of account** per trade — compute quantity from account value and last price
- All 3 slots may be filled simultaneously (batch entry)

### Order Structure (VWAP-anchored brackets)
For each of the top-3 approved candidates:

1. **Compute VWAP and ATR:**
   - Call `get_historical_bars(symbol=SYMBOL, duration="1 D", bar_size="1 min")` for VWAP calculation
   - Call `calculate_indicators(symbol=SYMBOL, indicators=["ATR"], duration="1 D", bar_size="5 mins", tail=1)` for ATR
   - `VWAP = sum(typical_price * volume) / sum(volume)`
   - `stop_price = VWAP - 2 * ATR`
   - `target_price = VWAP + 3 * ATR`

2. **Entry order:** Call `place_order(symbol=SYMBOL, action="BUY", quantity=QTY, order_type="MKT")`
3. **Stop loss:** Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="STP", stop_price=stop_price)`
4. **Take profit:** Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="LMT", limit_price=target_price)`

### For EVERY order placed, log to database:
1. **`scanner_picks` table:** symbol, scanner, rank, conviction_score, scanners_present, action="BUY", rejected=0, degree_centrality, predicted_return, graph_nodes, graph_edges
2. **`orders` table:** symbol, scanner, action, quantity, order_type, order_id, limit_price, stop_price, entry_price, status, strategy_id="gnn_cooccurrence", vwap, atr
3. **`strategy_positions` table:** strategy_id="gnn_cooccurrence", symbol, action="BUY", quantity, entry_price, entry_order_id, stop_price, target_price, stop_order_id, target_order_id, scanners_at_entry, conviction_score, degree_centrality, predicted_return, graph_snapshot (JSON: {nodes, edges, node_features}), vwap_at_entry, atr_at_entry

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring & Price Snapshots

For each open position with `strategy_id = "gnn_cooccurrence"` every run:

1. Call `get_quote(symbol=SYMBOL)` to get current price data
2. **Recompute VWAP and ATR** (they change intraday):
   - Call `get_historical_bars(symbol=SYMBOL, duration="1 D", bar_size="1 min")` for updated VWAP
   - Call `calculate_indicators(symbol=SYMBOL, indicators=["ATR"], duration="1 D", bar_size="5 mins", tail=1)` for updated ATR
   - Update `dynamic_stop = VWAP - 2 * ATR` and `dynamic_target = VWAP + 3 * ATR`
   - If stop or target has shifted significantly, update the orders:
     - Call `modify_order(order_id=STOP_ORDER_ID, stop_price=new_dynamic_stop)`
     - Call `modify_order(order_id=TARGET_ORDER_ID, limit_price=new_dynamic_target)`
3. Log `price_snapshots` with bid, ask, last, volume, unrealized P&L, current_vwap, current_atr, distance_to_stop, distance_to_target, degree_centrality (current)
4. Update position extremes via `update_position_extremes` (peak, trough, MFE, MAE, drawdown_pct)
5. **Graph re-evaluation:** Check if the node's degree centrality has dropped below 50th percentile
   - If so, log warning — the symbol is losing co-occurrence significance
   - Consider early exit if centrality dropped from >80th to <50th percentile
6. **2:00 PM forced close — MANDATORY:**
   - If current time >= 2:00 PM ET:
     a. Cancel all open stop and target orders for this strategy:
        - Call `cancel_order(order_id=STOP_ORDER_ID)`
        - Call `cancel_order(order_id=TARGET_ORDER_ID)`
     b. Close all positions at market:
        - Call `place_order(symbol=SYMBOL, action="SELL", quantity=QTY, order_type="MKT")`
     c. Log with `exit_reason = "eod_cutoff_2pm"`

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

### On Exit (stop hit, target hit, 2 PM cutoff, centrality drop, or manual close)
1. Close position in `strategy_positions` with exit_price, exit_reason, P&L:
   - `exit_reason` options: "stop_vwap_minus_2atr", "target_vwap_plus_3atr", "eod_cutoff_2pm", "centrality_drop", "manual"
2. Log to `lessons` table with full trade details:
   - symbol, strategy_id="gnn_cooccurrence", action, entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - scanner that triggered entry, exit_reason
   - degree_centrality_at_entry, degree_centrality_at_exit
   - predicted_return_at_entry, actual_return
   - graph_nodes_at_entry, graph_edges_at_entry
   - vwap_at_entry, vwap_at_exit, atr_at_entry, atr_at_exit
   - co_occurrence_neighbors (list of symbols sharing edges)
   - lesson text: analyze whether graph structure predicted the move, whether high-centrality nodes truly outperformed
3. Compute and log KPIs for `gnn_cooccurrence` via `compute_and_log_kpis`
4. **Model accuracy tracking:**
   - `prediction_correct = 1 if (predicted_return > 0 and actual_return > 0) else 0`
   - `prediction_error = abs(predicted_return - actual_return)`
   - Track rank correlation between predicted and actual returns across all trades
5. If significant lesson, write markdown file to `data/lessons/`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs` with: candidates_found, candidates_rejected, orders_placed, positions_held, graph_nodes, graph_edges, avg_degree_centrality, graph_density, summary
2. Log `strategy_runs` for `gnn_cooccurrence` with cycle-specific metrics:
   - graph_nodes, graph_edges, graph_density
   - centrality_threshold, nodes_above_threshold
   - top_3_symbols, top_3_predicted_returns
   - positions_opened, positions_closed, positions_held
   - avg_predicted_return, avg_actual_return (for closed positions)
3. Compute `strategy_kpis` for `gnn_cooccurrence` if any positions were closed:
   - win_rate, avg_win, avg_loss, profit_factor, expectancy
   - avg_hold_duration, max_drawdown
   - prediction_accuracy (% of predictions with correct direction)
   - prediction_mae (mean absolute error of return predictions)
   - centrality_correlation (correlation between degree centrality and actual return)
   - avg_graph_density_winners vs avg_graph_density_losers
   - skip_rate (% of cycles skipped due to <20 nodes)
4. Call `complete_job_execution(exec_id, summary)` with a full summary including graph metrics

---

## Model Training / Retraining Schedule

### GAT Training Protocol
- **Architecture:** 2-layer Graph Attention Network (GAT)
  - Layer 1: GATConv(in_channels=19, out_channels=32, heads=4, concat=True) → ELU → Dropout(0.3)
  - Layer 2: GATConv(in_channels=128, out_channels=1, heads=1, concat=False) → Sigmoid
- **Loss:** MSE between predicted and actual 30-min forward return
- **Optimizer:** Adam, lr=1e-3, weight_decay=5e-4
- **Batch size:** 32 graphs (each graph = one 10-min snapshot)
- **Epochs:** 100 with early stopping (patience=10)

### Training Data Preparation
1. Load scanner CSVs from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\` for all available dates
2. Load corresponding 1-min bars from `D:\Data\Strategies\HVLF\MinuteBars_SB`
3. For each 10-min snapshot:
   a. Construct the co-occurrence graph (same process as Phase 3)
   b. Compute 19-element node features
   c. Label each node with actual 30-min forward return from minute bars
4. Filter out snapshots with < 20 nodes (too sparse for meaningful graph structure)
5. Split: 70% train, 15% validation, 15% test (by date, not random)

### Retraining Schedule
- **Weekly** on Sundays at 8 PM ET
- Include all new live trading data
- Train from scratch (graph structure changes too much for fine-tuning)
- Validate on most recent 5 trading days

### Acceptance Criteria
- Validation MSE < prior model's validation MSE
- Direction accuracy (predicted sign matches actual sign) >= 55%
- Rank correlation (Spearman) between predicted and actual returns >= 0.15
- If criteria not met, retain previous model and log warning

### Artifacts to Save
- `gnn_cooccurrence_gat.pt` — GAT model weights (state_dict)
- `gnn_node_encoder.pkl` — symbol-to-ID mapping for consistent encoding
- `gnn_training_report.json` — loss curves, accuracy, feature attention weights, graph statistics

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | **Master record** of each cron run with graph metrics | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every graph node scored by GAT (accepted & rejected) | Phase 4, 5 |
| `orders` | Every order with VWAP/ATR context | Phase 2, 5, 6 |
| `strategy_positions` | Position lifecycle with graph snapshot, centrality, predicted return | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price + VWAP + centrality history each cycle | Phase 6 |
| `strategy_runs` | Per-strategy summary with graph topology metrics | Phase 8 |
| `scan_runs` | Overall scan cycle summary with graph density | Phase 8 |
| `lessons` | Exit lessons with graph structure analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L, prediction accuracy, centrality correlation | Phase 2, 8 |

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_dates()` | Phase 3 — confirm today's data is available |
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect ALL scanner types for graph construction |
| `get_quote(symbol)` | Phase 3 (node features), Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, duration, bar_size)` | Phase 3 (volume ratio), Phase 5 (VWAP calc), Phase 6 (VWAP update) |
| `calculate_indicators(symbol, indicators, duration, bar_size, tail)` | Phase 2 (ATR for stops), Phase 5 (ATR for brackets), Phase 6 (ATR update) |
| `get_positions()` | Phase 1, Phase 5 — check current holdings |
| `get_portfolio_pnl()` | Phase 1, Phase 2 — P&L for risk management |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5 — prevent duplicates |
| `get_closed_trades(save_to_db=True)` | Phase 2 — reconcile trades closed by IB |
| `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` | Phase 2 (stop exits), Phase 5 (entries + brackets), Phase 6 (2 PM forced close) |
| `cancel_order(order_id)` | Phase 6 — cancel stops/targets before forced close |
| `modify_order(order_id, quantity, limit_price, stop_price)` | Phase 6 — update dynamic VWAP-based stops/targets |
| `get_strategy_positions(strategy_id, status, limit)` | Phase 2, Phase 5 — check strategy-specific positions |
| `get_strategy_kpis_report(strategy_id)` | Phase 8 — compute and review KPIs |
| `get_trading_lessons(limit)` | Phase 1 — load historical lessons |
| `get_scan_runs(limit)` | Phase 8 — log run summary |
| `get_job_executions(job_id, limit)` | Phase 1 — check for repeated failures |
| `get_position_price_history(position_id)` | Phase 6 — review price trajectory |
| `get_contract_details(symbol)` | Phase 5 — verify tradability and contract type |
