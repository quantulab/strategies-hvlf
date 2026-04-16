---
noteId: "4c6bc73038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 1: Momentum Surfing with Trailing Stops

## Objective
Ride multi-day momentum breakouts on correlated sector moves using basket-level risk management.

## Universe
Stocks appearing on GainSinceOpenLarge OR PctGainLarge with >5x average daily volume.
Current candidates: IONX, IONL, SMU, ALMU, QUBX

## Entry Rules
1. Stock must appear on at least 2 of: GainSinceOpenLarge, PctGainLarge, HotByVolumeLarge
2. Price must be above prior day's high
3. Volume in first 30 minutes must exceed 50% of prior full-day volume
4. Enter at the first 5-minute candle that closes above the opening range (first 15 min high)
5. If entering after 10:30 AM, price must still be within 5% of the day's high (no chasing deep pullbacks)

## Position Sizing
- Max 2% of account per individual position
- Max 8% of account across the basket (since these are correlated)
- If 5 names qualify, allocate 1.6% each

## Stop Loss Rules
- Initial stop: 10% below entry price
- Trailing stop: 15% below the highest closing price since entry
- Basket stop: If 3 out of 5 positions hit their individual stops, close all remaining positions immediately

## Take Profit Rules
- Scale out 25% at +20% from entry
- Scale out another 25% at +40% from entry
- Trail remaining 50% with the 15% trailing stop
- Full exit if stock closes below its 5-day moving average after being above it for 2+ days

## Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

**Note: This is a minimum floor. If the strategy's own 15% trailing stop is tighter than the ratchet level below, use the strategy's trailing stop instead.**

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
- Hold minimum 1 day (no same-day exit unless stop is hit)
- Maximum hold period: 5 trading days
- If the stock gaps down >10% at next open, exit at market immediately (do not wait for stop)

## Risk Filters
- Do NOT enter if the stock has already moved >50% intraday (too extended)
- Do NOT enter if the stock is on any PctLoss scanner simultaneously
- Do NOT enter if average daily volume over past 20 days is <50,000 shares (illiquid)
- Do NOT add to a losing position
