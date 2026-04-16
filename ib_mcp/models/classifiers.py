"""Zero-shot classification and Named Entity Recognition models.

Supports: facebook/bart-large-mnli, dslim/bert-base-NER
Used by strategies: S15, S18, S25 (regime/scenario classification), S14/S24/S40 (NER)
"""

import logging
from dataclasses import dataclass

import torch

from ib_mcp.models import DEVICE, registry

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result from zero-shot classification."""
    text: str
    labels: list[str]
    scores: list[float]
    best_label: str
    best_score: float


@dataclass
class Entity:
    """Named entity extracted from text."""
    text: str
    label: str  # PER, ORG, LOC, MISC
    start: int
    end: int
    score: float


# Common classification label sets for trading
MARKET_REGIME_LABELS = [
    "broad market rally with strong momentum",
    "sector rotation and mixed signals",
    "risk-off selloff with high volatility",
    "low activity sideways drift",
    "earnings-driven moves",
    "macro event shock",
]

SCENARIO_LABELS = [
    "tech sector momentum continuation",
    "mean reversion day",
    "small cap speculative rally",
    "broad rotation out of growth into value",
    "macro risk event",
    "earnings season volatility",
    "fed policy driven moves",
    "short squeeze setup",
    "sector breakout",
    "distribution and profit taking",
]

CATALYST_LABELS = [
    "earnings surprise",
    "FDA approval or drug trial results",
    "analyst upgrade or price target increase",
    "partnership or acquisition announcement",
    "insider buying",
    "SEC investigation or lawsuit",
    "earnings miss or guidance cut",
    "analyst downgrade",
    "dilution or secondary offering",
    "management change",
    "technical breakout",
    "momentum and volume surge",
]


def classify_zero_shot(
    texts: list[str],
    candidate_labels: list[str],
    multi_label: bool = False,
) -> list[ClassificationResult]:
    """Zero-shot classification using BART-MNLI.

    Args:
        texts: List of text strings to classify
        candidate_labels: List of possible classification labels
        multi_label: If True, each label is scored independently.
                     If False, labels are mutually exclusive.

    Returns:
        List of ClassificationResult, one per input text
    """
    classifier = registry.get_model("bart_mnli")

    results = []
    for text in texts:
        output = classifier(text, candidate_labels, multi_label=multi_label)
        results.append(ClassificationResult(
            text=text,
            labels=output["labels"],
            scores=[round(s, 4) for s in output["scores"]],
            best_label=output["labels"][0],
            best_score=round(output["scores"][0], 4),
        ))

    return results


def classify_market_regime(scanner_summary: str) -> dict:
    """Classify current market regime from scanner state summary.

    Used by Strategy 15 (HMM Regime Detector) and Strategy 25 (VAE Clustering).

    Args:
        scanner_summary: Natural language summary of current scanner state.
            e.g. "Gainers dominated by NVDA, AMD, MRVL. Volume surging on tech.
                  Losers sparse. Bull/bear ratio 3.2."

    Returns:
        Dict with regime classification, confidence, and sub-strategy recommendation
    """
    results = classify_zero_shot([scanner_summary], MARKET_REGIME_LABELS)
    result = results[0]

    # Map regime to sub-strategy
    regime_strategies = {
        "broad market rally with strong momentum": {
            "regime": "rally",
            "sub_strategy": "momentum_chase",
            "action": "Buy top-5 GainSinceOpen LargeCap, trail with 5% stop",
            "position_size_multiplier": 1.0,
        },
        "sector rotation and mixed signals": {
            "regime": "chop",
            "sub_strategy": "mean_reversion",
            "action": "Short top LossSinceOpen, buy opposite cap tier gainers",
            "position_size_multiplier": 0.5,
        },
        "risk-off selloff with high volatility": {
            "regime": "selloff",
            "sub_strategy": "defensive_fade",
            "action": "Buy LowOpenGap reversal candidates, or stay cash",
            "position_size_multiplier": 0.25,
        },
        "low activity sideways drift": {
            "regime": "drift",
            "sub_strategy": "no_trade",
            "action": "No trades — expected value negative after commissions",
            "position_size_multiplier": 0.0,
        },
        "earnings-driven moves": {
            "regime": "earnings",
            "sub_strategy": "catalyst_trade",
            "action": "Trade earnings movers with wider stops, fundamental filter",
            "position_size_multiplier": 0.75,
        },
        "macro event shock": {
            "regime": "macro_shock",
            "sub_strategy": "wait_and_see",
            "action": "Reduce all position sizes, tighten stops, wait for clarity",
            "position_size_multiplier": 0.25,
        },
    }

    best = result.best_label
    strategy_info = regime_strategies.get(best, {
        "regime": "unknown",
        "sub_strategy": "no_trade",
        "action": "Unknown regime, stay in cash",
        "position_size_multiplier": 0.0,
    })

    return {
        "regime": strategy_info["regime"],
        "regime_label": best,
        "confidence": result.best_score,
        "sub_strategy": strategy_info["sub_strategy"],
        "action": strategy_info["action"],
        "position_size_multiplier": strategy_info["position_size_multiplier"],
        "all_regimes": dict(zip(result.labels, result.scores)),
        "tradeable": result.best_score >= 0.4 and strategy_info["position_size_multiplier"] > 0,
    }


def classify_scenario(scanner_summary: str) -> list[dict]:
    """Classify scanner state against multiple scenario types.

    Used by Strategy 18 (GenAI Scenario Planning).
    Returns all scenarios with probabilities.

    Args:
        scanner_summary: Natural language summary of scanner state

    Returns:
        List of scenario dicts with label, probability, and recommended action
    """
    results = classify_zero_shot(
        [scanner_summary], SCENARIO_LABELS, multi_label=True,
    )
    result = results[0]

    scenarios = []
    for label, score in zip(result.labels, result.scores):
        scenarios.append({
            "scenario": label,
            "probability": score,
            "matches": score >= 0.5,
        })

    return sorted(scenarios, key=lambda x: x["probability"], reverse=True)


def classify_catalyst(headline: str) -> dict:
    """Classify a news headline by catalyst type.

    Used by Strategy 14 to determine if a catalyst is fundamental vs technical.

    Args:
        headline: News headline text

    Returns:
        Dict with catalyst type, is_fundamental flag, confidence
    """
    results = classify_zero_shot([headline], CATALYST_LABELS)
    result = results[0]

    fundamental_catalysts = {
        "earnings surprise",
        "FDA approval or drug trial results",
        "analyst upgrade or price target increase",
        "partnership or acquisition announcement",
        "insider buying",
        "SEC investigation or lawsuit",
        "earnings miss or guidance cut",
        "analyst downgrade",
        "dilution or secondary offering",
        "management change",
    }

    return {
        "catalyst": result.best_label,
        "confidence": result.best_score,
        "is_fundamental": result.best_label in fundamental_catalysts,
        "all_catalysts": dict(zip(result.labels[:5], result.scores[:5])),
    }


def extract_entities(texts: list[str]) -> list[list[Entity]]:
    """Extract named entities (companies, people, orgs) from texts.

    Used by Strategy 14, 24, 40 to map entity names to ticker symbols.

    Args:
        texts: List of text strings (headlines, articles)

    Returns:
        List of lists of Entity objects (one list per input text)
    """
    model = registry.get_model("ner")
    tokenizer = registry.get_tokenizer("ner")

    all_entities = []

    for text in texts:
        inputs = tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512,
            return_offsets_mapping=True,
        )
        offset_mapping = inputs.pop("offset_mapping")[0]
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)
            predictions = torch.argmax(outputs.logits, dim=-1)[0]
            confidences = torch.softmax(outputs.logits, dim=-1)[0]

        entities = []
        current_entity = None
        id2label = model.config.id2label

        for idx, (pred, offset) in enumerate(zip(predictions, offset_mapping)):
            label = id2label[pred.item()]
            conf = confidences[idx][pred.item()].item()
            start, end = offset.tolist()

            if start == 0 and end == 0:
                continue  # Skip special tokens

            if label.startswith("B-"):
                if current_entity:
                    entities.append(current_entity)
                current_entity = Entity(
                    text=text[start:end],
                    label=label[2:],
                    start=start,
                    end=end,
                    score=conf,
                )
            elif label.startswith("I-") and current_entity and label[2:] == current_entity.label:
                current_entity.text = text[current_entity.start : end]
                current_entity.end = end
                current_entity.score = min(current_entity.score, conf)
            else:
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None

        if current_entity:
            entities.append(current_entity)

        all_entities.append(entities)

    return all_entities


# Common company name → ticker mappings (extend as needed)
COMPANY_TICKER_MAP = {
    "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL",
    "alphabet": "GOOGL", "amazon": "AMZN", "meta": "META", "facebook": "META",
    "tesla": "TSLA", "robinhood": "HOOD", "palantir": "PLTR", "snowflake": "SNOW",
    "crowdstrike": "CRWD", "datadog": "DDOG", "cloudflare": "NET",
    "salesforce": "CRM", "oracle": "ORCL", "amd": "AMD", "intel": "INTC",
    "ionq": "IONQ", "rigetti": "RGTI", "rocket lab": "RKLB",
    "nio": "NIO", "lucid": "LCID", "plug power": "PLUG",
    "sofi": "SOFI", "affirm": "AFRM", "coinbase": "COIN",
    "jpmorgan": "JPM", "goldman sachs": "GS", "morgan stanley": "MS",
    "bank of america": "BAC", "wells fargo": "WFC", "citigroup": "C",
}


# HMM Regime Detection state labels
HMM_REGIME_LABELS = ["bull_momentum", "bear_mean_reversion", "range_bound"]

# Rotation sub-strategy routing by HMM regime
HMM_REGIME_ROUTING = {
    "bull_momentum": {
        "prioritize": ["rotation_streak_continuation", "rotation_volume_surge", "rotation_elite_accumulation"],
        "deprioritize": ["rotation_whipsaw_fade"],
        "position_size_multiplier": 1.0,
    },
    "bear_mean_reversion": {
        "prioritize": ["rotation_whipsaw_fade", "rotation_premarket_persist"],
        "deprioritize": ["rotation_streak_continuation", "rotation_elite_accumulation"],
        "position_size_multiplier": 0.5,
    },
    "range_bound": {
        "prioritize": ["rotation_whipsaw_fade", "rotation_premarket_persist", "rotation_volume_surge"],
        "deprioritize": [],
        "position_size_multiplier": 0.75,
    },
}


def detect_hmm_regime(
    breadth: float,
    gl_ratio: float,
    volume_level: float,
    historical_features: list[list[float]] | None = None,
) -> dict:
    """Detect market regime using a 3-state Gaussian HMM.

    Classifies the market into: bull_momentum, bear_mean_reversion, range_bound.
    Used by Strategy 31 master rotation controller (Phase 1) to route capital.

    Args:
        breadth: Current market breadth (unique tickers on scanners)
        gl_ratio: Gain/loss scanner ratio
        volume_level: Normalized volume level (0-1 scale)
        historical_features: Optional list of [breadth, gl_ratio, volume] from
            past days for model fitting. If None, uses default priors.

    Returns:
        Dict with regime label, confidence, transition probabilities, routing
    """
    import numpy as np

    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        # Fallback: simple rule-based classification matching the HMM labels
        logger.warning("hmmlearn not installed, falling back to rule-based regime detection")
        if gl_ratio > 1.2:
            regime = "bull_momentum"
            confidence = min(gl_ratio / 2.0, 0.95)
        elif gl_ratio < 0.8:
            regime = "bear_mean_reversion"
            confidence = min((2.0 - gl_ratio) / 2.0, 0.95)
        else:
            regime = "range_bound"
            confidence = 0.6

        routing = HMM_REGIME_ROUTING.get(regime, HMM_REGIME_ROUTING["range_bound"])
        return {
            "regime": regime,
            "confidence": round(confidence, 4),
            "method": "rule_based_fallback",
            "transition_probs": {},
            "routing": routing,
        }

    current_obs = np.array([[breadth, gl_ratio, volume_level]])

    if historical_features and len(historical_features) >= 10:
        X = np.array(historical_features)
        # Fit HMM on historical data
        model = GaussianHMM(
            n_components=3,
            covariance_type="diag",
            n_iter=100,
            random_state=42,
        )
        model.fit(X)
    else:
        # Use default priors based on typical market behavior
        model = GaussianHMM(
            n_components=3,
            covariance_type="diag",
            n_iter=1,
            init_params="",
        )
        # Set means: bull (high breadth, high GL, high vol), bear (low, low, high), range (mid, mid, mid)
        model.means_ = np.array([
            [2500, 1.5, 0.7],   # bull_momentum
            [1500, 0.6, 0.8],   # bear_mean_reversion
            [2000, 1.0, 0.5],   # range_bound
        ])
        model.covars_ = np.array([
            [250000, 0.1, 0.05],
            [250000, 0.1, 0.05],
            [250000, 0.1, 0.05],
        ])
        model.startprob_ = np.array([0.4, 0.2, 0.4])
        model.transmat_ = np.array([
            [0.7, 0.1, 0.2],
            [0.1, 0.7, 0.2],
            [0.2, 0.2, 0.6],
        ])

    # Predict state for current observation
    try:
        state_probs = model.predict_proba(current_obs)[0]
        predicted_state = int(np.argmax(state_probs))
    except Exception:
        # If prediction fails, default to range_bound
        state_probs = np.array([0.33, 0.33, 0.34])
        predicted_state = 2

    regime = HMM_REGIME_LABELS[predicted_state]
    confidence = float(state_probs[predicted_state])

    # Get transition probabilities from current state
    try:
        trans_probs = {
            HMM_REGIME_LABELS[i]: round(float(model.transmat_[predicted_state, i]), 4)
            for i in range(3)
        }
    except Exception:
        trans_probs = {}

    routing = HMM_REGIME_ROUTING.get(regime, HMM_REGIME_ROUTING["range_bound"])

    return {
        "regime": regime,
        "confidence": round(confidence, 4),
        "method": "hmm",
        "state_probabilities": {
            HMM_REGIME_LABELS[i]: round(float(state_probs[i]), 4)
            for i in range(3)
        },
        "transition_probs": trans_probs,
        "routing": routing,
        "features": {
            "breadth": breadth,
            "gl_ratio": gl_ratio,
            "volume_level": volume_level,
        },
    }


def entities_to_tickers(entities: list[Entity]) -> list[dict]:
    """Map extracted entities to potential ticker symbols.

    Args:
        entities: List of Entity objects from extract_entities

    Returns:
        List of dicts with entity text, matched ticker (if found), confidence
    """
    results = []
    for ent in entities:
        if ent.label != "ORG":
            continue

        text_lower = ent.text.lower().strip()
        ticker = COMPANY_TICKER_MAP.get(text_lower)

        # Also check if the entity text IS a ticker (all caps, 1-5 chars)
        if not ticker and ent.text.isupper() and 1 <= len(ent.text) <= 5:
            ticker = ent.text

        results.append({
            "entity": ent.text,
            "ticker": ticker,
            "confidence": round(ent.score, 4),
            "matched": ticker is not None,
        })

    return results
