---
noteId: "a1e4457038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 10: Overnight Gap Risk Management

## Objective
Protect portfolio from overnight gap risk when positions have experienced large intraday moves, by systematically reducing exposure and setting protective orders.

## Universe
All open portfolio positions.

## Trigger Rules (when to activate this strategy)
This strategy activates when ANY of the following occur:
1. Any single position is up or down >20% intraday
2. The portfolio as a whole is up or down >10% intraday
3. More than 50% of positions moved >10% in the same direction (correlated risk)
4. Any position has volume >10x its 20-day average (abnormal activity)

## Position Reduction Rules
When triggered, apply these reductions BEFORE market close:

### For positions UP >50% from entry
- Sell 50% of the position (lock in profit)
- Set a GTC stop-loss on the remaining 50% at breakeven (entry price)

### For positions UP 20-50% from entry
- Sell 25% of the position
- Set a GTC stop-loss on the remaining 75% at 10% below current price

### For positions UP 0-20% from entry
- No reduction required
- Set a GTC stop-loss at entry price minus 5% (small cushion)

### For positions DOWN from entry
- If down >15%: evaluate against Strategy 4 (Cut Losers) rules — sell if triggered
- If down 5-15%: set a GTC stop-loss at 20% below entry (give room for recovery)
- If down 0-5%: set a GTC stop-loss at 10% below entry

## Correlated Risk Rules
When 3+ positions are from the same sector or moved in the same direction >20%:
1. Calculate total dollar exposure to the correlated group
2. If >30% of portfolio is in the correlated group, reduce each position proportionally until group is <25% of portfolio
3. Set a basket stop: if any 2 of the correlated positions drop >10% from today's close, exit all positions in the group at market open

## Order Placement Rules
1. All protective stops must be placed as GTC (Good Till Cancelled) orders
2. Use stop-market orders, not stop-limit (priority is execution, not price)
3. Place all stops at least 15 minutes before market close (3:45 PM)
4. For stocks that trade after hours, consider setting AH stops if the platform supports it
5. Review and adjust all stops at 9:30 AM the next morning based on premarket action

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

## Morning-After Rules (next trading day)
1. Check premarket prices for all holdings at 9:00 AM
2. If any stock is gapping down >10% premarket, place a market sell order for the open
3. If any stock is gapping UP >10% premarket, move stop to breakeven
4. Cancel any stops that are now >20% below current price (too far away to be useful)
5. Re-evaluate using Strategy 9 (multi-scanner scoring) at 9:35 AM

## Current Action Items (2026-04-15)
| Position | Today's Move | Action |
|----------|-------------|--------|
| IONX | +29% | Sell 25%, stop at $33.50 |
| IONL | +29% | Sell 25%, stop at $17.50 |
| SMU | +31% | Sell 25%, stop at $13.30 |
| ALMU | +22% | Sell 25%, stop at $15.00 |
| QUBX | +24% | Sell 25%, stop at $10.90 |
| NICM | +34% | Sell 25%, stop at $8.00 |
| OKLL | +23% | Sell 25%, stop at $8.50 |
| ASPI | +14% | No reduction, stop at $5.10 |
| IMMP | +159% | Sell 50%, stop remaining at entry ($0.84) |
| GPRO | +23% | No reduction, stop at $0.93 |
| CTNT | -82% | SELL ALL (Strategy 4) |
| HOTH | -4% (month: -37%) | SELL ALL (Strategy 4) |
