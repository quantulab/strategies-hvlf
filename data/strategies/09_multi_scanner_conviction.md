---
noteId: "951b1bc038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 9: Scanner Cross-Reference Conviction Filter

## Objective
Build a high-conviction watchlist by only trading stocks that appear on 3+ different scanners simultaneously, filtering out noise from single-scanner signals.

## Universe
All stocks across all 10 scanners.
Current multi-scanner hits: BIRD (3), VSA (3), NCI (3), IMMP (3), CTNT (3), ECIA (3)

## Scoring Rules
Assign points based on scanner appearances:
1. **+2 points:** Appearing on PctGainLarge or PctGainSmall (strongest momentum signal)
2. **+2 points:** Appearing on HotByVolumeLarge or HotByVolumeSmall (volume confirmation)
3. **+1 point:** Appearing on GainSinceOpenLarge or GainSinceOpenSmall (directional confirmation)
4. **-2 points:** Appearing on ANY loss scanner (PctLoss, LossSinceOpen)
5. **-1 point:** Appearing on loss AND gain scanners simultaneously (unstable)

## Conviction Tiers
- **Tier 1 (Score 5+):** Full position size, highest priority
- **Tier 2 (Score 3-4):** Half position size
- **Tier 3 (Score 1-2):** Watchlist only, do not trade
- **Negative Score:** Blacklist — do not trade under any strategy

## Entry Rules
1. Stock must score Tier 1 or Tier 2
2. Must appear on 3+ DIFFERENT scanner categories (not the same scanner on repeat checks)
3. At least one appearance must be on a Volume scanner (volume confirms the move)
4. At least one appearance must be on a Gain scanner (direction confirms)
5. Enter using the rules of whichever primary strategy (1-6) best fits the setup
6. Multi-scanner confirmation upgrades position size by 25% vs the primary strategy's default

## Position Sizing
- Tier 1: Primary strategy size + 25% bonus
- Tier 2: Primary strategy size (no bonus)
- Maximum across all Tier 1 trades: 10% of account

## Monitoring Rules
1. Re-score every 30 minutes during market hours
2. If a stock's score drops from Tier 1 to Tier 2 while holding, reduce position by 25%
3. If a stock's score goes negative while holding, exit immediately
4. If a stock drops OFF all scanners while holding, tighten stop to 5%

## Take Profit Rules
- Follow the primary strategy's take profit rules
- Bonus rule: if the stock appears on 4+ scanners at the same time, extend hold by 1 day before taking profit (extra conviction)

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

## Daily Workflow
1. 9:35 AM — Pull all 10 scanners
2. 9:40 AM — Cross-reference and score all unique tickers
3. 9:45 AM — Rank by score, identify Tier 1 and Tier 2 candidates
4. 9:50 AM — Check which primary strategy (1-6) applies to each candidate
5. 10:00 AM — Execute entries per primary strategy rules with conviction-adjusted sizing
6. Repeat scoring at 10:30, 11:00, 11:30, 12:00

## Current Scoring (2026-04-15)
| Ticker | Scanners | Score | Tier |
|--------|----------|-------|------|
| BIRD | GainLarge(+1), HotVolLarge(+2), PctGainLarge(+2) | 5 | Tier 1 |
| IMMP | HotVolSmall(+2), PctGainSmall(+2), LossSmall(-2), conflict(-1) | 1 | Tier 3 |
| NCI | GainSmall(+1), HotVolSmall(+2), PctGainSmall(+2) | 5 | Tier 1 |
| VSA | GainLarge(+1), HotVolLarge(+2), PctGainLarge(+2) | 5 | Tier 1 |
| CTNT | HotVolSmall(+2), LossSmall(-2), PctLossSmall(-2), conflict(-1) | -3 | Blacklist |
| ECIA | GainSmall(+1), HotVolSmall(+2), PctGainSmall(+2) | 5 | Tier 1 |
