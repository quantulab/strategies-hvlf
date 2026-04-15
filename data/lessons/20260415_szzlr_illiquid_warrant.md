---
noteId: "91e0fa3038e611f1aa17e506bb81f996"
tags: []

---

# SZZLR — Illiquid Warrant, No Volume, No Edge

**Date:** 2026-04-15
**Symbol:** SZZLR
**Action:** BUY → Manual Close
**Entry:** $0.21 | **Exit:** ~$0.20 | **P&L:** -$0.01 (-4.86%)

## What Happened

SZZLR is a warrant (the "R" suffix). It had zero volume on multiple days, a 5% bid-ask spread ($0.19/$0.20), and no news or catalyst. The RSI reading of 99 was completely meaningless due to zero-volume bars producing artificial price stickiness. There was no realistic way to exit profitably given the spread.

## Technicals at Exit

- RSI 99.3 — artificially inflated by zero-volume bars, not a real signal
- Price below SMA_50 ($0.206) — still in a downtrend on the bigger picture
- MACD negative overall despite minor improvement
- Zero volume today, 2,975 shares on the most active recent day

## Lesson

- **Avoid warrants and illiquid securities** with <1,000 daily volume. The bid-ask spread alone makes profitable round-trips nearly impossible.
- Scanner picks should be filtered for **minimum daily volume** (e.g., 10K+) and **exclude warrant suffixes** (R, W, WS).
- A 5% spread means you start every trade down 5% — the stock needs to move 10%+ just to break even after entry and exit slippage.
- RSI and other indicators are unreliable on zero-volume bars. Don't trust technical signals on illiquid names.
