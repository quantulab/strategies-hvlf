---
noteId: "agae_unprotected_gains_20260415"
tags: [lesson, risk-management, trailing-stop, profit-protection]
---

# Lesson: AGAE — Failed to Protect +26% Gain, Exited at -7%

## What Happened

- AGAE entered via volume_breakout strategy at $0.50 (avgCost $0.5918)
- Intraday high reached ~$0.9586 — a **+92% intraday move** from prior close ($0.328)
- Position was up **+26%** from entry at one point
- No trailing stop or profit-protection mechanism was in place
- Price reversed from $0.9586 all the way down to $0.5499
- Position was only cut when the end-of-day risk check found it at **-7.09%**
- Net result: **lost $0.04** on a position that was up **$0.13** at peak

## The Problem

The system had only two exit mechanisms:
1. Fixed stop loss at -5% (too far away when stock is up 26%)
2. Fixed take profit at +10% (already blown past this — should have triggered but bracket may not have been set)

There was **no trailing stop** and **no profit-locking rule** for positions with large unrealized gains. The Phase 6 monitoring logged the position as "+26%" but took no action.

## Rules

### New Rule: Profit Protection Tiers (Phase 6 addition)

When monitoring positions in Phase 6, apply these trailing stop rules:

| Unrealized Gain | Action |
|-----------------|--------|
| **+10% to +20%** | Move stop to breakeven (entry price). Lock in zero-loss. |
| **+20% to +50%** | Move stop to +10% above entry. Lock in partial profit. |
| **+50% to +100%** | Move stop to +25% above entry OR trail 20% below high, whichever is higher. |
| **>+100%** | Trail stop at 25% below intraday high. Sell 50% at market if 1+ shares. |

### Implementation

1. In Phase 6, after getting quote, check if unrealized P&L exceeds any tier threshold
2. If current stop is below the tier-required stop level, **modify the existing stop order** to the new higher level
3. If no stop order exists, **place a new GTC STP order** at the tier-required level
4. Log stop adjustment to `orders` table with `strategy_id = "profit_protection"`
5. Log to `price_snapshots` with the new stop distance

### For AGAE specifically

- At +26% ($0.63), stop should have been moved to +10% ($0.55) — this alone would have saved the gain
- At peak +92% intraday from close ($0.9586), stop should have been at +25% from entry ($0.625) or trail 20% below high ($0.767), whichever higher — $0.767
- Instead, stop stayed at original -5% ($0.475) the entire time

## How to Apply

- Update Phase 6 in scanner_cron_job.md to include profit protection tier logic
- Every cron cycle must check unrealized gains against tier thresholds
- Stop adjustments should only move UP, never down (ratchet mechanism)
- This is especially critical for volume breakout and momentum plays that can reverse fast
