---
noteId: "059391b038d611f1aa17e506bb81f996"
tags: []

---

# Lessons Learned — Trading System Post-Mortem

## Date: 2026-04-15
## Context: 20 automated bracket trades placed via scanner-based system, all closed same day

---

## Lesson 1: Scanners Show the Past, Not the Future
**What happened:** The system bought stocks already at rank #1 on GainSinceOpenLarge (e.g., BIRD at $11.32 after a 361% move). By the time a stock tops the gain scanner, the move has already happened.
**Rule:** Only buy stocks that have appeared on a gain scanner for <10 minutes. If a stock has been on the scanner for the full session, the easy money is gone. Freshness of signal matters more than rank.
**How to apply:** Track `first_seen_time` for each scanner appearance. Reject entries where `now - first_seen_time > 10 minutes`.

## Lesson 2: 5% Stop / 10% Target Is Wrong for Momentum Plays
**What happened:** Stop loss at ~5% and take profit at ~10% gives only 2:1 reward/risk. On extended momentum stocks, the probability of a 5% pullback is very high (these stocks are volatile by nature), so the stop gets hit far more than the target.
**Rule:** Use at least 8-10% stop and 15-20% target (or trailing stops) on momentum scanner plays. The volatility of these names demands wider stops.
**How to apply:** Calculate ATR (Average True Range) for the stock before entry. Set stop at 1.5x ATR below entry, not a fixed percentage.

## Lesson 4: Volume Without Direction Is Meaningless
**What happened:** TRAW was bought from HotByVolumeLarge, but TRAW was simultaneously on PctLossLarge. High volume on a losing stock means selling pressure, not buying opportunity.
**Rule:** NEVER buy a stock from a volume scanner if it also appears on ANY loss scanner (PctLoss, LossSinceOpen). Volume confirms direction — it doesn't create it.
**How to apply:** Before every entry, cross-reference the ticker against all 10 scanners. If it appears on any loss scanner, reject the trade immediately. This is a hard veto, no exceptions.

## Lesson 5: 20 Simultaneous Positions = No Conviction
**What happened:** 20 trades at 1 share each, all entered at the same timestamp. BIRD (rank #1, 37M volume, dominant all session) got the same allocation as TRAW (rank #9, declining rank). No differentiation between strong and weak signals.
**Rule:** Maximum 5 positions at a time. Weight allocation by conviction score (see Strategy 09). A Tier 1 signal (3+ scanners, score 5+) gets 2x the allocation of a Tier 2 signal.
**How to apply:** Score every candidate using the multi-scanner conviction system before entry. Only trade the top 5 by score. If fewer than 3 candidates score Tier 1 or Tier 2, trade fewer — cash is a position.

## Lesson 6: No Cross-Scanner Conflict Check Existed
**What happened:** The system only checked ONE scanner per pick. It never verified whether the stock was also flagged on conflicting scanners. Multiple stocks were simultaneously on gain AND loss scanners.
**Rule:** Implement the Scanner Conflict Filter (Strategy 07) as a mandatory pre-trade gate. Any stock with conflicting scanner signals (gain + loss) is automatically rejected.
**How to apply:** Run the conflict filter every time the scanner picks are generated. Tag each pick with a conflict level (Yellow/Orange/Red). Red = no trade. Orange = half size only. Yellow = proceed with tighter stops.

## Lesson 7: Rank Trend Alone Is Not Enough
**What happened:** The system picked stocks based on rank improvement (e.g., "rank 27→6", "rank 48→9"). But a stock improving from rank 48 to rank 9 on a gain scanner might just be bouncing from a crash — not starting a real trend.
**Rule:** Require BOTH rank improvement AND absolute rank in top 5 for at least 3 consecutive snapshots before entry. A stock that just entered the top 10 is unproven — wait for it to hold.
**How to apply:** Add a `consecutive_top5_count` field to scanner picks. Only trigger a buy when this count reaches 3+.

## Lesson 8: All Orders Had the Same Structure
**What happened:** Every single trade was: MKT buy → 5% STP sell → 10% LMT sell. No adaptation for different stock behaviors, price levels, or volatility profiles. A $0.009 stock (BDCC) and a $26.50 stock (QPUX) got identical bracket parameters.
**Rule:** Scale stop/target distances by the stock's recent volatility. Use ATR-based brackets, not fixed percentages. Penny stocks (<$1) need wider percentage stops (15-20%) because their spreads alone can be 5%.
**How to apply:** Before placing the bracket, calculate the stock's 5-day ATR. Set stop = entry - 1.5 * ATR. Set target = entry + 2.5 * ATR. If the resulting stop is <3% or >15%, skip the trade (too tight or too volatile).

---

## Summary of Required System Changes

| Priority | Change | Prevents |
|----------|--------|----------|
| P0 | Cross-scanner conflict filter (hard veto) | Buying into selling pressure |
| P0 | Max 5 positions, conviction-weighted | Spray-and-pray dilution |
| P1 | ATR-based brackets, not fixed % | Stops too tight on volatile names |
| P1 | Signal freshness filter (<10 min on scanner) | Chasing exhausted moves |
| P2 | Require top-5 rank for 3+ snapshots | Entering on unproven signals |
| P2 | Reject penny stocks or widen their parameters | Spread-induced stop-outs |

## Metrics to Track Going Forward
- Win rate by scanner type (which scanners produce the most winners?)
- Average time from entry to stop hit vs target hit
- P&L for trades with vs without scanner conflicts
- Average holding period for winners vs losers
