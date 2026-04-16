---
noteId: "TODO"
tags: [cron, trading, strategies, rotation, capsize-breakout, scanner-patterns]

---

# 36-Rotation-Cap-Size Breakout — Operating Instructions

## Overview
Captures explosive growth moves when tickers graduate from smaller cap-tier scanners to larger ones (SmallCap→MidCap or MidCap→LargeCap). This crossover indicates rapid market cap expansion driven by volume/price breakouts — the stock is literally outgrowing its classification.

**Data Backing (Report §5):** 1,889 cap-size crossover events across 53 days. Top crossover names: CLSK (23 days), JOBY (22 days), ONDS (20 days), TQQQ (16 days). Small→Large crossovers signal breakout growth phases that often run for a week+.

## Schedule
Runs every 10 minutes during market hours (9:35 AM – 3:50 PM ET) via Claude Code CronCreate.

## Data Sources
- Scanners: `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\`
- Scanner snapshots via MCP: `get_scanner_results(scanner, date, top_n)`
- Strategies: `D:\src\ai\mcp\ib\data\strategies\`
- Lessons: `D:\src\ai\mcp\ib\data\lessons\`
- **Database: `D:\src\ai\mcp\ib\rotation_scanner.db`**

## Strategy ID
`rotation_capsize_breakout`

---

## Known Frequent Crossover Tickers (from Report §5)

| Ticker | Direction | Crossover Days | Classification |
|--------|-----------|---------------|----------------|
| CLSK | Small↔Mid | 23 | Frequent upgrader |
| JOBY | Small↔Mid | 22 | Frequent upgrader |
| ONDS | Small↔Mid | 20 | Frequent upgrader |
| TQQQ | Mid↔Large | 16 | Cap-tier boundary |
| LCID | Small↔Mid | 16 | Frequent upgrader |
| ASTX | Mid↔Large | 15 | Frequent upgrader |
| SPXU | Mid↔Large | 15 | Leveraged ETF |
| RDW | Small↔Mid | 14 | Growth candidate |
| NBIL | Small↔Mid | 13 | Growth candidate |
| HUT | Mid↔Large | 13 | Growth candidate |
| IREX | Small↔Mid | 13 | Growth candidate |
| SLB | Mid↔Large | 12 | Cap-tier boundary |
| IONX | Small↔Mid | 12 | Growth candidate |
| PLTU | Mid↔Large | 11 | Growth candidate |
| OKLL | Small↔Mid | 11 | Growth candidate |
| VZ | Mid↔Large | 11 | Cap-tier boundary |
| UVXY | Mid↔Large | 11 | Leveraged ETF |
| NVTS | Small↔Mid | 9 | Growth candidate |
| CONL | Small↔Mid | 9 | Leveraged ETF |
| SOXL | Mid↔Large | 9 | Leveraged ETF |
| SERV | Small↔Mid | 9 | Growth candidate |
| VELO | Small↔Mid | 9 | Growth candidate |
| UAMY | Small↔Mid | 9 | Growth candidate |
| AXTI | Mid↔Large | 9 | Growth candidate |
| CENX | Mid↔Large | 8 | Growth candidate |

---

## PHASE 0: Job Execution Tracking (ALWAYS FIRST)

1. Open `rotation_scanner.db` — ensure tables exist
2. INSERT into `job_executions` with `job_id="rotation_capsize_breakout"` — capture `exec_id`
3. Track phases, update on completion/failure

---

## PHASE 1: Pre-Trade Checklist

1. **Load lessons** from `data/lessons/` AND `rotation_scanner.db` → `lessons` WHERE `sub_strategy="rotation_capsize_breakout"`
2. **Load active crossover tracking** from `rotation_scanner.db` → `capsize_crossovers` WHERE `traded=0`
3. **Check positions** via `get_positions()` and `get_portfolio_pnl()`
   - Count open: `strategy_positions` WHERE `sub_strategy="rotation_capsize_breakout" AND status="open"`
   - Max 2 concurrent positions — if at limit, skip to Phase 6
4. **Check open orders** via `get_open_orders()`
5. **Verify IB connection**
6. **Load whipsaw watchlist** from `whipsaw_watchlist` table
7. **Determine each symbol's "home" cap tier:**
   - Check previous 5 days of scanner data
   - The cap tier where the symbol appears most frequently = home tier
   - Crossover = appearing on a DIFFERENT tier today
8. UPDATE `job_executions` with `phase_completed=1`

---

## PHASE 2: Risk Management — Cut Losers (MANDATORY)

1. Call `get_portfolio_pnl()` for P&L
2. Query `strategy_positions` WHERE `sub_strategy="rotation_capsize_breakout" AND status="open"`
3. For each position with `pnl_pct <= -7%` (wider stop for multi-day holds):
   a. Check `get_open_orders()` — skip if SELL exists
   b. Place MKT SELL, log, close with `exit_reason="stop_loss_7pct"`
4. **Cap-tier reversion check:** For each open position:
   - Check today's scanners — is the symbol back on ONLY its home cap tier?
   - If reverted to home tier for 2+ consecutive days → crossover thesis broken
   - Prepare exit with `exit_reason="capsize_reverted"`
5. **Reconcile closed trades** via `get_closed_trades(save_to_db=True)`
6. UPDATE `job_executions` with `phase_completed=2`

---

## PHASE 3: Crossover Detection

### Step 1: Collect Scanner Data by Cap Tier
For each scanner type:
- Call `get_scanner_results(scanner="SmallCap-{ScannerType}", date=TODAY, top_n=50)`
- Call `get_scanner_results(scanner="MidCap-{ScannerType}", date=TODAY, top_n=50)`
- Call `get_scanner_results(scanner="LargeCap-{ScannerType}", date=TODAY, top_n=50)`

### Step 2: Detect Crossovers
For each symbol appearing on ANY scanner today:
1. Determine which cap tier(s) it appears in today
2. Compare to its home cap tier (from Phase 1 or prior days' data)
3. **UPGRADE detected** if:
   - Home = SmallCap AND appears on MidCap scanner today → Small→Mid
   - Home = SmallCap AND appears on LargeCap scanner today → Small→Large (rare, very bullish)
   - Home = MidCap AND appears on LargeCap scanner today → Mid→Large
4. **DOWNGRADE detected** if:
   - Home = LargeCap AND appears on MidCap/SmallCap → Large→Mid/Small (bearish, ignore)
   - Home = MidCap AND appears on SmallCap → Mid→Small (bearish, ignore)

### Step 3: Log Crossovers
For each UPGRADE crossover:
- Check `capsize_crossovers` for existing entry
- If exists: increment `crossover_day_count`, update `last_updated`
- If new: INSERT with `direction`, `source_cap`, `target_cap`, `scanner_type`, `crossover_day_count=1`

### Step 4: Identify Trade Signals
Signal fires when:
- `crossover_day_count >= 2` (sustained crossover, not a one-day fluke)
- Direction is UPGRADE (Small→Mid, Mid→Large, or Small→Large)
- Symbol is NOT a leveraged ETF (SPXU, UVXY, SOXL, CONL have structural crossovers, not growth)

UPDATE `job_executions` with `phase_completed=3, candidates_found=N`

---

## PHASE 4: Conviction Scoring

For each crossover candidate:

| Factor | Points | Check |
|--------|--------|-------|
| Small→Mid or Mid→Large upgrade | +3 | Direction check |
| 3+ consecutive crossover days | +3 | `crossover_day_count >= 3` |
| Volume > 2x 20-day average today | +2 | `get_quote` volume check |
| On a gain scanner in the NEW cap tier | +1 | Scanner type is TopGainers/GainSinceOpen |
| Known frequent crossover ticker (list above) | +1 | Symbol in known list |
| Small→Large (skip a tier — rare, explosive) | +2 | Direct 2-tier jump |
| Fundamental catalyst driving crossover (earnings, M&A, revenue growth) | +2 | `classify_catalyst_topic(headline)` returns `is_fundamental_catalyst=true` |
| Sentiment gate approves | +1 | `get_sentiment_gate(symbol)` |
| Volume trajectory sustained (forecast rising) | +1 | `forecast_volume_trajectory(symbol)` returns `volume_trend="rising"` |
| ETF rebalancing / structural crossover suspected (no fundamental catalyst) | -2 | No fundamental catalyst for known ETF |
| Large→Mid or Mid→Small (downgrade) | -5 | NEVER trade downgrades |
| Leveraged ETF crossover | -3 | Structural, not growth |
| On whipsaw watchlist (EXTREME) | -2 | Reversal risk |
| Only 1 crossover day (unconfirmed) | -2 | Could be noise |

### Tier Classification
- **Tier 1 (score 5+):** TRADE
- **Tier 2 (score 3-4):** REJECT
- **Negative:** SKIP

Log all to `scanner_picks` with:
- `sub_strategy="rotation_capsize_breakout"`
- `signal_metadata` JSON: `{"source_cap": "SmallCap", "target_cap": "MidCap", "crossover_days": N, "volume_ratio": X}`

UPDATE `job_executions` with `phase_completed=4, candidates_found=N, candidates_rejected=N`

---

## PHASE 5: Quality Gate & Order Execution

### Quality Gate (MANDATORY)
Call `get_quote(symbol)`. Reject if any fail:

1. **Minimum price:** Last >= $3.00 (slightly higher bar for multi-day holds)
2. **Minimum volume:** Avg daily volume >= 100,000 (need liquidity for multi-day hold)
3. **Maximum spread:** (ask - bid) / last <= 2%
4. **No warrants/units:** Reject R, W, WS, U suffixes
5. **Not a leveraged ETF:** Reject SPXU, UVXY, SOXL, CONL, and similar
6. **Not already held:** Check positions
7. **Not already ordered:** Check open orders
8. **Volume confirmation:** Today's volume must be > 2x 20-day average

### Position Limits
- Max **2** concurrent positions for this sub-strategy
- Max **1** new entry per cycle
- 1 share per ticker

### Order Structure
1. **Entry:** `place_order(symbol, action="BUY", quantity=1, order_type="MKT")` — buy on confirmed crossover
2. **Stop Loss:** STP SELL at entry × 0.93 (7% stop — wider for multi-day hold)
3. **Trailing Target:** No fixed target — trail 10% below peak for multi-day runs

### Post-Order Protection
- Place protective GTC STP SELL at entry × 0.93
- Verify via `get_open_orders()`

### Log to Database
1. `scanner_picks`: symbol, sub_strategy, conviction_score, signal_metadata
2. `orders`: full order details
3. `strategy_positions`: entry details + signal_metadata with crossover info
4. `capsize_crossovers`: UPDATE `traded=1` for this crossover

UPDATE `job_executions` with `phase_completed=5, orders_placed=N`

---

## PHASE 6: Position Monitoring

For each open `rotation_capsize_breakout` position:

1. Call `get_quote(symbol)` for current price
2. INSERT `price_snapshots`
3. Update position extremes

### Cap Tier Monitoring (KEY CHECK)
- Check which cap tier the symbol appears on today
- If still on upgraded tier → thesis intact, hold
- If reverted to home tier for 1 day → warning, tighten stop to 5% below current
- If reverted to home tier for 2+ consecutive days → prepare exit (crossover failed)

### Volume Confirmation
- If daily volume drops below 1x 20-day average → growth momentum may be fading
- Log warning but don't exit (volume can fluctuate day-to-day)

### Trailing Stop (Multi-Day)
- After day 2, activate trailing stop: 10% below highest closing price
- Adjust daily, not intra-day (multi-day strategy, avoid whipsawing out)

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
| Stop loss (-7%) | `stop_loss_7pct` | Auto via STP |
| Cap tier reverted (2+ days back to home) | `capsize_reverted` | MKT SELL |
| Trailing stop (10% below peak close) | `trailing_stop` | Auto via STP |
| Profit protection ratchet | `profit_protection` | Auto via STP |
| EOD close (3:50 PM) | `eod_hold` or `eod_close` | **HOLD OVERNIGHT if profitable + crossover active + not on whipsaw list. Otherwise MKT SELL.** |

### Overnight Hold Rules
This strategy is designed for multi-day holds. Overnight holds are ALLOWED if ALL of:
1. Position is profitable (pnl_pct > 0)
2. Crossover is still active (symbol still on upgraded tier as of last scan)
3. Symbol is NOT on whipsaw watchlist
4. Stop order is in place at the profit protection ratchet level

If ANY condition fails → close at EOD.

### On Exit
1. UPDATE `strategy_positions`: closed, exit details, P&L, hold_duration
2. INSERT `lessons`:
   - source_cap, target_cap, crossover_days at entry, crossover_days at exit
   - lesson_text: "[symbol] capsize breakout: [source]→[target] crossover on day [N]. Held [duration]. Crossover [sustained/reverted]. P&L: [X]%"
3. UPDATE `capsize_crossovers` with trade outcome
4. Compute KPIs

UPDATE `job_executions` with `phase_completed=7, lessons_logged=N`

---

## PHASE 8: Run Summary & KPIs

### KPIs

| KPI | Target |
|-----|--------|
| Win Rate | > 50% |
| Avg Win | > 5% (multi-day holds should capture larger moves) |
| Avg Loss | < -5% |
| Profit Factor | > 1.5 |
| Expectancy | > 1.0% |
| Avg Hold Duration | 2-7 days |
| Crossover Sustainability Rate | % of entered crossovers that lasted 3+ more days | > 60% |
| Reversion Exit Rate | % of exits from capsize_reverted | < 25% |
| Overnight Hold Win Rate | % of overnight holds profitable next day | > 65% |
| Max Single-Trade Gain | Track best performers | Informational |
| MFE/MAE Ratio | > 2.5 (multi-day runs should have high edge efficiency) |

### Circuit Breakers
- 4 consecutive losses → disable for rest of day
- Crossover sustainability rate < 40% over last 15 entries → pause and review crossover detection
- If 3 consecutive overnight holds lose money → stop holding overnight, exit at EOD

UPDATE `job_executions` with `phase_completed=8, kpis_computed=N`

---

## Lessons Pre-Loaded

### CB-1: Only Trade Upgrades, Never Downgrades
Large→Mid or Mid→Small crossovers signal deterioration, not opportunity. A stock shrinking into a smaller tier is losing institutional interest. Hard rule: upgrades only.

### CB-2: Leveraged ETFs Crossover Structurally
SPXU, UVXY, SOXL, CONL appear across cap tiers due to their leveraged structure and AUM fluctuations, NOT because of fundamental growth. Exclude all leveraged ETFs.

### CB-3: Volume is the Crossover Catalyst
A stock doesn't graduate to a larger cap tier just because its price went up — it needs volume expansion to appear on the larger tier's scanners. 2x average volume is the minimum confirmation that the crossover is real.

### CB-4: 2-Day Confirmation Filters Noise
A single-day crossover can happen from a one-day spike. Requiring 2+ consecutive crossover days eliminates 60%+ of false signals. The best crossovers (CLSK 23 days, JOBY 22 days) persist for weeks.

### CB-5: Wider Stops for Multi-Day Holds
Standard 5% stop is too tight for a multi-day strategy — normal daily volatility can trigger it. Use 7% initial stop, then tighten via profit protection ratchet as gains accumulate.

---

## MCP Tools Used

| Tool | When Called |
|------|------------|
| `get_scanner_results(scanner, date, top_n)` | Phase 3 — collect all cap tier scanner data |
| `get_quote(symbol)` | Phase 5 (quality gate + volume check), Phase 6 (monitoring) |
| `get_historical_bars(symbol, "5 D", "1 day")` | Phase 1 (home cap determination), Phase 5 (volume avg) |
| `calculate_indicators(symbol, indicators=["ATR"], ...)` | Phase 5 — ATR for stop refinement |
| `get_positions()` | Phase 1, Phase 5 |
| `get_portfolio_pnl()` | Phase 1, Phase 2 |
| `get_open_orders()` | Phase 1, Phase 2, Phase 5, Phase 6 |
| `get_closed_trades(save_to_db=True)` | Phase 2 |
| `place_order(...)` | Phase 2, Phase 5 |
| `modify_order(...)` | Phase 6 — trailing stops |
| `get_scanner_dates()` | Phase 3 |
| `classify_catalyst_topic(headline)` | Phase 4 — classify crossover catalyst |
| `get_sentiment_gate(symbol)` | Phase 4 — sentiment conviction modifier |
| `forecast_volume_trajectory(symbol)` | Phase 5 — volume sustainability check |

---

## ML/AI Enhancement Opportunities

### Research Papers for Implementation

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Survivorship Bias in Small-Cap Indices** | [2603.19380](https://arxiv.org/abs/2603.19380) | Quantifies survivorship bias in small-cap — critical for understanding that crossover signals may reflect index rebalancing, not genuine growth |
| **Intraday Order Dynamics by Market Cap** | [2502.07625](https://arxiv.org/abs/2502.07625) | Markov chain model of order transition dynamics across High/Medium/Low cap stocks — can model the probability of sustained cap-tier transitions |
| **Sector Rotation by Factor Model** | [2401.00001](https://hf.co/papers/2401.00001) | Factor model framework for sector/size rotation — applicable to predicting which cap tiers are favored in current regime |
| **TradeFM: Generative Foundation Model for Trade-Flow** | [2602.23784](https://hf.co/papers/2602.23784) | 524M-param transformer learns cross-asset trade representations — could detect cap-tier regime shifts from aggregate flow patterns |
| **Structured Event Representation for Returns** | [2512.19484](https://arxiv.org/abs/2512.19484) | LLM-extracted event features from news predict returns — identify fundamental catalysts driving crossover (earnings, contracts, M&A) |
| **Stockformer: Price-Volume Factor Model** | [2401.06139](https://hf.co/papers/2401.06139) | Graph embedding captures multi-stock relationships — detect when peer stocks are also crossing tiers (sector-wide crossover) |

### Hugging Face Models

| Model | Use Case |
|-------|----------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) (252K downloads) | Detect news catalysts driving crossover — fundamental catalysts (earnings, contracts) produce more sustainable crossovers |
| [nickmuchi/finbert-tone-finetuned-finance-topic-classification](https://hf.co/nickmuchi/finbert-tone-finetuned-finance-topic-classification) | Classify crossover catalyst type — M&A/earnings crossovers sustain better than technical crossovers |
| [soleimanian/financial-roberta-large-sentiment](https://hf.co/soleimanian/financial-roberta-large-sentiment) (3.4K downloads) | Deep sentiment analysis on corporate filings/ESG for fundamental crossover thesis validation |

### Proposed Enhancements

1. **Markov Transition Probability Model:** Use the Markov chain framework (paper 2502.07625) to compute transition probabilities between cap tiers. Replace fixed "2+ day confirmation" with dynamic sustainability probability. If P(stay in new tier) > 70%, enter immediately on day 1 with high conviction.
2. **Peer Crossover Detection:** Apply graph-based multi-stock modeling (Stockformer, paper 2401.06139) to detect when multiple stocks in the same sector are crossing tiers simultaneously. Sector-wide crossover = +3 conviction (industry rotation), single-stock crossover = standard scoring.
3. **Fundamental Catalyst Filter:** Use LLM event extraction (paper 2512.19484) + sentiment model to identify news catalysts driving crossover. Categories: (a) Fundamental (earnings, contracts, FDA) = +2 conviction, (b) Technical (volume only) = +0, (c) Index rebalancing (paper 2603.19380) = -2 conviction (temporary, will revert).
4. **Size Factor Regime Overlay:** Track the small-cap vs. large-cap factor spread (paper 2401.00001). When small-cap factor is outperforming, Small→Mid crossovers are more reliable. When large-cap is outperforming, Mid→Large crossovers are more reliable. Add as regime-aware conviction modifier.
