---
noteId: "s36_contrastive_fingerprint_01"
tags: [strategy, cron, ml, contrastive-learning, simclr, embedding, nearest-neighbor, fingerprint]

---

# Strategy 36: Contrastive Learning — Scanner Fingerprints — Operating Instructions

## Schedule

Runs twice daily during market hours via Claude Code CronCreate:
- **Run 1 (Primary):** 10:00 AM ET — initial fingerprint matching after 30 min of scanner data
- **Run 2 (Re-match):** 11:15 AM ET — re-match with updated scanner data, adjust positions if fingerprint changes
- **Monitoring runs:** Every 10 minutes from 11:15 AM – 3:40 PM for position management (Phases 2, 6, 7 only)
Max 3 concurrent positions.

## Data Sources

- Scanner CSVs: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`
- Historical scanner archives: `\\Station001\DATA\hvlf\rotating\` (all available dates for embedding space)
- Bar data: `D:\Data\Strategies\HVLF\MinuteBars_SB`
- Model artifacts: `D:\src\ai\mcp\ib\models\contrastive\simclr_scanner.pt` (encoder weights), `D:\src\ai\mcp\ib\models\contrastive\embedding_index.pkl` (pre-computed historical embeddings)
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- Database: `D:\src\ai\mcp\ib\trading.db`

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

Every run MUST be recorded in the `job_executions` table.

1. Call `start_job_execution(job_id="strategy_36_contrastive_fp")` — returns `exec_id`
2. After each phase completes, call `update_job_execution(exec_id, ...)` with:
   - `phase_completed`: current phase number (1–8)
   - Operation counts per standard schema
   - Model-specific: `nearest_neighbor_date`, `cosine_similarity`, `historical_outcome`, `embedding_norm`
3. On successful completion, call `complete_job_execution(exec_id, summary)`
4. On error, call `fail_job_execution(exec_id, error_message)`

---

## PHASE 1: Pre-Trade Checklist

1. **Load all lessons** from `data/lessons/` — focus on pattern-matching lessons (false analogs, regime changes)
2. **Load strategy files** — this strategy (S36) plus S04 (cut losers), S07 (conflict filter)
3. **Check current positions** via `get_positions()` and `get_portfolio_pnl()`
4. **Check open orders** via `get_open_orders()`
5. **Count open S36 positions** via `get_strategy_positions(strategy_id="contrastive_fingerprint", status="open")` — enforce max 3 concurrent
6. **Verify IB connection** — if `get_positions()` fails, call `fail_job_execution(exec_id, "IB disconnected")` and abort
7. **Verify model artifacts:**
   - `simclr_scanner.pt` — encoder must exist and be trained within last 14 days
   - `embedding_index.pkl` — pre-computed embeddings for historical days, must contain >= 30 days
8. **Determine run type:** Is this the 10:00 AM primary run, the 11:15 AM re-match, or a monitoring-only run?
9. Call `update_job_execution(exec_id, phase_completed=1, positions_checked=N, portfolio_pnl=X, portfolio_pnl_pct=Y)`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY, runs EVERY cycle)

1. Call `get_portfolio_pnl()` for current P&L
2. For each S36 position with `pnl_pct <= -5.0%` (strategy stop — wider because this is a longer-duration strategy):
   a. Check `get_open_orders()` — skip if SELL order exists
   b. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")`
   c. Log to `orders` with `strategy_id = "contrastive_fingerprint"`
   d. Close in `strategy_positions` with `exit_reason = "stop_loss_5pct"`
   e. Log to `lessons`: nearest neighbor date, cosine similarity at entry, what the historical analog did vs what this stock did
3. **Reconcile closed trades:**
   a. Call `get_closed_trades(save_to_db=True)`
   b. Cross-check DB positions against IB positions
   c. Close orphaned DB positions
4. Call `update_job_execution(exec_id, phase_completed=2, losers_closed=N, lessons_logged=N)`

---

## PHASE 3: Data Collection & Feature Engineering

**This phase runs fully only at 10:00 AM and 11:15 AM runs. Skip during monitoring-only runs.**

### Step 1: Build Today's Scanner Snapshot

Construct a comprehensive snapshot of today's scanner state:

1. For each of the 11 scanner types, call `get_scanner_results(scanner=type, date="today", top_n=30)` across all cap tiers
2. Build the **daily scanner snapshot matrix**:

```
Snapshot structure (per cap tier):
- Rows: 11 scanner types
- Columns: top-30 symbols per scanner
- Cell value: normalized rank (1/rank for present symbols, 0 for absent)
- Additional: binary presence matrix (11 scanners × all unique symbols today)
```

3. Aggregate across cap tiers into a unified snapshot

### Step 2: Scanner Snapshot → Feature Vector

Flatten the snapshot into a fixed-length feature vector for the SimCLR encoder:

| Feature Block | Dimension | Content |
|---------------|-----------|---------|
| Scanner pair co-occurrence | 55 | For each of C(11,2)=55 scanner pairs, count of symbols appearing on both |
| Scanner density | 11 | Number of unique symbols on each scanner |
| Top-symbol overlap | 11 | For each scanner, fraction of top-10 symbols also appearing on HotByVolume |
| Rank distribution stats | 33 | Mean, std, skew of ranks per scanner (3 × 11) |
| Time features | 2 | Minutes since open, day of week |
| Market breadth | 3 | Gainers/losers ratio, avg gain %, avg volume ratio |

**Total feature vector dimension: 115** (projected to 64-dim embedding by SimCLR encoder)

### Step 3: Identify Today's Top-3 Gainers

From the GainSinceOpen and TopGainers scanners:
1. Merge and deduplicate symbols across cap tiers
2. Call `get_quote(symbol)` for each to get current price and change
3. Rank by intraday gain percentage
4. Select top 3 — these are the candidates if the historical analog is bullish

Call `update_job_execution(exec_id, phase_completed=3, candidates_found=N)`

---

## PHASE 4: Model Inference / Signal Generation

### SimCLR Encoder Architecture (Reference)

```
Architecture:
- Input: 115-dim feature vector (daily scanner snapshot)
- Encoder: FC(115, 128) → BatchNorm → ReLU → FC(128, 64) → L2-normalize
- Output: 64-dim unit-norm embedding vector
- Projection head (training only): FC(64, 32) → ReLU → FC(32, 32)
- Contrastive loss: NT-Xent (normalized temperature-scaled cross-entropy) with τ=0.5

Training augmentations (positive pairs = augmented versions of same day):
- Gaussian noise injection (σ=0.05) to rank values
- Random scanner dropout (mask 1 random scanner to 0)
- Time jitter (±15 min to snapshot time)
```

### Step 1: Encode Today's Snapshot

1. Pass today's 115-dim feature vector through the SimCLR encoder
2. Obtain: `today_embedding` — a 64-dim unit-norm vector
3. Compute `embedding_norm` — should be ~1.0 (L2 normalized); flag if deviates >0.1

### Step 2: Nearest Neighbor Search

1. Load `embedding_index.pkl` — contains {date: 64-dim embedding} for all historical days
2. Compute cosine similarity between `today_embedding` and every historical embedding:
   ```
   cosine_sim(a, b) = dot(a, b) / (||a|| × ||b||)
   ```
3. Find the **top-1 nearest neighbor** (most similar historical day)
4. Record:
   - `nearest_date`: the historical date
   - `cosine_similarity`: similarity score (0.0–1.0)
   - `second_nearest_date` and `second_cosine_similarity`: for robustness check

### Step 3: Similarity Gate

**If cosine similarity < 0.5 → SKIP today entirely.** The scanner fingerprint is too novel; no reliable historical analog exists.

Log to `scanner_picks`: rejected=1, reject_reason="cosine_similarity_below_threshold", cosine_similarity, nearest_date

### Step 4: Historical Outcome Lookup

If similarity >= 0.5, look up what happened on the nearest historical day:

1. Call `get_scanner_results(scanner="GainSinceOpen", date=nearest_date, top_n=10)` — get that day's top-3 gainers at the equivalent time (10:00 AM or 11:15 AM)
2. Call `get_historical_bars(symbol, duration="1 D", bar_size="1 min")` for each of those top-3 gainers on nearest_date
3. Measure: **did those top-3 gainers continue up from the 10:00 AM snapshot to EOD?**
   - Calculate: (close_price - price_at_10am) / price_at_10am for each
   - `avg_continuation_return` = mean of the 3 returns

### Step 5: Decision

| Historical Outcome | Action | Rationale |
|-------------------|--------|-----------|
| avg_continuation_return > +1.0% | **BUY today's top-3 gainers** | Historical analog shows continuation |
| avg_continuation_return between -1.0% and +1.0% | **SKIP** | Ambiguous — not enough edge |
| avg_continuation_return < -1.0% | **SKIP** (or SHORT if enabled) | Historical analog shows reversal — today's gainers likely to fade |

### Step 6: Re-match at 11:15 AM

At the 11:15 AM run:
1. Rebuild the scanner snapshot with updated data
2. Re-encode and find nearest neighbor again
3. If the nearest neighbor **changes** from the 10:00 AM match:
   - If new analog is bearish and positions are open → tighten stops to 2%
   - If new analog is bullish and no positions → enter as normal
   - Log the shift as a lesson: "Fingerprint re-match shifted from {old_date} (sim={old_sim}) to {new_date} (sim={new_sim}). Outcome changed from {old_outcome} to {new_outcome}."
4. If the nearest neighbor is the **same** → increase confidence, widen stop to 6%

Call `update_job_execution(exec_id, phase_completed=4, candidates_found=N, candidates_rejected=N, nearest_neighbor_date=DATE, cosine_similarity=SIM, historical_outcome=RETURN)`

---

## PHASE 5: Quality Gate & Order Execution

**This phase runs only when Phase 4 decision is BUY.**

### Quality Gate — Pre-Order Checks (MANDATORY)

For each of today's top-3 gainer candidates:

1. **Minimum price:** `get_quote(symbol)` → last >= $2.00
2. **Minimum volume:** Avg daily volume >= 50,000
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject symbols ending in R, W, WS, U
5. **Contract validation:** `get_contract_details(symbol)` — must be common stock
6. **Position limit:** Open S36 positions < 3
7. **No duplicate:** Symbol not in `get_positions()` or `get_open_orders()`
8. **Cosine similarity:** Must be >= 0.5 (double-check from Phase 4)
9. **Loser scanner check:** Symbol must NOT appear on LossSinceOpen or TopLosers

If a candidate fails quality gate, move to the next-ranked gainer (4th, 5th, etc.) until 3 valid candidates are found or candidates are exhausted.

### Position Sizing

- **Size:** 1% of account value per position (3 positions = 3% total exposure)
- Calculate shares: `floor(account_value * 0.01 / ask_price)`

### Order Placement

For each approved candidate (up to 3):

1. **Entry order:** `place_order(symbol, action="BUY", quantity=shares, order_type="MKT")`
2. **Stop loss:** `place_order(symbol, action="SELL", quantity=shares, order_type="STP", stop_price=round(ask * 0.95, 2))` — 5% stop (wider for pattern-based strategy)
3. **Target:** Based on historical analog's continuation return:
   - `target_price = round(ask * (1 + avg_continuation_return), 2)`
   - Minimum target: +2%, maximum target: +8%
   - `place_order(symbol, action="SELL", quantity=shares, order_type="LMT", limit_price=target_price)`

### Database Logging (MANDATORY)

1. **`scanner_picks`**: symbol, scanner="GainSinceOpen", rank, action="BUY", rejected=0, metadata={nearest_date, cosine_similarity, historical_top3, avg_continuation_return, today_embedding_hash}
2. **`orders`**: symbol, action="BUY", quantity, order_type, order_id, strategy_id="contrastive_fingerprint"
3. **`strategy_positions`**: strategy_id="contrastive_fingerprint", symbol, action="BUY", quantity, entry_price, stop_price, target_price, metadata={nearest_date, cosine_similarity, historical_continuation_return, second_nearest_date, second_cosine_similarity, match_time ("10:00" or "11:15")}

### Post-Order Protection Check (MANDATORY)
After placing ANY entry order, immediately place a protective GTC STP SELL order:
- Default stop: 5% below entry price (or ATR-based if available)
- This ensures NO position ever exists without a stop order
- Log stop order to `orders` table with `strategy_id = "profit_protection"`

Call `update_job_execution(exec_id, phase_completed=5, orders_placed=N)`

---

## PHASE 6: Position Monitoring

For each open S36 position every monitoring cycle (every 10 min):

1. **Price snapshot:** `get_quote(symbol)` → log to `price_snapshots` (bid, ask, last, volume, unrealized P&L)
2. **Scanner persistence check:**
   - If symbol drops off GainSinceOpen AND TopGainers → the continuation thesis weakens
   - If symbol appears on LossSinceOpen → flag for immediate exit
3. **Historical analog tracking:**
   - Compare current intraday trajectory to the historical analog's trajectory at the same time of day
   - If divergence > 2% from expected trajectory → log warning, consider tightening stop
4. **Update position extremes:** peak, trough, MFE, MAE
5. **Post 11:15 AM re-match adjustments:**
   - If re-match at 11:15 AM changed the nearest neighbor to a bearish analog → tighten stop to 2% for all open S36 positions
   - If re-match confirmed the same nearest neighbor → maintain original stop

### Profit Protection — Trailing Stop Ratchet (MANDATORY, every cycle)
**Lesson: AGAE 2026-04-15 lost +26% gain, exited at -7%. This check runs EVERY cycle for EVERY open position.**

For each position, compute `unrealized_pnl_pct` from entry price, then apply:

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +10% to +20% | Breakeven (entry price) |
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

### Exit Triggers (in priority order)

| Trigger | Action | Exit Reason |
|---------|--------|-------------|
| Symbol appears on LossSinceOpen/TopLosers | Immediate MKT SELL | `thesis_broken_loser` |
| P&L <= -5.0% (stop hit) | Automatic (STP fills) | `stop_loss_5pct` |
| Target price hit (historical analog return) | Automatic (LMT fills) | `take_profit_analog` |
| Re-match shows bearish analog AND P&L < 0 | MKT SELL | `analog_shift_bearish` |
| End of day (3:45 PM) | MKT SELL | `eod_close` |

### For Each Exit

1. Call `place_order(symbol, action="SELL", quantity=shares, order_type="MKT")` if not already filled
2. Cancel remaining open orders via `cancel_order(order_id)`
3. Close position in `strategy_positions`: exit_price, exit_reason, pnl, pnl_pct, hold_duration_minutes
4. Log to `lessons` table with contrastive-specific analysis:
   - Nearest neighbor date and cosine similarity
   - Historical analog outcome vs actual outcome today
   - Whether the analogy held (did today's trajectory match the historical one?)
   - Embedding distance evolution throughout the day
   - Lesson text examples:
     - "Fingerprint matched {nearest_date} (cos_sim={sim:.3f}). Historical top-3 continued +{hist_return}%. Today's top-3 {symbol} returned {pnl_pct}%. Analogy {'held' if same_sign else 'failed'}."
     - "Re-match at 11:15 shifted from {old_date} to {new_date}. Adjusted stop saved {saved_pct}% on {symbol}."
     - "Cosine similarity {sim:.3f} was too low for reliable matching. Consider raising threshold from 0.5 to 0.6."
     - "Nearest neighbor was {days_ago} trading days ago. More recent analogs tend to be more reliable — consider weighting by recency."
5. **Analog accuracy tracking:** Record whether the historical analog correctly predicted today's direction
   - Feeds into retraining: if analog accuracy < 50% over last 20 trades, trigger model retraining
6. Compute KPIs via `get_strategy_kpis_report(strategy_id="contrastive_fingerprint")`

Call `update_job_execution(exec_id, phase_completed=7, lessons_logged=N, kpis_computed=N)`

---

## PHASE 8: Run Summary & KPIs

1. Log `scan_runs`: scanner snapshot built, fingerprint computed, nearest_neighbor found/rejected, orders placed, positions held
2. Log `strategy_runs` for strategy_id="contrastive_fingerprint" with:
   - Today's nearest neighbor date and cosine similarity
   - Historical analog outcome vs actual outcome
   - Re-match result (same neighbor or shifted?)
   - Embedding novelty: how far is today from the nearest neighbor compared to historical average distance
3. Compute `strategy_kpis` via `get_strategy_kpis_report(strategy_id="contrastive_fingerprint")`:
   - Win rate (target: >50%)
   - Analog accuracy: % of times the historical analog correctly predicted direction
   - Avg cosine similarity at entry — track drift over time
   - Return by similarity bucket: high (>0.8), medium (0.5–0.8)
   - Return by analog recency: how recent was the nearest neighbor?
   - Skip rate: % of days where cosine similarity < 0.5 (no trade)
   - Re-match shift rate: how often does the 11:15 re-match change the analog?
4. Call `complete_job_execution(exec_id, summary)` with:
   - Fingerprint match details
   - Positions entered/exited
   - Current open S36 positions and unrealized P&L
   - Analog accuracy running average

---

## Model Training / Retraining Schedule

### SimCLR Encoder Training

| Parameter | Value |
|-----------|-------|
| Retrain frequency | Bi-weekly (Sunday) |
| Training data | All available historical scanner snapshots (minimum 40 trading days) |
| Augmentation | Gaussian noise (σ=0.05), random scanner dropout (1 of 11), time jitter (±15 min) |
| Positive pairs | Two augmented versions of the same day's snapshot |
| Negative pairs | All other days in the batch |
| Batch size | 32 days |
| Temperature τ | 0.5 |
| Optimizer | AdamW, lr=3e-4, weight_decay=1e-4 |
| Epochs | 200, early stopping on contrastive loss (patience=30) |
| Embedding dimension | 64 |

### Embedding Index Rebuild

After retraining the encoder:
1. Re-encode all historical days through the new encoder
2. Save updated `embedding_index.pkl` with {date: 64-dim embedding} for all days
3. Verify: nearest-neighbor distances should be well-distributed (not all clustered or all far apart)
4. Log embedding space statistics: avg pairwise distance, number of clusters (DBSCAN), outlier days

### Quality Checks After Retraining

1. **Alignment test:** Known similar days (e.g., two FOMC days) should have high cosine similarity
2. **Separation test:** Known different days (e.g., crash day vs rally day) should have low similarity
3. **Stability test:** Nearest neighbors should not change dramatically vs previous model (>30% change = flag for review)
4. **Backtesting:** Run the full strategy on the last 20 trading days with the new model
   - Compare win rate, analog accuracy, and skip rate to the previous model
   - Only deploy if new model performance >= previous - 5%

### Shadow Mode After Retraining

1. Run new model in parallel with live model for 5 trading days
2. Log both models' nearest neighbors and decisions
3. Promote new model if its analog accuracy >= live model's accuracy

---

## Database Tables Used

| Table | Purpose | When Logged |
|-------|---------|-------------|
| `job_executions` | Master record of each run (2 full + N monitoring) | Phase 0 (start), every phase (update), Phase 8 (complete) |
| `scanner_picks` | Today's top-3 gainers + analog decision (accepted & rejected) | Phase 4, 5 |
| `orders` | Every entry/exit order | Phase 2, 5, 7 |
| `strategy_positions` | Position lifecycle + contrastive metadata | Phase 5, 6, 7 |
| `price_snapshots` | Price history per position per monitoring cycle | Phase 6 |
| `strategy_runs` | Per-run summary with fingerprint details | Phase 8 |
| `scan_runs` | Overall scan cycle summary | Phase 8 |
| `lessons` | Exit lessons with analog accuracy analysis | Phase 2, 7 |
| `strategy_kpis` | Win rate, analog accuracy, similarity distribution | Phase 7, 8 |

---

## MCP Tools Used

| Tool | Phase | Purpose |
|------|-------|---------|
| `get_scanner_results` | 3, 4, 6 | Build scanner snapshot, check top gainers, monitor persistence |
| `get_scanner_dates` | 1, 4 | Verify data availability, find historical dates |
| `get_quote` | 3, 5, 6, 7 | Current price for candidates, execution, monitoring |
| `get_historical_bars` | 3, 4 | Volume data, historical analog price trajectories |
| `calculate_indicators` | 3 | Supplementary features (RSI, VWAP) if needed |
| `get_news_headlines` | 4 | Check if analog day had a similar catalyst (optional enrichment) |
| `get_contract_details` | 5 | Validate security type |
| `get_positions` | 1, 5 | Current portfolio positions |
| `get_portfolio_pnl` | 1, 2 | P&L for stop-loss enforcement |
| `get_open_orders` | 1, 2, 5 | Duplicate/existing order check |
| `get_closed_trades` | 2 | Reconcile IB executions with DB |
| `place_order` | 2, 5, 7 | Entry, stop, target, and exit orders |
| `cancel_order` | 7 | Cancel remaining orders after exit |
| `get_strategy_positions` | 1, 2 | Count open S36 positions, enforce max 3 |
| `get_strategy_kpis_report` | 7, 8 | Compute and review strategy KPIs |
| `get_trading_picks` | 1 | Review recent picks for dedup |
| `get_trading_lessons` | 1 | Load lessons for rule application |
| `get_scan_runs` | 8 | Log scan cycle summary |
| `get_job_executions` | 0 | Track job execution lifecycle |
| `get_daily_kpis` | 8 | Daily aggregate performance |
| `get_position_price_history` | 6 | Review price trajectory for analog comparison |
