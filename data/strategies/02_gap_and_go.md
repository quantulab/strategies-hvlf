---
noteId: "5432227038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 2: Gap-and-Go Day Trade

## Objective
Capture intraday continuation after a massive gap up by entering on the first pullback to VWAP.

## Universe
Stocks gapping up >50% premarket with volume >1M shares in premarket.
Current candidates: BIRD, IMMP, NCI

## Entry Rules
1. Stock must gap up >50% from prior close
2. Premarket volume must be >1M shares
3. Wait for the first pullback to VWAP after market open
4. Enter ONLY if price bounces off VWAP with a bullish 1-minute candle (close > open, close in upper 1/3 of range)
5. Entry must occur between 9:35 AM and 10:30 AM — no entries after 10:30
6. Price at entry must be above the premarket low

## Position Sizing
- Max 1% of account per trade (these are high-volatility)
- Only 1 gap-and-go trade at a time — no stacking

## Stop Loss Rules
- Hard stop: Below VWAP by 2% at time of entry
- If price drops below VWAP and stays below for 3 consecutive 1-minute candles, exit immediately (do not wait for hard stop)
- Maximum loss per trade: 1% of account — if stop distance exceeds this, reduce share count

## Take Profit Rules
- Target 1: 1:1 risk/reward — sell 50% of position
- Target 2: 2:1 risk/reward — sell remaining 50%
- If price makes a new high of day after Target 1, move stop to breakeven on remaining shares
- If price stalls for >15 minutes without making a new high after 11:00 AM, exit remaining position

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
- ALL positions closed by 3:30 PM — no overnight holds
- If not filled by 10:30 AM, cancel the setup for the day
- No re-entry on the same stock if stopped out

## Risk Filters
- Do NOT trade if the stock has a history of halts (check for >3 halts in past 30 days)
- Do NOT trade if spread is >3% of share price
- Do NOT trade if the gap is caused by a secondary offering or dilution announcement (check news)
- Skip if the stock is already on LossSinceOpen scanners at time of entry
