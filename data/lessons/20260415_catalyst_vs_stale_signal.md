---
noteId: "catalyst_vs_stale_20260415"
tags: [signal-freshness, catalyst, conviction, entry-rules]

---

# Lesson — Not All Stale Signals Are Dead: Catalyst Plays vs Momentum Fades

## Date: 2026-04-15
## Context: BIRD was rejected 12+ times throughout the day despite scoring Tier 1 (5) on every cycle. It was the #1 stock on 3 scanners simultaneously all session.

---

## What Happened

BIRD (Allbirds) pivoted to AI compute infrastructure ("NewBird AI") with $50M financing announced pre-market. The stock:
- Closed prior day at $2.49
- Opened at $6.82 (+174% gap)
- Ran to $24.31 intraday (+876%)
- Consolidated at ~$18 (+626%) with 140M shares traded (2,700x normal volume)

Our system rejected BIRD on every single scan cycle because Lesson 1 ("Scanners Show Past, Not Future") auto-rejects any stock on a scanner for >10 minutes. BIRD was rank #0 on GainSinceOpen, HotByVolume, AND PctGain the entire session.

**Result: We missed the biggest mover of the day.** BIRD was the only consistent Tier 1 candidate all day, and we left it on the table.

## The Problem

Lesson 1 was written after buying stocks like CTNT at rank #1 after an 82% crash — a stock that was *losing* and topped the scanner because the drop was so large. That's a fundamentally different situation from BIRD.

The stale signal rule treats all long-duration scanner appearances the same. But there are two very different scenarios:

### Scenario A: Stale Momentum (REJECT) — What Lesson 1 Was Written For
- Stock ran 50-100% on no news or speculative momentum
- Already fading from highs when we see it
- Volume declining from peak
- Wide spreads, thin order book
- Price below VWAP or below 50% of intraday range
- Examples today: CTNT (-26.76%), VSA (-8.48%)

### Scenario B: Multi-Day Catalyst (TRADE) — What BIRD Was
- Real fundamental catalyst (corporate pivot, FDA, M&A, major financing)
- Volume is 1000x+ normal — institutional, not retail
- Price holding above 50% of intraday range (consolidating, not fading)
- Tight spreads (<1%) showing genuine two-sided liquidity
- News confirms multi-day story (analyst coverage coming, follow-up announcements likely)
- Examples today: BIRD (+626%, AI pivot), Nvidia quantum catalyst (IONX/IONL)

## Rules

**Do NOT auto-reject Tier 1 stocks that have been on scanners all session if they pass the Catalyst Confirmation Check:**

1. **Tier 1 conviction** — must score 5+ (on 3+ different scanner categories)
2. **Real catalyst confirmed** — check `get_news_headlines`. Must be a fundamental event (pivot, M&A, FDA, financing, partnership). Pure momentum/squeeze does NOT qualify
3. **Volume >1000x 20-day average** — institutional-scale participation
4. **Price holding >50% of intraday range** — `(current - low) / (high - low) > 0.50`. If it's crashed below 50%, the move is over
5. **Spread <1%** — tight liquidity confirms real two-sided market
6. **Price >$2** — quality gate still applies

If ALL 6 pass → override the stale signal rejection. Enter as a "catalyst hold" trade.

## How to Apply

### Before rejecting a Tier 1 stock as "stale":
1. Check if it has a news catalyst via `get_news_headlines`
2. If yes, run the full 6-condition Catalyst Confirmation Check
3. If all pass, enter on a pullback to consolidation support:
   - **Entry**: first 5-min candle holding above consolidation low, NOT chasing the high
   - **Stop**: below intraday consolidation low or 1.5x ATR
   - **Target**: trailing stop at 15% below the intraday high
   - **Max hold**: 2 days (multi-day catalyst decay risk)
4. Log as `strategy_id = "catalyst_hold"` with override reason

### Key distinction to remember:
- **Fading momentum + stale scanner = REJECT** (Lesson 1 still applies)
- **Confirmed catalyst + massive volume + price holding = TRADE** (new override)

## Metrics to Track
- Win rate for catalyst override trades vs standard Tier 1 trades
- Average P&L for catalyst holds vs momentum entries
- How often catalyst stocks hold >50% of range by end of day
- False positive rate: how many "catalyst" overrides were actually momentum fades

## Today's BIRD Numbers (for reference)
- Prior close: $2.49
- Open: $6.82 (+174% gap)
- High: $24.31
- Low: $6.11
- Close area: ~$18.07 (+626%)
- Volume: 140.5M (avg 52K = 2,700x)
- ATR(14): $1.87 (was $0.33)
- RSI(14): 92.22
- Spread: 0.4%
- Catalyst: Allbirds pivot to AI compute "NewBird AI" + $50M financing
- Score: 5 (Tier 1) — GainSinceOpen #0, HotByVolume #0, PctGain #0
