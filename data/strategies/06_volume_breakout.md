---
noteId: "78896b1038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 6: Volume Breakout Scanner Strategy

## Objective
Systematically buy stocks on their first appearance on HotByVolume scanners when volume confirms a new directional move.

## Universe
All stocks appearing on HotByVolumeLarge or HotByVolumeSmall scanners for the first time in 5 days.

## Scanning Rules (Pre-Entry)
1. Run scanner check every 5 minutes from 9:35 AM to 11:00 AM
2. Flag any stock that appears on HotByVolume for the FIRST time today (was not on the scanner yesterday)
3. The stock must also have positive price action (current price > prior close)
4. Current volume must be >3x the 20-day average daily volume at the same time of day

## Entry Rules
1. Stock must be newly appearing on HotByVolume (not a repeat from prior days)
2. Price must be UP for the day (no volume breakouts on selloffs — that's distribution)
3. Wait for the first 5-minute consolidation (a candle with range < 50% of the prior candle)
4. Enter on the break above the consolidation candle's high
5. Entry must occur before 11:00 AM
6. Spread must be <2% of share price at time of entry

## Position Sizing
- Max 1.5% of account per trade
- Max 3 volume breakout trades open simultaneously
- Scale position based on relative volume: >10x avg vol = full size, 3-10x = half size

## Stop Loss Rules
- Stop below the consolidation candle's low
- If stop distance is >8% from entry, reduce size to keep risk at 1.5% of account
- Time stop: if position is not profitable within 45 minutes, exit at market

## Take Profit Rules
- Target 1: Sell 33% at +1R (1x the initial risk)
- Target 2: Sell 33% at +2R
- Trail final 33% with a stop at the most recent 5-minute swing low
- If volume drops below 1x average on a 15-minute basis while position is open, exit remaining

## Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +5% to +10% | Breakeven (entry price) |
| +10% to +20% | Trail 2% below current price |
| +20% to +50% | MAX(trail 2% below current, +10% above entry) |
| +50%+ | Trail 3% below peak price |

- Stops only ratchet UP, never down
- Checked every monitoring cycle (Phase 6)
- Use `modify_order` to raise existing stop orders
- Log adjustments with `strategy_id = "profit_protection"`

## Time Rules
- Day trade only — close all positions by 3:30 PM
- Exception: if the stock closes at or near its high of day with >5x average volume, may hold overnight with a stop at the day's low
- No entries after 11:00 AM (the morning volume edge dissipates)

## Risk Filters
- Skip if the stock has a market cap <$10M (too illiquid for reliable execution)
- Skip if the stock is already up >30% when first spotted (too late)
- Skip if the stock appeared on any PctLoss scanner in the past 2 days (false breakout risk)
- Skip if >50% of the volume is from a single block trade (institutional dump/load)
