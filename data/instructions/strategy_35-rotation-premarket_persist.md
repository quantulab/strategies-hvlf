---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, premarket-persistence, scanner-patterns]

---

# 35-Rotation-Pre-Market Persistence Filter — Operating Instructions

## Overview
Exploits the statistically dominant pattern that 95.7% of pre-market scanner movers persist into regular trading hours. By confirming pre-market momentum at 9:35 AM and filtering out known whipsaw names (the 4.3% that fade), this strategy captures validated morning momentum with high confidence.

**Data Backing (Report §7):** 95.7% overall persist rate across 15 measured days. Multiple days showed 99-100% persistence. Reliable persisters identified (SGOV 29 days, BMNR 26 days, SCHD 24 days, etc.).

## Schedule
- **Pre-market scan:** 9:25 AM ET — identify pre-market movers
- **Entry window:** 9:35 AM – 10:00 AM ET — confirm persistence and enter
- **Monitoring:** Every 10 minutes 10:00 AM – 11:30 AM ET — ride momentum
- **No new entries after 10:00 AM** — morning momentum window only

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`**

## Strategy ID
`rotation_premarket_persist`

---

## Known Reliable Pre-Market Persisters (from Report §7)

| Ticker | Days Persisted | Reliability |
|--------|---------------|-------------|
| SGOV | 29 | Very High |
| BMNR | 26 | Very High |
| SCHD | 24 | Very High |
| JOBY | 24 | Very High |
| EXK | 23 | High |
| DUST | 22 | High |
| CPNG | 20 | High |
| SOUN | 17 | High |
| PURR | 14 | Moderate |
| IREZ | 13 | Moderate |
| RIOT | 12 | Moderate |
| APPX | 12 | Moderate |
| PONY | 9 | Moderate |
| ORCX | 9 | Moderate |
| METU | 8 | Moderate |

### Daily Persistence Rates (sample)
```
100% days: 20260325, 20260331, 20260401, 20260406, 20260413 (5 of 15 days)
 99% days: 20260324, 20260330, 20260402, 20260409, 20260414 (5 of 15 days)
 95-98%:   20260403, 20260415, 20260416 (3 of 15 days)
 92%:      20260408 (worst day — high pre-market count)
```

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

1. Open `rotation_scanner.db` — ensure tables exist
2. INSERT into `job_executions` with `job_id="rotation_premarket_persist"` — capture `exec_id`
3. Track phases, update on completion/failure

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` AND `rotation_scanner.db` → `lessons` WHERE `sub_strategy="rotation_premarket_persist"`
2. **Check time window:**
   - Before 9:25 AM → too early, abort
   - After 10:00 AM → no new entries, skip to Phase 6
3. **Check positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count open: `strategy_positions` WHERE `sub_strategy="rotation_premarket_persist" AND status="open"`
   - Max 2 concurrent positions — if at limit, skip to Phase 6
4. **Check open orders** via `get_open_orders()`
5. **Verify IB connection**
6. **Load whipsaw watchlist** from `whipsaw_watchlist` table — mandatory filter
7. UPDATE `job_executions` with `phase_completed=1`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for P&L
2. Query `strategy_positions` WHERE `sub_strategy="rotation_premarket_persist" AND status="open"`
3. For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if SELL exists
   b. Place MKT SELL, log, close with `exit_reason="stop_loss_5pct"`
4. **VWAP stop check:** For each position, get current VWAP:
   - Call `calculate_indicators(symbol, indicators=["VWAP"], duration="1 D", bar_size="1 min", tail=1)`
   - If last price < VWAP → momentum failed, prepare exit with `exit_reason="below_vwap"`
5. **Scanner fade check:** If symbol dropped off ALL gain scanners since entry → prepare exit with `exit_reason="scanner_faded"`
6. **Time stop:** For positions held > 90 min → close with `exit_reason="time_stop_90min"`
7. **Reconcile closed trades** via `get_closed_trades(save_to_db=True)`
8. UPDATE `job_executions` with `phase_completed=2`

---

## PHASE 3: Pre-Market Signal Detection

### At 9:25 AM — Pre-Market Scan
1. Call `get_scanner_results` for ALL scanner types × cap tiers (top 50)
2. Identify symbols currently on ANY gain scanner (TopGainers, GainSinceOpen, HighOpenGap)
3. Store as `premarket_movers` set with scanner details and rank

### At 9:35 AM — Persistence Confirmation
1. Call `get_scanner_results` again for gain scanners
2. For each symbol in `premarket_movers`:
   - If STILL on a gain scanner → **PERSISTED** — candidate for entry
   - If NO LONGER on any gain scanner → **FADED** — do not trade
3. Calculate persistence rate for today: `persisted / total_premarket_movers`

### Whipsaw Filter (MANDATORY)
For each persisted candidate:
- Look up in `whipsaw_watchlist`
- If `danger_level = "EXTREME"` → **REJECT** (these are the 4.3% that fade destructively)
- If `danger_level = "HIGH"` → **REJECT** (too risky for a persistence play)
- If `danger_level = "MODERATE"` → proceed with caution (reduce conviction by -1)

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring

For each persisted, non-whipsaw candidate:

| Factor | Points | Check |
|--------|--------|-------|
| Known reliable persister (top 15 list above) | +3 | Symbol in list |
| Still on gain scanner at 9:35 AM (confirmed) | +3 | Phase 3 persistence check |
| Pre-market volume > 100K shares | +2 | `get_quote` volume check |
| On 2+ gain scanners simultaneously | +1 | Count distinct gain scanners |
| NOT on whipsaw watchlist at all | +1 | Clean watchlist check |
| Gap > 10% from prior close (overextended) | -2 | Excessive gap = fade risk |
| On whipsaw watchlist (MODERATE level) | -1 | Elevated risk |
| Spread > 2% at 9:35 | -2 | Poor open liquidity |

### Tier Classification
- **Tier 1 (score 5+):** TRADE
- **Tier 2 (score 3-4):** REJECT
- **Negative:** SKIP

Log all to `scanner_picks` with:
- `sub_strategy="rotation_premarket_persist"`
- `signal_metadata` JSON: `{"premarket_scanners": [...], "persisted": true, "persistence_confirmed_at": "09:35", "gap_pct": X}`

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate (MANDATORY)
Call `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $2.00
2. **Minimum volume:** Pre-market volume >= 50,000
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject R, W, WS, U suffixes
5. **Not already held:** Check positions
6. **Not already ordered:** Check open orders
7. **Time check:** Must be between 9:35 AM and 10:00 AM

### Position Limits
- Max **2** concurrent positions for this sub-strategy
- Max **1** new entry per cycle
- 1 share per ticker

### Order Structure
1. **Entry:** `place_order(symbol, action="BUY", quantity=1, order_type="MKT")` — buy at 9:35 AM confirmation
2. **Stop Loss:** STP SELL at the LOWER of:
   - VWAP (dynamic — will be monitored in Phase 6)
   - Entry price × 0.95 (5% hard stop)
3. **No fixed target** — ride momentum 30-60 min with trailing stop

### Post-Order Protection
- Place protective GTC STP SELL at entry × 0.95
- Verify via `get_open_orders()`
- Log all to `rotation_scanner.db`

### Log to Database
1. `scanner_picks`: symbol, sub_strategy, scanner, rank, conviction_score, signal_metadata
2. `orders`: full order details
3. `strategy_positions`: entry details + signal_metadata with pre-market scanner info

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring

For each open `rotation_premarket_persist` position:

1. Call `get_quote(symbol)` for current price
2. INSERT `price_snapshots`
3. Update position extremes

### Momentum Continuation Check
- Check if symbol still on ANY gain scanner
- If dropped off ALL gain scanners for 2 consecutive cycles (20 min) → tighten stop to 1% below current
- If still on gain scanners → momentum intact, hold position

### VWAP Dynamic Stop
- Call `calculate_indicators(symbol, indicators=["VWAP"], ...)` each cycle
- If last < VWAP → prepare exit (momentum broken)

### Trailing Stop (Active After 15 min)
- After 15 min in position, activate trailing stop: 2% below highest price since entry
- Use `modify_order` to raise stop as price climbs

### Profit Protection — Trailing Stop Ratchet (MANDATORY)

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +5% to +10% | Breakeven (entry price) |
| +10% to +20% | Trail 2% below current price |
| +50% to +100% | MAX(+25% above entry, peak × 0.80) |
| >+100% | Trail at peak × 0.75 |

- Stops only ratchet UP

UPDATE `job_executions` with `phase_completed=6, positions_monitored=N, snapshots_logged=N`

---

## PHASE 7: Exit Handling & Lessons

### Exit Triggers
| Trigger | Exit Reason | Action |
|---------|-------------|--------|
| Stop loss (-5% or VWAP breach) | `stop_loss` / `below_vwap` | Auto via STP / MKT SELL |
| Scanner fade (off all gain scanners 20 min) | `scanner_faded` | MKT SELL |
| Time stop (90 min) | `time_stop_90min` | MKT SELL |
| Trailing stop hit | `trailing_stop` | Auto via STP |
| Profit protection ratchet | `profit_protection` | Auto via STP |
| EOD close (3:50 PM) | `eod_close` | MKT SELL — **never hold overnight** |

### On Exit
1. UPDATE `strategy_positions`: closed, exit details, P&L
2. INSERT `lessons`:
   - pre-market scanners, persistence confirmation time, gap_pct, hold_duration
   - lesson_text: "[symbol] pre-market persist: confirmed at 9:35 on [scanners]. Entered at [price], exited [reason] after [N] min. P&L: [X]%"
3. Compute KPIs

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N`

---

## PHASE 8: Run Summary & KPIs

### KPIs

| KPI | Target |
|-----|--------|
| Win Rate | > 60% (95.7% persist rate should translate to high win rate with filters) |
| Avg Win | > 1.5% (short-hold morning momentum) |
| Avg Loss | < -3% |
| Profit Factor | > 2.0 |
| Expectancy | > 0.5% |
| Avg Hold Duration | 30-60 min |
| Persistence Confirmation Rate | % of pre-market movers that persisted at 9:35 | Track (expect ~96%) |
| Whipsaw Filter Save Rate | % of rejected whipsaw names that would have lost | Track (validates filter) |
| Scanner Fade Exit Rate | % of exits from scanner_faded | < 20% |
| VWAP Exit Rate | % of exits from below_vwap | < 15% |
| MFE/MAE Ratio | > 2.5 (morning momentum should run fast) |

### Circuit Breakers
- 3 consecutive losses → disable for rest of day
- If today's persistence rate < 90% → market is unusual, disable strategy
- If win rate < 45% over last 20 trades → review whipsaw filter effectiveness

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`

---

## Lessons Pre-Loaded

### PM-1: 95.7% Persist Rate is the Edge
The base rate is overwhelmingly in favor of persistence. The strategy's job is not to predict persistence (it's near-certain) but to FILTER OUT the 4.3% that fade — which are disproportionately whipsaw names.

### PM-2: High Pre-Market Count Days Have Lower Persist Rate
20260403 had 902 pre-market movers but only 95% persist (49 faded). 20260408 had 378 but 92% persist (30 faded). When pre-market count is unusually high, be more selective.

### PM-3: Never Chase After 10:00 AM
Morning momentum peaks in the first 30 minutes. Entries after 10:00 AM are chasing, not persisting. Hard cutoff at 10:00 AM for new entries.

### PM-4: VWAP is the Kill Switch
If price drops below VWAP, the pre-market momentum is invalidated. VWAP represents the day's average institutional price — below it means sellers are winning.

### PM-5: HighOpenGap Scanners are Trap Indicators
Report §8: 311,303 transitions from HighOpenGap → LossSinceOpen. If a pre-market mover ONLY appears on HighOpenGap (not TopGainers or GainSinceOpen), it's more likely to fade. Require TopGainers or GainSinceOpen confirmation.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — pre-market and 9:35 confirmation scans |
| `get_quote(symbol)` | Phase 3 (gap calc), Phase 5 (quality gate), Phase 6 (monitoring) |
| `calculate_indicators(symbol, indicators=["VWAP"], ...)` | Phase 6 — dynamic VWAP stop |
| `get_positions()` | Phase 1, Phase 5 |
| `get_portfolio_pnl()` | Phase 1, Phase 2 |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 |
| `get_closed_trades(save_to_db=True)` | Phase 2 |
| `place_order(...)` | Phase 2, Phase 5 |
| `modify_order(...)` | Phase 6 — trailing stop |
| `get_scanner_dates()` | Phase 3 |

---

## ML/AI Enhancement Opportunities

### Research Papers for Implementation

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Universal Price Formation from Deep Learning** | [1803.06917](https://hf.co/papers/1803.06917) | Universal and stationary price formation mechanism learned from order books — applicable to modeling the pre-market→open transition as a universal pattern |
| **Empirical Regularities of Opening Call Auction** | [0905.0582](https://arxiv.org/abs/0905.0582) | Statistical patterns in opening auctions — directly models the pre-market price discovery process and persistence mechanics |
| **Pre-training Time Series with Stock Data** | [2506.16746](https://hf.co/papers/2506.16746) | Pre-trained transformer (SSPT) for stock selection — applicable to scoring pre-market movers with transfer-learned representations |
| **Proactive Model Adaptation Against Concept Drift** | [2412.08435](https://hf.co/papers/2412.08435) | Handles non-stationarity in time series forecasting — critical since persistence rates vary day-to-day (92%-100%) |
| **Alpha-R1: Alpha Screening with LLM Reasoning** | [2512.23515](https://hf.co/papers/2512.23515) | RL-trained 8B reasoning model for context-aware alpha screening — could dynamically screen pre-market movers with market-condition awareness |
| **Adaptive Market Intelligence: MoE Framework** | [2508.02686](https://hf.co/papers/2508.02686) | Volatility-aware MoE — route pre-market signals differently on high-volatility vs. low-volatility days |

### Hugging Face Models

| Model | Use Case |
|-------|----------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) (252K downloads) | Score pre-market news — positive news-driven movers persist more reliably than technical movers |
| [ahmedrachid/FinancialBERT-Sentiment-Analysis](https://hf.co/ahmedrachid/FinancialBERT-Sentiment-Analysis) (22K downloads) | Financial-specific sentiment for earnings/guidance pre-market movers |
| [nickmuchi/finbert-tone-finetuned-finance-topic-classification](https://hf.co/nickmuchi/finbert-tone-finetuned-finance-topic-classification) | Classify pre-market catalyst type — earnings gaps persist differently than technical gaps |

### Proposed Enhancements

1. **Dynamic Persistence Probability Model:** Replace fixed 95.7% base rate with a per-ticker, per-day binary classifier. Features: gap size, pre-market volume, whipsaw history, market breadth, day-of-week, VIX level, sector momentum, news sentiment score. Output: probability of persistence at 9:35 AM. Only trade when model predicts >90%.
2. **Concept Drift Detector:** Implement concept drift detection (paper 2412.08435) to identify when persistence rate regime has shifted. If detected drift (e.g., persistence rate dropping below 90% over recent sessions), auto-tighten entry criteria or disable strategy.
3. **News Catalyst Scoring:** Use financial sentiment model to classify pre-market movers into: (a) news-driven positive (earnings beat, upgrade) — highest persistence, (b) news-driven negative context (sector sympathy, macro) — moderate persistence, (c) no-news technical — filter more aggressively against whipsaw list.
4. **Opening Auction Pattern Model:** Apply opening auction research (paper 0905.0582) to model the price discovery mechanism at open. Tickers with orderly pre-market price discovery (narrow spread, convergent quotes) persist more than chaotic ones. Add as conviction factor.
