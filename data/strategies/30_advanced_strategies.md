---
noteId: "c390423038ea11f1aa17e506bb81f996"
tags: []

---

# 30 Advanced Trading Strategies — Scanner-Driven

> Generated 2026-04-15 from `\\Station001\DATA\hvlf\rotating` scanner directory
> Data: 52 trading days (2026-01-28 to 2026-04-15), 31 scanners × 3 cap tiers, ~30s refresh

---

## GLOBAL RULE: Profit Protection — Trailing Stop Ratchet (MANDATORY)
**Applies to ALL 30 sub-strategies below. Overrides strategy-specific stops when it produces a tighter (higher) stop. Learned from AGAE 2026-04-15: +26% gain reversed to -7% loss with no protection.**

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

---

## Strategy 12: ML Rank Velocity Classifier

### Objective
Use a gradient-boosted classifier (XGBoost/LightGBM) to predict whether a stock's intraday return over the next 60 minutes will exceed +2%, based on how fast it is climbing scanner rankings.

### Features (per symbol per scan snapshot)
1. **Rank delta** — change in rank position over last 5/10/20 snapshots on GainSinceOpen, HotByVolume, HotByPrice
2. **First-appearance flag** — binary: is this the first time the symbol appeared on this scanner today?
3. **Cross-scanner count** — number of distinct scanner types the symbol currently appears on
4. **Cap-tier consistency** — does the symbol appear on the same scanner in multiple cap tiers?
5. **Time-of-day bucket** — pre-market / first-15-min / morning / midday
6. **Rank stability** — standard deviation of rank over trailing 10 snapshots (low = sticky leader)

### Labels
- 1 if the stock's price 60 min after signal exceeds the signal-time price by ≥ 2%
- 0 otherwise
- Collect labels by joining scanner timestamps to historical bar data (1-min OHLCV)

### Training
- Walk-forward: train on days 1–30, validate on 31–40, test on 41–52
- Class-weight balancing (positive cases are minority)
- Feature importance → prune to top 8 features
- Hyperparameter search via Optuna (max 200 trials)

### Entry Rules
1. Model probability ≥ 0.70
2. Stock must be on at least 2 scanners simultaneously
3. Current spread < 1.5% of mid price
4. Entry only between 9:35 AM and 11:30 AM

### Position Sizing & Risk
- 1% of account per trade, max 4 concurrent
- Stop: 3% below entry
- Target: 2% above entry (1:0.67 risk/reward, compensated by >70% win rate)
- Time stop: exit if target not hit within 60 min

---

## Strategy 13: Reinforcement Learning Scanner Navigator

### Objective
Train a PPO (Proximal Policy Optimization) agent to decide BUY / HOLD / SELL based on real-time scanner state, learning optimal timing that no static rule can capture.

### State Space (observation vector per timestep)
- Top-10 ranked symbols on each of the 11 scanner types for the target cap tier (110 one-hot encoded slots)
- Target symbol's current rank on each scanner (11 integers, -1 if absent)
- Minutes since market open (continuous)
- Current unrealized P&L of open position (continuous)
- Number of trades taken today (integer)

### Action Space
- **0 = Do nothing** — no position change
- **1 = Buy** — enter long with fixed size (if flat)
- **2 = Sell** — close position (if long)

### Reward Function
- Realized P&L per trade, minus a $0.005/share friction penalty
- Penalty of -0.1 for each action that is invalid (buy when already long, sell when flat)
- Bonus of +0.05 for holding through a profitable 5-min candle (encourages patience)
- Daily Sharpe component: at end-of-day, add 0.1 × (daily_return / daily_std) to reward

### Training
- Environment: replay scanner CSVs + 1-min bar data day-by-day
- PPO with GAE (λ=0.95), clip ratio 0.2, entropy coefficient 0.01
- 500 episodes (full-day replays), batch size 64
- Curriculum: start with LargeCap only (more liquid), then add MidCap/SmallCap

### Deployment
- Run agent inference every 30 seconds when new scanner snapshot arrives
- Hard guardrails: max 3 trades/day, max 2% account risk per trade, no trading after 3:00 PM
- Shadow-mode first 10 days: log decisions but don't execute, compare to baseline strategies

---

## Strategy 14: LLM News Sentiment + Scanner Confluence

### Objective
Use a large language model (Claude API) to score real-time news headlines for each symbol appearing on scanners, entering only when positive sentiment aligns with scanner momentum.

### Pipeline
1. Every 5 minutes, collect current top-20 symbols from GainSinceOpen + HotByVolume across all cap tiers
2. For each symbol, fetch latest 5 news headlines via `get_news_headlines` MCP tool
3. Send headlines to Claude with prompt:
   ```
   Rate the sentiment of these headlines for {SYMBOL} on a scale of -1.0 (very bearish)
   to +1.0 (very bullish). Consider: earnings surprise, analyst upgrades, FDA approvals,
   partnership announcements, insider buying as bullish. Consider: SEC investigations,
   earnings misses, downgrades, lawsuits, dilution as bearish. Return JSON: {"score": float, "catalyst": string}
   ```
4. Cache results for 30 minutes (headlines don't change that fast)

### Entry Rules
1. Symbol on GainSinceOpen or TopGainers scanner
2. LLM sentiment score ≥ +0.5
3. Catalyst is fundamental (earnings, FDA, partnership) — NOT technical/momentum-only
4. Volume today > 2× 20-day average
5. Stock not already up > 30% on the day (too extended)

### Position Sizing & Risk
- 1.5% of account per position, max 5 concurrent
- Stop: 8% below entry
- Target: scale out 50% at +15%, trail remainder with 10% trailing stop
- Time limit: close by EOD if catalyst is intraday news; hold up to 3 days if catalyst is multi-day (e.g., earnings beat)

### Risk Filters
- If LLM returns score between -0.3 and +0.3, skip (ambiguous)
- If the same symbol appeared on TopLosers in the past 2 days, skip
- If LLM confidence varies > 0.5 between two consecutive calls for the same headlines, flag as unreliable and skip

---

## Strategy 15: Scanner Regime Detector (Hidden Markov Model)

### Objective
Classify the market into regimes (trending-up, mean-reverting, high-volatility-crash) based on scanner composition, and select the appropriate sub-strategy for each regime.

### Observable Emissions (per 30-min window)
- Ratio of symbols on Gainer scanners vs. Loser scanners (bull/bear ratio)
- Average number of symbols per scanner (market breadth)
- Turnover rate: % of top-10 symbols that changed vs. prior window
- Cross-cap coherence: Jaccard similarity of symbol sets between LargeCap and SmallCap scanners

### Hidden States
- **State A — Broad Rally**: high bull/bear ratio, high breadth, low turnover (trend day)
- **State B — Rotational Chop**: moderate ratios, high turnover (sector rotation)
- **State C — Risk-Off Selloff**: low bull/bear ratio, losers dominating, high breadth on loss scanners

### Sub-Strategies by Regime
| Regime | Strategy | Description |
|--------|----------|-------------|
| A — Rally | Momentum chase | Buy top-5 on GainSinceOpen LargeCap, trail with 5% stop |
| B — Chop | Mean reversion | Short top LossSinceOpen, buy top GainSinceOpen in opposite cap tier |
| C — Selloff | Defensive fade | Buy LowOpenGap symbols showing reversal (moved from Loser to Gainer scanner within 1 hour) |

### Regime Transition Rules
- Minimum 3 consecutive 30-min windows in a state before acting
- If HMM posterior probability for any state < 0.6, stay in cash (uncertain regime)
- Retrain HMM weekly using past 20 days of scanner data

### Risk
- Max 3% account risk per regime-trade
- If regime switches mid-trade, close all positions immediately
- Daily loss limit: -2% of account → stop trading for the day

---

## Strategy 16: Graph Neural Network — Scanner Co-occurrence Network

### Objective
Build a dynamic graph where nodes are stocks and edges represent co-occurrence on the same scanner at the same time. Use a GNN to identify "hub" stocks that are central to momentum clusters and trade them.

### Graph Construction (updated every 5 minutes)
- **Nodes**: every unique symbol across all scanners in the current snapshot
- **Edges**: connect two symbols if they appear on the same scanner. Edge weight = number of scanners they share.
- **Node features**: rank on each scanner (11-dim vector), cap tier (one-hot), minutes on scanner today

### GNN Architecture
- 2-layer Graph Attention Network (GAT)
- Predict next-30-min return direction (binary classification)
- Train on 40 days, validate on 12

### Trading Signal
1. After GNN forward pass, select top-5 nodes by predicted probability of positive return
2. Among those, filter to nodes with degree centrality > 80th percentile (they're connected to many other movers)
3. Enter long on the top 3 after filtering

### Position Sizing & Risk
- Equal weight, 1% account each, max 3 positions
- Stop: VWAP - 2 ATR (14-period ATR on 5-min bars)
- Target: VWAP + 3 ATR
- Exit all at 2:00 PM if not stopped out

### Edge Cases
- If graph has < 20 nodes (quiet market), do not trade
- If a single stock is connected to > 50% of all nodes, skip it (likely an ETF/index proxy)

---

## Strategy 17: Transformer Sequence Model — Scanner Rank Trajectories

### Objective
Treat the sequence of a stock's rank positions across scanner snapshots as a time series and use a Transformer encoder to predict breakout vs. fade.

### Input Sequence
- For each symbol, extract its rank on every scanner at each snapshot for the past 60 minutes (≈120 snapshots)
- Shape: (120 timesteps, 11 scanner types) → flatten to 120 × 11 = 1,320 token sequence
- Add positional encoding for time and scanner-type encoding

### Architecture
- 4-layer Transformer encoder, 8 attention heads, d_model=128
- Classification head: binary (breakout: +3% in next 30 min vs. not)
- Trained on 40 days of labeled data

### Training Details
- Sliding window: every 5 min during market hours, generate a sample
- ~8,000 samples per day × 40 days = 320,000 training samples
- AdamW optimizer, cosine annealing LR schedule, dropout 0.1
- Augmentation: randomly mask 10% of scanner positions (robustness to missing data)

### Entry Rules
1. Transformer confidence ≥ 0.75
2. Symbol must be on at least 1 Gainer-type scanner
3. Symbol must NOT be on any Loser scanner
4. Entry within 5 seconds of signal (latency matters)

### Risk
- 1% account per trade, max 5 concurrent
- Hard stop: 4% below entry
- Profit target: 3% above entry
- Close all by 3:30 PM

---

## Strategy 18: Generative AI — Synthetic Scanner Scenario Planning

### Objective
Use a fine-tuned generative model to produce "what-if" scanner scenarios (e.g., "what would scanners look like if NVDA gaps down 10% tomorrow?") and pre-position based on likely cascade effects.

### Approach
1. Fine-tune a small language model (or use Claude with structured prompting) on historical scanner CSV data
2. Each evening, generate 10 hypothetical next-day scenarios:
   - Bull case: top sector continues
   - Bear case: reversal of today's leaders
   - Macro shock: rates spike, sector rotation
   - Earnings catalyst: specific earnings due tomorrow
   - etc.
3. For each scenario, the model outputs predicted scanner compositions (which stocks on which scanners)
4. Identify stocks that appear in bullish scanners across ≥ 7 of 10 scenarios ("robust winners")

### Pre-Market Actions
- At 8:00 AM, check pre-market scanner data against scenarios
- If actual scanner matches a scenario with > 60% Jaccard similarity, activate that scenario's trades
- Enter at market open with limit orders 0.5% above pre-market price

### Position Sizing & Risk
- 0.5% account per scenario-trade (small size — speculative)
- Max 6 positions from scenarios
- Stop: 5% below entry
- Target: hold until EOD, exit at 3:45 PM
- If no scenario matches by 10:00 AM, skip the day

---

## Strategy 19: Multi-Armed Bandit — Scanner Type Selector

### Objective
Use a contextual multi-armed bandit (Thompson Sampling) to dynamically learn which scanner type produces the best entry signals on any given day, adapting to changing market conditions.

### Arms (Actions)
Each arm = one scanner type used as the primary signal source:
1. GainSinceOpen
2. HighOpenGap
3. HotByPrice
4. HotByPriceRange
5. HotByVolume
6. TopGainers
7. TopVolumeRate
8. MostActive

### Context Vector
- VIX level bucket (low/med/high)
- S&P 500 overnight futures return direction
- Day of week
- Number of earnings reports due today
- Yesterday's winning scanner arm

### Reward
- Average return of top-3 stocks from the selected scanner over the next 2 hours after selection
- Measured at 10:00 AM daily (select scanner based on 9:35–9:55 AM data)

### Algorithm
- Thompson Sampling with Beta priors per arm
- Update posteriors daily based on observed reward (binarized: > 0% = success)
- Exploration bonus decays over time (ε starts at 0.3, decays to 0.05 over 30 days)

### Trading
- At 10:00 AM, bandit selects one scanner
- Buy top-3 ranked symbols from that scanner
- 1% account each, stop 5%, target 3%
- Close all by 1:00 PM (short hold = fast feedback for bandit learning)

---

## Strategy 20: Anomaly Detection — Scanner Population Shock

### Objective
Detect abnormal changes in scanner population (sudden flood of new symbols or mass exodus) as early warning of regime shifts, and trade the implied direction.

### Metrics (computed per scanner, per 5-min window)
1. **Population count**: number of unique symbols on the scanner
2. **Newcomer ratio**: % of symbols that were NOT on the scanner in the prior window
3. **Dropout ratio**: % of prior-window symbols that disappeared
4. **Rank entropy**: Shannon entropy of the rank distribution (uniform = high entropy)

### Anomaly Model
- Isolation Forest trained on 30 days of these 4 metrics × 11 scanner types = 44-dim feature vector
- Contamination parameter: 0.05 (expect 5% of windows to be anomalous)
- Retrain weekly

### Trading Signals
| Anomaly Type | Signal | Trade |
|-------------|--------|-------|
| Sudden population spike on Gainer scanners | Broad bullish rush | Buy QQQ calls (or top-3 on GainSinceOpen LargeCap) |
| Mass dropout from Gainer + population spike on Loser | Risk-off rotation | Short top GainSinceOpen (or buy puts on overextended leader) |
| Rank entropy collapse (one stock domininating) | Single-stock catalyst | Trade that dominant stock in direction of its scanner |
| Newcomer ratio > 80% on HotByVolume | Volume event (news/earnings) | Buy the top newcomer, tight stop |

### Risk
- 1% account per anomaly trade, max 2 per day
- Stop: 4% below entry (long) or 4% above entry (short)
- If anomaly resolves (metrics return to normal within 15 min), close immediately
- No anomaly trades after 2:00 PM

---

## Strategy 21: Pairs Trading — Scanner Divergence

### Objective
Identify historically correlated stock pairs where one appears on Gainer scanners while the other appears on Loser scanners (or is absent), and trade the convergence.

### Pair Selection (weekly rebalancing)
1. From the past 20 days of scanner data, find all symbol pairs that appeared on the same scanner (same cap tier) on ≥ 15 days
2. Compute rolling correlation of their daily scanner rank trajectories
3. Select pairs with correlation > 0.7 (they normally move together)
4. Current candidates (based on recent data): IONQ/QBTS, NIO/LCID, SOUN/BBAI, PLUG/EOSE

### Entry Rules
1. Pair member A is on GainSinceOpen (or TopGainers) AND pair member B is on LossSinceOpen (or TopLosers) — or B is absent from all Gainer scanners
2. The rank divergence (A's rank - B's rank, normalized) exceeds 2 standard deviations from the 20-day mean
3. Entry: long B (the laggard) + short A (the leader)
4. Entry only between 10:00 AM and 2:00 PM (avoid open/close volatility)

### Position Sizing
- Dollar-neutral: equal dollar amounts long and short
- 1.5% of account per leg (3% total notional)
- Max 2 pairs simultaneously

### Exit Rules
- Target: rank divergence returns to within 0.5 standard deviations (convergence)
- Stop: divergence exceeds 3.5 standard deviations (pair is breaking down)
- Time stop: close after 3 trading days if no convergence
- If either leg gets halted, close the other immediately

---

## Strategy 22: CNN on Scanner Heatmaps

### Objective
Render scanner data as 2D heatmap images (x-axis = time, y-axis = scanner type, pixel intensity = rank) and use a Convolutional Neural Network to classify visual patterns as bullish/bearish.

### Image Construction
- Per symbol: create an 11×120 grayscale image (11 scanner types × 120 time steps = 1 hour)
- Pixel value = normalized rank (0 = #1 ranked, 255 = not on scanner)
- Stack 3 consecutive hours as RGB channels for multi-timeframe context

### CNN Architecture
- ResNet-18 backbone (pretrained on ImageNet, fine-tuned)
- Binary output: stock will be up > 2% in 30 min (1) vs. not (0)
- Dropout 0.3, batch norm

### Training
- Generate images for every symbol that appeared on ≥ 3 scanners in a given hour
- ~500 images per day × 40 training days = 20,000 samples
- Data augmentation: horizontal flip (time reversal — tests if pattern is symmetric), Gaussian noise

### Entry
1. CNN probability ≥ 0.72
2. Symbol currently on HotByVolume (confirms real activity)
3. Enter at next 1-min bar close

### Risk
- 1% account, max 4 trades concurrent
- Stop: 3% below entry
- Target: 2.5% above entry
- Auto-close at 3:00 PM

---

## Strategy 23: LSTM Rank Forecaster

### Objective
Use a bidirectional LSTM to forecast a stock's rank on GainSinceOpen 30 minutes into the future. Enter when predicted rank is ≤ 5 (i.e., model predicts the stock will be a top-5 gainer).

### Input Features (per timestep = 30 seconds)
- Current rank on all 11 scanner types (11 features)
- Rank change velocity (11 features: difference from prior snapshot)
- Time-of-day embedding (sin/cos encoding)
- Cap-tier one-hot (3 features)
- Total: 27 features per timestep, lookback = 60 timesteps (30 min)

### Architecture
- 2-layer BiLSTM, hidden_size=64
- Dense head → regression output: predicted rank on GainSinceOpen at t+60
- Loss: MSE with extra penalty for predicting rank ≤ 5 when actual rank > 20 (punish false positives hard)

### Training
- Walk-forward: 30 train / 10 val / 12 test
- Early stopping on validation MAE
- Trained separately per cap tier

### Entry Rules
1. Predicted rank ≤ 5 AND current rank > 15 (i.e., model sees it climbing before it happens)
2. The symbol must currently be on at least 1 scanner (not completely absent)
3. Current time between 9:45 AM and 1:00 PM
4. Price > $1.00 (avoid sub-penny noise)

### Risk
- 1.5% account per trade, max 3 concurrent
- Stop: 5% below entry
- Target: sell when actual rank reaches top-5 on GainSinceOpen (the prediction came true) or after 45 min
- If predicted rank worsens (increases) on next model run, close immediately

---

## Strategy 24: News Event Velocity + Scanner Confirmation

### Objective
Detect rapid news publication velocity (multiple headlines in < 10 min) for a symbol and trade only if scanner data confirms momentum building in parallel.

### News Velocity Detection
1. Poll `get_news_headlines` every 2 minutes for all symbols on any scanner
2. Compute news_velocity = count of unique headlines in trailing 10 minutes
3. Flag if news_velocity ≥ 3 (unusual burst)

### Scanner Confirmation Rules
1. Symbol must appear on ≥ 2 different scanner types within 5 minutes of the news burst
2. Symbol must be climbing ranks (rank improved by ≥ 5 positions in last 10 min on any scanner)
3. Symbol must be on HotByVolume (volume confirming the news)

### Entry
- Buy at market after both conditions met
- Entry only 9:30 AM – 12:00 PM

### Sentiment Overlay (Optional Enhancement)
- If time permits, run headlines through sentiment classifier
- Only enter if sentiment is unanimously positive across all recent headlines
- If sentiment is mixed, reduce position size by 50%

### Risk
- 2% account per news-velocity trade (high conviction when confirmed)
- Stop: 6% below entry (news trades are volatile)
- Target: 10% above entry (news catalysts can run)
- Time stop: close by EOD if target not reached
- Max 2 news-velocity trades per day

---

## Strategy 25: Autoencoder — Scanner Latent Space Clustering

### Objective
Compress daily scanner data into a low-dimensional latent space using a variational autoencoder (VAE), then cluster trading days by "type" and use cluster-specific trading rules.

### Input (per trading day)
- For each of 11 scanner types × 3 cap tiers = 33 scanners:
  - Top-10 symbols at 10:00 AM, 11:00 AM, 12:00 PM (3 snapshots)
  - Encode each symbol as a hash → fixed-size embedding
- Flatten to a single vector per day (33 × 3 × 10 = 990 dimensions)

### VAE Architecture
- Encoder: 990 → 256 → 64 → latent (16-dim μ, 16-dim σ)
- Decoder: 16 → 64 → 256 → 990
- Train on 40 days, KL divergence weight β = 0.5

### Clustering
- K-means on the 16-dim latent space, K=4 (determined by elbow method)
- Label clusters by inspecting decoded scanner compositions:
  - Cluster 1: "Tech momentum day"
  - Cluster 2: "Broad rotation day"
  - Cluster 3: "Small-cap speculative day"
  - Cluster 4: "Low-activity drift day"

### Strategy per Cluster
| Cluster | Action |
|---------|--------|
| Tech momentum | Buy top-3 LargeCap GainSinceOpen, hold until EOD |
| Broad rotation | Short yesterday's #1 gainer, buy today's new entrants on HotByVolume |
| Small-cap speculative | Buy top SmallCap HotByPrice, tight 3% stop, 5% target |
| Low-activity drift | No trades (expected value is negative after commissions) |

### Execution
- At 10:15 AM, encode today's scanner state, classify cluster
- If cluster assignment probability > 0.7, execute cluster strategy
- Reassess at 11:15 AM — if cluster changed, close all and switch

---

## Strategy 26: Federated Learning Across Cap Tiers

### Objective
Train separate models per cap tier (Large/Mid/Small) but share gradient updates in a federated learning framework, letting each tier benefit from patterns discovered in others without mixing their distinct dynamics.

### Local Models (per cap tier)
- LightGBM classifier: predict if top-5 ranked stock will sustain its rank for 30+ min
- Features: rank, rank velocity, time-of-day, newcomer flag, scanner count
- Each model trains on its own tier's scanner data

### Federation Protocol
- After each daily training cycle, extract feature importance vectors from each tier's model
- Average the importance vectors (FedAvg)
- Use the averaged importance to re-weight features in all three models
- This transfers knowledge: e.g., if "rank velocity on HotByVolume" is important for SmallCap, LargeCap model also considers it more

### Trading
- Each tier model independently generates buy signals for its own universe
- Cross-tier confirmation bonus: if a symbol appears in bullish predictions from 2+ tier models (e.g., IONQ predicted bullish by both MidCap and SmallCap models), increase position size by 50%

### Risk
- 1% account per trade per tier, max 2 per tier = 6 max concurrent
- Stop: 4% below entry
- Target: 3% above entry
- Retrain federation weekly

---

## Strategy 27: Causal Inference — Scanner Lead-Lag Discovery

### Objective
Use Granger causality tests to discover which scanner types lead others in predicting stock price moves, then trade the leading signals before the lagging ones confirm.

### Analysis (run weekly)
1. For each stock that appeared on ≥ 5 scanners in the past week:
   - Extract time series of its rank on each scanner type (interpolated to 1-min frequency)
   - Run pairwise Granger causality tests between all scanner type pairs (lag = 1 to 10 min)
2. Build a causality graph: edge from Scanner A → Scanner B if A Granger-causes B at p < 0.05
3. Identify "leading scanners" (high out-degree) and "lagging scanners" (high in-degree)

### Expected Findings
- HotByVolume and HotByPrice tend to lead GainSinceOpen by 5-10 min (volume/price action precedes the "gain" classification)
- HighOpenGap leads TopGainers in the first hour (gap stocks convert to day gainers)
- TopVolumeRate may lead MostActive by 2-5 min

### Trading Rules
1. When a stock enters the top-10 on a leading scanner, set an alert
2. If within 10 minutes it has NOT yet appeared on the expected lagging scanner, enter long (anticipating it will appear soon and attract more attention)
3. Exit when the stock appears on the lagging scanner (the "confirmation trade" is done, edge disappears)

### Risk
- 1% account per trade, max 4 concurrent
- Stop: 3% below entry
- Expected hold time: 5-15 minutes (scalp)
- No trading if the Granger test R² < 0.1 (weak causal link this week)

---

## Strategy 28: Sentiment-Weighted Scanner Composite Score

### Objective
Create a composite "conviction score" for each stock by combining its scanner rank with real-time news sentiment and social media buzz, weighted by a dynamically learned function.

### Score Components
1. **Scanner Score** (0-100): weighted sum of normalized ranks across all scanners the stock appears on
   - Weight by scanner predictive power (from Strategy 27's Granger analysis)
   - Bonus points for appearing on multiple cap-tier scanners
2. **News Sentiment Score** (0-100): from LLM analysis of recent headlines (see Strategy 14)
3. **Social Buzz Score** (0-100): count of recent social media mentions weighted by account influence
   - Source: aggregate from financial APIs or web scraping
4. **Institutional Flow Score** (0-100): unusual options activity, dark pool prints
   - Source: options chain data via `get_option_chain` MCP tool

### Weighting
- Initial weights: Scanner 40%, News 25%, Social 15%, Flow 20%
- Adapt weekly using Bayesian optimization: maximize correlation between composite score and next-day returns
- Enforce minimum 20% weight on Scanner (it's the primary signal)

### Entry Rules
1. Composite score ≥ 80
2. No single component below 30 (balanced conviction)
3. Stock is not on any Loser scanner
4. Price > $2.00, average volume > 100K shares/day

### Position Sizing
- Size proportional to composite score: score 80 → 1% account, score 90 → 1.5%, score 95+ → 2%
- Max 5 concurrent positions
- Stop: 7% below entry
- Target: hold until composite score drops below 50, then exit

---

## Strategy 29: Monte Carlo Simulation — Scanner Outcome Distributions

### Objective
For each stock on a scanner, simulate 1,000 forward price paths using historical scanner-conditioned return distributions, and only trade when the simulated distribution is strongly skewed positive.

### Simulation Setup
1. From 40 days of history, collect all instances where a stock appeared at rank R on scanner S at time T
2. Record the actual forward returns at +15 min, +30 min, +60 min, +EOD
3. Fit a kernel density estimate (KDE) to these conditional return distributions

### Forward Simulation (per candidate stock)
1. Stock appears at rank R on scanner S at time T
2. Draw 1,000 samples from KDE(returns | rank=R, scanner=S, time_bucket=T)
3. Compute: P(return > 2%), P(return < -3%), expected return, 5th percentile (CVaR)

### Entry Rules
1. P(return > 2% in 30 min) ≥ 0.55
2. P(return < -3% in 30 min) ≤ 0.15 (downside protection)
3. Expected return > 0.8%
4. CVaR (5th percentile) > -4%
5. At least 50 historical observations for this (rank, scanner, time) tuple

### Position Sizing (Kelly Criterion)
- Kelly fraction = (p × b - q) / b where p = win prob, b = avg win / avg loss, q = 1-p
- Use half-Kelly for safety
- Cap at 2% of account per trade

### Risk
- Stop: at the 10th percentile of the simulated distribution
- Target: at the 75th percentile
- Max 4 concurrent, close all by 3:00 PM

---

## Strategy 30: Meta-Learning — Few-Shot Scanner Adaptation

### Objective
Use MAML (Model-Agnostic Meta-Learning) to train a model that can adapt to new market regimes with only 5 examples, solving the problem of models going stale after regime changes.

### Meta-Training
- Treat each trading day as a "task"
- For each task: sample 5 (scanner_state, forward_return) pairs as the support set, 20 as the query set
- Inner loop: 3 gradient steps on support set (fast adaptation)
- Outer loop: update meta-parameters to minimize query set loss across all tasks
- Base model: 3-layer MLP with 128 hidden units

### Deployment
1. Each morning at 9:45 AM, collect the first 5 scanner snapshots + their 15-min forward returns (from yesterday's close to today's open, use gap as proxy)
2. Run 3 gradient steps of inner-loop adaptation
3. Use adapted model to score stocks from 10:00 AM onward

### Advantages
- Adapts to new regimes (tariff shock, earnings season, Fed day) within 5 examples
- No need to retrain from scratch when market character changes
- Naturally handles distribution shift between training and deployment

### Entry Rules
1. Adapted model probability ≥ 0.65
2. Stock on at least 1 momentum scanner (GainSinceOpen, HotByPrice, TopGainers)
3. Volume confirmation: on HotByVolume or TopVolumeRate

### Risk
- 1% account per trade, max 3 concurrent
- Stop: 4% below entry
- Target: 3% above entry
- If adapted model accuracy on morning samples < 40%, skip the day (model can't adapt to today's regime)

---

## Strategy 31: Diffusion Model — Scanner State Prediction

### Objective
Use a denoising diffusion probabilistic model (DDPM) to generate predicted future scanner states and trade stocks that consistently appear in generated futures.

### Training
- Input: scanner state at time T (which symbols on which scanners, their ranks)
- Target: scanner state at time T+30 min
- Diffusion process: add Gaussian noise to target scanner state, train model to denoise
- Architecture: U-Net adapted for tabular data (1D convolutions over scanner dimension)

### Inference
1. At current time T, encode current scanner state
2. Run 50-step denoising to generate 20 predicted scanner states at T+30
3. Count how many of the 20 generated states include each symbol in top-10 of GainSinceOpen
4. "Consensus score" = count / 20

### Entry
1. Consensus score ≥ 0.7 (14+ of 20 generated futures agree)
2. Stock currently ranked below top-10 on GainSinceOpen (it's predicted to rise, not already there)
3. Stock is on at least HotByVolume (real activity backing the prediction)

### Risk
- 1% account per trade, max 3 concurrent
- Stop: 3.5% below entry
- Target: exit when stock actually enters top-10 on GainSinceOpen (prediction confirmed)
- Time stop: 45 min from entry

---

## Strategy 32: Cross-Scanner Arbitrage Detector

### Objective
Exploit information asymmetry between scanner types: when a stock appears on HotByVolume (buying pressure) but NOT yet on GainSinceOpen (price hasn't caught up), front-run the expected price catch-up.

### Signal Detection
1. Every 30 seconds, check all stocks on HotByVolume (any cap tier)
2. For each, check if it is NOT on GainSinceOpen, TopGainers, or HotByPrice
3. This divergence means: volume is surging but price hasn't moved yet
4. Possible causes: accumulation phase, block trades, pre-news positioning

### Confirmation Filters
1. Stock's HotByVolume rank must be ≤ 15 (significant volume, not marginal)
2. Stock must have been on HotByVolume for ≤ 5 minutes (fresh signal)
3. Stock must NOT be on any Loser scanner (volume isn't selling pressure)
4. Stock's TopVolumeRate rank must also be improving (volume is accelerating, not one-time block)

### Entry
- Buy immediately when all conditions met
- Use limit order at current ask (no chasing)

### Position Sizing & Risk
- 1.5% account per trade
- Stop: 2.5% below entry (tight — if volume doesn't translate to price, thesis is wrong)
- Target: exit when stock appears on GainSinceOpen or HotByPrice (information gap closed)
- Time stop: 20 min (if volume doesn't convert to price in 20 min, it won't)
- Max 3 concurrent

---

## Strategy 33: Ensemble Voting — Multi-Model Scanner Council

### Objective
Run 5 independent models simultaneously and only trade when ≥ 4 of 5 agree on direction, dramatically reducing false positives.

### Council Members
1. **XGBoost** — rank features + time features → binary classification (Strategy 12)
2. **LSTM** — rank sequences → rank prediction (Strategy 23)
3. **Isolation Forest** — anomaly detection on scanner populations (Strategy 20)
4. **Granger Lead-Lag** — rule-based from causal analysis (Strategy 27)
5. **Monte Carlo** — simulation-based probability (Strategy 29)

### Voting Protocol
- Each model outputs: {symbol, direction (long/short/neutral), confidence (0-1)}
- For a trade to execute: ≥ 4 models must agree on direction with confidence ≥ 0.5
- Final confidence = average of agreeing models' confidences
- If exactly 4 agree but the dissenter has confidence > 0.8 in the opposite direction, veto the trade

### Position Sizing
- Based on council average confidence:
  - 4/5 agree, avg conf 0.5–0.6: 0.5% account
  - 4/5 agree, avg conf 0.6–0.75: 1% account
  - 5/5 agree, avg conf 0.75+: 2% account (max conviction)

### Risk
- Stop: tightest stop of the 5 models' individual stops (most conservative)
- Target: median target of the 5 models
- Daily limit: max 3 council trades per day
- If council produces 0 trades for 3 consecutive days, retrain all models

---

## Strategy 34: Attention-Based Scanner Importance Weighting

### Objective
Use a multi-head self-attention mechanism to learn which scanner types deserve the most weight for each individual stock, personalizing the signal extraction.

### Architecture
- Input: for target stock, its rank on all 11 scanners at current + past 10 snapshots = 11 × 11 = 121 features
- Multi-head self-attention (4 heads) over the scanner dimension
- Attention weights reveal: for THIS stock, which scanners matter most
- Output: predicted 15-min forward return (regression)

### Key Insight
- For a biotech stock, HotByVolume + GainSinceOpen matter most (news-driven)
- For a large-cap tech stock, HotByPriceRange + TopVolumeRate matter most (institutional flow)
- The attention mechanism learns these sector-specific scanner preferences automatically

### Training
- Per-stock training with shared attention parameters
- Group stocks by GICS sector for transfer learning
- Train on 35 days, validate on 7, test on 10

### Entry Rules
1. Predicted return > 1.5%
2. The top-2 attention-weighted scanners must show the stock in top-20
3. Attention entropy must be < 2.0 (model is focused, not confused)
4. Entry between 9:45 AM – 1:00 PM

### Risk
- 1% account per trade, max 4 concurrent
- Stop: 3% below entry
- Target: predicted return level (dynamic per stock)
- If attention weights shift dramatically between snapshots (instability), exit immediately

---

## Strategy 35: Deep Q-Network — Optimal Entry Timing

### Objective
Train a Deep Q-Network (DQN) specifically to optimize WHEN to enter a trade after a scanner signal fires, learning the optimal delay that maximizes expected return.

### Problem
- Entering immediately on a scanner signal often means buying the spike
- Waiting too long means missing the move
- The optimal delay depends on scanner type, time of day, and volatility

### State Space
- Minutes since signal fired (0–30)
- Current price relative to signal-time price (% change)
- Volume since signal relative to pre-signal volume
- Scanner rank trajectory since signal
- Number of scanners the stock is currently on
- Bid-ask spread as % of price

### Action Space
- **ENTER NOW** — place buy order
- **WAIT** — check again in 30 seconds
- **ABORT** — cancel this opportunity (price moved too much or signal faded)

### Reward
- If ENTER: reward = return over next 30 min minus 0.1% transaction cost
- If WAIT: reward = 0 (delayed gratification)
- If ABORT: reward = 0 (no loss, no gain)
- Penalty for entering after price already moved > 5% from signal (chasing)

### Training
- Replay historical signals from all scanners, 40 days
- DQN with target network (soft update τ=0.005), replay buffer 100K
- ε-greedy exploration: ε decays from 1.0 to 0.05 over 200 episodes

### Deployment
- When any scanner signal fires (stock enters top-10), DQN takes over timing
- DQN makes enter/wait/abort decision every 30 seconds
- Hard limit: must decide within 15 minutes or auto-abort

### Risk
- Once DQN enters: 1% account, 3% stop, 2% target
- Max 4 DQN-timed entries per day

---

## Strategy 36: Contrastive Learning — Scanner Fingerprints

### Objective
Learn a dense embedding ("fingerprint") for each trading day's scanner pattern using contrastive learning, then find the most similar historical day and replicate its best trades.

### Embedding Construction
- For each day, extract:
  - Top-20 symbols on each scanner at 10:00 AM (33 scanners × 20 = 660 symbols)
  - Encode symbol presence as a binary vector (universe size ≈ 2,000 unique symbols)
  - Scanner rank distributions (histograms of rank positions)
- Total: high-dimensional sparse vector per day

### Contrastive Learning (SimCLR)
- Positive pairs: same day augmented (random 10% symbol dropout + time jitter ±2 snapshots)
- Negative pairs: different days
- Encoder: 3-layer MLP → 64-dim embedding
- Loss: NT-Xent (normalized temperature-scaled cross entropy)
- Train on 40 days

### Trading
1. At 10:15 AM today, compute today's fingerprint embedding
2. Find the nearest neighbor in the historical embedding space (cosine similarity)
3. Look up what the top-3 GainSinceOpen stocks did for the rest of that historical day
4. If they continued up: buy today's top-3 GainSinceOpen
5. If they reversed: short today's top-3 GainSinceOpen (or skip)

### Risk
- 1% account per trade, max 3 concurrent
- Stop: 5%
- Target: replicate the historical day's median return for top-3 gainers
- If nearest neighbor similarity < 0.5, skip (today is novel, no good match)
- Re-embed and re-match at 11:15 AM as a confirmation check

---

## Strategy 37: Bayesian Online Learning — Adaptive Scanner Thresholds

### Objective
Use Bayesian online learning to continuously update beliefs about optimal scanner rank thresholds for entry, adapting in real-time as each trade provides feedback.

### Prior Beliefs (initial)
- For each scanner type, the "optimal entry rank" follows a Beta distribution
- Initial prior: Beta(5, 5) → centered around rank 25 (middle of 50)
- Separate priors for each cap tier

### Online Update
- After each trade, observe: did entering when stock was at rank R on scanner S result in a profit?
- If profitable: increase the posterior mass around rank R (reinforce this threshold)
- If loss: decrease the posterior mass around rank R (discourage this threshold)
- Update rule: conjugate Beta update with pseudocounts

### Trading
1. Every 5 minutes, for each stock on each scanner:
   - Check if its current rank is within the 80% credible interval of the posterior for "profitable entry ranks"
   - If yes, it's a candidate
2. Among candidates, select those on ≥ 2 scanners
3. Enter the top candidate (highest posterior probability of profitability)

### Advantages
- No fixed thresholds ("top 5" or "top 10") — the system learns the right cutoff
- Adapts to scanner-specific dynamics (HotByVolume top-3 might be profitable while GainSinceOpen top-15 is optimal)
- Uncertainty-aware: wide credible intervals → less confident → smaller positions

### Risk
- Position size inversely proportional to posterior variance (more certain = bigger size, max 2%)
- Stop: 4%, target: 3%
- Max 3 concurrent
- If posterior variance hasn't decreased after 20 trades, reset priors (model isn't learning)

---

## Strategy 38: Knowledge Distillation — Compress Complex Signals

### Objective
Train a large "teacher" ensemble (all models from strategies 12-37) and distill their collective knowledge into a tiny, fast "student" model that runs in < 10ms for ultra-low latency trading.

### Teacher Ensemble
- Run all applicable models from this document in parallel
- Each model outputs: P(profitable_trade | current_scanner_state)
- Teacher output = weighted average of all model probabilities (weights from Strategy 33 voting track record)

### Student Model
- Architecture: 2-layer MLP with 32 hidden units (< 5,000 parameters)
- Input: 30 hand-crafted features (top features from each teacher model's feature importance)
- Output: single probability matching teacher's output
- Loss: KL divergence between student and teacher outputs
- Temperature: τ = 3.0 (softened probabilities for better knowledge transfer)

### Training
- Generate teacher labels for every scanner snapshot over 30 days (≈ 50,000 samples)
- Train student to match teacher outputs
- Validate that student agrees with teacher on > 90% of trade/no-trade decisions

### Deployment
- Student model runs every 500ms (vs. teacher ensemble at 30s)
- Latency advantage: enters 29.5 seconds before the full ensemble would signal
- Use for scalping: enter on student signal, confirm or exit when teacher ensemble catches up

### Risk
- 0.5% account per student-only trade (lower conviction)
- If teacher confirms within 2 min, add another 0.5% (total 1%)
- If teacher disagrees, exit student position immediately
- Stop: 2%, target: 1.5%

---

## Strategy 39: World Model — Scanner Dynamics Simulator

### Objective
Train a world model (à la Dreamer/MuZero) that learns the transition dynamics of scanner states, enabling planning by "imagining" future scanner states before committing to trades.

### World Model Components
1. **Representation Model**: encode current scanner snapshot → latent state z_t
2. **Transition Model**: predict z_{t+1} from z_t and action (buy/sell/hold)
3. **Reward Model**: predict expected return from latent state
4. **Decoder**: reconstruct scanner state from latent (for interpretability)

### Architecture
- Representation: CNN over scanner matrix (11 scanners × 50 ranks) → 128-dim latent
- Transition: GRU with 128 hidden units
- Reward: 2-layer MLP → scalar
- Trained end-to-end on 40 days of scanner + return data

### Planning (at inference)
1. Encode current scanner state → z_0
2. Simulate 50 future trajectories of length 10 steps (5 min each = 50 min horizon)
3. At each step, try all 3 actions (buy/sell/hold), evaluate predicted reward
4. Select the action sequence that maximizes cumulative predicted reward
5. Execute only the first action (replan at next step — MPC style)

### Advantages
- Plans ahead instead of reacting
- Can evaluate "what happens if I buy NOW vs. wait 5 min" in simulation
- Handles sequential decision-making (when to enter, when to add, when to exit)

### Risk
- 1% account per world-model trade
- Hard stops override world model predictions (3% stop regardless of what model predicts)
- If world model's predicted scanner states diverge > 50% from actual (next step), halt trading and retrain
- Max 3 concurrent positions

---

## Strategy 40: Retrieval-Augmented Generation — Historical Pattern Lookup

### Objective
Use RAG (vector database + LLM) to find historical trading days with similar scanner patterns and generate actionable trade plans based on what worked historically.

### Vector Database Construction
- For each historical day, create a document:
  ```
  Date: 2026-03-15
  Top scanners: GainSinceOpen dominated by [NVDA, AMD, MRVL]
  Theme: Semiconductor rally, broad tech momentum
  Outcome: Top-5 gainers averaged +4.2% by EOD
  Best trade: NVDA entry at 9:45 AM, +6.1% by close
  Worst trade: MRVL entered at 11 AM, reversed -2.3%
  ```
- Embed each document using text-embedding model → store in vector DB (e.g., ChromaDB, Pinecone)

### Real-Time Query
1. At 10:00 AM, summarize today's scanner state in natural language
2. Query vector DB for top-3 most similar historical days
3. Send retrieved documents + today's state to Claude:
   ```
   Based on these similar historical days and today's scanner state, recommend:
   1. Top 3 stocks to buy and why
   2. Optimal entry time window
   3. Expected return range
   4. Key risk to watch for
   ```
4. Parse Claude's structured response into executable trade parameters

### Execution
- Enter trades recommended by RAG+LLM pipeline
- Cross-check: every recommended symbol must currently be on at least 1 scanner (sanity filter)
- If LLM recommends a stock NOT on any scanner, skip it

### Risk
- 1% account per RAG trade, max 3
- Stop: use the historical worst-case from similar days (e.g., if similar day's worst trade was -2.3%, set stop at -3%)
- Target: use historical average outcome (e.g., +4.2%)
- If 0 of top-3 similar days were profitable, skip today

---

## Strategy 41: Multi-Agent RL — Cooperative Scanner Watchers

### Objective
Deploy 3 specialized RL agents — one per cap tier — that cooperate to maximize total portfolio return by sharing information about scanner state through a communication channel.

### Agent Architecture (per cap tier)
- Observation: that tier's 11 scanner snapshots + shared message from other agents
- Action: BUY(symbol) / SELL(symbol) / HOLD / SEND_MESSAGE(content)
- Communication: each agent can broadcast a 16-dim learned message vector to others every 5 min

### Communication Protocol
- SmallCap agent detects unusual volume → sends alert vector to MidCap/LargeCap agents
- LargeCap agent detects sector rotation → informs others to shift sector focus
- Messages are learned (not hand-designed) — the agents discover useful communication through training

### Training
- Multi-agent PPO (MAPPO) with centralized critic
- Reward: portfolio-level Sharpe ratio (encourages cooperation over individual agent greed)
- Train on 40 days of synchronized scanner data across all 3 tiers
- Curriculum: first train agents independently (10 epochs), then enable communication (20 epochs)

### Deployment
- 3 agents run in parallel, each watching their cap tier's scanners
- Shared portfolio: combined position limit of 6 concurrent (2 per agent max)
- If any agent sends a "risk-off" message (learned during training), all agents close positions

### Risk
- 0.75% account per agent per trade (2.25% max per agent, 6.75% max total)
- Per-agent daily loss limit: -1%
- Portfolio daily loss limit: -2%
- If communication channel latency > 5 seconds, agents operate independently (fallback mode)

---

## Notes on Implementation

### Data Pipeline
All strategies consume data from `\\Station001\DATA\hvlf\rotating\{YYYYMMDD}\{CapTier}-{ScannerType}_Scanner.csv`. The CSV format is:
```
timestamp, 0:SYMBOL_STK, 1:SYMBOL_STK, ..., N:SYMBOL_STK
```
Parse by splitting on commas, then splitting each field on `:` to extract rank and symbol (strip `_STK` suffix).

### Infrastructure Requirements
| Strategy Category | Compute | Data | Latency |
|---|---|---|---|
| Classical (12, 19-21, 27, 29, 32) | CPU only | Scanner CSVs + bars | 1-5 sec |
| Deep Learning (16, 17, 22-23, 31, 34, 36) | GPU (single) | Scanner CSVs + bars | 5-30 sec |
| RL (13, 35, 39, 41) | GPU (multi) | Scanner CSVs + bars + simulation | 10-60 sec |
| LLM/GenAI (14, 18, 28, 40) | API calls | Scanner CSVs + news + headlines | 2-10 sec |
| Ensemble/Meta (26, 30, 33, 37, 38) | GPU + CPU | All of above | 30-120 sec |

### Backtesting Framework
- Walk-forward validation: never train on future data
- Transaction costs: $0.005/share + 0.1% spread assumption
- Slippage model: 0.05% for LargeCap, 0.15% for MidCap, 0.3% for SmallCap
- All returns reported net of costs

### Priority Order for Implementation
1. **Quick wins** (rule-based, no ML): Strategy 32 (Cross-Scanner Arbitrage), Strategy 21 (Pairs Divergence), Strategy 20 (Anomaly Detection)
2. **Medium effort** (classical ML): Strategy 12 (XGBoost Classifier), Strategy 19 (Bandit), Strategy 29 (Monte Carlo)
3. **High effort** (deep learning): Strategy 17 (Transformer), Strategy 23 (LSTM), Strategy 22 (CNN)
4. **Research projects** (RL/GenAI): Strategy 13 (PPO Agent), Strategy 39 (World Model), Strategy 41 (Multi-Agent RL)
