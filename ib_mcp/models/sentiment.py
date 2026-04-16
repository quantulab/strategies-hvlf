"""Financial sentiment analysis using HuggingFace models.

Supports: ProsusAI/finbert, mrm8488/distilroberta, cardiffnlp/twitter-roberta,
nickmuchi/deberta-v3-finance, ElKulako/cryptobert, gtfintechlab/FOMC-RoBERTa
"""

import logging
from dataclasses import dataclass

import torch

from ib_mcp.models import DEVICE, registry
from ib_mcp.models.config import SENTIMENT_LABELS

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """Result from sentiment analysis."""
    text: str
    label: str
    score: float  # Raw model confidence 0-1
    sentiment: float  # Normalized -1 to +1
    model: str


def analyze_sentiment(
    texts: list[str],
    model_key: str = "finbert",
    batch_size: int = 32,
) -> list[SentimentResult]:
    """Analyze financial sentiment for a list of texts.

    Args:
        texts: List of text strings (headlines, articles, etc.)
        model_key: Which sentiment model to use. Options:
            - "finbert" (default, best for financial news)
            - "distilroberta_financial" (fastest, good for batches)
            - "twitter_sentiment" (best for social media text)
            - "deberta_finance" (highest accuracy, slower)
            - "cryptobert" (crypto-specific social media)
            - "fomc_roberta" (hawkish/dovish for Fed text)
        batch_size: Batch size for inference

    Returns:
        List of SentimentResult, one per input text
    """
    model = registry.get_model(model_key)
    tokenizer = registry.get_tokenizer(model_key)
    label_map = SENTIMENT_LABELS.get(model_key, {})

    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        inputs = tokenizer(
            batch, padding=True, truncation=True, max_length=512,
            return_tensors="pt",
        ).to(DEVICE)

        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1)

        # Get label names from model config
        id2label = model.config.id2label

        for j, text in enumerate(batch):
            pred_idx = probs[j].argmax().item()
            pred_label = id2label[pred_idx]
            confidence = probs[j][pred_idx].item()

            # Map to normalized sentiment score
            sentiment_val = label_map.get(pred_label, 0.0)
            # Weight by confidence: strong positive with 0.95 conf = 0.95, with 0.5 conf = 0.5
            weighted_sentiment = sentiment_val * confidence

            results.append(SentimentResult(
                text=text,
                label=pred_label,
                score=confidence,
                sentiment=weighted_sentiment,
                model=model_key,
            ))

    return results


def analyze_sentiment_ensemble(
    texts: list[str],
    model_keys: list[str] | None = None,
) -> list[dict]:
    """Run multiple sentiment models and aggregate results.

    Useful for Strategy 28 (Sentiment Composite Score).

    Args:
        texts: List of text strings
        model_keys: Models to use. Default: finbert + distilroberta_financial

    Returns:
        List of dicts with per-model scores and ensemble average
    """
    if model_keys is None:
        model_keys = ["finbert", "distilroberta_financial"]

    all_results: dict[str, list[SentimentResult]] = {}
    for key in model_keys:
        try:
            all_results[key] = analyze_sentiment(texts, model_key=key)
        except Exception as e:
            logger.warning(f"Model {key} failed: {e}")
            continue

    ensemble_output = []
    for i, text in enumerate(texts):
        entry = {"text": text, "models": {}}
        sentiments = []
        for key, model_results in all_results.items():
            if i < len(model_results):
                r = model_results[i]
                entry["models"][key] = {
                    "label": r.label,
                    "score": r.score,
                    "sentiment": r.sentiment,
                }
                sentiments.append(r.sentiment)

        entry["ensemble_sentiment"] = (
            sum(sentiments) / len(sentiments) if sentiments else 0.0
        )
        entry["ensemble_confidence"] = (
            min(abs(s) for s in sentiments) if sentiments else 0.0
        )
        entry["agreement"] = (
            all(s > 0 for s in sentiments) or all(s < 0 for s in sentiments)
            if sentiments else False
        )
        ensemble_output.append(entry)

    return ensemble_output


def score_headlines_for_symbol(
    headlines: list[dict],
    model_key: str = "finbert",
) -> dict:
    """Score a set of news headlines for a single symbol.

    Used by Strategy 14 and 24.

    Args:
        headlines: List of headline dicts from get_news_headlines MCP tool.
            Each has keys: time, providerCode, articleId, headline
        model_key: Sentiment model to use

    Returns:
        Dict with: symbol_sentiment (float), headline_count, positive_count,
        negative_count, neutral_count, headlines (with individual scores)
    """
    if not headlines:
        return {
            "symbol_sentiment": 0.0,
            "headline_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "headlines": [],
        }

    texts = [h.get("headline", "") for h in headlines]
    results = analyze_sentiment(texts, model_key=model_key)

    scored_headlines = []
    for h, r in zip(headlines, results):
        scored_headlines.append({
            **h,
            "sentiment_label": r.label,
            "sentiment_score": round(r.sentiment, 4),
            "confidence": round(r.score, 4),
        })

    sentiments = [r.sentiment for r in results]
    pos = sum(1 for s in sentiments if s > 0.1)
    neg = sum(1 for s in sentiments if s < -0.1)
    neu = len(sentiments) - pos - neg

    return {
        "symbol_sentiment": round(sum(sentiments) / len(sentiments), 4),
        "headline_count": len(headlines),
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count": neu,
        "headlines": scored_headlines,
    }


def classify_topic(
    texts: list[str],
    model_key: str = "finbert_topic",
) -> list[dict]:
    """Classify financial text by topic category.

    Uses nickmuchi/finbert-tone-finetuned-finance-topic-classification
    to categorize headlines/text into topics like earnings, M&A, macro, etc.
    Used by rotation strategies 34-36 to distinguish catalyst types.

    Args:
        texts: List of text strings (headlines, articles)
        model_key: Topic classification model (default "finbert_topic")

    Returns:
        List of dicts with topic, confidence, and all topic scores
    """
    model = registry.get_model(model_key)
    tokenizer = registry.get_tokenizer(model_key)

    results = []
    for text in texts:
        inputs = tokenizer(
            text, padding=True, truncation=True, max_length=512,
            return_tensors="pt",
        ).to(DEVICE)

        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1)

        id2label = model.config.id2label
        pred_idx = probs[0].argmax().item()
        pred_label = id2label[pred_idx]
        confidence = probs[0][pred_idx].item()

        all_topics = {
            id2label[i]: round(probs[0][i].item(), 4)
            for i in range(len(id2label))
        }

        # Classify as fundamental vs technical catalyst
        fundamental_keywords = {
            "earnings", "revenue", "profit", "FDA", "approval", "acquisition",
            "merger", "buyback", "dividend", "guidance", "upgrade", "IPO",
            "analyst", "rating", "partnership",
        }
        is_fundamental = any(
            kw in pred_label.lower() for kw in fundamental_keywords
        )

        results.append({
            "text": text,
            "topic": pred_label,
            "confidence": round(confidence, 4),
            "is_fundamental_catalyst": is_fundamental,
            "all_topics": all_topics,
        })

    return results


def detect_news_velocity(
    headlines: list[dict],
    window_minutes: int = 10,
    burst_threshold: int = 3,
    model_key: str = "distilroberta_financial",
) -> dict:
    """Detect news velocity bursts and score sentiment of the burst.

    Used by Strategy 24.

    Args:
        headlines: Headline dicts with 'time' field (YYYY-MM-DD HH:MM:SS)
        window_minutes: Rolling window to count headlines
        burst_threshold: Minimum headlines in window to trigger burst
        model_key: Sentiment model for burst headlines

    Returns:
        Dict with: is_burst (bool), burst_count, burst_headlines,
        burst_sentiment, burst_start, burst_end
    """
    from datetime import datetime, timedelta

    if len(headlines) < burst_threshold:
        return {"is_burst": False, "burst_count": 0}

    # Parse times and sort
    timed = []
    for h in headlines:
        try:
            t = datetime.strptime(h["time"], "%Y-%m-%d %H:%M:%S")
            timed.append((t, h))
        except (ValueError, KeyError):
            continue

    timed.sort(key=lambda x: x[0])

    # Sliding window burst detection
    best_burst = []
    for i in range(len(timed)):
        window_end = timed[i][0] + timedelta(minutes=window_minutes)
        window = [(t, h) for t, h in timed if timed[i][0] <= t <= window_end]
        if len(window) > len(best_burst):
            best_burst = window

    if len(best_burst) < burst_threshold:
        return {"is_burst": False, "burst_count": len(best_burst)}

    # Score the burst headlines
    burst_headlines = [h for _, h in best_burst]
    texts = [h.get("headline", "") for h in burst_headlines]
    results = analyze_sentiment(texts, model_key=model_key)

    sentiments = [r.sentiment for r in results]

    return {
        "is_burst": True,
        "burst_count": len(best_burst),
        "burst_start": best_burst[0][0].isoformat(),
        "burst_end": best_burst[-1][0].isoformat(),
        "burst_sentiment": round(sum(sentiments) / len(sentiments), 4),
        "unanimous_positive": all(s > 0 for s in sentiments),
        "unanimous_negative": all(s < 0 for s in sentiments),
        "burst_headlines": [
            {"headline": h.get("headline", ""), "sentiment": round(r.sentiment, 4)}
            for h, r in zip(burst_headlines, results)
        ],
    }
