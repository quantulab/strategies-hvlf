"""Strategy signal generators for backtesting.

Each strategy function takes scanner data and returns trading signals.
These are simplified implementations for backtesting - they capture the
core signal logic without requiring ML model inference.

For ML-dependent strategies, we use scanner-based proxy signals that
approximate what the trained model would produce.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from backtest.engine import (
    GAINER_SCANNERS, LOSER_SCANNERS, VOLUME_SCANNERS, SCANNER_TYPES,
    ScannerSnapshot, Signal, build_symbol_state,
    compute_scanner_population_metrics,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Strategy 12: ML Rank Velocity Classifier
# Proxy: rank improving by ≥5 positions over last 10 snapshots on 2+ scanners
# ─────────────────────────────────────────────
def strategy_12_rank_velocity(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym, state in states.items():
        if state["total_scanners"] < 2:
            continue
        if state["loser_count"] > 0:
            continue

        # Check rank improvement across any scanner
        improving_scanners = 0
        total_improvement = 0
        for scanner, ranks in state["rank_history"].items():
            if len(ranks) >= 3:
                if ranks[-1] < ranks[0] and (ranks[0] - ranks[-1]) >= 5:
                    improving_scanners += 1
                    total_improvement += ranks[0] - ranks[-1]

        if improving_scanners >= 1 and state["gainer_count"] >= 1:
            confidence = min(0.5 + (total_improvement / 50), 0.95)
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S12",
                direction="LONG", confidence=confidence,
                scanners_present=list(state["scanners_present"]),
                metadata={"improving_scanners": improving_scanners, "total_improvement": total_improvement},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 14: News Sentiment (proxy: on 3+ gainer/volume scanners = high conviction)
# Real version uses FinBERT; backtest proxy uses scanner confluence as sentiment proxy
# ─────────────────────────────────────────────
def strategy_14_sentiment_proxy(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym, state in states.items():
        if state["gainer_count"] >= 2 and state["volume_count"] >= 1:
            if state["loser_count"] > 0:
                continue
            best_rank = min(state["ranks"].values())
            if best_rank > 20:
                continue

            confidence = min(0.5 + (state["total_scanners"] * 0.1), 0.9)
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S14",
                direction="LONG", confidence=confidence,
                scanners_present=list(state["scanners_present"]),
                metadata={"gainer_count": state["gainer_count"], "volume_count": state["volume_count"]},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 15: HMM Regime Detector
# Proxy: bull/bear ratio across all scanners
# ─────────────────────────────────────────────
def strategy_15_regime(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=15)

    total_gainers = sum(1 for s in states.values() if s["gainer_count"] > 0)
    total_losers = sum(1 for s in states.values() if s["loser_count"] > 0)
    ratio = total_gainers / max(total_losers, 1)

    signals = []
    if ratio >= 2.0:  # Rally regime
        # Buy top-5 gainers
        candidates = [(sym, s) for sym, s in states.items()
                      if s["gainer_count"] >= 2 and s["loser_count"] == 0]
        candidates.sort(key=lambda x: min(x[1]["ranks"].values()))
        for sym, state in candidates[:5]:
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S15",
                direction="LONG", confidence=min(ratio / 5, 0.9),
                scanners_present=list(state["scanners_present"]),
                metadata={"regime": "rally", "bull_bear_ratio": ratio},
            ))
    elif ratio <= 0.5:  # Selloff regime - look for reversals
        candidates = [(sym, s) for sym, s in states.items()
                      if s["loser_count"] >= 2 and s["volume_count"] >= 1]
        candidates.sort(key=lambda x: min(x[1]["ranks"].values()))
        for sym, state in candidates[:3]:
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S15",
                direction="LONG", confidence=0.4,
                scanners_present=list(state["scanners_present"]),
                metadata={"regime": "selloff_reversal", "bull_bear_ratio": ratio},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 19: Multi-Armed Bandit Scanner Selector
# Proxy: rotate through scanner types daily, pick top-3 from selected scanner
# ─────────────────────────────────────────────
_bandit_wins = defaultdict(int)
_bandit_pulls = defaultdict(int)


def strategy_19_bandit(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
    day_index: int = 0,
) -> list[Signal]:
    # Thompson sampling: pick scanner with highest expected reward
    scanner_arms = ["GainSinceOpen", "HighOpenGap", "HotByPrice", "HotByVolume",
                    "TopGainers", "TopVolumeRate", "MostActive", "HotByPriceRange"]

    best_arm = None
    best_sample = -1
    for arm in scanner_arms:
        a = _bandit_wins.get(arm, 1) + 1
        b = _bandit_pulls.get(arm, 1) - _bandit_wins.get(arm, 0) + 1
        sample = np.random.beta(a, b)
        if sample > best_sample:
            best_sample = sample
            best_arm = arm

    # Get latest snapshot for selected scanner
    recent = [s for s in snapshots
              if s.scanner_type == best_arm
              and (timestamp - s.timestamp).total_seconds() < 600]

    if not recent:
        return []

    latest = recent[-1]
    signals = []
    for sym_entry in latest.symbols[:3]:
        # Check not on loser scanner
        states = build_symbol_state(snapshots, timestamp, window_minutes=5)
        sym = sym_entry["symbol"]
        if sym in states and states[sym]["loser_count"] > 0:
            continue

        signals.append(Signal(
            timestamp=timestamp, symbol=sym, strategy_id="S19",
            direction="LONG", confidence=0.6,
            scanners_present=[latest.scanner_name],
            metadata={"selected_scanner": best_arm, "rank": sym_entry["rank"]},
        ))

    return signals


# ─────────────────────────────────────────────
# Strategy 20: Anomaly Detection — Scanner Population Shock
# ─────────────────────────────────────────────
def strategy_20_anomaly(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
    historical_means: dict | None = None,
) -> list[Signal]:
    metrics = compute_scanner_population_metrics(snapshots, timestamp, window_minutes=5)
    signals = []

    for scanner_type, m in metrics.items():
        # Anomaly: newcomer ratio > 80% on volume scanner
        if scanner_type in VOLUME_SCANNERS and m["newcomer_ratio"] > 0.8:
            # Find top newcomer
            recent = [s for s in snapshots if s.scanner_type == scanner_type
                      and (timestamp - s.timestamp).total_seconds() < 300]
            if recent:
                latest = recent[-1]
                if latest.symbols:
                    sym = latest.symbols[0]["symbol"]
                    signals.append(Signal(
                        timestamp=timestamp, symbol=sym, strategy_id="S20",
                        direction="LONG", confidence=0.65,
                        scanners_present=[latest.scanner_name],
                        metadata={"anomaly": "newcomer_flood", "newcomer_ratio": m["newcomer_ratio"]},
                    ))

        # Anomaly: rank entropy collapse (one stock dominating)
        if m["rank_entropy"] < 1.0 and m["population"] > 0:
            recent = [s for s in snapshots if s.scanner_type == scanner_type
                      and (timestamp - s.timestamp).total_seconds() < 300]
            if recent:
                latest = recent[-1]
                if latest.symbols:
                    sym = latest.symbols[0]["symbol"]
                    direction = "LONG" if scanner_type in GAINER_SCANNERS else "SHORT"
                    if direction == "LONG":
                        signals.append(Signal(
                            timestamp=timestamp, symbol=sym, strategy_id="S20",
                            direction=direction, confidence=0.6,
                            scanners_present=[latest.scanner_name],
                            metadata={"anomaly": "entropy_collapse", "entropy": m["rank_entropy"]},
                        ))

    return signals


# ─────────────────────────────────────────────
# Strategy 21: Pairs Trading — Scanner Divergence
# Proxy: find correlated pairs where one is gaining and other losing
# ─────────────────────────────────────────────
KNOWN_PAIRS = [
    ("IONQ", "QBTS"), ("NIO", "LCID"), ("SOUN", "BBAI"),
    ("PLUG", "EOSE"), ("SNAP", "PINS"), ("AMD", "INTC"),
]


def strategy_21_pairs(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym_a, sym_b in KNOWN_PAIRS:
        a_state = states.get(sym_a)
        b_state = states.get(sym_b)
        if not a_state or not b_state:
            continue

        # Check for divergence: one gaining, other losing
        if a_state["gainer_count"] > 0 and b_state["loser_count"] > 0:
            # Long the laggard (B), short the leader (A)
            signals.append(Signal(
                timestamp=timestamp, symbol=sym_b, strategy_id="S21",
                direction="LONG", confidence=0.55,
                scanners_present=list(b_state["scanners_present"]),
                metadata={"pair": f"{sym_a}/{sym_b}", "divergence": "a_gaining_b_losing"},
            ))
        elif b_state["gainer_count"] > 0 and a_state["loser_count"] > 0:
            signals.append(Signal(
                timestamp=timestamp, symbol=sym_a, strategy_id="S21",
                direction="LONG", confidence=0.55,
                scanners_present=list(a_state["scanners_present"]),
                metadata={"pair": f"{sym_a}/{sym_b}", "divergence": "b_gaining_a_losing"},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 27: Granger Lead-Lag — volume leads price
# Proxy: on HotByVolume but NOT on GainSinceOpen → anticipate price catch-up
# ─────────────────────────────────────────────
def strategy_27_lead_lag(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym, state in states.items():
        volume_present = state["scanner_types"] & VOLUME_SCANNERS
        gainer_present = state["scanner_types"] & GAINER_SCANNERS
        loser_present = state["scanner_types"] & LOSER_SCANNERS

        if volume_present and not gainer_present and not loser_present:
            # Volume leading, price hasn't moved yet
            best_vol_rank = min(
                state["ranks"].get(s, 99) for s in state["scanners_present"]
                if any(vs in s for vs in VOLUME_SCANNERS)
            )
            if best_vol_rank <= 15:
                confidence = min(0.5 + (15 - best_vol_rank) / 30, 0.8)
                signals.append(Signal(
                    timestamp=timestamp, symbol=sym, strategy_id="S27",
                    direction="LONG", confidence=confidence,
                    scanners_present=list(state["scanners_present"]),
                    metadata={"volume_rank": best_vol_rank, "signal": "volume_leads_price"},
                ))

    return signals


# ─────────────────────────────────────────────
# Strategy 32: Cross-Scanner Arbitrage
# On HotByVolume but NOT on any price scanner → front-run price catch-up
# ─────────────────────────────────────────────
def strategy_32_cross_scanner_arb(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=5)
    signals = []

    for sym, state in states.items():
        volume_types = state["scanner_types"] & VOLUME_SCANNERS
        price_types = state["scanner_types"] & (GAINER_SCANNERS | {"HotByPrice", "HotByPriceRange"})
        loser_types = state["scanner_types"] & LOSER_SCANNERS

        if not volume_types:
            continue
        if price_types:
            continue  # Already on price scanners, no arbitrage
        if loser_types:
            continue  # Volume is selling pressure

        # Check rank on volume scanner
        vol_ranks = [state["ranks"][s] for s in state["scanners_present"]
                     if any(v in s for v in VOLUME_SCANNERS)]
        if not vol_ranks:
            continue
        best_vol_rank = min(vol_ranks)

        if best_vol_rank > 15:
            continue

        # Check freshness: appeared within last 5 min
        age_seconds = (timestamp - state["first_seen"]).total_seconds()
        if age_seconds > 300:
            continue

        # Check volume rank is improving
        vol_improving = False
        for scanner, ranks in state["rank_history"].items():
            if any(v in scanner for v in VOLUME_SCANNERS) and len(ranks) >= 2:
                if ranks[-1] <= ranks[0]:
                    vol_improving = True

        if not vol_improving:
            continue

        confidence = min(0.6 + (15 - best_vol_rank) / 30, 0.85)
        signals.append(Signal(
            timestamp=timestamp, symbol=sym, strategy_id="S32",
            direction="LONG", confidence=confidence,
            scanners_present=list(state["scanners_present"]),
            metadata={
                "volume_rank": best_vol_rank,
                "age_seconds": age_seconds,
                "signal": "volume_without_price",
            },
        ))

    return signals


# ─────────────────────────────────────────────
# Strategy 33: Ensemble Voting (simplified)
# Proxy: require agreement from S12, S27, S32 signals
# ─────────────────────────────────────────────
def strategy_33_ensemble(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    # Run component strategies
    s12 = {s.symbol for s in strategy_12_rank_velocity(snapshots, timestamp)}
    s27 = {s.symbol for s in strategy_27_lead_lag(snapshots, timestamp)}
    s32 = {s.symbol for s in strategy_32_cross_scanner_arb(snapshots, timestamp)}
    s14 = {s.symbol for s in strategy_14_sentiment_proxy(snapshots, timestamp)}
    s20 = {s.symbol for s in strategy_20_anomaly(snapshots, timestamp)}

    all_sets = [s12, s27, s32, s14, s20]
    signals = []

    # Find symbols that appear in 3+ strategy signals
    all_symbols = set()
    for s in all_sets:
        all_symbols.update(s)

    for sym in all_symbols:
        votes = sum(1 for s in all_sets if sym in s)
        if votes >= 3:
            states = build_symbol_state(snapshots, timestamp, window_minutes=5)
            state = states.get(sym, {})
            confidence = min(0.5 + votes * 0.1, 0.95)
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S33",
                direction="LONG", confidence=confidence,
                scanners_present=list(state.get("scanners_present", [])),
                metadata={"votes": votes, "agreeing_strategies": votes},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 17: Transformer (proxy: sustained top-10 presence + rank improving)
# ─────────────────────────────────────────────
def strategy_17_transformer_proxy(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=30)
    signals = []

    for sym, state in states.items():
        if state["gainer_count"] == 0:
            continue
        if state["loser_count"] > 0:
            continue

        # Check for sustained top-10 presence
        sustained = False
        for scanner, ranks in state["rank_history"].items():
            if any(g in scanner for g in GAINER_SCANNERS):
                if len(ranks) >= 5 and all(r <= 10 for r in ranks[-5:]):
                    sustained = True
                    break

        if sustained:
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S17",
                direction="LONG", confidence=0.75,
                scanners_present=list(state["scanners_present"]),
                metadata={"signal": "sustained_top10"},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 23: LSTM Rank Forecast (proxy: rapid rank climb)
# ─────────────────────────────────────────────
def strategy_23_lstm_proxy(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=15)
    signals = []

    for sym, state in states.items():
        if state["loser_count"] > 0:
            continue

        for scanner, ranks in state["rank_history"].items():
            if any(g in scanner for g in GAINER_SCANNERS) and len(ranks) >= 4:
                # Detect rapid climb: rank improving consistently
                if all(ranks[i] > ranks[i+1] for i in range(len(ranks)-3, len(ranks)-1)):
                    current_rank = ranks[-1]
                    if current_rank > 15 and ranks[0] - current_rank >= 10:
                        signals.append(Signal(
                            timestamp=timestamp, symbol=sym, strategy_id="S23",
                            direction="LONG", confidence=0.65,
                            scanners_present=list(state["scanners_present"]),
                            metadata={"predicted_to_enter_top5": True, "current_rank": current_rank},
                        ))
                        break

    return signals


# ─────────────────────────────────────────────
# Strategy 29: Monte Carlo (proxy: symbol on 3+ scanners with strong ranks)
# ─────────────────────────────────────────────
def strategy_29_monte_carlo_proxy(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym, state in states.items():
        if state["total_scanners"] < 3:
            continue
        if state["loser_count"] > 0:
            continue

        avg_rank = np.mean(list(state["ranks"].values()))
        if avg_rank > 20:
            continue

        confidence = min(0.5 + (state["total_scanners"] * 0.08) + ((20 - avg_rank) / 40), 0.85)
        signals.append(Signal(
            timestamp=timestamp, symbol=sym, strategy_id="S29",
            direction="LONG", confidence=confidence,
            scanners_present=list(state["scanners_present"]),
            metadata={"avg_rank": float(avg_rank), "scanner_count": state["total_scanners"]},
        ))

    return signals


# ─────────────────────────────────────────────
# Strategy 28: Sentiment Composite (proxy: multi-scanner + multi-cap conviction)
# ─────────────────────────────────────────────
def strategy_28_composite_proxy(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym, state in states.items():
        scanner_score = min(state["total_scanners"] * 15, 100)
        cap_tier_score = len(state["cap_tiers"]) * 33
        direction_score = (state["gainer_count"] * 25) - (state["loser_count"] * 30)
        volume_score = state["volume_count"] * 20

        composite = (scanner_score * 0.4 + cap_tier_score * 0.15 +
                     direction_score * 0.25 + volume_score * 0.2)

        if composite >= 60 and state["loser_count"] == 0:
            confidence = min(composite / 100, 0.9)
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S28",
                direction="LONG", confidence=confidence,
                scanners_present=list(state["scanners_present"]),
                metadata={"composite_score": composite, "scanner_score": scanner_score},
            ))

    return signals


# ─────────────────────────────────────────────
# Strategy 30: MAML Few-Shot (proxy: new-to-scanner today with immediate momentum)
# ─────────────────────────────────────────────
def strategy_30_maml_proxy(
    snapshots: list[ScannerSnapshot],
    timestamp: datetime,
    prior_day_symbols: set | None = None,
) -> list[Signal]:
    states = build_symbol_state(snapshots, timestamp, window_minutes=10)
    signals = []

    for sym, state in states.items():
        if state["gainer_count"] == 0 or state["volume_count"] == 0:
            continue
        if state["loser_count"] > 0:
            continue

        # Check if symbol is new to scanners today (wasn't in prior day)
        is_new = prior_day_symbols is None or sym not in prior_day_symbols
        if not is_new:
            continue

        best_rank = min(state["ranks"].values())
        if best_rank <= 20:
            signals.append(Signal(
                timestamp=timestamp, symbol=sym, strategy_id="S30",
                direction="LONG", confidence=0.65,
                scanners_present=list(state["scanners_present"]),
                metadata={"new_today": True, "best_rank": best_rank},
            ))

    return signals


# ─────────────────────────────────────────────
# All strategies registry
# ─────────────────────────────────────────────
STRATEGY_REGISTRY = {
    "S12": {"name": "ML Rank Velocity", "fn": strategy_12_rank_velocity,
            "stop": 0.03, "target": 0.02, "max_hold": 60},
    "S14": {"name": "News Sentiment Proxy", "fn": strategy_14_sentiment_proxy,
            "stop": 0.08, "target": 0.15, "max_hold": 390},
    "S15": {"name": "HMM Regime Detector", "fn": strategy_15_regime,
            "stop": 0.05, "target": 0.03, "max_hold": 120},
    "S17": {"name": "Transformer Proxy", "fn": strategy_17_transformer_proxy,
            "stop": 0.04, "target": 0.03, "max_hold": 120},
    "S19": {"name": "Bandit Scanner Select", "fn": strategy_19_bandit,
            "stop": 0.05, "target": 0.03, "max_hold": 180},
    "S20": {"name": "Anomaly Detection", "fn": strategy_20_anomaly,
            "stop": 0.04, "target": 0.03, "max_hold": 60},
    "S21": {"name": "Pairs Divergence", "fn": strategy_21_pairs,
            "stop": 0.035, "target": 0.025, "max_hold": 180},
    "S23": {"name": "LSTM Rank Forecast", "fn": strategy_23_lstm_proxy,
            "stop": 0.05, "target": 0.03, "max_hold": 45},
    "S27": {"name": "Granger Lead-Lag", "fn": strategy_27_lead_lag,
            "stop": 0.03, "target": 0.02, "max_hold": 15},
    "S28": {"name": "Sentiment Composite", "fn": strategy_28_composite_proxy,
            "stop": 0.07, "target": 0.05, "max_hold": 240},
    "S29": {"name": "Monte Carlo Proxy", "fn": strategy_29_monte_carlo_proxy,
            "stop": 0.04, "target": 0.025, "max_hold": 60},
    "S30": {"name": "MAML Few-Shot Proxy", "fn": strategy_30_maml_proxy,
            "stop": 0.04, "target": 0.03, "max_hold": 120},
    "S32": {"name": "Cross-Scanner Arb", "fn": strategy_32_cross_scanner_arb,
            "stop": 0.025, "target": 0.02, "max_hold": 20},
    "S33": {"name": "Ensemble Voting", "fn": strategy_33_ensemble,
            "stop": 0.03, "target": 0.025, "max_hold": 60},
}
