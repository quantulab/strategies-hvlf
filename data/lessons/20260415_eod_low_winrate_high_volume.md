---
noteId: "eod_20260415_winrate"
tags: [lesson, eod, risk-management, win-rate, position-sizing]
---

# End-of-Day Lesson: 34% Win Rate Despite Profitable Day

## What Happened

- 32 closed trades, 11 winners, 21 losers — **34.38% win rate** (below 40% target)
- Yet the day was profitable: **+$3.64 net realized P&L** (profit factor 1.49)
- 10 consecutive losses occurred in the first batch of trades (initial scanner-based entries)
- Winners averaged +8.8% while losers averaged -5.7% — the few winners were large enough to overcome the many losers
- Best trade: IONX +$4.02 (+11.42%), Worst trade: NICM -$1.20 (-12.17%)
- 7 accidental shorts had to be closed (all losers, -$0.29 total)
- Take-profit exits: 8 trades, 100% win rate, +$3.77 — these carried the day
- Stop-loss exits: 6 trades, 0% win rate, -$1.82

## Key Findings

1. **Early batch entries (13:51-14:01) were mostly losers** — 10 consecutive losses suggest entering too many positions simultaneously without conviction filtering
2. **Accidental shorts still happening** — 7 occurrences despite the lesson being documented. The check-before-sell logic needs to be enforced more strictly
3. **Quantum catalyst (Strategy 11) was the real alpha** — IONX (+$4.02), IONL (+$2.28), QUBX (+$1.32), QPUX (+$2.64) accounted for most profits. Without the catalyst play, the day would have been deeply negative
4. **Volume breakout strategy underperformed** — 44.4% win rate but -$0.09 net, basically breakeven
5. **Leveraged ETFs held too long** — XNDU, ASTI still held overnight with massive intraday moves (>50%). Strategy 11 warned about leveraged decay risk on multi-day holds

## Rules

1. **Do NOT batch-enter positions** — stagger entries, require conviction score before each trade
2. **Max 5 new positions in first 30 minutes** — prevents the 10-loss streak pattern
3. **Accidental short prevention must be a hard gate** — query open orders AND current positions before ANY sell
4. **Catalyst plays should be sized larger** — they were the only reliable alpha source today
5. **Close leveraged ETFs within 1 trading day** — XNDU and ASTI should not be held overnight (decay risk per Strategy 11)

## How to Apply

- Scanner cron job Phase 5: add a rate limit of max 2 new entries per 10-minute cycle
- Phase 2: double-check the accidental short prevention — query both open orders AND IB positions before selling
- When a clear catalyst is identified (like Nvidia quantum), allocate more capital to direct plays (IONQ, RGTI) and less to leveraged ETFs
- End-of-day: close ALL leveraged ETF positions regardless of P&L
