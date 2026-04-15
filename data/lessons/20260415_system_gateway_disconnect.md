---
noteId: "b644235038de11f1aa17e506bb81f996"
tags: []

---

# Lesson: IB Gateway Disconnect — 2026-04-15

## What Happened
- Gateway logs stop at 10:50:51 AM
- MCP server lost connection to IB Gateway
- All positions returned empty, all open orders gone
- `get_closed_trades` returned "Not connected"

## Impact
- 14+ open positions with bracket orders became unmonitored
- Stop losses and take profit orders may have been cancelled by IB on disconnect
- Cannot verify actual fill state or P&L without reconnecting

## Gateway Log Clues
- Last entries show scanner results processing normally
- Dialog popups appeared (possible reconnection prompt or error)
- No explicit error logged before disconnect

## Lesson
1. **Add heartbeat/ping** to connection.py — detect drops within 30 seconds
2. **Add auto-reconnect** with exponential backoff in the lifespan manager
3. **After reconnect**: immediately call get_positions and get_open_orders to verify state
4. **Re-place missing protective orders** (stops/limits) if they were cancelled
5. **Log connection state** to the errors table on every scan cycle
6. **Consider GTC orders** instead of day orders so they survive reconnection

## How to Apply
- Before every scan cycle, verify connection with a simple API call
- If connection fails, log error and attempt reconnect before proceeding
- Track connection uptime as a KPI
