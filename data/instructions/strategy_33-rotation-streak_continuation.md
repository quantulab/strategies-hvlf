---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, streak-continuation, scanner-patterns]

---

# 33-Rotation-Streak Continuation — Operating Instructions

## Overview
Captures multi-day momentum by entering stocks that appear on the same scanner type for 3+ consecutive trading days. The data shows streaks are bimodal — they either break early or persist for weeks. By entering on day 3, we filter out noise and ride the persistent ones.

**Data Backing (Report §4):** 100 multi-day momentum streaks detected. Distribution is bimodal: 44 streaks lasted all 53 days, most others 39-44 days. Average streak length 47.1 days. Tickers on gain scanners for 5+ days indicate strong institutional accumulation.

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 3:50 PM ET) via Claude Code CronCreate.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`**

## Strategy ID
`rotation_streak_continuation`

---

## Known Long-Streak Tickers (from Report §4 — 53-Day Persistent Streaks)

| Ticker | Scanner | Streak Days |
|--------|---------|-------------|
| SOXL | TopVolumeRate, MostActive | 53 |
| SLV | MostActive, TopVolumeRate | 53 |
| IREN | MostActive | 53 |
| CRCL | TopVolumeRate | 53 |
| CRWV | TopVolumeRate | 53 |
| NOW | TopVolumeRate | 53 |
| MSTR | TopVolumeRate | 53 |
| PLTR | TopVolumeRate | 53 |
| TLT | MostActive | 53 |
| NVDA | MostActive, TopVolumeRate | 53 |
| SQQQ | MostActive, TopVolumeRate | 53 |
| XLE | MostActive | 53 |
| TQQQ | MostActive, TopVolumeRate | 53 |
| IBIT | MostActive | 53 |
| HOOD | TopVolumeRate | 53 |
| ORCL | MostActive | 53 |
| SGOV | TopVolumeRate | 53 |
| NBIS | TopVolumeRate | 53 |
| PSLV | TopVolumeRate | 53 |
| INTC | TopVolumeRate, MostActive | 53 |
| ONDS | TopVolumeRate | 53 |
| ETHA | MostActive | 53 |
| BITO | MostActive | 53 |
| RGTI | MostActive | 53 |

### Streak Length Distribution
```
39 days: 19 streaks
40 days:  2 streaks
41 days:  1 streak
43 days:  4 streaks
44 days: 24 streaks
47 days:  4 streaks
49 days:  1 streak
52 days:  1 streak
53 days: 44 streaks  ← bimodal peak: once past ~day 5, streaks persist
```

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

1. Open `rotation_scanner.db` — ensure tables exist
2. INSERT into `job_executions` with `job_id="rotation_streak_continuation"` — capture `exec_id`
3. Track phases, update on completion/failure

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` AND `rotation_scanner.db` → `lessons` WHERE `sub_strategy="rotation_streak_continuation"`
2. **Load active streaks** from `rotation_scanner.db` → `streak_tracker` WHERE `status="active"`
3. **Check positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count open: `strategy_positions` WHERE `sub_strategy="rotation_streak_continuation" AND status="open"`
   - Max 3 concurrent positions — if at limit, skip to Phase 6
4. **Check open orders** via `get_open_orders()`
5. **Verify IB connection**
6. **Load whipsaw watchlist** from `whipsaw_watchlist` table
7. UPDATE `job_executions` with `phase_completed=1`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for P&L
2. Query `strategy_positions` WHERE `sub_strategy="rotation_streak_continuation" AND status="open"`
3. For each position with `pnl_pct <= -5%`:
   a. Check `get_open_orders()` — skip if SELL exists
   b. Place MKT SELL, log to `orders`, close in `strategy_positions` with `exit_reason="stop_loss_5pct"`
   c. INSERT into `lessons`
4. **Streak break check:** For each open position, verify the symbol's streak is still active:
   - Check today's scanner results for the symbol on its entry scanner
   - If symbol is ABSENT from the scanner today → the streak broke
   - Prepare exit in Phase 7 with `exit_reason="streak_broken"`
5. **Reconcile closed trades** via `get_closed_trades(save_to_db=True)`
6. UPDATE `job_executions` with `phase_completed=2`

---

## PHASE 3: Streak Detection & Signal Generation

### Step 1: Collect Today's Scanner Data
For each scanner type × cap tier:
- Call `get_scanner_results(scanner, date=TODAY, top_n=50)`

### Step 2: Update Streak Tracker
For each active streak in `streak_tracker`:
1. Check if symbol appears on the same `scanner_type` today
2. If YES:
   - UPDATE `streak_days += 1`, `streak_end = TODAY`, `last_updated = now`
3. If NO:
   - UPDATE `status = "broken"`, `streak_end = YESTERDAY`
   - This streak is over — any position based on it should exit

### Step 3: Detect New Streaks
For each symbol on today's scanners:
1. Check if it was on the same scanner yesterday (query yesterday's data or `streak_tracker`)
2. If YES and no active streak exists → create new `streak_tracker` entry with `streak_days=2`, `streak_start=YESTERDAY`
3. If it was on for 2 consecutive days already → streak_days is now 3 → **SIGNAL FIRES**

### Step 4: Identify Tradeable Signals
A signal fires when:
- `streak_days >= 3` (day 3 of streak — Lesson R3: day 2 entries have higher break rate)
- Symbol's rank is improving (today's rank < yesterday's rank on same scanner)
- Scanner is a GAIN scanner (TopGainers, GainSinceOpen) — volume-only streaks are informational, not entry signals
- For VOLUME scanner streaks (MostActive, TopVolumeRate, HotByVolume): only signal if symbol is ALSO on a gain scanner today

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring

For each streak continuation candidate:

| Factor | Points | Check |
|--------|--------|-------|
| Streak >= 5 days | +3 | `streak_tracker.streak_days >= 5` |
| Rank improving (delta < -5 over last 3 days) | +2 | Compare rank today vs 3 days ago |
| On 2+ scanner types simultaneously today | +2 | Count distinct scanner appearances |
| Elite holder (top-5 for 3+ days) — report §11 | +2 | Cross-ref elite holders list |
| Known 53-day persistent ticker (list above) | +1 | Symbol in known long-streak list |
| On whipsaw watchlist | -2 | `whipsaw_watchlist` lookup |
| Streak just started (day 3 exactly) | -1 | More confidence at day 5+ |
| Rank deteriorating (delta > +5) | -2 | Rank worsening despite streak |

### Tier Classification
- **Tier 1 (score 5+):** TRADE
- **Tier 2 (score 3-4):** REJECT
- **Tier 3 (score 1-2):** WATCH only
- **Negative:** BLACKLIST

Log all to `scanner_picks` with:
- `sub_strategy="rotation_streak_continuation"`
- `signal_metadata` JSON: `{"streak_days": N, "scanner_type": "...", "rank_delta_3d": N, "is_elite_holder": bool}`

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate (MANDATORY)
Call `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $2.00
2. **Minimum volume:** Avg daily volume >= 50,000
3. **Maximum spread:** (ask - bid) / last <= 3%
4. **No warrants/units:** Reject R, W, WS, U suffixes
5. **Not already held:** Check positions
6. **Not already ordered:** Check open orders

### Position Limits
- Max **3** concurrent positions for this sub-strategy
- Max **1** new entry per cycle
- 1 share per ticker

### Order Structure
1. **Entry:** MKT BUY (buy on day 3+ pullback)
2. **Stop Loss:** STP SELL below prior day's low (from `get_historical_bars(symbol, "2 D", "1 day")`)
3. **No fixed target** — exit on streak break or rank deterioration >10 positions

### Post-Order Protection
- Place protective GTC STP SELL at stop price
- Verify via `get_open_orders()`
- Log all to `rotation_scanner.db`

### Log to Database
1. `scanner_picks`: symbol, sub_strategy, scanner, rank, conviction_score, conviction_tier
2. `orders`: full order details
3. `strategy_positions`: entry details + `signal_metadata` with streak info

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring

For each open `rotation_streak_continuation` position:

1. Call `get_quote(symbol)` for current price
2. INSERT `price_snapshots`
3. Update position extremes

### Streak Continuation Check (KEY MONITORING)
- Check if symbol still appears on the entry scanner type
- If symbol's rank deteriorated >10 positions from entry rank → prepare exit
- If symbol disappeared from scanner → streak broken, prepare exit
- If symbol's rank improved → widen trailing stop (momentum strengthening)

### Rank Deterioration Alert
- Track rank each cycle
- If rank worsens by 5+ positions in a single cycle → tighten stop to 2% below current price

### Profit Protection — Trailing Stop Ratchet (MANDATORY)

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +5% to +10% | Breakeven (entry price) |
| +10% to +20% | Trail 2% below current price |
| +50% to +100% | MAX(+25% above entry, peak × 0.80) |
| >+100% | Trail at peak × 0.75 |

- Stops only ratchet UP
- Use `modify_order` to raise stops

UPDATE `job_executions` with `phase_completed=6, positions_monitored=N, snapshots_logged=N`

---

## PHASE 7: Exit Handling & Lessons

### Exit Triggers
| Trigger | Exit Reason | Action |
|---------|-------------|--------|
| Stop loss (-5% or prior day low) | `stop_loss` | Auto via STP |
| Streak broken (symbol off scanner) | `streak_broken` | MKT SELL |
| Rank deteriorated >10 positions | `rank_deteriorated` | MKT SELL |
| Trailing stop (profit protection) | `trailing_stop` | Auto via STP |
| EOD close (3:50 PM) | `eod_close` | MKT SELL — **EXCEPTION: hold overnight if profitable AND streak still active AND not on whipsaw list** |

### On Exit
1. UPDATE `strategy_positions`: closed, exit details, P&L
2. INSERT `lessons`:
   - streak_days at entry, streak_days at exit, rank at entry, rank at exit
   - lesson_text: "Streak of [N] days on [scanner]. Entered day [M], exited on [reason] after [duration]. Streak [continued/broke] after exit."
3. UPDATE `streak_tracker` if streak broke
4. Compute KPIs

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N`

---

## PHASE 8: Run Summary & KPIs

### KPIs

| KPI | Target |
|-----|--------|
| Win Rate | > 55% (streaks have directional persistence) |
| Avg Win | > 3% (multi-day holds should capture larger moves) |
| Avg Loss | < -4% |
| Profit Factor | > 1.5 |
| Expectancy | > 0.5% |
| Avg Hold Duration | 1-5 days (not intraday) |
| Streak Survival Rate | % of entered streaks that lasted 5+ more days | > 70% |
| Rank Deterioration Exit Rate | % of exits from rank loss | < 25% |
| Overnight Hold Win Rate | % of overnight holds that were profitable next day | > 60% |
| MFE/MAE Ratio | > 2.0 |

### Circuit Breakers
- 5 consecutive losses → disable for rest of day
- Streak survival rate < 50% over last 20 entries → pause and review streak detection logic
- If win rate < 40% over 30 trades → require score 6+ (stricter Tier 1)

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`

---

## Lessons Pre-Loaded

### SC-1: Streaks are Bimodal — Enter on Day 3+
Day-2 entries have higher break rates. If a streak survives to day 3, it likely persists much longer (avg 47.1 days). Never enter on day 1 or 2.

### SC-2: Volume Streaks ≠ Gain Streaks
Being on MostActive/TopVolumeRate for 53 consecutive days (like SOXL, NVDA, INTC) means persistent volume, NOT persistent gains. Only trade streaks on GAIN scanners, or volume streaks confirmed by same-day gain scanner appearance.

### SC-3: Rank Matters More Than Presence
A ticker can be on a scanner with worsening rank (sliding from #2 to #30). Streak alone is insufficient — rank must be stable or improving. Deterioration >10 positions = exit signal.

### SC-4: Whipsaw Names Can Streak on Both Sides
A ticker may streak on TopGainers AND TopLosers alternating days. Always check whipsaw watchlist before entering streak trades.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect scanner data for streak detection |
| `get_quote(symbol)` | Phase 5 (quality gate), Phase 6 (monitoring) |
| `get_historical_bars(symbol, "2 D", "1 day")` | Phase 5 — prior day low for stop |
| `get_positions()` | Phase 1, Phase 5 |
| `get_portfolio_pnl()` | Phase 1, Phase 2 |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 |
| `get_closed_trades(save_to_db=True)` | Phase 2 |
| `place_order(...)` | Phase 2, Phase 5 |
| `modify_order(...)` | Phase 6 — ratchet stops |
| `get_scanner_dates()` | Phase 3 |

---

## ML/AI Enhancement Opportunities

### Research Papers for Implementation

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **NoxTrader: LSTM Momentum Prediction** | [2310.00747](https://arxiv.org/abs/2310.00747) | LSTM for return momentum prediction — can predict streak sustainability and expected return magnitude |
| **Is Factor Momentum More than Stock Momentum?** | [2009.04824](https://arxiv.org/abs/2009.04824) | Factor momentum works at short lags — validates multi-day streak continuation thesis and suggests factor-level streak tracking |
| **Time-Series Momentum with Deep Multi-Task Learning** | [2306.13661](https://hf.co/papers/2306.13661) | Multi-task learning jointly optimizes momentum portfolio construction AND volatility forecasting — apply to jointly predict streak survival probability + expected return |
| **MTMD: Multi-Scale Temporal Memory** | [2212.08656](https://hf.co/papers/2212.08656) | Temporal memory captures self-similarity in stock trends — day-5 streaks that "look like" historically successful patterns get conviction boost |
| **Intraday Patterns in Cross-Section Returns** | [1005.3535](https://arxiv.org/abs/1005.3535) | Half-hour return continuation lasting 40+ trading days — validates persistence of intraday momentum patterns underlying streaks |
| **When Alpha Breaks: Safe Stock Rankers** | [2603.13252](https://arxiv.org/abs/2603.13252) | Two-level uncertainty for safe deployment during regime shifts — detect when streak model is unreliable and should be paused |
| **Deep Learning for Cross-Section Returns** | [1801.01777](https://arxiv.org/abs/1801.01777) | Neural nets for cross-sectional return prediction — improve rank prediction component of streak signals |

### Hugging Face Models

| Model | Use Case |
|-------|----------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) (252K downloads) | Detect news catalysts sustaining streaks — positive sentiment flow confirms institutional interest |
| [ahmedrachid/FinancialBERT-Sentiment-Analysis](https://hf.co/ahmedrachid/FinancialBERT-Sentiment-Analysis) (22K downloads) | Deeper financial-specific sentiment for streak tickers with earnings/guidance events |

### Proposed Enhancements

1. **Streak Survival Classifier:** Train multi-task model (paper 2306.13661) that jointly predicts: (a) probability streak continues tomorrow, (b) expected return if it does. Features: streak_days, rank trajectory, volume trend, whipsaw history, market regime, sector momentum. Use survival probability as dynamic conviction factor.
2. **Temporal Pattern Matching:** Apply MTMD temporal memory (paper 2212.08656) to encode current streak "shape" (rank trajectory over days) and match against historical successful/failed streaks. Similar-to-successful patterns get +2 conviction, similar-to-failed get -2.
3. **Regime-Aware Streak Filtering:** Implement the "When Alpha Breaks" uncertainty framework (paper 2603.13252) to detect when cross-sectional rank models are unreliable. During detected regime shifts, require score 7+ instead of 5+ for Tier 1.
4. **Factor Momentum Overlay:** Track factor-level momentum (paper 2009.04824) — if the factor driving the streak (e.g., tech momentum, energy rotation) is itself in a positive trend, add +1 conviction.
