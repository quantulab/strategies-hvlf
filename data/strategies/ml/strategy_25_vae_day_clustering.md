---
noteId: "a4c25e0038d711f1aa17e506bb81f996"
tags: [cron, trading, strategy, ml, vae, autoencoder, clustering, regime-detection]

---

# Strategy 25: Autoencoder (VAE) Latent Space Clustering — Operating Instructions

## Schedule

Runs at **3 fixed times** during market hours via Claude Code CronCreate:
- **10:15 AM ET** — Initial classification and cluster strategy execution
- **11:15 AM ET** — Reassessment: re-classify, adjust positions if cluster changed
- **2:00 PM ET** — Final check, begin winding down positions

All positions must be closed by 3:45 PM ET.

## Data Sources

- **Scanner CSVs:** `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- **Scanner Types (11):** GainSinceOpen, HighOpenGap, HotByPrice, HotByPriceRange, HotByVolume, LossSinceOpen, LowOpenGap, MostActive, TopGainers, TopLosers, TopVolumeRate
- **Cap Tiers (3):** LargeCap, MidCap, SmallCap → **33 total scanner feeds** (11 types × 3 tiers)
- **Bar Data:** `D:\Data\Strategies\HVLF\MinuteBars_SB`
- **Database:** `D:\src\ai\mcp\ib\trading.db`
- **Lessons:** `D:\src\ai\mcp\ib\data\lessons\`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_25_vae_cluster")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (0–8)
   - Operation counts: `positions_checked`, `losers_closed`, `shorts_closed`, `candidates_found`, `candidates_rejected`, `orders_placed`, `positions_monitored`, `snapshots_logged`, `lessons_logged`, `kpis_computed`
   - Additional: `cluster_id`, `cluster_name`, `cluster_confidence`
   - Portfolio state: `portfolio_pnl`, `portfolio_pnl_pct`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — apply rules learned
2. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
   - Identify all positions tagged `strategy_id` starting with `"vae_cluster_"` (each sub-strategy has its own ID)
3. **Check open orders** via `get_open_orders()`
4. **Verify IB connection** — if disconnected, call `fail_job_execution(exec_id, "IB gateway disconnected")` and abort
5. **Time validation:**
   - 10:15 AM run: proceed with full execution
   - 11:15 AM run: proceed with reassessment (PHASE 4 re-classification)
   - 2:00 PM run: monitoring and wind-down only — no new entries
   - Any other time: abort with `fail_job_execution(exec_id, "Outside scheduled run times")`
6. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management

Before any new trades, enforce risk rules on ALL strategy_25 positions.

1. Call `get_portfolio_pnl()` for current P&L
2. For each position with `strategy_id` starting with `"vae_cluster_"`:
   a. **Sub-strategy-specific stop** (see cluster definitions in PHASE 4):
      - Cluster 0 (Tech Momentum): -4% stop
      - Cluster 1 (Broad Rotation): -3% stop
      - Cluster 2 (SmallCap Speculative): -6% stop
      - Cluster 3 (Low-Activity): -2% stop
   b. If P&L breaches the cluster-specific stop:
      - Check `get_open_orders()` — skip if SELL order already exists
      - Call `place_order(symbol, action="SELL", quantity=position_qty, order_type="MKT")`
      - Close in `strategy_positions` with `exit_reason = "stop_loss_cluster_N"`
      - Log to `orders`, `lessons`
3. **EOD wind-down:** If current time >= 3:30 PM ET:
   - Close ALL remaining strategy_25 positions at market
   - Cancel all associated stop/target orders
   - Log with `exit_reason = "eod_close"`
4. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. For every externally closed position, log to all tables
5. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, shorts_closed=0, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

### 3.1 — Collect Scanner State Vector

Build the daily scanner state vector from 3 snapshots:
- **Snapshot 1:** 9:45 AM scanner data (15 min after open)
- **Snapshot 2:** 10:00 AM scanner data (30 min after open)
- **Snapshot 3:** 10:15 AM scanner data (45 min after open — current)

For the 11:15 AM reassessment, use:
- **Snapshot 1:** 10:15 AM
- **Snapshot 2:** 10:45 AM
- **Snapshot 3:** 11:15 AM

For each snapshot, for each of the 33 scanner feeds (11 types × 3 tiers):
1. Call `get_scanner_results(scanner=SCANNER_TYPE, date="YYYYMMDD", top_n=10)` for each tier
2. Extract the top-10 symbols and their ranks
3. Encode as a 10-dimensional vector: `[rank_1/10, rank_2/10, ..., rank_10/10]` where `rank_i/10` is the normalized rank of the i-th symbol (1.0 = rank 1, 0.1 = rank 10)

### 3.2 — Flatten to Feature Vector

- 33 scanner feeds × 3 snapshots × 10 symbols = **990 dimensions**
- Feature vector shape: `(990,)` — one per day
- Missing scanners (no data): fill with zeros
- Normalize: z-score across the historical distribution of each feature

### 3.3 — Supplementary Market Context

Additionally collect:
- SPY price change since open via `get_quote("SPY")` — overall market direction
- VIX level via `get_quote("VIX")` — volatility regime
- Sector ETF changes (XLK, XLF, XLE, XLV) via `get_quote()` — sector rotation signals
- Total unique symbols across all scanners — market breadth proxy

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### 4.1 — VAE Encoding

1. Load the VAE model from `D:\src\ai\mcp\ib\models\vae_scanner_state.pt`
   - Architecture: Encoder: 990 → 256 → 64 → 16 (mu + log_var). Decoder: 16 → 64 → 256 → 990. Beta-VAE with beta=0.5
   - Input: 990-dim feature vector
   - Output: 16-dim latent representation `z`
2. Run encoder forward pass: `z = encoder(feature_vector)` — use the mean (mu), not a sample

### 4.2 — K-Means Cluster Assignment

1. Load pre-trained K-Means model (K=4) from `D:\src\ai\mcp\ib\models\kmeans_scanner_clusters.pkl`
2. Assign today's latent vector to the nearest cluster: `cluster_id = kmeans.predict(z)`
3. Compute distance to cluster centroid: `cluster_distance = ||z - centroid[cluster_id]||`
4. Compute confidence: `cluster_confidence = 1 - (cluster_distance / max_historical_distance)` — higher is better

### 4.3 — Cluster Definitions & Sub-Strategies

| Cluster ID | Name | Characteristics | Sub-Strategy ID | Entry Logic |
|------------|------|----------------|-----------------|-------------|
| 0 | **Tech Momentum** | LargeCap GainSinceOpen and HotByVolume dominated by tech names. High TopGainers activity in LargeCap | `vae_cluster_tech_momentum` | Buy top-3 on LargeCap GainSinceOpen with rank improving over 3 snapshots. 2% account per position, max 3 positions. 4% stop, 5% target |
| 1 | **Broad Rotation** | Even distribution across cap tiers and scanner types. No single sector dominance. MostActive elevated across all tiers | `vae_cluster_broad_rotation` | Buy top-1 from each cap tier on TopGainers (3 positions total). 1.5% account per position. 3% stop, 4% target. Diversification play |
| 2 | **SmallCap Speculative** | SmallCap scanners dominate. High activity on HotByPrice, HotByPriceRange. HighOpenGap elevated for SmallCap | `vae_cluster_smallcap_spec` | Buy top-2 on SmallCap HotByVolume with confirmation on GainSinceOpen. 1% account per position (smaller due to higher risk), max 2 positions. 6% stop, 8% target |
| 3 | **Low-Activity** | Few symbols across all scanners. Low TopVolumeRate. Market is quiet or pre-event | `vae_cluster_low_activity` | **Do NOT trade.** Log classification and wait. If reassessment at 11:15 AM shows cluster change, execute that cluster's strategy. If still low-activity, stay flat. |

### 4.4 — 11:15 AM Reassessment Logic

If this is the 11:15 AM run:
1. Re-encode the updated scanner state (new 3 snapshots)
2. Re-classify into cluster
3. **If cluster changed from 10:15 AM classification:**
   - Close all positions from the previous cluster's sub-strategy
   - Execute the new cluster's sub-strategy
   - Log cluster transition to `lessons` table: "Cluster changed from {old} to {new} at 11:15 AM"
4. **If cluster is the same:** Continue monitoring existing positions

### 4.5 — Candidate Selection per Cluster

For the active cluster's sub-strategy:

1. Call `get_scanner_results()` for the relevant scanners (per cluster table above)
2. Identify candidates meeting the cluster-specific entry logic
3. Score candidates:
   - +3 if rank improved over 3 consecutive snapshots
   - +2 if on 2+ scanner types simultaneously
   - +1 if volume rank in top-5
   - -2 if on any loss scanner
   - -1 if cluster_confidence < 0.5

**Minimum score for entry: 3**

Log all candidates to `scanner_picks` with cluster_id, cluster_name, cluster_confidence, sub_strategy_id

Call `update_job_execution(exec_id, phase_completed=4, cluster_id=N, cluster_name=NAME, cluster_confidence=X, candidates_found=N, candidates_rejected=N)`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate — Pre-Order Checks (MANDATORY)

Before placing ANY order, verify via `get_quote(symbol)`:

1. **Minimum price:** `last >= $2.00`
2. **Minimum volume:** Average daily volume >= 50,000 shares
3. **Maximum spread:** `(ask - bid) / last <= 3%`
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Cluster 3 check:** If today's cluster = Low-Activity (ID 3), place NO orders. Log and exit.
6. **Cluster confidence check:** If `cluster_confidence < 0.3`, reduce position sizes by 50% (uncertain classification)

Log rejection reason to `scanner_picks` if any check fails.

### Position Sizing (per cluster)

| Cluster | Size per Position | Max Positions | Stop | Target |
|---------|------------------|---------------|------|--------|
| 0 — Tech Momentum | 2% of account | 3 | -4% | +5% |
| 1 — Broad Rotation | 1.5% of account | 3 (one per tier) | -3% | +4% |
| 2 — SmallCap Speculative | 1% of account | 2 | -6% | +8% |
| 3 — Low-Activity | 0% (no trades) | 0 | N/A | N/A |

If `cluster_confidence < 0.3`, halve the size values above.

### Order Placement

For each accepted candidate:

1. Call `place_order(symbol=SYMBOL, action="BUY", quantity=SHARES, order_type="MKT")`
2. Place bracket orders per cluster stop/target table above:
   - **Stop Loss:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="STP", stop_price=round(entry_price * (1 - stop_pct), 2))`
   - **Take Profit:** `place_order(symbol=SYMBOL, action="SELL", quantity=SHARES, order_type="LMT", limit_price=round(entry_price * (1 + target_pct), 2))`
3. Log to database:
   - `scanner_picks`: symbol, scanner, rank, conviction_score, cluster_id, cluster_name, cluster_confidence, sub_strategy_id, action="BUY", rejected=0
   - `orders`: symbol, strategy_id=sub_strategy_id, action="BUY", quantity, order_type, order_id, entry_price, status
   - `strategy_positions`: strategy_id=sub_strategy_id, symbol, action="BUY", quantity, entry_price, stop_price, target_price, cluster_id, cluster_confidence, entry_order_id, stop_order_id, target_order_id

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open position with `strategy_id` starting with `"vae_cluster_"`:

1. **Price snapshot:** Call `get_quote(symbol)` — log to `price_snapshots`: bid, ask, last, volume, unrealized_pnl, pnl_pct, cluster_id
2. **Cluster drift detection:** At the 11:15 AM run, compare current cluster to 10:15 AM cluster. If changed, trigger reassessment (handled in PHASE 4.4)
3. **Scanner persistence:** Check if entry scanners still show the symbol. If dropped off all relevant scanners, flag for early exit consideration
4. **EOD exit:** If current time >= 3:45 PM ET:
   - Close ALL remaining positions at market
   - Cancel all stop/target orders via `cancel_order(order_id)`
   - Close in `strategy_positions` with `exit_reason = "eod_close_345pm"`
5. Update position extremes: peak, trough, MFE, MAE, drawdown

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

On every exit (stop hit, target hit, cluster change, EOD, or manual):

1. Close position in `strategy_positions`:
   - `exit_price`, `exit_time`, `exit_reason`, `pnl`, `pnl_pct`, `hold_duration_minutes`
   - `cluster_id`, `cluster_name`, `cluster_confidence` at entry
2. Log to `lessons` table:
   - symbol, strategy_id=sub_strategy_id, action="BUY", entry_price, exit_price
   - pnl, pnl_pct, hold_duration_minutes
   - max_drawdown_pct, max_favorable_excursion
   - cluster_id, cluster_name, cluster_confidence
   - Did cluster change during hold? (cluster_transition flag)
   - exit_reason
   - lesson text: e.g., "Day classified as Tech Momentum (cluster 0, confidence 0.82). Entered NVDA at $145, exited at +5% target. LargeCap GainSinceOpen rank held top-3 for 4 consecutive snapshots. VAE correctly identified tech-driven momentum regime."
3. Compute and log KPIs via `get_strategy_kpis_report(strategy_id=sub_strategy_id)`
4. Write a lesson file for cluster transitions (rare, high-value learning)

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

At the end of each run:

1. Log `scan_runs`: strategy_id="vae_cluster", cluster_id, cluster_name, cluster_confidence, scanner_features_collected=990, candidates_found, candidates_rejected, orders_placed, positions_held, summary
2. Log `strategy_runs` for each active sub-strategy
3. Compute `strategy_kpis` if any positions were closed:
   - Win rate, avg win %, avg loss % per cluster
   - **Cluster-specific metrics:**
     - Cluster classification accuracy: % of days where the cluster label matched the actual market behavior (evaluated in hindsight)
     - Cluster stability: % of days where 10:15 AM and 11:15 AM classifications matched
     - Per-cluster P&L: separate win rate and expectancy for each of the 4 clusters
     - Reconstruction error: VAE loss on today's input — high error may indicate novel market regime
4. Call `complete_job_execution(exec_id, summary)` with full summary including cluster assignment and sub-strategy performance

---

## Model Training / Retraining Schedule

| Task | Frequency | Details |
|------|-----------|---------|
| **Data collection** | Daily | Store the 990-dim feature vector and cluster assignment for each day |
| **VAE retraining** | Bi-weekly | Train on last 120 days of daily feature vectors. Adam optimizer, lr=5e-4, batch_size=32, max 500 epochs. Monitor ELBO (reconstruction + KL). Early stopping on val ELBO, patience=20 |
| **K-Means re-fit** | Bi-weekly (after VAE retrain) | Re-run K-Means (K=4) on the new 16-dim latent representations. Verify cluster separation via silhouette score (target > 0.4) |
| **Cluster label audit** | Monthly | Manually review cluster assignments for last 30 days. Verify that cluster names (Tech Momentum, Broad Rotation, SmallCap Speculative, Low-Activity) still match the actual market behavior in each cluster. Relabel if needed |
| **K selection review** | Quarterly | Test K=3,4,5,6 via silhouette score and calinski-harabasz index. Adjust K if a different value produces better-separated clusters |
| **Full backtest** | Monthly | Simulate strategy on last 90 days with updated models. Compare live vs. backtest P&L |

**Model artifacts:**
- VAE: `D:\src\ai\mcp\ib\models\vae_scanner_state.pt`
- K-Means: `D:\src\ai\mcp\ib\models\kmeans_scanner_clusters.pkl`
- Training logs: `D:\src\ai\mcp\ib\models\training_logs\strategy_25\`

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each run with cluster assignment | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Every candidate with cluster_id, cluster_confidence | Phase 4, 5 |
| `orders` | Every order placed per sub-strategy | Phase 2, 5 |
| `strategy_positions` | Position lifecycle with cluster metadata | Phase 2, 5, 6, 7 |
| `price_snapshots` | Price/P&L history each cycle | Phase 6 |
| `strategy_runs` | Per-sub-strategy summary each run | Phase 8 |
| `scan_runs` | Overall run summary with cluster classification | Phase 8 |
| `lessons` | Exit lessons with cluster analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, P&L per cluster, cluster stability metrics | Phase 7, 8 |

---

## MCP Tools Used

- `get_scanner_results(scanner, date, top_n)` — collect scanner data for all 33 feeds (11 types × 3 tiers) at 3 snapshot times
- `get_scanner_dates()` — verify available data
- `get_quote(symbol)` — quality gate, monitoring, SPY/VIX/sector ETF context
- `get_historical_bars(symbol, duration, bar_size)` — supplementary price data
- `calculate_indicators(symbol, indicators, duration, bar_size, tail)` — optional technical overlays
- `get_positions()` — current portfolio state
- `get_portfolio_pnl()` — P&L for risk management
- `get_open_orders()` — prevent duplicate orders
- `get_closed_trades(save_to_db=True)` — reconcile externally closed trades
- `place_order(symbol, action, quantity, order_type, limit_price, stop_price)` — entry and exit orders
- `cancel_order(order_id)` — cancel stop/target on EOD or cluster-change exit
- `get_strategy_positions(strategy_id, status="open")` — position count per sub-strategy
- `get_strategy_kpis_report(strategy_id)` — KPI computation per sub-strategy
- `get_trading_lessons(limit=50)` — load historical lessons
- `get_scan_runs(limit=10)` — recent scan history
- `get_job_executions(job_id="strategy_25_vae_cluster", limit=5)` — execution history
- `get_daily_kpis()` — daily performance overview
- `get_position_price_history(position_id)` — full price trail
