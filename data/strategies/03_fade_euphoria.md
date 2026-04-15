---
noteId: "5cd3e99038d411f1aa17e506bb81f996"
tags: []

---

# Strategy 3: Fade the Euphoria (Short Squeeze Reversal)

## Objective
Short overextended stocks after 100%+ moves when volume exhaustion and topping signals appear.

## Universe
Stocks up >100% intraday that show distribution patterns.
Current candidates: BIRD, VSA, IMMP

## Entry Rules (Short)
1. Stock must have gained >100% from prior close
2. Wait for a clear topping signal — at least ONE of:
   - Three consecutive 5-minute candles with lower highs AND decreasing volume
   - A 5-minute candle that closes below its open with volume >2x the average 5-min volume (distribution candle)
   - Price fails to make a new high for 30+ minutes while volume remains elevated
3. Enter short on the next 5-minute candle AFTER the topping signal confirms
4. Entry must occur after 11:00 AM — never fade the opening momentum
5. Price must be at least 10% below the high of day at time of entry (confirming rejection)

## Position Sizing
- Max 0.5% of account per trade (shorts have unlimited risk)
- Never short more than $5,000 notional value per position
- Only 1 fade trade at a time

## Stop Loss Rules
- Hard stop: 5% above the high of day at time of entry
- If price makes a new all-time high after entry, exit immediately (do not wait for stop)
- If borrowing cost exceeds 50% annualized, do not enter
- Maximum loss: 0.5% of account

## Take Profit Rules
- Target 1: Cover 50% when price drops 10% from entry
- Target 2: Cover remaining 50% at VWAP or prior day's close, whichever is higher
- If price drops 20%+ from day's high, cover all — the easy money is made

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

## Time Rules
- Cover ALL shorts by 3:45 PM — never hold short overnight on a squeeze day
- If the position is not profitable within 1 hour of entry, cover at market
- No re-entry if stopped out — the squeeze may not be over

## Risk Filters
- Do NOT short if shares are hard to borrow or borrow fee is >100% annualized
- Do NOT short during a trading halt — wait 5 minutes after halt resumes
- Do NOT short if the stock has confirmed positive news (FDA approval, earnings beat, acquisition)
- Do NOT short if stock is <$1 (penny stocks can squeeze indefinitely)
- NEVER short premarket or after-hours
- Check short interest — if SI >30% of float, skip (already crowded short)
