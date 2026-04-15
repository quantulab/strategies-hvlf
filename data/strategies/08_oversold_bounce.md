---
noteId: "8911989038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 8: Bounce Play on Oversold Names

## Objective
Buy deeply oversold stocks after they show confirmed bottoming patterns, targeting a reversion to a short-term mean.

## Universe
Stocks that have dropped >40% from their 20-day high and are now showing a bottoming pattern.
Current candidates: NCI (crashed from $5.85 to $0.49), OKLL (dropped from $9.45 to $5.14), GPRO (stabilizing after decline)

## Pre-Screening Rules
1. Stock must be down >40% from its 20-day high
2. Stock must have average daily volume >200K (liquid enough to exit)
3. Stock must NOT be on any PctLoss scanner today (selling pressure must have subsided)
4. The decline must have occurred over >3 trading days (not a single-day crash — those are Strategy 4 exits)

## Entry Rules
1. **Bottoming pattern required** — at least ONE of:
   - Higher low on the daily chart (today's low > yesterday's low, and yesterday was a down day)
   - Bullish engulfing candle on the daily chart (today's body fully engulfs yesterday's body)
   - Price holds above prior support level on a retest with declining volume
2. Enter at the close of the confirmation candle OR the next morning's open if the candle confirmed late
3. Price must be above the lowest low of the past 5 days at time of entry
4. RSI(14) must be below 35 (confirming oversold condition)

## Position Sizing
- Max 1% of account per bounce trade (these are catching knives — small size)
- Max 2 bounce plays open simultaneously
- Never allocate >3% of account to this strategy total

## Stop Loss Rules
- Stop below the most recent swing low (the bottom of the pattern)
- If stop distance >15% from entry, reduce size to keep risk at 1% of account
- If stock makes a new all-time low after entry, exit immediately regardless of stop level

## Take Profit Rules
- Target 1: Sell 50% at the 10-day moving average (mean reversion target)
- Target 2: Sell remaining 50% at the 20-day moving average
- If price stalls at Target 1 for 2+ days, exit remaining at market

## Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +10% to +20% | Breakeven (entry price) |
| +20% to +50% | +10% above entry |
| +50% to +100% | MAX(+25% above entry, 20% below peak price) |
| >+100% | Trail 25% below peak price |

- Stops only ratchet UP, never down
- Checked every monitoring cycle (Phase 6)
- Use `modify_order` to raise existing stop orders
- Log adjustments with `strategy_id = "profit_protection"`

## Time Rules
- Maximum hold: 10 trading days
- If the stock has not reached Target 1 within 5 days, exit at market (thesis is wrong)
- Review daily: if the stock makes a lower low after entry, exit next open

## Risk Filters
- Do NOT buy if the drop was caused by: delisting notice, SEC investigation, fraud allegation, reverse split announcement
- Do NOT buy if the company has filed for bankruptcy or is in default
- Do NOT buy if daily volume has dried up to <50K (no one is buying)
- Do NOT buy if insiders have been selling in the past 30 days (SEC Form 4 filings)
- Check news — if there is a clear fundamental reason for the decline that hasn't resolved, skip
