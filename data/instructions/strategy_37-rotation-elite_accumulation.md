---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, elite-accumulation, scanner-patterns]

---

# 37-Rotation-Elite Accumulation — Operating Instructions

## Overview
Targets the market's strongest names — tickers holding top-5 rank on gain scanners for 3+ consecutive days. These are institutional accumulation targets with dominant scanner presence. The strategy enters on pullbacks to VWAP during the accumulation phase, riding the sustained momentum.

**Data Backing (Report §11, §1):** 50 elite tickers identified holding top-5 rank for 49-53 consecutive days. Report §1 shows 30 tickers appearing all 53 trading days with average ranks between 7.4 (NVDA) and 24.1 (MSTR). These are NOT one-day runners — they have sustained, persistent institutional interest.

## Schedule
Runs every 10 minutes during market hours (9:45 AM – 3:50 PM ET). **Starts at 9:45 AM** (skip first 15 min — let VWAP establish before pullback entries).

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`**

## Strategy ID
`rotation_elite_accumulation`

---

## Elite Top-5 Holders (from Report §11)

### Volume/Activity Scanners (Institutional Presence)
| Ticker | Scanner | Days in Top 5 |
|--------|---------|---------------|
| TQQQ | MostActive | 53 |
| SOXL | MostActive | 53 |
| TSLL | MostActive | 53 |
| NVDA | MostActive | 52 |
| TQQQ | TopVolumeRate | 52 |
| SOXL | TopVolumeRate | 52 |
| TSLL | TopVolumeRate | 52 |
| NVDA | TopVolumeRate | 51 |
| SLV | TopVolumeRate | 51 |
| SQQQ | TopVolumeRate | 51 |
| XLE | TopVolumeRate | 51 |
| IBIT | TopVolumeRate | 51 |
| INTC | TopVolumeRate | 51 |
| ONDS | TopVolumeRate | 51 |
| ETHA | TopVolumeRate | 51 |
| UVIX | TopVolumeRate | 51 |
| NIO | TopVolumeRate | 51 |
| SQQQ | MostActive | 50 |
| TZA | TopVolumeRate | 50 |

### Persistent Tickers — Institutional Favorites (from Report §1)
| Ticker | Days Seen | Total Scans | Avg Rank | Cap Sizes |
|--------|-----------|-------------|----------|-----------|
| SOXL | 53 | 87,267 | 10.3 | LargeCap, MidCap |
| SQQQ | 53 | 83,898 | 11.6 | LargeCap |
| NVDA | 53 | 59,685 | 7.4 | LargeCap |
| TQQQ | 53 | 59,912 | 8.6 | LargeCap, MidCap |
| PLTR | 53 | 59,698 | 16.4 | LargeCap |
| HOOD | 53 | 59,511 | 20.3 | LargeCap |
| IBIT | 53 | 53,931 | 12.9 | LargeCap, MidCap |
| INTC | 53 | 56,554 | 14.4 | LargeCap, MidCap |

**Note:** For this strategy, we focus on tickers in top-5 on GAIN scanners (TopGainers, GainSinceOpen), not just volume scanners. Volume-only elite holders are informational but not direct trade signals.

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

1. Open `rotation_scanner.db` — ensure tables exist
2. INSERT into `job_executions` with `job_id="rotation_elite_accumulation"` — capture `exec_id`
3. Track phases, update on completion/failure

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` AND `rotation_scanner.db` → `lessons` WHERE `sub_strategy="rotation_elite_accumulation"`
2. **Check positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count open: `strategy_positions` WHERE `sub_strategy="rotation_elite_accumulation" AND status="open"`
   - Max 3 concurrent positions — if at limit, skip to Phase 6
3. **Check time:** If before 9:45 AM → too early (VWAP not established), abort
4. **Check open orders** via `get_open_orders()`
5. **Verify IB connection**
6. **Load whipsaw watchlist** — elite holders that are ALSO whipsaw names need special handling
7. **Load streak tracker** — cross-reference elite status with streak data
8. UPDATE `job_executions` with `phase_completed=1`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for P&L
2. Query `strategy_positions` WHERE `sub_strategy="rotation_elite_accumulation" AND status="open"`
3. For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if SELL exists
   b. Place MKT SELL, log, close with `exit_reason="stop_loss_5pct"`
4. **Rank drop check:** For each open position:
   - Get current rank on the entry gain scanner
   - If rank > 5 for 2+ consecutive cycles (20 min) → elite status lost
   - If rank > 10 → immediate exit signal with `exit_reason="rank_dropped"`
5. **Prior day low stop:** For each position:
   - If current price < prior day's low → prepare exit with `exit_reason="below_prior_day_low"`
6. **Reconcile closed trades** via `get_closed_trades(save_to_db=True)`
7. UPDATE `job_executions` with `phase_completed=2`

---

## PHASE 3: Elite Signal Detection

### Step 1: Collect Gain Scanner Data
For each cap tier:
- Call `get_scanner_results` for: TopGainers, GainSinceOpen (top 10 — focus on top ranks)

### Step 2: Identify Current Top-5 Holders
For each gain scanner feed:
1. Extract the top 5 ranked symbols
2. Check `streak_tracker` — how many consecutive days has this symbol been in top-5 on THIS scanner?
   - If no streak tracker entry, check prior day's scanner data
   - Create/update streak tracker entry

### Step 3: Identify Trade Signals
Signal fires when:
- Symbol has been in top-5 on a GAIN scanner for **3+ consecutive trading days**
- Symbol is available for a PULLBACK entry (see Phase 5)

### Step 4: VWAP Pullback Detection
For each eligible elite symbol:
1. Call `get_quote(symbol)` for current price
2. Call `calculate_indicators(symbol, indicators=["VWAP"], duration="1 D", bar_size="1 min", tail=1)`
3. Pullback detected if:
   - Current price is within 0.5% of VWAP (price pulled back to institutional average)
   - Current price was ABOVE VWAP earlier today (it ran, then pulled back — not falling into VWAP from below)
4. NOT a pullback if price has been below VWAP all day → this is weakness, not accumulation

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring

For each elite accumulation candidate:

| Factor | Points | Check |
|--------|--------|-------|
| Top-5 on gain scanner for 5+ consecutive days | +3 | `streak_tracker` |
| Appears all 53 days in report (persistent ticker) | +2 | Cross-ref report §1 |
| On 3+ scanner types simultaneously today | +2 | Count distinct scanners |
| Avg rank < 10 (dominant position) | +2 | From report §1 or current data |
| VWAP pullback confirmed (price within 0.5% of VWAP) | +2 | Phase 3 pullback detection |
| Top-5 for only 3 days exactly (just qualifying) | -1 | Less confidence than 5+ |
| On whipsaw watchlist (EXTREME danger) | -3 | These flip direction constantly |
| Price below VWAP (weakness, not pullback) | -3 | Not an accumulation signal |

### Tier Classification
- **Tier 1 (score 5+):** TRADE — VWAP pullback entry
- **Tier 2 (score 3-4):** REJECT
- **Negative:** SKIP

Log all to `scanner_picks` with:
- `sub_strategy="rotation_elite_accumulation"`
- `signal_metadata` JSON: `{"top5_streak_days": N, "scanner": "...", "avg_rank": X, "vwap_distance_pct": Y, "persistent_ticker": bool}`

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate (MANDATORY)
Call `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $5.00 (elite names should be quality — higher price bar)
2. **Minimum volume:** Avg daily volume >= 500,000 (elite names have institutional volume)
3. **Maximum spread:** (ask - bid) / last <= 1% (tight for quality entry)
4. **No warrants/units:** Reject R, W, WS, U suffixes
5. **Not already held:** Check positions
6. **Not already ordered:** Check open orders
7. **VWAP proximity confirmed:** Must be within 0.5% of VWAP at time of order

### Position Limits
- Max **3** concurrent positions for this sub-strategy
- Max **1** new entry per cycle
- 1 share per ticker

### Order Structure
1. **Entry:** `place_order(symbol, action="BUY", quantity=1, order_type="LMT", limit_price=VWAP)` — limit at VWAP for pullback entry
2. **Stop Loss:** STP SELL below prior day's low
   - Get prior day low via `get_historical_bars(symbol, "2 D", "1 day")`
   - `stop_price = prior_day_low × 0.99` (1% below prior day low for buffer)
3. **Target:** No fixed target — trail 5% below peak for sustained momentum

### Post-Order Protection
- Place protective GTC STP SELL at stop price
- Verify via `get_open_orders()`

### Log to Database
1. `scanner_picks`: symbol, sub_strategy, conviction_score, signal_metadata
2. `orders`: full order details
3. `strategy_positions`: entry details + signal_metadata with elite streak info

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring

For each open `rotation_elite_accumulation` position:

1. Call `get_quote(symbol)` for current price
2. INSERT `price_snapshots`
3. Update position extremes

### Elite Status Check (KEY MONITORING)
- Check current rank on entry gain scanner each cycle
- **Rank 1-5:** Elite status maintained — hold with confidence
- **Rank 6-10:** Warning zone — tighten trailing stop to 3% below current
- **Rank > 10:** Elite status lost — prepare exit with `exit_reason="rank_dropped"`
- **Off scanner entirely:** Immediate exit signal

### VWAP Relationship
- If price drops below VWAP after having been above it → momentum weakening
- Don't exit immediately (normal pullbacks cross VWAP) but tighten stop

### Trailing Stop (Active After Entry Fill)
- Start with prior-day-low stop
- After +3% gain: activate 5% trailing stop below peak
- Use `modify_order` to adjust

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
| Stop loss (prior day low) | `stop_loss_prior_day_low` | Auto via STP |
| Rank dropped (> 10 on gain scanner) | `rank_dropped` | MKT SELL |
| Off gain scanner entirely | `scanner_dropped` | MKT SELL |
| Trailing stop (5% below peak) | `trailing_stop` | Auto via STP |
| Profit protection ratchet | `profit_protection` | Auto via STP |
| EOD close | `eod_hold` or `eod_close` | **HOLD OVERNIGHT if profitable + still top-5 + not whipsaw. Otherwise MKT SELL.** |

### Overnight Hold Rules
Like capsize breakout, this is a multi-day strategy. ALLOW overnight if ALL:
1. Position profitable (pnl_pct > 0)
2. Symbol still in top-5 on gain scanner as of last scan
3. Symbol NOT on whipsaw watchlist (EXTREME)
4. Stop order in place at profit protection level

### On Exit
1. UPDATE `strategy_positions`: closed, exit details, P&L, hold_duration
2. INSERT `lessons`:
   - top5_streak at entry, rank at entry, rank at exit, hold_duration
   - lesson_text: "[symbol] elite accumulation: top-5 on [scanner] for [N] days. Entered VWAP pullback at [price], rank [R]. Exited [reason] after [duration]. Final rank: [R]. P&L: [X]%"
3. Compute KPIs

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N`

---

## PHASE 8: Run Summary & KPIs

### KPIs

| KPI | Target |
|-----|--------|
| Win Rate | > 60% (elite names have institutional support — high directional consistency) |
| Avg Win | > 3% (multi-day accumulation targets) |
| Avg Loss | < -3% (tight stops relative to multi-day potential) |
| Profit Factor | > 2.0 |
| Expectancy | > 1.0% |
| Avg Hold Duration | 1-5 days |
| VWAP Entry Accuracy | % of limit orders at VWAP that filled | > 70% |
| Elite Persistence Rate | % of entered positions where symbol remained top-5 for 2+ more days | > 75% |
| Rank Drop Exit Rate | % of exits from rank_dropped | < 20% |
| Overnight Hold Win Rate | % of overnight holds profitable next day | > 70% |
| MFE/MAE Ratio | > 3.0 (elite names should have strong directional bias) |

### Circuit Breakers
- 4 consecutive losses → disable for rest of day
- VWAP fill rate < 50% → switch from LMT to MKT entries (market too fast for limit)
- Elite persistence rate < 60% over last 15 entries → top-5 requirement may need to be top-3

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`

---

## Lessons Pre-Loaded

### EA-1: Elite Holders on Volume Scanners ≠ Elite Holders on Gain Scanners
Being top-5 on MostActive (TQQQ 53 days, SOXL 53 days) means high volume, NOT necessarily high gains. Only enter when the ticker is top-5 on a GAIN scanner (TopGainers, GainSinceOpen). Volume-only elites are for other sub-strategies.

### EA-2: VWAP Pullback is the Entry — Not the Breakout
This strategy buys the DIP in a strong name, not the rip. Entry on VWAP pullback means buying when price reverts to institutional average. Chasing a breakout above the day's high is a different thesis (momentum, not accumulation).

### EA-3: Avg Rank Distinguishes Dominant from Marginal
NVDA avg rank 7.4 and TQQQ avg rank 8.6 are dominant — consistently near the top. MSTR avg rank 24.1 is marginal — frequently on scanners but rarely near the top. Prefer avg rank < 15 for highest confidence.

### EA-4: Whipsaw Elite Names are Traps
UVIX is top-5 on TopVolumeRate for 51 days but also has 38 whipsaw days (EXTREME). Being elite AND whipsaw means the stock is highly active in both directions. The whipsaw filter overrides the elite signal.

### EA-5: Day 3+ Entry Filters Transient Tops
A ticker can be #1 on TopGainers for 1-2 days due to a news catalyst then disappear. Requiring 3+ consecutive days filters out one-off spikes and targets sustained institutional buying.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — gain scanner top-10 data |
| `get_quote(symbol)` | Phase 3 (pullback detection), Phase 5 (quality gate), Phase 6 (monitoring) |
| `calculate_indicators(symbol, indicators=["VWAP"], ...)` | Phase 3 (pullback), Phase 6 (VWAP check) |
| `get_historical_bars(symbol, "2 D", "1 day")` | Phase 5 — prior day low for stop |
| `get_positions()` | Phase 1, Phase 5 |
| `get_portfolio_pnl()` | Phase 1, Phase 2 |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 |
| `get_closed_trades(save_to_db=True)` | Phase 2 |
| `place_order(...)` | Phase 2, Phase 5 |
| `modify_order(...)` | Phase 6 — trailing stops |
| `get_scanner_dates()` | Phase 3 |

---

## ML/AI Enhancement Opportunities

### Research Papers for Implementation

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **VWAP Execution as Optimal Strategy** | [1408.6118](https://arxiv.org/abs/1408.6118) | Mathematical proof that VWAP is optimal execution benchmark — validates the VWAP pullback entry thesis from an institutional perspective |
| **Optimal VWAP Under Transient Impact** | [1901.02327](https://arxiv.org/abs/1901.02327) | VWAP optimization accounting for permanent + transient market impact — models how institutional accumulation affects VWAP behavior |
| **Deep Learning for VWAP Execution** | [2502.13722](https://arxiv.org/abs/2502.13722) | DL model for volume curve prediction — predict intraday volume distribution to identify optimal VWAP pullback windows |
| **Price Impact Asymmetry of Institutional Trading** | [1110.3133](https://arxiv.org/abs/1110.3133) | Buy/sell impact asymmetry in institutional orders — if buy impact > sell impact, accumulation thesis confirmed. Use as conviction factor |
| **TLOB: Transformer for LOB Price Trend** | [2502.15757](https://hf.co/papers/2502.15757) | Dual-attention transformer for limit order book prediction — predict VWAP bounce probability before placing limit order |
| **RL for Optimal Execution with Time-Varying Liquidity** | [2402.12049](https://hf.co/papers/2402.12049) | Double Deep Q-learning for adaptive execution — learn optimal pullback depth dynamically instead of fixed 0.5% VWAP proximity |
| **MM-DREX: Multimodal Expert Routing for Trading** | [2509.05080](https://hf.co/papers/2509.05080) | Vision-language model for candlestick patterns + dynamic expert routing — detect accumulation patterns from candlestick chart analysis |

### Hugging Face Models

| Model | Use Case |
|-------|----------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) (252K downloads) | Score news for elite tickers — sustained positive sentiment confirms institutional accumulation thesis |
| [mrm8488/deberta-v3-ft-financial-news-sentiment-analysis](https://hf.co/mrm8488/deberta-v3-ft-financial-news-sentiment-analysis) (87K downloads) | High-accuracy sentiment for elite stock validation — analyst upgrades, institutional filings |
| [soleimanian/financial-roberta-large-sentiment](https://hf.co/soleimanian/financial-roberta-large-sentiment) (3.4K downloads) | Deep analysis of earnings calls, ESG reports for fundamental accumulation thesis |

### Proposed Enhancements

1. **RL-Based VWAP Entry Optimization:** Replace fixed 0.5% VWAP proximity trigger with a DRL agent (paper 2402.12049) that learns optimal pullback depth per ticker. Features: current distance to VWAP, volume profile, bid-ask spread, time of day, historical VWAP bounce success rate. The agent learns when shallow pullbacks (0.2%) are sufficient vs. when to wait for deeper pullbacks (1%).
2. **LOB Bounce Probability:** Apply dual-attention LOB transformer (paper 2502.15757) to predict the probability of price bouncing off VWAP before placing limit order. Only place LMT at VWAP when bounce probability > 65%. When bounce probability is low, wait for next cycle.
3. **Institutional Flow Asymmetry Factor:** Compute the buy/sell impact ratio (paper 1110.3133) using recent trade data. If buy_impact / sell_impact > 1.2, institutional accumulation is confirmed — add +2 conviction. If ratio < 0.8, distribution may be occurring — add -2 conviction.
4. **Volume Curve Prediction for Entry Timing:** Use DL volume curve model (paper 2502.13722) to predict when VWAP pullbacks are most likely (typically at volume troughs, 11:30 AM - 1:00 PM). Schedule entry attempts during predicted pullback windows rather than random 10-minute cycles.
5. **News-Driven Accumulation Confirmation:** Use financial sentiment models to detect sustained positive institutional interest (analyst upgrades, 13F filings, insider buying). Sustained positive news flow + top-5 rank = strongest accumulation signal (+2 conviction).
