---
noteId: "5c65080039cd11f19da93711749444a5"
tags: []

---

# Trading Improvement Plan for April 17, 2026

**Based on:** Apr 15-16 performance data (48 trades, +$30.23 net P&L) | **Generated:** 2026-04-16

---

## Data-Driven Findings

### What's Working (Keep)

| Element | Evidence |
|---------|----------|
| Trailing stop ratchet | ASTI +145.6% ($3.64) — old 10% LMT would have capped at ~$0.25 |
| -5% hard stop | Avg loss -2.75% (Apr 16) vs -4.56% (Apr 15) |
| Quality gate (99.1% rejection) | Prevented batch-entry loss streaks from Apr 15 |
| Momentum surfing strategy | 80% WR, profit factor 855, generated 103% of all profits |
| Max 2 entries per cycle | Eliminated the 10-consecutive-loss problem from Apr 15 |

### What the Data Reveals

#### 1. $2-$5 Price Bracket is the Sweet Spot

```
$2-$5   ======================== 71.4% WR | +$25.18 | 109.4% avg return
$5-$10  ========                 33.3% WR |  +$8.57 |  58.3% avg return
$20+    ======================== 100%  WR |  +$0.61 |   2.8% avg return
Sub-$2  ========                 33.3% WR |  +$0.11 |  18.6% avg return
$10-$20                           0.0% WR |  -$1.34 |  -7.4% avg return
```

**Action:** Prioritize $2-$5 entries. Avoid $10-$20 range entirely.

#### 2. Scanner Combo Performance

```
GainSinceOpenLarge + PctGainLarge   85.7% WR | +$34.72 (dominates)
GainSinceOpenSmall + PctGainSmall   25.0% WR |  +$0.16
HotByVolumeSmall + PctGainSmall     33.3% WR |  -$0.13
GainSinceOpenLarge + HotByVolume    25.0% WR |  -$0.36
```

**Action:** Give +3 bonus conviction points when GainSinceOpenLarge + PctGainLarge are both present.

#### 3. Conviction Score Paradox (Higher = Worse)

```
Score 3 (Moderate)  60.0% WR | +$34.68 P&L  <-- BEST
Score 0 (Low)      100.0% WR |  +$0.20 P&L
Score 4 (High)      33.3% WR |  -$0.13 P&L
Score 5 (Max)       28.6% WR |  -$1.62 P&L  <-- WORST
```

**Action:** Lower minimum conviction from 5 (Tier 1) to 3 (Tier 2). High scores may indicate we're chasing tops instead of catching early moves.

#### 4. Optimal Entry Time

```
10:00 AM  ====    25.0% WR | $0.05 avg P&L (noisy open)
11:00 AM  ======= 44.4% WR | $2.34 avg P&L
12:00 PM  ======= 66.7% WR | $2.17 avg P&L (BEST)
 1:00 PM  =====   50.0% WR | -$0.57 avg P&L
```

**Action:** Add a warm-up period 9:30-10:30 AM (monitor only, no entries). Begin trading at 10:30 AM.

#### 5. Hold Time Optimization

```
8+ hours     100.0% WR | $3.64 avg P&L (multi-day winners)
2-4 hours     57.1% WR | $4.15 avg P&L (OPTIMAL)
30-120 min    37.5% WR | $0.08 avg P&L
< 30 min      40.0% WR | -$0.04 avg P&L (loses money)
```

**Action:** Increase default max_hold for momentum surfing from 120 min to 240 min. Let the trailing ratchet manage exits instead of time stops.

#### 6. Missed Catalyst Opportunities

- BIRD was +626% on Apr 15, rejected as "stale signal"
- Catalyst confirmation check (6 conditions) from lessons would have caught it
- Multi-day catalysts with institutional volume are different from momentum fades

**Action:** Implement the catalyst override rule (6-condition check) in Phase 4.

---

## Recommended Changes for Apr 17

### Priority 1: High Impact, Easy to Implement

| Change | Current | Proposed | Expected Impact |
|--------|---------|----------|-----------------|
| Min conviction score | 5 (Tier 1 only) | 3 (Tier 2+) | Captures early movers before they top out |
| Entry start time | 9:35 AM | 10:30 AM | Avoids noisy open (25% WR → 50%+ WR) |
| $10-$20 price filter | Allowed | Reject | Eliminates 0% WR bracket |
| Scanner combo bonus | None | +3 for GainLarge+PctGainLarge | Prioritizes 85.7% WR combo |

### Priority 2: Medium Impact, Moderate Effort

| Change | Current | Proposed | Expected Impact |
|--------|---------|----------|-----------------|
| Max hold (momentum) | 120 min | 240 min | Lets 2-4 hr winners play out (57% WR, $4.15 avg) |
| $2-$5 scoring bonus | None | +2 conviction points | Prioritizes sweet spot bracket |
| Catalyst override | Reject stale signals | 6-condition override check | Catches multi-day runners like BIRD |

### Priority 3: Monitor and Evaluate

| Change | Rationale | Metric to Watch |
|--------|-----------|-----------------|
| Reduce multi_scanner weight | 25% WR, -$0.36 P&L | If WR stays <30% after 20 trades, disable |
| Extend overnight holds | ASTI +145.6% was a multi-day hold | Track overnight gap risk vs multi-day returns |
| Add extended-move filter | PBM entered at +178%, stopped in 9 sec | Reject entries >100% from prior close |

---

## Expected Outcome

```
Current (Apr 16):
  7 trades | 57% WR | +$7.02 | Avg Win +43.6% | Avg Loss -2.75%

Target (Apr 17):
  5-8 trades | 55-65% WR | +$10-15 | Bigger winners via trailing ratchet
                                     | Same tight losses via -5% hard stop
```

**Key principle:** We don't need more trades. We need the *right* trades in the $2-$5 range, entering after 10:30 AM, on the GainLarge+PctGainLarge scanner combo, with the trailing ratchet letting winners run.

---

## Risk Guardrails (Do Not Change)

- Max 10 open positions
- Max 2 new entries per 10-min cycle
- -5% hard stop on all positions
- Trailing stop ratchet (Phase 6)
- No warrants/units/rights
- Spread < 3%
- Volume > 50,000

---

*Plan based on 48 trades across Apr 15-16. Sample size is small — treat these as hypotheses to validate, not certainties.*
