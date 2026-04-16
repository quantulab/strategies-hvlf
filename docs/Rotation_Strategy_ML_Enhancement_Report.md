---
noteId: "37c99f6039aa11f19da93711749444a5"
tags: []

---

# Rotation Strategy ML/AI Enhancement Report

**Date:** 2026-04-16
**Scope:** All 7 rotation sub-strategies (Strategy 31–37)
**Sources:** arxiv (30+ queries, ~40 relevant papers), Hugging Face (15+ model/paper searches)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Strategy 32: Volume Surge Entry](#strategy-32-volume-surge-entry)
3. [Strategy 33: Streak Continuation](#strategy-33-streak-continuation)
4. [Strategy 34: Whipsaw Fade](#strategy-34-whipsaw-fade)
5. [Strategy 35: Pre-Market Persistence](#strategy-35-pre-market-persistence)
6. [Strategy 36: Cap-Size Breakout](#strategy-36-cap-size-breakout)
7. [Strategy 37: Elite Accumulation](#strategy-37-elite-accumulation)
8. [Cross-Strategy Enhancements](#cross-strategy-enhancements)
9. [Hugging Face Models](#hugging-face-models)
10. [Implementation Priority](#implementation-priority)

---

## Executive Summary

Each of the 7 rotation sub-strategies was analyzed against current academic research (arxiv) and available pre-trained models (Hugging Face). A total of **42 papers** and **6 Hugging Face models** were identified as directly applicable. Enhancements fall into three categories:

1. **Signal Quality** — ML models to improve conviction scoring (lead-lag prediction, streak survival, regime detection)
2. **Execution Optimization** — RL/DL models for entry timing (VWAP pullback optimization, volume curve prediction)
3. **Risk Filtering** — Sentiment models and anomaly detection to filter false signals (news-driven gap detection, concept drift)

All enhancement recommendations have been added to each strategy's instruction file in `data/instructions/`.

---

## Strategy 32: Volume Surge Entry

**Core Edge:** Volume scanner appearances precede gain scanner appearances by ~120 minutes.

### Relevant Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Hidden Order in Trades Predicts Price Moves** | [2512.15720](https://arxiv.org/abs/2512.15720) | Order-flow entropy from 15-state Markov model predicts price move magnitude — add as conviction factor for volume signals |
| **Emergence of Intraday Lead-Lag Relationships** | [1401.0462](https://arxiv.org/abs/1401.0462) | Statistically validated lead-lag detection framework — replace fixed 120-min avg with dynamic per-ticker lead-lag estimation |
| **Forecasting Intraday Volume with ML** | [2505.08180](https://arxiv.org/abs/2505.08180) | ML models (gradient boosting, LSTM) for intraday volume prediction — predict WHICH volume spikes convert to gain scanner appearances |
| **LIFT: Learning from Leading Indicators** | [2401.17548](https://hf.co/papers/2401.17548) | Framework to identify and use leading indicators in time series — directly applicable to modeling volume as a leading indicator for price |
| **Stockformer: Price-Volume Factor Model** | [2401.06139](https://hf.co/papers/2401.06139) | Wavelet transform + multi-task self-attention for price-volume relationships — encode volume surge patterns as multi-scale features |
| **Deep Learning for VWAP Execution** | [2502.13722](https://arxiv.org/abs/2502.13722) | DL volume curve prediction — can predict intraday volume distribution to time entries when volume surges are most likely to convert |
| **Lead-Lag via Stop-and-Reverse-MinMax** | [1504.06235](https://arxiv.org/abs/1504.06235) | Mathematical framework for formalizing and detecting lead-lag relationships between any two time series |

### Proposed Enhancements

1. **Dynamic Lead-Time Model:** Replace static 120-min average lead time with per-ticker ML model using LIFT framework. Features: historical lead times, volume scanner count, cap tier, day-of-week, market breadth. Output: predicted lead time distribution per ticker.
2. **Order-Flow Entropy Conviction Factor:** Implement 15-state Markov model from arxiv 2512.15720 to compute order-flow entropy. High entropy = more predictable price magnitude. Add as +2 conviction bonus when entropy exceeds threshold.
3. **Volume Conversion Classifier:** Train gradient boosting or xLSTM on historical volume→gain transitions. Features: volume spike magnitude, # of volume scanners, spread, market cap, whipsaw history. Output: probability of gain scanner appearance within 180 min.
4. **News Sentiment Filter:** Use distilroberta financial sentiment model to score headlines for volume surge tickers. Positive sentiment + volume surge = +1 conviction. Negative sentiment + volume surge = -1 (selling pressure, not accumulation).

---

## Strategy 33: Streak Continuation

**Core Edge:** Multi-day scanner streaks are bimodal — they either break early or persist for weeks. Enter on day 3+.

### Relevant Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **NoxTrader: LSTM Momentum Prediction** | [2310.00747](https://arxiv.org/abs/2310.00747) | LSTM for return momentum prediction — can predict streak sustainability and expected return magnitude |
| **Is Factor Momentum More than Stock Momentum?** | [2009.04824](https://arxiv.org/abs/2009.04824) | Factor momentum works at short lags — validates multi-day streak continuation thesis and suggests factor-level streak tracking |
| **Time-Series Momentum with Deep Multi-Task Learning** | [2306.13661](https://hf.co/papers/2306.13661) | Multi-task learning jointly optimizes momentum portfolio construction AND volatility forecasting — apply to jointly predict streak survival probability + expected return |
| **MTMD: Multi-Scale Temporal Memory** | [2212.08656](https://hf.co/papers/2212.08656) | Temporal memory captures self-similarity in stock trends — day-5 streaks that "look like" historically successful patterns get conviction boost |
| **Intraday Patterns in Cross-Section Returns** | [1005.3535](https://arxiv.org/abs/1005.3535) | Half-hour return continuation lasting 40+ trading days — validates persistence of intraday momentum patterns underlying streaks |
| **When Alpha Breaks: Safe Stock Rankers** | [2603.13252](https://arxiv.org/abs/2603.13252) | Two-level uncertainty framework — detect when streak model is unreliable during regime shifts and should be paused |
| **Deep Learning for Cross-Section Returns** | [1801.01777](https://arxiv.org/abs/1801.01777) | Neural nets for cross-sectional return prediction — improve rank prediction component of streak signals |

### Proposed Enhancements

1. **Streak Survival Classifier:** Train multi-task model (paper 2306.13661) that jointly predicts: (a) probability streak continues tomorrow, (b) expected return if it does. Features: streak_days, rank trajectory, volume trend, whipsaw history, market regime, sector momentum. Use survival probability as dynamic conviction factor.
2. **Temporal Pattern Matching:** Apply MTMD temporal memory (paper 2212.08656) to encode current streak "shape" (rank trajectory over days) and match against historical successful/failed streaks. Similar-to-successful patterns get +2 conviction, similar-to-failed get -2.
3. **Regime-Aware Streak Filtering:** Implement the "When Alpha Breaks" uncertainty framework (paper 2603.13252) to detect when cross-sectional rank models are unreliable. During detected regime shifts, require score 7+ instead of 5+ for Tier 1.
4. **Factor Momentum Overlay:** Track factor-level momentum (paper 2009.04824) — if the factor driving the streak (e.g., tech momentum, energy rotation) is itself in a positive trend, add +1 conviction.

---

## Strategy 34: Whipsaw Fade

**Core Edge:** Known whipsaw tickers (UVIX 72%, SQQQ 70%, SOXL 70% reversal rates) mean-revert intraday.

### Relevant Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Compounding Effects in Leveraged ETFs** | [2504.20116](https://arxiv.org/abs/2504.20116) | LETF performance depends on return autocorrelation — negative autocorrelation = higher mean reversion edge. Use as dynamic conviction factor |
| **LETF Rebalancing Destabilizes Markets** | [2010.13036](https://arxiv.org/abs/2010.13036) | Agent-based model showing LETF rebalancing creates predictable reversals near close — explains WHY whipsaw names mean-revert and optimal fade timing |
| **Threshold Model for Local Volatility** | [1712.08329](https://arxiv.org/abs/1712.08329) | Piecewise-constant volatility with leverage effect + mean reversion — mathematical basis for estimating reversion speed |
| **HMM + LSTM for Stock Trends** | [2104.09700](https://arxiv.org/abs/2104.09700) | HMM regime detection combined with LSTM — replace simple G/L ratio with HMM-based trending vs. mean-reverting regime classifier |
| **Advance Bull/Bear Phase Detection** | [2411.13586](https://arxiv.org/abs/2411.13586) | Advance detection of market phases — predict when trending days will break fades BEFORE entering |
| **Adaptive Market Intelligence: MoE Framework** | [2508.02686](https://hf.co/papers/2508.02686) | Mixture of Experts with volatility-aware gating — route decisions to fade expert vs. trend expert per detected regime |
| **Trade the Event: Corporate Events Detection** | [2105.12825](https://hf.co/papers/2105.12825) | News-based event detection — distinguish news-driven gaps (less likely to revert) from flow-driven gaps (more likely to revert) |

### Proposed Enhancements

1. **HMM Regime Classifier:** Replace simple G/L ratio threshold with HMM-based regime detector (paper 2104.09700). Train on historical scanner breadth + G/L ratio + VIX to classify: TRENDING (disable fades), MEAN-REVERTING (enable fades), TRANSITION (reduce size). Update regime classification every 30 min.
2. **Return Autocorrelation Conviction Factor:** Compute rolling 5-day return autocorrelation per whipsaw ticker (paper 2504.20116). Negative autocorrelation = higher fade conviction (+2 points). Positive autocorrelation = trending, reduce conviction (-2 points).
3. **LETF Rebalancing Timer:** Model the LETF rebalancing flow (paper 2010.13036) to predict optimal fade entry window. LETFs rebalance near close — fading at 2-3 PM captures the pre-rebalancing reversal.
4. **News-Driven Gap Filter:** Use financial sentiment model + topic classifier to detect if gap is news-driven (earnings surprise, FDA approval) vs. technical/flow-driven. News-driven gaps get -3 conviction (less likely to revert). Flow-driven gaps get +1 conviction.
5. **Mixture of Experts Routing:** Implement MoE framework (paper 2508.02686) with two experts: fade expert (mean-reversion model) and trend expert (momentum model). Volatility-aware gate routes each signal to the appropriate expert. If fade expert's confidence > 70%, trade; otherwise skip.

---

## Strategy 35: Pre-Market Persistence

**Core Edge:** 95.7% of pre-market scanner movers persist into regular trading hours.

### Relevant Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Universal Price Formation from Deep Learning** | [1803.06917](https://hf.co/papers/1803.06917) | Universal and stationary price formation mechanism learned from order books — applicable to modeling the pre-market→open transition as a universal pattern |
| **Empirical Regularities of Opening Call Auction** | [0905.0582](https://arxiv.org/abs/0905.0582) | Statistical patterns in opening auctions — directly models the pre-market price discovery process and persistence mechanics |
| **Pre-training Time Series with Stock Data** | [2506.16746](https://hf.co/papers/2506.16746) | Pre-trained transformer (SSPT) for stock selection — applicable to scoring pre-market movers with transfer-learned representations |
| **Proactive Model Adaptation Against Concept Drift** | [2412.08435](https://hf.co/papers/2412.08435) | Handles non-stationarity in time series forecasting — critical since persistence rates vary day-to-day (92%-100%) |
| **Alpha-R1: Alpha Screening with LLM Reasoning** | [2512.23515](https://hf.co/papers/2512.23515) | RL-trained 8B reasoning model for context-aware alpha screening — could dynamically screen pre-market movers with market-condition awareness |
| **Adaptive Market Intelligence: MoE Framework** | [2508.02686](https://hf.co/papers/2508.02686) | Volatility-aware MoE — route pre-market signals differently on high-volatility vs. low-volatility days |

### Proposed Enhancements

1. **Dynamic Persistence Probability Model:** Replace fixed 95.7% base rate with a per-ticker, per-day binary classifier. Features: gap size, pre-market volume, whipsaw history, market breadth, day-of-week, VIX level, sector momentum, news sentiment score. Output: probability of persistence at 9:35 AM. Only trade when model predicts >90%.
2. **Concept Drift Detector:** Implement concept drift detection (paper 2412.08435) to identify when persistence rate regime has shifted. If detected drift (e.g., persistence rate dropping below 90% over recent sessions), auto-tighten entry criteria or disable strategy.
3. **News Catalyst Scoring:** Use financial sentiment model to classify pre-market movers into: (a) news-driven positive (earnings beat, upgrade) — highest persistence, (b) news-driven negative context (sector sympathy, macro) — moderate persistence, (c) no-news technical — filter more aggressively against whipsaw list.
4. **Opening Auction Pattern Model:** Apply opening auction research (paper 0905.0582) to model the price discovery mechanism at open. Tickers with orderly pre-market price discovery (narrow spread, convergent quotes) persist more than chaotic ones. Add as conviction factor.

---

## Strategy 36: Cap-Size Breakout

**Core Edge:** Tickers graduating from SmallCap→MidCap or MidCap→LargeCap scanners signal explosive growth.

### Relevant Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **Survivorship Bias in Small-Cap Indices** | [2603.19380](https://arxiv.org/abs/2603.19380) | Quantifies survivorship bias in small-cap — critical for understanding that crossover signals may reflect index rebalancing, not genuine growth |
| **Intraday Order Dynamics by Market Cap** | [2502.07625](https://arxiv.org/abs/2502.07625) | Markov chain model of order transition dynamics across High/Medium/Low cap stocks — can model the probability of sustained cap-tier transitions |
| **Sector Rotation by Factor Model** | [2401.00001](https://hf.co/papers/2401.00001) | Factor model framework for sector/size rotation — applicable to predicting which cap tiers are favored in current regime |
| **TradeFM: Generative Foundation Model for Trade-Flow** | [2602.23784](https://hf.co/papers/2602.23784) | 524M-param transformer learns cross-asset trade representations — could detect cap-tier regime shifts from aggregate flow patterns |
| **Structured Event Representation for Returns** | [2512.19484](https://arxiv.org/abs/2512.19484) | LLM-extracted event features from news predict returns — identify fundamental catalysts driving crossover (earnings, contracts, M&A) |
| **Stockformer: Price-Volume Factor Model** | [2401.06139](https://hf.co/papers/2401.06139) | Graph embedding captures multi-stock relationships — detect when peer stocks are also crossing tiers (sector-wide crossover) |

### Proposed Enhancements

1. **Markov Transition Probability Model:** Use the Markov chain framework (paper 2502.07625) to compute transition probabilities between cap tiers. Replace fixed "2+ day confirmation" with dynamic sustainability probability. If P(stay in new tier) > 70%, enter immediately on day 1 with high conviction.
2. **Peer Crossover Detection:** Apply graph-based multi-stock modeling (Stockformer, paper 2401.06139) to detect when multiple stocks in the same sector are crossing tiers simultaneously. Sector-wide crossover = +3 conviction (industry rotation), single-stock crossover = standard scoring.
3. **Fundamental Catalyst Filter:** Use LLM event extraction (paper 2512.19484) + sentiment model to identify news catalysts driving crossover. Categories: (a) Fundamental (earnings, contracts, FDA) = +2 conviction, (b) Technical (volume only) = +0, (c) Index rebalancing (paper 2603.19380) = -2 conviction (temporary, will revert).
4. **Size Factor Regime Overlay:** Track the small-cap vs. large-cap factor spread (paper 2401.00001). When small-cap factor is outperforming, Small→Mid crossovers are more reliable. When large-cap is outperforming, Mid→Large crossovers are more reliable. Add as regime-aware conviction modifier.

---

## Strategy 37: Elite Accumulation

**Core Edge:** Tickers holding top-5 rank on gain scanners for 3+ consecutive days signal institutional accumulation. Enter on VWAP pullback.

### Relevant Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **VWAP Execution as Optimal Strategy** | [1408.6118](https://arxiv.org/abs/1408.6118) | Mathematical proof that VWAP is optimal execution benchmark — validates the VWAP pullback entry thesis from an institutional perspective |
| **Optimal VWAP Under Transient Impact** | [1901.02327](https://arxiv.org/abs/1901.02327) | VWAP optimization accounting for permanent + transient market impact — models how institutional accumulation affects VWAP behavior |
| **Deep Learning for VWAP Execution** | [2502.13722](https://arxiv.org/abs/2502.13722) | DL model for volume curve prediction — predict intraday volume distribution to identify optimal VWAP pullback windows |
| **Price Impact Asymmetry of Institutional Trading** | [1110.3133](https://arxiv.org/abs/1110.3133) | Buy/sell impact asymmetry in institutional orders — if buy impact > sell impact, accumulation thesis confirmed. Use as conviction factor |
| **TLOB: Transformer for LOB Price Trend** | [2502.15757](https://hf.co/papers/2502.15757) | Dual-attention transformer for limit order book prediction — predict VWAP bounce probability before placing limit order |
| **RL for Optimal Execution with Time-Varying Liquidity** | [2402.12049](https://hf.co/papers/2402.12049) | Double Deep Q-learning for adaptive execution — learn optimal pullback depth dynamically instead of fixed 0.5% VWAP proximity |
| **MM-DREX: Multimodal Expert Routing for Trading** | [2509.05080](https://hf.co/papers/2509.05080) | Vision-language model for candlestick patterns + dynamic expert routing — detect accumulation patterns from candlestick chart analysis |

### Proposed Enhancements

1. **RL-Based VWAP Entry Optimization:** Replace fixed 0.5% VWAP proximity trigger with a DRL agent (paper 2402.12049) that learns optimal pullback depth per ticker. Features: current distance to VWAP, volume profile, bid-ask spread, time of day, historical VWAP bounce success rate. The agent learns when shallow pullbacks (0.2%) are sufficient vs. when to wait for deeper pullbacks (1%).
2. **LOB Bounce Probability:** Apply dual-attention LOB transformer (paper 2502.15757) to predict the probability of price bouncing off VWAP before placing limit order. Only place LMT at VWAP when bounce probability > 65%. When bounce probability is low, wait for next cycle.
3. **Institutional Flow Asymmetry Factor:** Compute the buy/sell impact ratio (paper 1110.3133) using recent trade data. If buy_impact / sell_impact > 1.2, institutional accumulation is confirmed — add +2 conviction. If ratio < 0.8, distribution may be occurring — add -2 conviction.
4. **Volume Curve Prediction for Entry Timing:** Use DL volume curve model (paper 2502.13722) to predict when VWAP pullbacks are most likely (typically at volume troughs, 11:30 AM - 1:00 PM). Schedule entry attempts during predicted pullback windows rather than random 10-minute cycles.
5. **News-Driven Accumulation Confirmation:** Use financial sentiment models to detect sustained positive institutional interest (analyst upgrades, 13F filings, insider buying). Sustained positive news flow + top-5 rank = strongest accumulation signal (+2 conviction).

---

## Cross-Strategy Enhancements

These apply to the master strategy (Strategy 31) and affect all 6 sub-strategies.

### Research Papers

| Paper | arxiv | Enhancement |
|-------|-------|-------------|
| **HMM + LSTM for Stock Trends** | [2104.09700](https://arxiv.org/abs/2104.09700) | Replace Phase 1 regime classification (simple G/L ratio) with HMM-based regime detector |
| **When Alpha Breaks: Safe Stock Rankers** | [2603.13252](https://arxiv.org/abs/2603.13252) | Two-level uncertainty — detect when ANY sub-strategy's scoring model is unreliable |
| **Adaptive Market Intelligence: MoE** | [2508.02686](https://hf.co/papers/2508.02686) | Route capital allocation across sub-strategies using volatility-aware gating |
| **Concept Drift Detection** | [2412.08435](https://hf.co/papers/2412.08435) | Detect when scanner pattern statistical properties have shifted |
| **TradeFM: Foundation Model for Trade-Flow** | [2602.23784](https://hf.co/papers/2602.23784) | 524M-param transformer for cross-asset flow analysis — detect macro regime shifts |
| **Alpha-R1: LLM Reasoning for Alpha** | [2512.23515](https://hf.co/papers/2512.23515) | RL-trained LLM as a meta-strategy selector across all 6 sub-strategies |

### Proposed Architecture

1. **Regime Detection Layer (Phase 1):** HMM trained on scanner breadth, G/L ratio, VIX, sector rotation → regime probabilities + transition probabilities for sub-strategy priority weighting.
2. **Intelligent Rotation Selector (Phase 4):** Mixture of Experts where each sub-strategy is an "expert" with a volatility-aware gate that learns capital allocation weights.
3. **Universal News Sentiment Layer (Phase 3-4):** Score every candidate with distilroberta sentiment model; classify catalyst type with finbert topic classifier → route to best sub-strategy.
4. **Anomaly Detection Guard (Phase 5):** Flag unusual scanner behavior; reduce entries on anomaly detection.
5. **Meta-Learning KPI Optimizer (Phase 8):** Auto-adjust conviction thresholds based on rolling sub-strategy performance.

---

## Hugging Face Models

Models recommended for integration across all rotation strategies.

| Model | Downloads | Primary Use | Strategies |
|-------|-----------|-------------|------------|
| [mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis](https://hf.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis) | 252K | Universal news sentiment scoring for all candidates | ALL |
| [mrm8488/deberta-v3-ft-financial-news-sentiment-analysis](https://hf.co/mrm8488/deberta-v3-ft-financial-news-sentiment-analysis) | 87K | High-accuracy DeBERTa-v3 sentiment for Tier 1 signal validation | ALL |
| [ahmedrachid/FinancialBERT-Sentiment-Analysis](https://hf.co/ahmedrachid/FinancialBERT-Sentiment-Analysis) | 22K | Earnings/guidance-specific sentiment | 33, 35, 37 |
| [soleimanian/financial-roberta-large-sentiment](https://hf.co/soleimanian/financial-roberta-large-sentiment) | 3.4K | Deep analysis of corporate filings, ESG reports | 36, 37 |
| [nickmuchi/finbert-tone-finetuned-finance-topic-classification](https://hf.co/nickmuchi/finbert-tone-finetuned-finance-topic-classification) | 694 | Catalyst type classification (earnings, M&A, macro, technical) | 32, 34, 35, 36 |
| [keras-io/timeseries-anomaly-detection](https://hf.co/keras-io/timeseries-anomaly-detection) | 30 | Anomalous volume/price pattern detection | 31 (cross-strategy) |

### Integration Notes

- **distilroberta** is the recommended default — fast inference (252K downloads, battle-tested), suitable for real-time 10-minute cycle scoring
- **deberta-v3** should be used as a secondary confirmation for high-conviction signals only (higher accuracy but slower)
- **Topic classifier** enables routing: earnings news → elite accumulation, gap news → pre-market persist, sector rotation → capsize breakout

---

## Implementation Priority

Ordered by expected impact and implementation complexity.

### Tier 1 — High Impact, Low Complexity (implement first)

| Enhancement | Strategy | Rationale |
|-------------|----------|-----------|
| News sentiment conviction factor | ALL | Drop-in: fetch headlines, score with distilroberta, ±1 conviction. No model training needed. |
| HMM regime classifier | 31, 34 | Replace G/L ratio with HMM. Well-studied problem, libraries available (hmmlearn). Directly improves Phase 1 for all strategies. |
| Return autocorrelation factor | 34 | Simple rolling computation, no model training. Directly improves fade conviction accuracy. |
| Concept drift detection | 31, 35 | Statistical test on rolling persistence/win rates. Alert when edge has degraded. |

### Tier 2 — High Impact, Medium Complexity (implement second)

| Enhancement | Strategy | Rationale |
|-------------|----------|-----------|
| Volume conversion classifier | 32 | Train gradient boosting on historical volume→gain transitions. Requires labeled data from `volume_lead_signals` table. |
| Streak survival classifier | 33 | Train on historical streak data from `streak_tracker`. Multi-task learning adds complexity but high value. |
| Dynamic persistence probability | 35 | Binary classifier on per-ticker persistence data. Requires accumulating labeled examples first. |
| Markov transition probability | 36 | Compute from historical cap-tier data. Requires `capsize_crossovers` history. |

### Tier 3 — High Impact, High Complexity (implement later)

| Enhancement | Strategy | Rationale |
|-------------|----------|-----------|
| RL-based VWAP entry optimization | 37 | DRL agent requires simulation environment and significant training. High potential but complex. |
| Mixture of Experts rotation selector | 31 | Replace fixed priority mapping. Requires per-expert training and gating network. |
| LOB bounce predictor | 37 | Requires limit order book data feed (not currently available via MCP scanners). |
| LETF rebalancing timer | 34 | Requires modeling fund-level rebalancing mechanics. Research-grade implementation. |

---

## Files Modified

Each strategy instruction file now contains a `## ML/AI Enhancement Opportunities` section at the end:

| File | Section Added |
|------|---------------|
| `data/instructions/strategy_31_rotation_scanner_patterns.md` | Cross-strategy ML enhancements, HF models, architecture proposal |
| `data/instructions/strategy_32-rotation-volume_surge.md` | Lead-lag ML, order-flow entropy, volume conversion classifier |
| `data/instructions/strategy_33-rotation-streak_continuation.md` | Streak survival classifier, temporal pattern matching, factor momentum |
| `data/instructions/strategy_34-rotation-whipsaw_fade.md` | HMM regime, autocorrelation, LETF rebalancing, MoE routing |
| `data/instructions/strategy_35-rotation-premarket_persist.md` | Dynamic persistence model, concept drift, news catalyst scoring |
| `data/instructions/strategy_36-rotation-capsize_breakout.md` | Markov transition, peer crossover, fundamental catalyst filter |
| `data/instructions/strategy_37-rotation-elite_accumulation.md` | RL VWAP optimization, LOB bounce, institutional flow asymmetry |
