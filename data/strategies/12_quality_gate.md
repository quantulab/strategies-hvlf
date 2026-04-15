---
noteId: "7dac1b9038ea11f1aa17e506bb81f996"
tags: []

---

# Strategy 12: Quality Gate Filter

**ID:** `quality_gate`
**Type:** Pre-entry filter (overlay — runs before every order)
**Added:** 2026-04-15

## Problem

On 2026-04-15, the system took 25 trades with a 40% win rate. Analysis revealed:
- Sub-$1 stocks: 25% win rate, -3.30% avg P&L
- $1-$5 stocks: 50% win rate, +1.36% avg P&L
- $5-$10 stocks: 0% win rate, -7.80% avg P&L
- $10+ stocks: 62.5% win rate, +4.73% avg P&L

The system was taking too many low-quality trades on illiquid penny stocks and warrants.

## Rules

### Hard Filters (instant reject)
| Filter | Threshold | Rationale |
|--------|-----------|-----------|
| Minimum price | $2.00 | Sub-$1 wins only 25% of the time |
| Minimum avg volume | 50,000 shares/day | Illiquid names can't be exited cleanly |
| Maximum spread | 3% of last price | Wide spreads guarantee losses on entry |
| Warrant/unit suffix | Reject R, W, WS, U | Different dynamics, lower liquidity |

### Conviction Filter
| Filter | Threshold | Rationale |
|--------|-----------|-----------|
| Minimum conviction score | 5 (Tier1 only) | Tier2 (3-4) had too many false signals |
| Maximum positions | 10 | Forces selectivity, prevents scatter-shooting |

### Confirmation Filter
| Price Range | Rule | Rationale |
|-------------|------|-----------|
| $5-$10 | Must appear on 2+ consecutive scan runs | 0% win rate on first-pop entries in this bracket |

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

## Expected Impact
- Trades per day: 25 → ~8-10
- Win rate: 40% → 60-65%
- Avg winner: ~8.8% (unchanged)
- Avg loser: smaller (higher quality entries)
