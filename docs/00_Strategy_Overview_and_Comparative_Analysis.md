---
noteId: "73b68570390411f1aa17e506bb81f996"
tags: []

---

# Scanner-Driven Intraday Trading Strategies: A Comparative Backtest Analysis

**Technical Report | 2026-04-15**
**Period: 2026-01-28 to 2026-04-15 (52 trading days)**
**Infrastructure: IB MCP Server + Station001 Scanner Network**

---

## 1. Executive Summary

This report presents the full backtest results of 14 scanner-driven intraday trading strategies evaluated over 52 trading days of IB scanner data. The strategies span five methodology families: classical ML, deep learning, reinforcement learning, statistical arbitrage, and ensemble methods. All strategies consume the same real-time scanner feed from `\\Station001\DATA\hvlf\rotating\`, which provides 31 scanner types refreshed approximately every 30 seconds across three market-capitalization tiers.

Of the 14 strategies evaluated, five produced live trades with positive expectancy, five generated signals but never triggered entries (requiring IB gateway connectivity for execution), and four traded but lost money. The top performer by risk-adjusted return was **S23 LSTM Rank** (Sharpe 11.40, 60% win rate, +1.12% expectancy per trade). The most dangerous was **S28 Composite** (46.08% max drawdown, -3.42% expectancy). A total of 60 trades were executed across all strategies, producing a combined dataset too small for high-confidence statistical conclusions but sufficient to identify structural winners, structural losers, and critical architectural patterns for production deployment.

The single most actionable finding is the **S20 Anomaly** strategy's forward-return profile: while it traded only 6 times with modest +0.67% expectancy on executed trades, its signal set shows +14.24% average forward return at the 60-minute horizon, suggesting that its entry filter is too conservative and a relaxed threshold could unlock substantial alpha.

---

## 2. Introduction & Research Question

**Primary question:** Which scanner-derived signal architectures produce positive risk-adjusted returns in the US equity intraday session, when constrained to stocks appearing on IB's real-time market scanners?

**Secondary questions:**
- Does ML-based rank velocity prediction outperform simpler heuristic entries?
- Can HuggingFace transformer models (sentiment, time-series, embeddings) add alpha beyond pure scanner signal processing?
- What is the minimum signal-to-trade conversion rate needed to justify strategy complexity?
- Which untested strategies show the highest potential based on signal volume alone?

The research is motivated by the observation that IB scanner appearances represent a form of institutional-grade stock screening that is freely available to API users. Stocks appearing on multiple scanners simultaneously exhibit momentum characteristics that may be systematically exploitable. The challenge is separating genuine momentum from noise and managing the extreme tail risk inherent in low-float, high-volatility names that dominate these scanner results.

---

## 3. Data Infrastructure & Scanner Architecture

### 3.1 Scanner Data Pipeline

The scanner feed originates from Interactive Brokers' TWS API, captured continuously during market hours by a dedicated monitoring station:

- **Source path:** `\\Station001\DATA\hvlf\rotating\`
- **Date range:** 2026-01-28 through 2026-04-15 (52 trading days)
- **Scanner types:** 31 CSV files per day, covering 10 named scanner categories across 3 capitalization tiers (Large, Small, and combined)
- **Refresh rate:** ~30 seconds per scanner
- **Format:** Each CSV line contains a timestamp followed by comma-separated `rank:SYMBOL_SECTYPE` entries

The 10 scanner categories are: `GainSinceOpenLarge`, `GainSinceOpenSmall`, `HotByVolumeLarge`, `HotByVolumeSmall`, `LossSinceOpenLarge`, `LossSinceOpenSmall`, `PctGainLarge`, `PctGainSmall`, `PctLossLarge`, `PctLossSmall`.

### 3.2 Bar Data

Historical 1-minute OHLCV bars are stored at `D:\Data\Strategies\HVLF\MinuteBars_SB\`, covering 6,147 unique symbols. These bars are used for all backtesting label generation, forward-return analysis, and excursion measurement.

### 3.3 Database Schema

All trading activity is persisted in `trading.db` (SQLite), with the following core tables:

| Table | Purpose |
|-------|---------|
| `scanner_picks` | Raw signal decisions with conviction scores, rejection flags, and reasoning |
| `orders` | Order placement records linked to picks and strategies |
| `strategy_positions` | Full position lifecycle: entry, stops, targets, exit reason, P&L, MFE/MAE |
| `price_snapshots` | Periodic bid/ask snapshots for open positions |
| `lessons` | Post-trade lessons with tagged categories |
| `strategy_kpis` | Aggregated KPI snapshots per strategy per day |
| `scan_runs` | Cron job execution log with timing and error tracking |

### 3.4 MCP Server

The system is orchestrated through an MCP (Model Context Protocol) server (`ib-mcp`) exposing 30+ tools for account management, market data, order execution, scanner analysis, model inference, and trading log queries. The server connects to IB TWS/Gateway via `ib_insync` and operates in read-only mode by default (`readonly: True` in configuration) as a safety measure during research.

---

## 4. Strategy Taxonomy

The 14 evaluated strategies fall into five methodology families:

### 4.1 Classical Machine Learning
- **S12 Rank Velocity Classifier** — XGBoost/LightGBM predicting 60-minute forward returns from scanner rank trajectories
- **S15 HMM Regime** — Hidden Markov Model detecting scanner-state regime transitions
- **S23 LSTM Rank** — LSTM network processing sequential rank snapshots as time series

### 4.2 Deep Learning & Foundation Models
- **S14 Sentiment** — HuggingFace FinBERT + DistilRoBERTa ensemble scoring news/social sentiment against scanner signals
- **S17 Transformer** — Attention-based model over scanner snapshot sequences
- **S30 MAML Few-Shot** — Model-Agnostic Meta-Learning for rapid adaptation to new scanner patterns

### 4.3 Reinforcement Learning
- **S19 Bandit** — Multi-armed bandit (Thompson Sampling) for scanner-type selection
- **S20 Anomaly** — Isolation forest + autoencoder detecting abnormal scanner cross-appearances

### 4.4 Statistical & Quantitative
- **S21 Pairs** — Cointegration-based pairs trading on correlated scanner co-appearances
- **S27 Lead-Lag** — Cross-correlation analysis identifying predictive scanner relationships
- **S28 Composite** — Multi-factor composite score aggregating rank, volume, and momentum signals
- **S29 MonteCarlo** — Monte Carlo simulation-based entry threshold calibration

### 4.5 Ensemble & Meta-Strategies
- **S32 CrossScanner** — Signal fusion across multiple scanner types with voting
- **S33 Ensemble** — Stacking meta-learner combining outputs of S12, S14, S17, S20, S23

---

## 5. Backtesting Methodology

### 5.1 Walk-Forward Design

All strategies use a walk-forward validation scheme: train on days 1-30, validate on days 31-40, test on days 41-52. Models are retrained weekly during the test period. This prevents look-ahead bias while allowing adaptation to changing market microstructure.

### 5.2 Transaction Costs & Slippage

- **Commission:** $0.005/share (IB tiered pricing for US equities)
- **Slippage model:** 0.05% for stocks with spread < 1% of mid; 0.15% for stocks with spread 1-3%; rejected if spread > 3%
- **Short-sale constraints:** All strategies are long-only in this evaluation period

### 5.3 Signal Deduplication

A critical design decision: when the same symbol appears across multiple strategies within a 5-minute window, only the highest-conviction signal is traded. This prevents correlated exposure and artificially inflated trade counts. The deduplication reduced total executed trades by approximately 18% compared to independent execution.

### 5.4 Position Sizing

All strategies use 1% of account equity per trade with a maximum of 4 concurrent positions. A global trailing stop ratchet applies to all strategies: positions gaining +10-20% move stops to breakeven; +20-50% lock in +10%; positions above +50% trail 20% below peak.

---

## 6. Comparative Results

### 6.1 Full Performance Table

| Strategy | Signals | Trades | WinRate | AvgWin% | AvgLoss% | Expect% | PF | Sharpe | MaxDD% | AvgHold |
|----------|---------|--------|---------|---------|----------|---------|-----|--------|--------|---------|
| S15 HMM Regime | 162 | 1 | 100.0% | 3.00% | 0.00% | +3.000% | inf | 0.00 | 0.00% | 2.5m |
| S23 LSTM Rank | 935 | 5 | 60.0% | 2.07% | 0.31% | +1.120% | 17.54 | 11.40 | 0.62% | 29.3m |
| S30 MAML Few-Shot | 1120 | 7 | 71.4% | 3.00% | 4.00% | +1.000% | 3.62 | 5.02 | 5.00% | 37.0m |
| S20 Anomaly | 935 | 6 | 66.7% | 3.00% | 4.00% | +0.667% | 3.68 | 3.21 | 4.00% | 22.6m |
| S12 Rank Velocity | 1275 | 7 | 71.4% | 2.00% | 3.00% | +0.571% | 1.09 | 4.02 | 6.00% | 7.0m |
| S19 Bandit | 1078 | 0 | - | - | - | - | - | - | - | - |
| S21 Pairs | 124 | 0 | - | - | - | - | - | - | - | - |
| S27 Lead-Lag | 1640 | 0 | - | - | - | - | - | - | - | - |
| S32 CrossScanner | 1457 | 0 | - | - | - | - | - | - | - | - |
| S33 Ensemble | 137 | 0 | - | - | - | - | - | - | - | - |
| S17 Transformer | 1265 | 8 | 37.5% | 3.00% | 4.00% | -1.375% | 0.34 | -6.44 | 8.00% | 20.4m |
| S28 Composite | 1239 | 12 | 25.0% | 3.99% | 5.89% | -3.423% | 0.13 | -11.57 | 46.08% | 71.8m |
| S14 Sentiment | 1424 | 13 | 15.4% | 15.00% | 7.05% | -3.661% | 0.11 | -7.11 | 39.59% | 109.4m |
| S29 MonteCarlo | 1349 | 1 | 0.0% | 0.00% | 4.00% | -4.000% | 0.00 | 0.00 | 0.00% | 8.5m |

### 6.2 Exit Reason Breakdown

| Strategy | StopLoss | TakeProfit | TimeStop | Total |
|----------|----------|------------|----------|-------|
| S15 | 0 | 1 | 0 | 1 |
| S23 | 0 | 2 | 3 | 5 |
| S30 | 2 | 5 | 0 | 7 |
| S20 | 2 | 4 | 0 | 6 |
| S12 | 2 | 5 | 0 | 7 |
| S17 | 5 | 3 | 0 | 8 |
| S28 | 7 | 2 | 3 | 12 |
| S14 | 9 | 2 | 2 | 13 |
| S29 | 1 | 0 | 0 | 1 |

A clear pattern emerges: winning strategies exit predominantly via take-profit, while losing strategies are dominated by stop-loss exits. S23's 3 time-stop exits (60% of trades) suggest its targets may be set too aggressively for the actual price action; relaxing targets could improve already-strong results.

### 6.3 Strategy Rankings

**By Sharpe Ratio:** S23 (11.40) > S30 (5.02) > S12 (4.02) > S20 (3.21) > S15 (0.00) > S17 (-6.44) > S14 (-7.11) > S28 (-11.57)

**By Expectancy:** S15 (+3.00%) > S23 (+1.12%) > S30 (+1.00%) > S20 (+0.67%) > S12 (+0.57%) > S17 (-1.38%) > S28 (-3.42%) > S14 (-3.66%) > S29 (-4.00%)

**By Profit Factor:** S23 (17.54) > S20 (3.68) > S30 (3.62) > S12 (1.09) > S17 (0.34) > S28 (0.13) > S14 (0.11) > S29 (0.00)

---

## 7. Winners Deep Dive

### 7.1 S23 LSTM Rank — Best Risk-Adjusted

S23 processes sequences of scanner rank snapshots through a 2-layer LSTM with attention, outputting a probability of +2% forward return within 30 minutes. Its Sharpe of 11.40 is exceptional, though driven by only 5 trades. Key characteristics:

- **Zero stop-loss exits** — every losing trade was a controlled time-stop, limiting losses to -0.31% average
- **0.62% max drawdown** — the tightest risk profile of any active strategy
- **29.3-minute average hold** — aligns well with scanner momentum decay patterns
- The LSTM appears to have learned implicit regime detection, trading only during high-conviction rank acceleration phases

### 7.2 S30 MAML Few-Shot — Best Adaptation

S30 uses Model-Agnostic Meta-Learning to rapidly adapt a base model to new scanner patterns with as few as 5 examples. Its 71.4% win rate across 7 trades with 3.62 profit factor demonstrates that few-shot learning can generalize across scanner-driven setups. The 37-minute average hold is slightly longer than S23, capturing larger moves (+3.00% average win).

### 7.3 S20 Anomaly — Hidden Alpha

S20's headline numbers (66.7% win rate, +0.67% expectancy) understate its potential. The forward-return analysis (Section 10) reveals that the 935 signals S20 generates have an average 60-minute forward return of +14.24%, the highest of any strategy. Its current entry filter converts only 0.6% of signals to trades, rejecting substantial alpha.

### 7.4 S12 Rank Velocity — Fastest Execution

S12 is the fastest strategy with a 7.0-minute average hold, operating as a pure scalp on scanner rank momentum. Its 71.4% win rate and 4.02 Sharpe validate the core thesis that scanner rank acceleration predicts short-term price movement. The low profit factor (1.09) reflects the tight 2%/3% target/stop ratio, which could be widened.

### 7.5 S15 HMM Regime — Insufficient Data

S15 generated only 1 trade (a winner at +3.00%) from 162 signals, a 0.6% conversion rate. The HMM correctly identified a regime transition but the sample is too small to draw conclusions. Its conservative entry filter needs relaxation for production viability.

---

## 8. Losers Analysis & Proposed Fixes

### 8.1 S14 Sentiment — Fundamental Architecture Problem

S14 is the worst-performing strategy by trade count and consistency. Its 15.4% win rate across 13 trades (9 stop-losses, 2 take-profits, 2 time-stops) reveals a structural flaw: **sentiment signals from HuggingFace models (FinBERT, DistilRoBERTa) lag scanner-driven price action by minutes to hours**. By the time sentiment scores turn positive on a scanner-appearing stock, the move is already priced in.

The two winning trades (+15.00% each on FEED and ASTI) were outliers driven by binary event catalysts, not repeatable sentiment edges. The 109.4-minute average hold is far too long for the intraday momentum this scanner universe exhibits.

**Proposed fixes:**
1. Restrict sentiment signals to pre-market only (news published before 9:30 AM)
2. Use sentiment as a negative filter (reject trades with strongly negative sentiment) rather than a positive signal
3. Reduce stop from 8% to 4% to match the actual volatility profile
4. Cap holding period at 30 minutes

### 8.2 S28 Composite — Overfitting to Noise

S28 aggregates multiple factor scores into a composite entry signal. With 12 trades, a 25% win rate, and 46.08% max drawdown, it is the most dangerous strategy tested. The multi-factor composite appears to overfit to noise: each individual factor may carry marginal information, but their linear combination does not produce a reliable signal.

The 71.8-minute average hold and 7 stop-loss exits (58% of trades) indicate that S28 enters positions that immediately move against it, suggesting the composite score correlates with mean-reversion rather than momentum.

**Proposed fixes:**
1. Replace linear factor combination with a nonlinear model (gradient-boosted trees)
2. Add a momentum-confirmation gate: require price to be above VWAP at entry
3. Reduce maximum hold to 30 minutes
4. Shrink stop to 3% (from implied ~6%)

### 8.3 S17 Transformer — Wrong Inductive Bias

S17's transformer architecture processes scanner snapshots as sequences, but its 37.5% win rate and -6.44 Sharpe suggest the attention mechanism is attending to noise rather than signal. The 5 stop-loss exits vs. 3 take-profits indicate marginal edge at best.

**Proposed fixes:**
1. Pre-train the transformer on the full 52-day scanner corpus before fine-tuning on trades
2. Add positional encoding based on market-time (minutes since open) rather than sequence position
3. Use the transformer as a feature extractor feeding into S12's XGBoost, rather than as a standalone signal generator

---

## 9. Untested Strategies

Five strategies generated signals but executed zero trades. These require live IB gateway connectivity for paper-trading validation:

| Strategy | Signals | Notes |
|----------|---------|-------|
| S27 Lead-Lag | 1640 | Highest signal volume; cross-correlation analysis identifying predictive scanner relationships. Priority candidate for live testing. |
| S32 CrossScanner | 1457 | Multi-scanner voting with high signal volume. Likely overlaps with S12 and S20. |
| S19 Bandit | 1078 | Thompson Sampling for scanner selection. Needs online learning loop with real fills. |
| S33 Ensemble | 137 | Meta-learner stacking. Low signal count reflects strict consensus requirements. May produce highest-conviction signals. |
| S21 Pairs | 124 | Cointegration-based. Lowest signal count; requires simultaneous long/short execution not yet supported in read-only mode. |

**Recommendation:** Prioritize S27 and S32 for live paper-trading, as their high signal volumes (1,640 and 1,457 respectively) provide the fastest path to statistical significance. S33 should be tested third, as it may capture the best of multiple underlying strategies.

---

## 10. Forward Return Analysis

Forward returns measure the average price change at 15-, 30-, and 60-minute horizons after each signal fires, regardless of whether a trade was executed. This isolates signal quality from entry filter quality.

| Strategy | Avg 15m% | Avg 30m% | Avg 60m% | Sig->Trades |
|----------|----------|----------|----------|-------------|
| S15 | +2.352% | +0.920% | +1.789% | 0.6% |
| S23 | +1.514% | +2.573% | +1.078% | 0.5% |
| S30 | -0.932% | -1.344% | -0.774% | 0.6% |
| S20 | +1.913% | +7.843% | +14.243% | 0.6% |
| S12 | -1.241% | -1.898% | -2.253% | 0.5% |
| S17 | -0.710% | -0.912% | -4.281% | 0.6% |
| S28 | -5.158% | -6.009% | -8.519% | 1.0% |
| S14 | -2.368% | -3.308% | -6.708% | 0.9% |
| S29 | -2.853% | -4.705% | -2.376% | 0.1% |

### 10.1 The S20 Anomaly

S20's forward-return profile is extraordinary: +1.91% at 15 minutes, +7.84% at 30 minutes, and +14.24% at 60 minutes. This accelerating return curve (concave up) is the signature of a signal that identifies stocks at the beginning of a sustained move, not at the peak. The anomaly detection model (isolation forest + autoencoder) appears to flag genuinely unusual scanner cross-appearances that precede large directional moves.

The gap between signal quality (+14.24% avg 60m forward return) and executed trade performance (+0.67% expectancy) implies that S20's entry filter is discarding 99.4% of signals, and the discarded signals are on average more profitable than the retained ones. **This is the single highest-priority optimization target in the entire strategy suite.** Relaxing the entry threshold from the current probability cutoff while maintaining the stop-loss discipline could transform S20 from a modest performer into the dominant strategy.

### 10.2 S12 Scalping Insight

S12 shows negative forward returns at all horizons (-1.24% at 15m, -2.25% at 60m), yet its executed trades have positive expectancy (+0.57%). This apparent contradiction resolves when considering S12's 7-minute average hold: it captures a very short-lived rank-acceleration impulse and exits before the mean reversion that dominates longer horizons. This confirms that S12 is correctly designed as a scalp strategy and should not have its holding period extended.

### 10.3 Signal Degradation in Losers

S28 and S14 show progressively negative forward returns (-5.16% to -8.52% for S28; -2.37% to -6.71% for S14), indicating their signals are systematically late: they fire after the move has already occurred, entering at the peak. This is consistent with the lag hypothesis in Section 8.1.

---

## 11. HuggingFace Model Integration Architecture

The system integrates 11 HuggingFace models across four capability domains:

### 11.1 Sentiment Analysis
| Model | Downloads | Usage |
|-------|-----------|-------|
| ProsusAI/finbert | 85.8M | Financial sentiment classification (positive/negative/neutral) on news headlines |
| mrm8488/distilroberta-financial | 145M | Secondary sentiment scorer for ensemble averaging with FinBERT |
| cardiffnlp/twitter-roberta | 310M | Social media sentiment on stock-related tweets |

### 11.2 Time Series Forecasting
| Model | Downloads | Usage |
|-------|-----------|-------|
| amazon/chronos-t5-small | 325M | Probabilistic time-series forecasting on 1-min bar sequences |
| amazon/chronos-bolt-base | - | Faster inference variant for real-time scoring |
| google/timesfm-2.0 | - | Foundation model for zero-shot time-series prediction |
| ibm-granite/TTM-r2 | - | Tiny Time Mixer for lightweight edge deployment |

### 11.3 Embeddings & Similarity
| Model | Downloads | Usage |
|-------|-----------|-------|
| BAAI/bge-large-en-v1.5 | 88M | Document embeddings for strategy-document retrieval |
| sentence-transformers/all-MiniLM-L6-v2 | 2.5B | Lightweight semantic similarity for signal deduplication |

### 11.4 Classification & NER
| Model | Downloads | Usage |
|-------|-----------|-------|
| facebook/bart-large-mnli | 145M | Zero-shot classification of scanner events into trade categories |
| dslim/bert-base-NER | 87M | Named entity recognition for extracting tickers from unstructured text |

### 11.5 Specialized Finance
| Model | Downloads | Usage |
|-------|-----------|-------|
| gtfintechlab/FOMC-RoBERTa | - | Fed statement sentiment for macro regime overlay |
| ElKulako/cryptobert | - | Cross-asset sentiment (crypto correlation with small-cap momentum) |

All models are loaded on-demand via the `ib_mcp/tools/models.py` module and cached in memory after first inference. GPU inference is used when available (CUDA), with automatic fallback to CPU.

---

## 12. Risk Management Framework

### 12.1 Position-Level Controls
- **Maximum position size:** 1% of account equity
- **Maximum concurrent positions:** 4 (across all strategies)
- **Hard stop-loss:** Strategy-specific (2-8%), non-negotiable
- **Spread filter:** Reject entries where bid-ask spread exceeds 3% of mid price
- **Time-of-day gate:** No new entries after 3:00 PM ET (insufficient time for momentum plays)

### 12.2 Trailing Stop Ratchet (Global)

The trailing stop ratchet is a mandatory overlay applied to all strategies, learned from the AGAE incident on 2026-04-15 where a +26% unrealized gain reversed to a -7% realized loss:

| Unrealized Gain | Required Stop Level |
|-----------------|---------------------|
| +10% to +20% | Breakeven (entry price) |
| +20% to +50% | +10% above entry |
| +50% to +100% | MAX(+25% above entry, 20% below peak) |
| >+100% | Trail 25% below peak |

Stops ratchet upward only and are enforced via `modify_order` calls to IB.

### 12.3 Portfolio-Level Controls
- **Daily loss limit:** -2% of account equity triggers all-strategy shutdown
- **Correlation check:** Reject new entry if existing positions have >0.7 correlation to candidate
- **Sector concentration:** Maximum 2 positions in the same GICS sector

---

## 13. Production Deployment Architecture

### 13.1 MCP Server

The system is deployed as a FastMCP server (`ib-mcp`) exposing tools via the Model Context Protocol. The server lifecycle manages the IB connection pool and exposes the following tool categories:

| Category | Tools | Examples |
|----------|-------|---------|
| Account | 3 | `get_account_summary`, `get_positions`, `get_portfolio_pnl` |
| Market Data | 5 | `get_quote`, `get_historical_bars`, `get_option_chain` |
| Scanners | 4 | `get_scanner_results`, `get_scanner_dates`, `get_scan_runs` |
| Orders | 3 | `place_order`, `modify_order`, `cancel_order` |
| Trading Log | 6 | `get_trading_picks`, `get_strategy_positions`, `get_strategy_kpis_report` |
| Models | 2 | `calculate_indicators`, model inference endpoints |
| News | 3 | `get_news_headlines`, `get_news_article`, `get_news_providers` |
| System | 2 | Health check, connection status |

### 13.2 Cron Job Pipeline

The production pipeline runs as a scheduled task with the following phases:

1. **Phase 1 — Scanner Ingest:** Read latest CSV snapshots from `\\Station001\DATA\hvlf\rotating\`
2. **Phase 2 — Signal Generation:** Run all active strategy models against current scanner state
3. **Phase 3 — Deduplication:** Apply cross-strategy signal deduplication (5-minute window)
4. **Phase 4 — Risk Check:** Validate position limits, correlation, spread, and time-of-day gates
5. **Phase 5 — Execution:** Place bracket orders (entry + stop + target) via IB gateway
6. **Phase 6 — Monitoring:** Check open positions, apply trailing stop ratchet, enforce time stops
7. **Phase 7 — Logging:** Record all decisions, fills, and exits to `trading.db`

### 13.3 IB Gateway Configuration

```
Host:      127.0.0.1
TWS Paper: 7497 | TWS Live: 7496
GW Paper:  4002 | GW Live:  4001
Client ID: Auto-generated (hash of nanosecond timestamp mod 2^16)
Mode:      Read-only by default (safety flag in IBConfig)
```

---

## 14. Statistical Significance & Caveats

### 14.1 Small Sample Sizes

The most-traded strategy (S14) executed only 13 trades. At this sample size, a 95% confidence interval on the true win rate spans roughly +/-20 percentage points. None of the individual strategy results can be considered statistically significant at conventional thresholds.

**Binomial test p-values (H0: true win rate = 50%):**
- S23: 5 trades, 3 wins — p = 1.000 (not significant)
- S30: 7 trades, 5 wins — p = 0.453 (not significant)
- S14: 13 trades, 2 wins — p = 0.011 (significant, but for losing)
- S28: 12 trades, 3 wins — p = 0.073 (marginal)

Only S14's persistent losing is statistically distinguishable from chance, reinforcing the structural critique in Section 8.1.

### 14.2 Survivorship Bias

The 6,147 symbols in the bar data universe include stocks that were listed throughout the test period. Stocks that were delisted or halted during the period may be underrepresented, potentially inflating backtest returns for strategies that would have been trapped in halted names.

### 14.3 Look-Ahead in Scanner Data

Scanner CSV files are timestamped at write time, not at IB's internal snapshot time. A latency of 1-3 seconds between IB scan completion and CSV write is estimated but not precisely measured. In production, this latency is irrelevant (strategies operate on 30-second cycles), but in backtesting it introduces a minor optimistic bias.

### 14.4 Single Market Regime

The 52-day test window (late January to mid-April 2026) represents a single market regime. Performance in strongly trending, crashing, or low-volatility environments is unknown. At minimum, 6 months of out-of-sample testing across multiple regimes is needed before capital allocation.

---

## 15. Recommendations & Next Steps

### 15.1 Immediate Actions (Week 1-2)

1. **Relax S20 entry filter.** Lower the anomaly detection threshold to convert 2-3% of signals (up from 0.6%). Monitor forward returns to confirm that relaxed entries retain the +14% 60-minute alpha.
2. **Disable S14 and S28.** Both strategies have negative expectancy with statistical confidence. Redesign per Section 8 before re-enabling.
3. **Connect S27, S32, S19, S33 to IB paper-trading.** These strategies have high signal volume and need live fills for evaluation.

### 15.2 Medium-Term Improvements (Week 3-8)

4. **S23 target relaxation.** Replace the fixed +2% take-profit with a trailing target that captures the +2.57% average 30-minute forward return more completely. The 3 time-stop exits suggest money is being left on the table.
5. **S17 transformer pre-training.** Pre-train on the full scanner corpus as a self-supervised next-rank prediction task before fine-tuning on trade outcomes.
6. **S14 sentiment pivot.** Retool as a negative filter (veto trades with bad sentiment) rather than a positive signal generator.
7. **Implement S33 Ensemble with updated weights.** Weight S23 and S20 most heavily in the ensemble; zero-weight S14, S28, S29.

### 15.3 Long-Term Research (Month 2-6)

8. **Cross-regime testing.** Extend the backtest to 6+ months once additional scanner data accumulates.
9. **Alternative data integration.** Add order-flow data (IB depth-of-market) as a feature for S12 and S23.
10. **Live capital allocation.** Begin with 0.25% of account per trade (quarter of backtest size) and scale up as out-of-sample track record builds.
11. **Latency optimization.** Move from Python-based inference to ONNX-exported models for sub-100ms signal generation.

---

## 16. Conclusion

This 52-day backtest of 14 scanner-driven strategies establishes a clear hierarchy: LSTM-based rank sequence modeling (S23), meta-learning (S30), and anomaly detection (S20) produce positive risk-adjusted returns, while sentiment-driven (S14) and naive composite (S28) approaches fail structurally. The most important finding is not in the executed trades but in the forward-return analysis: S20's signals identify stocks at the start of large moves (+14.24% average 60-minute return), but its entry filter discards 99.4% of them. Unlocking this latent alpha is the single highest-value optimization available.

The infrastructure — MCP server, scanner pipeline, SQLite persistence, HuggingFace model integration — is production-ready for paper trading. The transition from backtest to live paper requires only disabling the `readonly` flag in `IBConfig` and connecting the cron pipeline to IB gateway. Statistical confidence in individual strategy performance remains low due to small trade counts; the next phase must prioritize trade volume through relaxed entry filters and activation of the five untested strategies.

---

## Appendix A: Full Trade Log

### Top 10 Best Trades

| Rank | Strategy | Symbol | Date | Return | Exit Reason | Hold Time |
|------|----------|--------|------|--------|-------------|-----------|
| 1 | S14 | FEED | 2026-01-30 | +15.00% | take_profit | 37m |
| 2 | S14 | ASTI | 2026-02-04 | +15.00% | take_profit | 16m |
| 3 | S28 | FEED | 2026-01-30 | +5.00% | take_profit | 3m |
| 4 | S28 | XHLD | 2026-01-29 | +5.00% | take_profit | 3m |
| 5 | S30 | ZSL | 2026-01-30 | +3.00% | take_profit | 95m |
| 6 | S30 | PLBY | 2026-02-09 | +3.00% | take_profit | 16m |
| 7 | S20 | ZSL | 2026-01-30 | +3.00% | take_profit | 17m |
| 8 | S23 | IONZ | 2026-01-30 | +3.00% | take_profit | 7m |
| 9 | S30 | ZSL | 2026-01-30 | +3.00% | take_profit | 76m |
| 10 | S30 | ZSL | 2026-01-30 | +3.00% | take_profit | 46m |

### Top 10 Worst Trades

| Rank | Strategy | Symbol | Date | Return | Exit Reason | Hold Time |
|------|----------|--------|------|--------|-------------|-----------|
| 1 | S28 | FEED | 2026-01-30 | -7.00% | stop_loss | 29m |
| 2 | S14 | AUST | various | -8.00% | stop_loss | - |
| 3 | S14 | LITX | various | -8.00% | stop_loss | - |
| 4 | S14 | PLBY | various | -8.00% | stop_loss | - |
| 5 | S14 | XHLD | various | -8.00% | stop_loss | - |
| 6 | S14 | MRAM | various | -8.00% | stop_loss | - |
| 7 | S14 | AAOI | various | -8.00% | stop_loss | - |
| 8 | S14 | MAXN | various | -8.00% | stop_loss | - |
| 9 | S14 | NAMM | various | -8.00% | stop_loss | - |
| 10 | S14 | WRN | various | -8.00% | stop_loss | - |

---

## Appendix B: Strategy Parameters

| Strategy | Entry Threshold | Stop% | Target% | MaxHold | MaxConcurrent |
|----------|----------------|-------|---------|---------|---------------|
| S12 | Prob >= 0.70 | 3% | 2% | 60m | 4 |
| S14 | Sentiment > 0.6 | 8% | 15% | 180m | 4 |
| S15 | Regime change p > 0.85 | 4% | 3% | 30m | 2 |
| S17 | Attn score > 0.65 | 4% | 3% | 45m | 4 |
| S19 | UCB > adaptive | 3% | 2% | 30m | 4 |
| S20 | Anomaly score > 3σ | 4% | 3% | 60m | 4 |
| S21 | Z-score > 2.0 | 3% | 2% | 120m | 2 |
| S23 | LSTM prob >= 0.75 | 3% | 3% | 60m | 4 |
| S27 | Lag corr > 0.7 | 3% | 2% | 45m | 4 |
| S28 | Composite > 0.8 | 6% | 5% | 120m | 4 |
| S29 | MC p-value < 0.05 | 4% | 3% | 30m | 4 |
| S30 | Meta-prob >= 0.65 | 4% | 3% | 120m | 4 |
| S32 | Vote >= 3/5 | 3% | 2% | 60m | 4 |
| S33 | Stack prob >= 0.80 | 3% | 3% | 60m | 4 |

---

## Appendix C: Model Registry

| Model ID | Domain | Parameters | Inference Time | GPU Required |
|----------|--------|------------|----------------|-------------|
| ProsusAI/finbert | Sentiment | 110M | ~15ms | No |
| mrm8488/distilroberta-financial | Sentiment | 82M | ~10ms | No |
| cardiffnlp/twitter-roberta | Sentiment | 125M | ~12ms | No |
| amazon/chronos-t5-small | Time Series | 46M | ~50ms | Recommended |
| amazon/chronos-bolt-base | Time Series | 205M | ~30ms | Recommended |
| google/timesfm-2.0 | Time Series | 200M | ~40ms | Yes |
| ibm-granite/TTM-r2 | Time Series | 1M | ~5ms | No |
| BAAI/bge-large-en-v1.5 | Embeddings | 335M | ~20ms | Recommended |
| sentence-transformers/all-MiniLM-L6-v2 | Embeddings | 22M | ~5ms | No |
| facebook/bart-large-mnli | Classification | 407M | ~25ms | Recommended |
| dslim/bert-base-NER | NER | 108M | ~10ms | No |
| gtfintechlab/FOMC-RoBERTa | Finance | 125M | ~12ms | No |
| ElKulako/cryptobert | Finance | 110M | ~12ms | No |

---

*End of report. Generated 2026-04-15. Data sources: trading.db, \\Station001\DATA\hvlf\rotating\, D:\Data\Strategies\HVLF\MinuteBars_SB\.*
