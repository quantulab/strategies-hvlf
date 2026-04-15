---
noteId: "6e130b0038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 5: Pairs Trade — Correlated Sector Play

## Objective
Exploit relative value between two highly correlated stocks by going long the stronger and short the weaker, neutralizing market/sector risk.

## Universe
Pairs of stocks from the same sector that move in lockstep.
Current candidates: IONX / IONL (correlated names, similar sector, move together)

## Pair Selection Rules
1. Both stocks must appear on the same scanner category (e.g., both on PctGainLarge)
2. 20-day rolling correlation must be >0.80
3. Both stocks must have average daily volume >100K shares
4. Price ratio (Stock A / Stock B) must be at a 1-standard-deviation extreme from its 20-day mean

## Entry Rules
1. Calculate the price ratio: Ratio = Price_A / Price_B
2. Calculate 20-day mean and standard deviation of the ratio
3. **Long the underperformer / Short the outperformer** when ratio deviates >1 standard deviation from mean
4. Enter both legs simultaneously — never have a naked leg
5. Dollar-neutral: equal dollar amounts on each side (e.g., $1,000 long IONX, $1,000 short IONL)

## Position Sizing
- Max 3% of account per pair (1.5% each leg)
- Only 1 active pair at a time
- If one leg requires >$5,000 notional, skip the trade

## Stop Loss Rules
- If the ratio moves >2.5 standard deviations from mean (against you), close both legs
- If either leg is halted, immediately close the other leg
- Maximum loss per pair: 2% of account
- If correlation drops below 0.60 on a 5-day basis, close the trade (relationship is breaking)

## Take Profit Rules
- Close both legs when ratio returns to its 20-day mean
- If ratio overshoots the mean by >0.5 standard deviations in your favor, close immediately (don't get greedy)
- Take profit within 5 trading days regardless — pairs revert quickly or not at all

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
- Maximum hold: 5 trading days
- Review the ratio daily at close — if it hasn't started reverting by day 3, close the trade
- Do not enter a pair trade in the last 30 minutes of trading (spreads widen)

## Risk Filters
- Do NOT pair stocks with different market caps (>5x difference in market cap)
- Do NOT pair if either stock has earnings in the next 5 days
- Do NOT pair if either stock has a pending FDA decision or binary catalyst
- If short borrow cost on either leg exceeds 30% annualized, skip
- Do NOT enter if the ratio deviation is caused by a stock-specific catalyst (news on one but not the other)
