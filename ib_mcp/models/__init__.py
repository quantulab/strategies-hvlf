"""HuggingFace model registry with lazy loading for trading strategies."""

import logging
from pathlib import Path
from typing import Any

import torch

logger = logging.getLogger(__name__)

MODEL_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".model_cache"
MODEL_CACHE_DIR.mkdir(exist_ok=True)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# HuggingFace model ID registry
MODEL_IDS = {
    # Sentiment models
    "finbert": "ProsusAI/finbert",
    "distilroberta_financial": "mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis",
    "twitter_sentiment": "cardiffnlp/twitter-roberta-base-sentiment-latest",
    "deberta_finance": "nickmuchi/deberta-v3-base-finetuned-finance-text-classification",
    "cryptobert": "ElKulako/cryptobert",
    "fomc_roberta": "gtfintechlab/FOMC-RoBERTa",
    # Time series models
    "chronos_small": "amazon/chronos-t5-small",
    "chronos_bolt": "amazon/chronos-bolt-base",
    "chronos_large": "amazon/chronos-t5-large",
    "timesfm": "google/timesfm-2.0-500m-pytorch",
    "ttm": "ibm-granite/granite-timeseries-ttm-r2",
    # Embedding models
    "bge_large": "BAAI/bge-large-en-v1.5",
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    # Classification models
    "bart_mnli": "facebook/bart-large-mnli",
    "ner": "dslim/bert-base-NER",
}


class ModelRegistry:
    """Singleton registry for lazy-loaded HuggingFace models."""

    _instance = None
    _models: dict[str, Any] = {}
    _tokenizers: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._models = {}
            cls._tokenizers = {}
        return cls._instance

    def is_loaded(self, key: str) -> bool:
        return key in self._models

    def get_model(self, key: str):
        if key not in MODEL_IDS:
            raise KeyError(f"Unknown model key '{key}'. Available: {list(MODEL_IDS.keys())}")
        if key not in self._models:
            self._load(key)
        return self._models[key]

    def get_tokenizer(self, key: str):
        if key not in MODEL_IDS:
            raise KeyError(f"Unknown model key '{key}'. Available: {list(MODEL_IDS.keys())}")
        if key not in self._tokenizers:
            self._load(key)
        return self._tokenizers[key]

    def _load(self, key: str):
        model_id = MODEL_IDS[key]
        logger.info(f"Loading model '{key}' ({model_id}) on {DEVICE}...")

        if key in ("chronos_small", "chronos_bolt", "chronos_large"):
            from chronos import ChronosPipeline
            self._models[key] = ChronosPipeline.from_pretrained(
                model_id, device_map=DEVICE, torch_dtype=torch.float32,
                cache_dir=str(MODEL_CACHE_DIR),
            )
            self._tokenizers[key] = None  # Chronos has its own tokenizer built-in
        elif key == "timesfm":
            import timesfm
            self._models[key] = timesfm.TimesFm(
                hparams=timesfm.TimesFmHparams(
                    backend="gpu" if DEVICE == "cuda" else "cpu",
                    per_core_batch_size=32,
                    horizon_len=128,
                ),
                checkpoint=timesfm.TimesFmCheckpoint(
                    huggingface_repo_id=model_id,
                ),
            )
            self._tokenizers[key] = None
        elif key == "ttm":
            from tsfm_public.models.tinytimemixer import TinyTimeMixerForPrediction
            self._models[key] = TinyTimeMixerForPrediction.from_pretrained(
                model_id, cache_dir=str(MODEL_CACHE_DIR),
            )
            self._tokenizers[key] = None
        elif key in ("bge_large", "minilm"):
            from sentence_transformers import SentenceTransformer
            self._models[key] = SentenceTransformer(
                model_id, device=DEVICE, cache_folder=str(MODEL_CACHE_DIR),
            )
            self._tokenizers[key] = None
        elif key == "ner":
            from transformers import AutoModelForTokenClassification, AutoTokenizer
            self._tokenizers[key] = AutoTokenizer.from_pretrained(
                model_id, cache_dir=str(MODEL_CACHE_DIR),
            )
            self._models[key] = AutoModelForTokenClassification.from_pretrained(
                model_id, cache_dir=str(MODEL_CACHE_DIR),
            ).to(DEVICE)
        elif key == "bart_mnli":
            from transformers import pipeline
            self._models[key] = pipeline(
                "zero-shot-classification", model=model_id,
                device=0 if DEVICE == "cuda" else -1,
                model_kwargs={"cache_dir": str(MODEL_CACHE_DIR)},
            )
            self._tokenizers[key] = None
        else:
            # Default: text-classification models (finbert, distilroberta, etc.)
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self._tokenizers[key] = AutoTokenizer.from_pretrained(
                model_id, cache_dir=str(MODEL_CACHE_DIR),
            )
            self._models[key] = AutoModelForSequenceClassification.from_pretrained(
                model_id, cache_dir=str(MODEL_CACHE_DIR),
            ).to(DEVICE)

        logger.info(f"Model '{key}' loaded successfully.")

    def unload(self, key: str):
        self._models.pop(key, None)
        self._tokenizers.pop(key, None)
        if DEVICE == "cuda":
            torch.cuda.empty_cache()

    def list_models(self) -> dict[str, dict]:
        return {
            key: {
                "model_id": MODEL_IDS[key],
                "loaded": key in self._models,
            }
            for key in MODEL_IDS
        }


registry = ModelRegistry()
