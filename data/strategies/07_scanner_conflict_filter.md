---
noteId: "8037f89038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 7: PctGain to PctLoss Rotation Warning System

## Objective
Detect stocks showing extreme two-way volatility by monitoring cross-scanner appearances, then either avoid them or tighten risk controls.

## Universe
All stocks currently held or on watchlist.

## Detection Rules
A stock triggers this filter when it appears on CONFLICTING scanners simultaneously:
1. **Level 1 (Yellow):** Stock on a Gain scanner AND a HotByVolume scanner — elevated volatility, proceed with caution
2. **Level 2 (Orange):** Stock on a Gain scanner AND a Loss scanner on the same day — active tug-of-war between buyers and sellers
3. **Level 3 (Red):** Stock on PctGain AND PctLoss AND HotByVolume — extreme instability, maximum danger

## Action Rules by Level

### Yellow (Level 1)
- Tighten trailing stop to 8% (from default 15%)
- Reduce position size by 25%
- Set price alerts at +5% and -5% from current price

### Orange (Level 2)
- Tighten trailing stop to 5%
- Reduce position size by 50%
- Do NOT add to position
- Set a hard time limit: must exit within 2 hours if entered today

### Red (Level 3)
- Do NOT enter any new position
- If already holding, exit 75% of position immediately
- Trail remaining 25% with a 3% stop
- Add to 5-day blacklist after full exit

## Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

**Note: This profit protection applies to the underlying position regardless of which strategy triggered the exit signal.**

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

## Monitoring Rules
1. Check all 10 scanners at 9:45, 10:15, 10:45, 11:15, and 12:00 (5 checks per morning)
2. Cross-reference every held position and watchlist ticker against ALL scanner results
3. Log every conflict detection with timestamp, ticker, scanners involved, and price at detection

## Current Alerts
- **IMMP:** RED — on PctGainSmall + LossSinceOpenSmall + HotByVolumeSmall
- **CTNT:** RED — on PctLossSmall + LossSinceOpenSmall + HotByVolumeSmall

## Implementation Notes
- This strategy does NOT generate entries — it is a risk management overlay
- Apply this filter BEFORE any other strategy's entry rules
- A Red flag from this system OVERRIDES any buy signal from other strategies
