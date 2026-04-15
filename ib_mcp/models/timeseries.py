"""Time series forecasting using HuggingFace foundation models.

Supports: Chronos (Amazon), TimesFM (Google), TTM (IBM Granite)
Used by strategies: S17, S23, S29, S30, S31, S38
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import torch

from ib_mcp.models import DEVICE, registry
from ib_mcp.models.config import TIMESERIES_CONFIGS

logger = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    """Result from time series forecast."""
    point_forecast: list[float]  # Median/mean predictions
    quantile_low: list[float]  # 10th percentile
    quantile_high: list[float]  # 90th percentile
    horizon: int
    model: str
    context_length: int


def forecast_chronos(
    context: list[float],
    prediction_length: int = 30,
    model_key: str = "chronos_small",
    num_samples: int = 20,
) -> ForecastResult:
    """Generate probabilistic forecasts using Amazon Chronos.

    Args:
        context: Historical values (e.g., rank positions over time, prices)
        prediction_length: How many steps ahead to forecast
        model_key: "chronos_small" (46M, fast), "chronos_bolt" (205M, balanced),
                   "chronos_large" (709M, best quality)
        num_samples: Number of sample paths for quantile estimation

    Returns:
        ForecastResult with point forecast and quantile bands
    """
    pipeline = registry.get_model(model_key)
    context_tensor = torch.tensor(context, dtype=torch.float32)

    forecast = pipeline.predict(
        context_tensor.unsqueeze(0),
        prediction_length,
        num_samples=num_samples,
    )

    # forecast shape: (1, num_samples, prediction_length)
    samples = forecast[0].numpy()
    median = np.median(samples, axis=0).tolist()
    q10 = np.quantile(samples, 0.1, axis=0).tolist()
    q90 = np.quantile(samples, 0.9, axis=0).tolist()

    return ForecastResult(
        point_forecast=median,
        quantile_low=q10,
        quantile_high=q90,
        horizon=prediction_length,
        model=model_key,
        context_length=len(context),
    )


def forecast_rank_trajectory(
    rank_history: list[int],
    prediction_steps: int = 60,
    model_key: str = "chronos_small",
) -> dict:
    """Forecast a stock's future scanner rank trajectory.

    Used by Strategy 23 (LSTM Rank Forecaster replacement) and
    Strategy 17 (Transformer Rank Trajectory).

    Args:
        rank_history: List of rank positions over time (e.g., last 120 snapshots).
                      Use -1 or 51 for "not on scanner".
        prediction_steps: Number of future snapshots to predict
        model_key: Chronos model variant

    Returns:
        Dict with predicted ranks, probability of entering top-5,
        predicted direction, etc.
    """
    # Replace "not on scanner" values with a high rank
    cleaned = [r if 0 <= r <= 50 else 51 for r in rank_history]

    result = forecast_chronos(
        context=[float(r) for r in cleaned],
        prediction_length=prediction_steps,
        model_key=model_key,
    )

    predicted_ranks = [max(0, round(r)) for r in result.point_forecast]

    # Compute signal metrics
    current_rank = cleaned[-1] if cleaned else 51
    predicted_best_rank = min(predicted_ranks) if predicted_ranks else 51
    enters_top5 = predicted_best_rank <= 5
    enters_top10 = predicted_best_rank <= 10
    rank_improving = predicted_ranks[-1] < current_rank if predicted_ranks else False

    return {
        "current_rank": current_rank,
        "predicted_ranks": predicted_ranks,
        "predicted_best_rank": predicted_best_rank,
        "enters_top5": enters_top5,
        "enters_top10": enters_top10,
        "rank_improving": rank_improving,
        "rank_change": current_rank - (predicted_ranks[-1] if predicted_ranks else current_rank),
        "confidence_band_low": [max(0, round(r)) for r in result.quantile_low],
        "confidence_band_high": [min(51, round(r)) for r in result.quantile_high],
        "model": model_key,
    }


def forecast_price_distribution(
    price_history: list[float],
    prediction_length: int = 30,
    model_key: str = "chronos_bolt",
    num_samples: int = 1000,
) -> dict:
    """Generate price forecast distribution for Monte Carlo analysis.

    Used by Strategy 29 (Monte Carlo Simulation).

    Args:
        price_history: Historical prices (1-min bars recommended)
        prediction_length: Forward steps to simulate
        model_key: Chronos variant ("chronos_bolt" recommended for speed)
        num_samples: Number of Monte Carlo sample paths

    Returns:
        Dict with distribution statistics: probabilities, expected return,
        CVaR, quantiles, etc.
    """
    pipeline = registry.get_model(model_key)
    context_tensor = torch.tensor(price_history, dtype=torch.float32)

    forecast = pipeline.predict(
        context_tensor.unsqueeze(0),
        prediction_length,
        num_samples=num_samples,
    )

    samples = forecast[0].numpy()  # (num_samples, prediction_length)
    entry_price = price_history[-1]

    # Terminal returns (at end of prediction horizon)
    terminal_prices = samples[:, -1]
    terminal_returns = (terminal_prices - entry_price) / entry_price

    # Distribution statistics
    prob_up_2pct = float(np.mean(terminal_returns > 0.02))
    prob_down_3pct = float(np.mean(terminal_returns < -0.03))
    expected_return = float(np.mean(terminal_returns))
    cvar_5 = float(np.percentile(terminal_returns, 5))
    cvar_10 = float(np.percentile(terminal_returns, 10))

    # Quantile targets and stops
    q10 = float(np.percentile(terminal_prices, 10))
    q25 = float(np.percentile(terminal_prices, 25))
    q50 = float(np.percentile(terminal_prices, 50))
    q75 = float(np.percentile(terminal_prices, 75))
    q90 = float(np.percentile(terminal_prices, 90))

    # Kelly criterion
    wins = terminal_returns[terminal_returns > 0]
    losses = terminal_returns[terminal_returns < 0]
    if len(wins) > 0 and len(losses) > 0:
        p_win = len(wins) / len(terminal_returns)
        avg_win = float(np.mean(wins))
        avg_loss = float(np.mean(np.abs(losses)))
        b = avg_win / avg_loss if avg_loss > 0 else 1
        kelly = (p_win * b - (1 - p_win)) / b if b > 0 else 0
        half_kelly = max(0, kelly / 2)
    else:
        p_win = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        kelly = 0.0
        half_kelly = 0.0

    return {
        "entry_price": entry_price,
        "prediction_length": prediction_length,
        "num_samples": num_samples,
        "prob_up_2pct": round(prob_up_2pct, 4),
        "prob_down_3pct": round(prob_down_3pct, 4),
        "expected_return": round(expected_return, 4),
        "cvar_5pct": round(cvar_5, 4),
        "cvar_10pct": round(cvar_10, 4),
        "price_quantiles": {
            "q10": round(q10, 4),
            "q25": round(q25, 4),
            "q50_median": round(q50, 4),
            "q75": round(q75, 4),
            "q90": round(q90, 4),
        },
        "suggested_stop": round(q10, 4),
        "suggested_target": round(q75, 4),
        "win_rate": round(p_win, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "kelly_fraction": round(kelly, 4),
        "half_kelly_fraction": round(half_kelly, 4),
        "half_kelly_pct_account": round(min(half_kelly * 100, 2.0), 2),
        "model": model_key,
    }


def multi_scanner_rank_forecast(
    rank_histories: dict[str, list[int]],
    prediction_steps: int = 60,
    model_key: str = "chronos_small",
) -> dict:
    """Forecast ranks across multiple scanner types simultaneously.

    Used by Strategy 31 (Diffusion Model replacement) and
    Strategy 17 (Transformer multi-scanner).

    Args:
        rank_histories: Dict mapping scanner_name -> list of rank positions.
            e.g. {"GainSinceOpen": [15, 12, 10, ...], "HotByVolume": [3, 3, 2, ...]}
        prediction_steps: Steps ahead to forecast
        model_key: Chronos variant

    Returns:
        Dict with per-scanner forecasts and consensus metrics
    """
    forecasts = {}
    for scanner_name, ranks in rank_histories.items():
        if len(ranks) < 10:
            continue
        forecasts[scanner_name] = forecast_rank_trajectory(
            ranks, prediction_steps, model_key,
        )

    # Consensus: how many scanners predict the stock entering top-10?
    top10_count = sum(1 for f in forecasts.values() if f["enters_top10"])
    top5_count = sum(1 for f in forecasts.values() if f["enters_top5"])
    total_scanners = len(forecasts)

    consensus_score = top10_count / total_scanners if total_scanners > 0 else 0

    return {
        "scanner_forecasts": forecasts,
        "consensus_top10": top10_count,
        "consensus_top5": top5_count,
        "total_scanners_forecast": total_scanners,
        "consensus_score": round(consensus_score, 4),
        "signal": consensus_score >= 0.7,
        "model": model_key,
    }
