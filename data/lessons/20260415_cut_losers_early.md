---
noteId: "cut_losers_early_20260415"
tags: [risk-management, stop-loss, portfolio]

---

# Lesson — Cut Losers Early at -5%

## Date: 2026-04-15
## Context: 24-position portfolio with small-cap/micro-cap stocks, manually monitored throughout the session

---

## What Happened
Portfolio started the session with 24 positions and an overall P&L of -$2.90 (-1.29%). A handful of positions were dragging down the entire portfolio — NICM (-12.17%), WGRX (-9.54%), MNTS (-7.23%), CTNT (-23.12%). After liquidating all positions losing more than 5% in multiple rounds, the portfolio recovered from -$2.90 to +$6.03 (+3.79%) with only 12 remaining long positions.

## Key Observations
1. **A few deep losers poison the whole portfolio.** Out of 24 positions, 6 were losing >5%, and they accounted for most of the portfolio's unrealized loss.
2. **Cutting losers freed capital and improved clarity.** Fewer positions meant easier monitoring and a cleaner P&L picture.
3. **Losers kept losing.** Positions like NICM went from -8.95% to -12.17% between checks. Stocks that are already weak tend to stay weak intraday.
4. **Sell orders can create accidental shorts.** MNTS and NXXT ended up as short positions (-1 share) after sell orders filled — likely due to order duplication or timing. This needs a safeguard.

## Rules
- **Hard stop at -5%.** Liquidate any position that reaches -5% unrealized P&L. Do not wait for recovery on intraday momentum plays.
- **Check for existing sell orders before placing new ones.** Avoid accidental short positions from duplicate sell orders.
- **Fewer positions = better risk control.** 10-15 concentrated positions are more manageable than 20+ thinly spread bets.

## How to Apply
- Implement an automated -5% stop-loss check that runs on every P&L refresh.
- Before placing a SELL order, query open orders for that symbol to prevent duplicates.
- Add a position-count cap (e.g., max 15) to the scanner entry logic.
