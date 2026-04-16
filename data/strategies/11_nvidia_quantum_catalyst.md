---
noteId: "5fb57e5038d711f1aa17e506bb81f996"
tags: []

---

# Strategy 11: Nvidia Quantum Computing Catalyst Play

## Date: 2026-04-15
## Catalyst: Nvidia released open-source quantum AI models (Ising model) for error correction & system calibration

---

## What Happened Today

Nvidia introduced a new collection of open-source AI models for quantum systems. The **NVIDIA Ising model** is designed to enhance quantum processor development by tackling error correction and system calibration — making quantum computing more commercially viable.

### Sector Impact
| Underlying | Move | Description |
|-----------|------|-------------|
| IONQ | +20% | Leading pure-play quantum computing stock |
| RGTI (Rigetti) | +10% | Quantum processor maker |
| QBTS (D-Wave) | +13% | Quantum annealing leader |

### Portfolio Exposure (all 2X leveraged ETFs!)
| Ticker | Full Name | Underlying | Today |
|--------|-----------|-----------|-------|
| IONX | Defiance Daily Target 2X Long IONQ ETF | IONQ | +29% |
| IONL | Granite 2X Long IONQ ETF | IONQ | +29% |
| QUBX | Tradr 2X Long QUBT Daily ETF | QUBT | +24% |
| SMU | ? (likely quantum-related 2X ETF) | ? | +31% |
| ALMU | ? (likely quantum-related 2X ETF) | ? | +22% |

**Critical finding: The portfolio is NOT holding individual quantum stocks — it's holding 2X LEVERAGED ETFs on them.** This means:
- Double the gain on up days
- Double the loss on down days
- Daily rebalancing decay erodes value over multi-day holds
- These are day-trade instruments, NOT position trades

### Also Moving Today
| Ticker | Catalyst |
|--------|----------|
| BIRD (+361%) | Allbirds pivoted to AI compute infra ("NewBird AI"), $50M financing |
| IMMP (+159%) | No clear news — likely speculative sympathy / short squeeze |

---

## The Trade: Quantum Sector Momentum (Multi-Day)

### Thesis
Nvidia's Ising model is a real technical advancement, not hype. It addresses the #1 barrier to quantum commercialization (error correction). This could sustain a multi-day rally as:
1. Analysts publish coverage (Day 2-3)
2. Quantum companies announce integration plans (Day 3-5)
3. Retail momentum piles in (Day 1-3)

But the 2X leveraged ETFs are the WRONG vehicle for a multi-day hold due to decay.

### Instrument Selection
**Trade the underlyings, not the leveraged ETFs:**
- **IONQ** — purest play, largest quantum computing company, most liquid
- **RGTI** (Rigetti) — cheaper, more volatile, higher beta
- **QBTS** (D-Wave) — different architecture (annealing), diversification

**Exit the leveraged ETFs (IONX, IONL, QUBX) within 1-2 days** — they are for day trades only. Replace with IONQ direct if you want multi-day exposure.

### Entry Rules
1. If already holding leveraged ETFs (IONX, IONL, QUBX): hold through tomorrow's open, then evaluate
2. For new entries on IONQ/RGTI/QBTS: wait for a pullback to the 5-minute VWAP or the first 15-minute consolidation tomorrow morning
3. Do NOT chase if the stock gaps up >10% at tomorrow's open — wait for a pullback
4. Confirm the rally is continuing by checking:
   - Volume in first 30 minutes > 50% of today's full-day volume
   - Price holds above today's closing VWAP
   - No negative news overnight (Nvidia retraction, quantum setback, etc.)

### Position Sizing
- Max 5% of account in total quantum exposure (across all names)
- If holding 2X leveraged ETFs, count them at 2x their notional value for sizing purposes
- Prefer IONQ as the primary vehicle (most liquid, biggest market cap)

### Stop Loss Rules
- For leveraged ETFs (IONX, IONL, QUBX): 8% trailing stop from today's close — exit by EOD tomorrow regardless
- For underlyings (IONQ, RGTI, QBTS): 12% trailing stop from entry, allow multi-day hold
- If IONQ drops below $33 (today's low), exit all quantum positions

### Take Profit Rules
**Day 1 (already done):** Today's move captured. If holding overnight, profits are unrealized.

**Day 2 (tomorrow):**
- If gap up >5%: sell 50% of leveraged ETFs at open, trail rest with 5% stop
- If flat/slight gap down: hold with stops, watch for analyst upgrades
- If gap down >8%: sell all leveraged ETFs at open, keep IONQ with 12% stop

**Day 3-5:**
- Exit ALL leveraged ETFs by Day 2 close (mandatory)
- For IONQ direct: sell 25% at each +10% increment
- Full exit by Day 5 unless a new catalyst emerges

### Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

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

### Scenario Analysis

**Bull Case (30% probability):** Nvidia announces quantum partnership with IONQ/RGTI. IONQ runs to $50+ over 5 days. Leveraged ETFs could double again but decay risk is extreme.
- Action: Sell leveraged ETFs Day 2, hold IONQ with trailing stop

**Base Case (50% probability):** Rally fades over 2-3 days as initial excitement cools. IONQ settles 10-15% above pre-rally levels (~$25-28).
- Action: Take profits on Day 2, exit leveraged ETFs, keep small IONQ position

**Bear Case (20% probability):** Market sells off broadly, quantum names give back entire rally. Leveraged ETFs get hit twice as hard.
- Action: Exit everything at 8% trailing stop. Do not attempt to catch the bounce.

### Key Risk: Leveraged ETF Decay
**You are holding 2X leveraged daily-rebalancing ETFs.** If IONQ goes up 20% then down 20%:
- IONQ: $100 → $120 → $96 (net -4%)
- IONX (2X): $100 → $140 → $84 (net -16%)

The math gets worse the longer you hold. These are instruments for 1-day directional bets, not swing trades.

---

## Immediate Action Items

1. **Tomorrow morning:** Sell 50-100% of IONX, IONL, QUBX on any gap up
2. **If you want to stay long quantum:** Buy IONQ directly with the proceeds
3. **Set stops tonight:** GTC stop on IONX at $33, IONL at $17, QUBX at $11
4. **Watch for:** Analyst upgrades on IONQ, Nvidia follow-up announcements, quantum company press releases
5. **Do NOT add more leveraged ETF exposure** — the easy money was today

---

## Sources
- [Bloomberg: Nvidia's New AI Models Spark Rally in Quantum Computing Stocks](https://www.bloomberg.com/news/articles/2026-04-15/nvidia-new-ai-models-spark-rally-in-quantum-computing-stocks)
- [Seeking Alpha: Nvidia's newest AI models spark rally in quantum computing stocks](https://seekingalpha.com/news/4575035-nvidias-latest-ai-models-ignite-surge-in-quantum-computing-stocks)
- [TradingKey: Nvidia Releases Open-Source Quantum AI Model Ising, IonQ Gains Over 20%](https://www.tradingkey.com/analysis/stocks/us-stocks/261784660-nvidia-ising-quantum-ai-model-ionq-stock-surge-tradingkey)
- [Yahoo Finance: IonQ Soars 18%, D-Wave Climbs 15%, Rigetti Gains 12%](https://finance.yahoo.com/markets/stocks/articles/ionq-soars-18-d-wave-153521791.html)
- [Bloomberg: Allbirds Soars 373% After Rebranding as AI Stock](https://www.bloomberg.com/news/articles/2026-04-15/ex-sneaker-firm-allbirds-soars-373-after-rebranding-as-ai-stock)
- [CNBC: Allbirds announces pivot from shoes to AI](https://www.cnbc.com/2026/04/15/allbirds-bird-stock-shoes-ai.html)
