---
noteId: "660d5cd038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 4: Cut the Losers Immediately

## Objective
Identify positions with broken fundamentals or catastrophic price action and exit without hesitation to preserve capital.

## Universe
All current portfolio holdings.
Current candidates: CTNT, HOTH

## Exit Trigger Rules (if ANY one is met, sell immediately)
1. **Single-day crash >50%:** Stock drops >50% in one trading session — this signals a fundamental event (delisting, fraud, offering), not normal volatility
2. **Sustained downtrend:** Stock is down >30% from entry over 10+ trading days with no recovery above the 5-day moving average
3. **Volume spike on selloff:** Stock drops >20% on volume >10x the 20-day average — institutions are dumping
4. **Price below $0.50 and declining:** For stocks that were purchased above $1.00, a drop below $0.50 signals potential delisting risk
5. **Appears on LossSinceOpen AND PctLoss AND HotByVolume simultaneously:** Triple-scanner loss confirmation means the market is actively rejecting the stock

## Execution Rules
- Place a market sell order, not a limit order — priority is getting out, not optimizing price
- If the stock is halted, place a sell order to execute when trading resumes
- Do NOT average down on a stock that triggered an exit rule
- Do NOT set a "mental stop" and wait — execute the moment a trigger fires

## Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

**Note: This profit protection applies to the underlying position regardless of which strategy triggered the exit signal.**

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

## Post-Exit Rules
- Add the ticker to a 30-day blacklist — no re-entry for 30 calendar days
- Log the reason for exit and the trigger that fired
- Review the entry criteria that selected this stock — was the scanner signal a false positive?

## Exception (do NOT exit if)
- The stock is halted for a positive catalyst (merger, acquisition announcement) — wait for resumption
- The drop is market-wide (>90% of holdings are down similarly) rather than stock-specific

## Current Action Items
- **CTNT:** SELL — dropped 82% today ($1.68→$0.30), volume 2M vs normal 10K. Triggered rules 1, 3, 4, and 5.
- **HOTH:** SELL — down 37% over the month ($1.04→$0.66), triggered rule 2. Briefly spiked on Apr 14 but failed to hold.
