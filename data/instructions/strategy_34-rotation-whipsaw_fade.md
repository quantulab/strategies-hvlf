---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, whipsaw-fade, mean-reversion, scanner-patterns]

---

# 34-Rotation-Whipsaw Fade — Operating Instructions

## Overview
Mean-reversion strategy that fades (shorts or sells into) known whipsaw tickers when they appear on gain scanners. These are tickers with a statistically proven pattern of appearing on BOTH gain AND loss scanners on the same day — they gap up then reverse, making them unreliable for directional longs but predictable for fade trades.

**Data Backing (Report §2):** 16,076 whipsaw events detected across 53 days. 970 tickers with 5+ whipsaw days. Top whipsaw names (UVIX, SQQQ, SOXL) reverse on 35-38 of 53 days (66-72% reversal rate).

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 2:00 PM ET). **Stops scanning at 2:00 PM** — late-day fades have less room to revert.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`**

## Strategy ID
`rotation_whipsaw_fade`

---

## Whipsaw Watchlist — EXTREME Danger (from Report §2)

These tickers have the highest reversal frequency. They are the primary universe for this strategy.

| Ticker | Whipsaw Days | Reversal Rate |
|--------|-------------|---------------|
| UVIX | 38 | 72% |
| SQQQ | 37 | 70% |
| SOXL | 37 | 70% |
| LITX | 36 | 68% |
| IONX | 35 | 66% |
| MSTU | 35 | 66% |
| CRWG | 34 | 64% |
| SNXX | 34 | 64% |
| BMNZ | 34 | 64% |
| OKLL | 34 | 64% |
| MSTZ | 34 | 64% |
| AGQ | 34 | 64% |
| IRE | 34 | 64% |
| SATL | 33 | 62% |
| BATL | 33 | 62% |
| IREZ | 33 | 62% |
| RKLZ | 32 | 60% |
| AAOI | 32 | 60% |
| CCUP | 32 | 60% |
| ONDL | 31 | 58% |
| CRWV | 31 | 58% |
| TE | 31 | 58% |
| ONDS | 31 | 58% |
| ZSL | 31 | 58% |
| NBIS | 31 | 58% |

**Full universe:** 970 tickers with 5+ whipsaw days (stored in `whipsaw_watchlist` table).

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

1. Open `rotation_scanner.db` — ensure tables exist
2. INSERT into `job_executions` with `job_id="rotation_whipsaw_fade"` — capture `exec_id`
3. Track phases, update on completion/failure

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` AND `rotation_scanner.db` → `lessons` WHERE `sub_strategy="rotation_whipsaw_fade"`
2. **Load whipsaw watchlist** from `rotation_scanner.db` → `whipsaw_watchlist`
   - If watchlist is empty, populate from report §2 data (all tickers with 5+ whipsaw days)
   - Classify: EXTREME (30+ days), HIGH (15-29 days), MODERATE (5-14 days)
3. **Check positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count open: `strategy_positions` WHERE `sub_strategy="rotation_whipsaw_fade" AND status="open"`
   - Max 2 concurrent positions — if at limit, skip to Phase 6
4. **Check time:** If after 2:00 PM ET, skip to Phase 6 (monitoring only, no new entries)
5. **Check open orders** via `get_open_orders()`
6. **Verify IB connection**
7. UPDATE `job_executions` with `phase_completed=1`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for P&L
2. Query `strategy_positions` WHERE `sub_strategy="rotation_whipsaw_fade" AND status="open"`
3. **For fade (short) positions with pnl_pct <= -5% (price went HIGHER):**
   a. Check `get_open_orders()` — skip if BUY-to-cover exists
   b. Place MKT BUY to close short
   c. Log with `exit_reason="stop_loss_5pct_fade_failed"`
4. **Hard stop: new high of day +2%:**
   a. For each short position, check if current price > (day_high_at_entry × 1.02)
   b. If YES → exit immediately, fade thesis invalidated
   c. Log with `exit_reason="new_high_breakout"`
5. **Time stop:** For each position where `minutes_held >= 60`:
   - Close position — mean reversion should happen fast
   - Log with `exit_reason="time_stop_60min"`
6. **Reconcile closed trades** via `get_closed_trades(save_to_db=True)`
7. UPDATE `job_executions` with `phase_completed=2`

---

## PHASE 3: Signal Detection

### Step 1: Collect Scanner Data
For each cap tier:
- Call `get_scanner_results` for gain scanners: TopGainers, GainSinceOpen, HighOpenGap (top 50)
- Call `get_scanner_results` for loss scanners: TopLosers, LossSinceOpen, LowOpenGap (top 50)

### Step 2: Identify Whipsaw Fade Candidates
For each symbol on ANY gain scanner today:
1. Look up in `whipsaw_watchlist`
2. If found with `danger_level = "EXTREME"` (30+ whipsaw days) → **PRIMARY CANDIDATE**
3. If found with `danger_level = "HIGH"` (15-29 whipsaw days) → **SECONDARY CANDIDATE**
4. If not on watchlist → SKIP (not a known whipsaw name)

### Step 3: Confirm Fade Setup
For each candidate, call `get_quote(symbol)`:
1. Check if stock is UP from prior close (it gapped up or rallied — this is the setup to fade)
2. Calculate `gain_from_close_pct = (last - prior_close) / prior_close`
3. If `gain_from_close_pct > 5%` → strong fade setup (overextended)
4. If `gain_from_close_pct < 2%` → weak setup, skip (not enough to revert)

### Step 4: Check for Existing Loss Scanner Confirmation
- If symbol is ALREADY on a loss scanner today → fade is already in progress, may be too late
- Best entry: on gain scanner but NOT YET on loss scanner (anticipating the reversal)

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring

For each whipsaw fade candidate:

| Factor | Points | Check |
|--------|--------|-------|
| EXTREME danger (30+ whipsaw days) | +3 | `whipsaw_watchlist.danger_level` |
| On BOTH gain AND loss scanner today | +3 | Cross-reference scanners (reversal confirmed) |
| Up >5% from prior close (overextended) | +2 | `get_quote` calculation |
| Known leveraged ETF (UVIX, SQQQ, SOXL, MSTU, etc.) | +1 | Symbol classification |
| Currently on gain scanner ONLY (anticipatory) | +1 | Not yet on loss scanner — early entry |
| Spread > 2% (poor liquidity for fade) | -3 | `get_quote` spread check |
| Up < 2% (insufficient move to fade) | -2 | Weak setup |
| Already on loss scanner only (missed the move) | -2 | Already reverted |

### Tier Classification
- **Tier 1 (score 5+):** TRADE — fade entry
- **Tier 2 (score 3-4):** REJECT
- **Negative:** SKIP

Log all to `scanner_picks` with:
- `sub_strategy="rotation_whipsaw_fade"`, `action="SELL"` (fade/short)
- `signal_metadata` JSON: `{"whipsaw_days": N, "danger_level": "...", "gain_from_close_pct": X, "on_loss_scanner": bool}`

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate (MANDATORY)
Call `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $2.00
2. **Minimum volume:** Avg daily volume >= 100,000 (higher bar for shorts — need liquidity)
3. **Maximum spread:** (ask - bid) / last <= 2% (tighter for fades — slippage kills mean-reversion)
4. **No warrants/units:** Reject R, W, WS, U suffixes
5. **Not already held:** Check positions
6. **Not already ordered:** Check open orders
7. **Shortable check:** Verify shares available to short (if shorting)

### Position Limits
- Max **2** concurrent positions for this sub-strategy
- Max **1** new entry per cycle
- 1 share per ticker

### Order Structure
**Option A: Direct Short (if shortable)**
1. **Entry:** `place_order(symbol, action="SELL", quantity=1, order_type="MKT")` — sell short
2. **Stop Loss:** `place_order(symbol, action="BUY", quantity=1, order_type="STP", stop_price=day_high * 1.02)` — new HOD +2%
3. **Target:** `place_order(symbol, action="BUY", quantity=1, order_type="LMT", limit_price=prior_close)` — mean revert to prior close

**Option B: If not shortable, SKIP** — do not attempt to long a whipsaw name as a "fade proxy"

### Post-Order Protection
- Place protective GTC STP BUY (cover) at day_high × 1.02
- Verify via `get_open_orders()`

### Log to Database
1. `scanner_picks`: sub_strategy, action="SELL", conviction_score, signal_metadata
2. `orders`: action="SELL", order_type, stop_price (day_high × 1.02), limit_price (prior_close)
3. `strategy_positions`: sub_strategy="rotation_whipsaw_fade", action="SELL"

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring

For each open `rotation_whipsaw_fade` position (short):

1. Call `get_quote(symbol)` for current price
2. INSERT `price_snapshots`
3. Update position extremes (for shorts: peak = lowest price, trough = highest price)

### Mean Reversion Check
- Compute `distance_to_target = (last - prior_close) / prior_close`
- If last <= prior_close → TARGET HIT, prepare exit (cover short)
- If last > day_high at entry → fade failed, prepare exit via stop

### Loss Scanner Confirmation
- Check if symbol now appears on loss scanner → confirms reversal is underway
- Tighten stop to 1% above current price (lock in gains)

### Time Stop Warning
- At 45 min held, log warning — if not near target, prepare to exit at 60 min

### Profit Protection for Shorts (Inverted Ratchet)
Since this is a short position, the ratchet works inversely:

| Unrealized Gain (short) | Required Cover Level |
|-------------------------|---------------------|
| +5% to +10% | Breakeven (entry price) — move stop down to entry |
| >+10% | Trail 3% above trough (lowest price reached) |

- Stops only ratchet DOWN for shorts
- Use `modify_order` to lower cover stops

UPDATE `job_executions` with `phase_completed=6, positions_monitored=N, snapshots_logged=N`

---

## PHASE 7: Exit Handling & Lessons

### Exit Triggers
| Trigger | Exit Reason | Action |
|---------|-------------|--------|
| Target hit (price <= prior close) | `mean_reverted` | Auto via LMT BUY cover |
| Stop loss (new HOD +2%) | `new_high_breakout` | Auto via STP BUY cover |
| Time stop (60 min) | `time_stop_60min` | MKT BUY cover |
| Loss scanner confirms reversion, target tightened | `trailing_cover` | Auto via modified STP |
| EOD forced close (3:50 PM) | `eod_close` | MKT BUY cover — **NEVER hold short overnight** |

### On Exit
1. UPDATE `strategy_positions`: closed, exit details, P&L
2. INSERT `lessons`:
   - whipsaw_days, danger_level, gain_from_close at entry, reversion achieved
   - lesson_text: "[symbol] fade: entered short at [price] (up [X]% from close). [Reverted/Failed] in [N] min. P&L: [Y]%"
3. UPDATE `whipsaw_watchlist` with today's whipsaw event (increment if both gain+loss scanners triggered)
4. Compute KPIs

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N`

---

## PHASE 8: Run Summary & KPIs

### KPIs

| KPI | Target |
|-----|--------|
| Win Rate | > 55% (known whipsaw names should revert >55% of the time) |
| Avg Win | > 2% (mean reversion target) |
| Avg Loss | < -3% (tight stop at HOD +2%) |
| Profit Factor | > 1.5 |
| Expectancy | > 0.3% |
| Avg Hold Duration | 15-45 min (mean reversion is fast) |
| Mean Reversion Rate | % of fades that hit prior-close target | > 50% |
| Time Stop Rate | % of exits via 60-min time stop | < 30% |
| False Breakout Rate | % of exits via new-HOD stop | < 20% |
| MFE/MAE Ratio | > 1.5 |

### Circuit Breakers
- 3 consecutive losses → disable for rest of day (fade thesis may be wrong in current regime)
- Mean reversion rate < 40% over last 15 trades → pause and review market regime (trending day = no fades)
- If market G/L ratio > 1.5 (strong BULL) → disable fades (momentum > mean reversion on trend days)

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`

---

## Lessons Pre-Loaded

### WF-1: Leveraged ETFs are the Best Fade Candidates
UVIX (72%), SQQQ (70%), SOXL (70%) have the highest reversal rates. They are designed to be volatile and mean-revert intraday. Prioritize these over single-stock whipsaws.

### WF-2: Spread Kills Fade Profits
Mean-reversion targets are typically 2-5%. A 2%+ spread eats half the profit or more. Strict 2% max spread is non-negotiable for this strategy.

### WF-3: Never Hold Fades Overnight
Whipsaw names can gap in either direction. A profitable fade at 3:30 PM can be a -10% loss at 9:30 AM. Always cover before close.

### WF-4: Trending Days Break Fades
When market G/L ratio is > 1.5 (strong bull) or < 0.5 (strong bear), whipsaw names tend to trend rather than revert. Disable fades on trending days.

### WF-5: HighOpenGap → LossSinceOpen is the Fade Lifecycle
Report §8 shows 311,303 transitions from HighOpenGap → LossSinceOpen. This IS the fade pattern — gap up, then lose. Entry on HighOpenGap appearance, exit when LossSinceOpen confirms.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — gain and loss scanner data |
| `get_quote(symbol)` | Phase 3 (setup confirm), Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, "2 D", "1 day")` | Phase 3 — prior close for target |
| `get_positions()` | Phase 1, Phase 5 |
| `get_portfolio_pnl()` | Phase 1, Phase 2 |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 |
| `get_closed_trades(save_to_db=True)` | Phase 2 |
| `place_order(...)` | Phase 2, Phase 5 |
| `modify_order(...)` | Phase 6 |
| `classify_market_regime()` | Phase 1 — disable on trending days |

---

## ML/AI Enhancement Opportunities

### Research Papers for Implementation

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Compounding Effects in Leveraged ETFs** | [2504.20116](https://arxiv.org/abs/2504.20116) | LETF performance depends on return autocorrelation — negative autocorrelation = higher mean reversion edge. Use as dynamic conviction factor |
| **LETF Rebalancing Destabilizes Markets** | [2010.13036](https://arxiv.org/abs/2010.13036) | Agent-based model showing LETF rebalancing creates predictable reversals near close — explains WHY whipsaw names mean-revert and optimal fade timing |
| **Threshold Model for Local Volatility** | [1712.08329](https://arxiv.org/abs/1712.08329) | Piecewise-constant volatility with leverage effect + mean reversion — mathematical basis for estimating reversion speed |
| **HMM + LSTM for Stock Trends** | [2104.09700](https://arxiv.org/abs/2104.09700) | HMM regime detection combined with LSTM — replace simple G/L ratio with HMM-based trending vs. mean-reverting regime classifier |
| **Advance Bull/Bear Phase Detection** | [2411.13586](https://arxiv.org/abs/2411.13586) | Advance detection of market phases — predict when trending days will break fades BEFORE entering |
| **Adaptive Market Intelligence: MoE Framework** | [2508.02686](https://hf.co/papers/2508.02686) | Mixture of Experts with volatility-aware gating — route decisions to fade expert vs. trend expert per detected regime |
| **Trade the Event: Corporate Events Detection** | [2105.12825](https://hf.co/papers/2105.12825) | News-based event detection — distinguish news-driven gaps (less likely to revert) from flow-driven gaps (more likely to revert) |

### Hugging Face Models

| Model | Use Case |
|-------|----------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) (252K downloads) | Detect if whipsaw ticker's gap is news-driven (earnings, FDA) vs. flow-driven — news-driven gaps less likely to revert |
| [mrm8488/deberta-v3-ft-financial-news-sentiment-analysis](https://hf.co/mrm8488/deberta-v3-ft-financial-news-sentiment-analysis) (87K downloads) | Higher-accuracy sentiment model for critical fade decisions on high-conviction signals |
| [nickmuchi/finbert-tone-finetuned-finance-topic-classification](https://hf.co/nickmuchi/finbert-tone-finetuned-finance-topic-classification) | Classify news catalyst type — earnings/guidance gaps revert less than flow/technical gaps |

### Proposed Enhancements

1. **HMM Regime Classifier:** Replace simple G/L ratio threshold with HMM-based regime detector (paper 2104.09700). Train on historical scanner breadth + G/L ratio + VIX to classify: TRENDING (disable fades), MEAN-REVERTING (enable fades), TRANSITION (reduce size). Update regime classification every 30 min.
2. **Return Autocorrelation Conviction Factor:** Compute rolling 5-day return autocorrelation per whipsaw ticker (paper 2504.20116). Negative autocorrelation = higher fade conviction (+2 points). Positive autocorrelation = trending, reduce conviction (-2 points).
3. **LETF Rebalancing Timer:** Model the LETF rebalancing flow (paper 2010.13036) to predict optimal fade entry window. LETFs rebalance near close — fading at 2-3 PM captures the pre-rebalancing reversal.
4. **News-Driven Gap Filter:** Use financial sentiment model + topic classifier to detect if gap is news-driven (earnings surprise, FDA approval) vs. technical/flow-driven. News-driven gaps get -3 conviction (less likely to revert). Flow-driven gaps get +1 conviction.
5. **Mixture of Experts Routing:** Implement MoE framework (paper 2508.02686) with two experts: fade expert (mean-reversion model) and trend expert (momentum model). Volatility-aware gate routes each signal to the appropriate expert. If fade expert's confidence > 70%, trade; otherwise skip.
