"""Model configuration constants for strategy integration."""

# Strategy-to-model mapping
STRATEGY_MODELS = {
    "S14_llm_news_sentiment": ["finbert", "distilroberta_financial"],
    "S15_hmm_regime": ["fomc_roberta"],
    "S17_transformer_rank": ["chronos_large"],
    "S18_genai_scenario": ["bart_mnli"],
    "S23_lstm_rank": ["chronos_small"],
    "S24_news_velocity": ["distilroberta_financial", "ner"],
    "S25_vae_clustering": ["bart_mnli"],
    "S28_sentiment_composite": [
        "finbert",
        "deberta_finance",
        "twitter_sentiment",
        "cryptobert",
    ],
    "S29_monte_carlo": ["chronos_bolt"],
    "S30_maml_few_shot": ["chronos_small"],
    "S31_diffusion": ["timesfm"],
    "S36_contrastive": ["minilm"],
    "S38_distillation": ["ttm"],
    "S40_rag_lookup": ["bge_large", "ner"],
    # Rotation strategy enhancements
    "S31_rotation_master": ["finbert", "bart_mnli"],
    "S32_volume_surge": ["finbert", "chronos_bolt"],
    "S33_streak_continuation": ["finbert", "chronos_small"],
    "S34_whipsaw_fade": ["finbert", "finbert_topic"],
    "S35_premarket_persist": ["finbert", "finbert_topic"],
    "S36_capsize_breakout": ["finbert", "finbert_topic"],
    "S37_elite_accumulation": ["finbert"],
}

# Sentiment label mappings (model-specific)
SENTIMENT_LABELS = {
    "finbert": {"positive": 1.0, "negative": -1.0, "neutral": 0.0},
    "distilroberta_financial": {"positive": 1.0, "negative": -1.0, "neutral": 0.0},
    "twitter_sentiment": {"positive": 1.0, "negative": -1.0, "neutral": 0.0},
    "deberta_finance": {"positive": 1.0, "negative": -1.0, "neutral": 0.0},
    "cryptobert": {"Bullish": 1.0, "Bearish": -1.0, "Neutral": 0.0},
    "fomc_roberta": {"hawkish": -0.5, "dovish": 0.5, "neutral": 0.0},
    # Rotation strategy enhancement models
    "finbert_topic": {},  # topic classification — labels from model.config.id2label
    "modern_finbert": {"positive": 1.0, "negative": -1.0, "neutral": 0.0},
}

# Time series model configs
TIMESERIES_CONFIGS = {
    "chronos_small": {"context_length": 512, "prediction_length": 64},
    "chronos_bolt": {"context_length": 512, "prediction_length": 64},
    "chronos_large": {"context_length": 512, "prediction_length": 64},
    "chronos_2": {"context_length": 512, "prediction_length": 64},
    "timesfm": {"context_length": 512, "horizon_len": 128},
    "ttm": {"context_length": 512, "prediction_length": 96},
}

# Embedding dimensions
EMBEDDING_DIMS = {
    "bge_large": 1024,
    "minilm": 384,
}

# Local rotation models (trained on rotation_scanner.db, stored as joblib)
ROTATION_LOCAL_MODELS = {
    "hmm_regime": {
        "type": "hmmlearn.GaussianHMM",
        "artifact": "rotation/hmm_regime.joblib",
        "min_training_rows": 50,
        "retrain_interval_days": 7,
    },
    "volume_conversion_gb": {
        "type": "sklearn.GradientBoostingClassifier",
        "artifact": "rotation/volume_conversion_gb.joblib",
        "min_training_rows": 100,
        "retrain_interval_days": 7,
    },
    "streak_survival_gb": {
        "type": "sklearn.GradientBoostingClassifier",
        "artifact": "rotation/streak_survival_gb.joblib",
        "min_training_rows": 30,
        "retrain_interval_days": 7,
    },
    "premarket_persist_lr": {
        "type": "sklearn.LogisticRegression",
        "artifact": "rotation/premarket_persist_lr.joblib",
        "min_training_rows": 50,
        "retrain_interval_days": 14,
    },
}
