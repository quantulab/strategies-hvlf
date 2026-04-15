"""Run the full backtest across all strategies and all available dates.

Usage:
    python -m backtest.run_backtest
    python -m backtest.run_backtest --strategies S12,S32,S27
    python -m backtest.run_backtest --dates 20260303,20260304
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import (
    PriceCache, Signal, Trade, StrategyResult,
    get_available_dates, load_day_scanner_data, evaluate_trade,
    compute_strategy_results, save_results_to_db, build_symbol_state,
)
from backtest.strategies import STRATEGY_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_backtest(
    strategy_ids: list[str] | None = None,
    dates: list[str] | None = None,
    sample_interval_minutes: int = 10,
    max_signals_per_day: int = 20,
    max_concurrent_trades: int = 6,
    no_ib: bool = False,
):
    """Execute the full backtest.

    Args:
        strategy_ids: List of strategy IDs to test (None = all)
        dates: List of dates to test (None = all available)
        sample_interval_minutes: How often to sample scanner state
        max_signals_per_day: Max signals per strategy per day
        max_concurrent_trades: Max open trades per strategy at once
    """
    all_dates = dates or get_available_dates()
    strategies = {
        sid: cfg for sid, cfg in STRATEGY_REGISTRY.items()
        if strategy_ids is None or sid in strategy_ids
    }

    if not all_dates:
        logger.error("No scanner dates found!")
        return

    logger.info(f"Backtesting {len(strategies)} strategies across {len(all_dates)} days")
    logger.info(f"Strategies: {', '.join(strategies.keys())}")
    logger.info(f"Date range: {all_dates[0]} to {all_dates[-1]}")

    prices = PriceCache(disable_ib=no_ib)

    if no_ib:
        logger.info("IB fallback disabled (--no-ib)")

    # Try connecting to IB for price data fallback
    if not no_ib:
        try:
            from ib_insync import IB
            ib = IB()
            try:
                ib.connect("127.0.0.1", 7497, clientId=99, timeout=5)
                logger.info("Connected to IB TWS (port 7497) for price data fallback")
            except Exception:
                try:
                    ib.connect("127.0.0.1", 4002, clientId=99, timeout=5)
                    logger.info("Connected to IB Gateway (port 4002) for price data fallback")
                except Exception:
                    ib = None
                    logger.warning("Could not connect to IB — will use local CSV bars only")
            if ib:
                prices.set_ib_client(ib)
        except ImportError:
            logger.warning("ib_insync not installed — will use local CSV bars only")

    all_trades: dict[str, list[Trade]] = defaultdict(list)
    all_signals: dict[str, int] = defaultdict(int)

    prior_day_symbols: set = set()

    for day_idx, date in enumerate(all_dates):
        logger.info(f"Processing {date} ({day_idx + 1}/{len(all_dates)})...")

        snapshots = load_day_scanner_data(date)
        if not snapshots:
            logger.warning(f"  No scanner data for {date}")
            continue

        # Get time range for this day
        first_ts = snapshots[0].timestamp
        last_ts = snapshots[-1].timestamp

        # Market hours: sample every N minutes from first snapshot
        current_time = first_ts
        recent_signals: dict[str, dict[str, datetime]] = defaultdict(dict)  # strategy -> {symbol: last_signal_time}
        daily_signal_count: dict[str, int] = defaultdict(int)
        open_trades: dict[str, int] = defaultdict(int)

        while current_time <= last_ts:
            for sid, cfg in strategies.items():
                if daily_signal_count[sid] >= max_signals_per_day:
                    continue
                if open_trades[sid] >= max_concurrent_trades:
                    continue

                # Generate signals
                try:
                    if sid == "S30":
                        raw_signals = cfg["fn"](snapshots, current_time, prior_day_symbols)
                    elif sid == "S19":
                        raw_signals = cfg["fn"](snapshots, current_time, day_index=day_idx)
                    else:
                        raw_signals = cfg["fn"](snapshots, current_time)
                except Exception as e:
                    logger.debug(f"  {sid} error at {current_time}: {e}")
                    continue

                # Deduplicate: no repeat signal for same symbol within 30 min
                for signal in raw_signals:
                    last_time = recent_signals[sid].get(signal.symbol)
                    if last_time and (signal.timestamp - last_time).total_seconds() < 1800:
                        continue

                    all_signals[sid] += 1
                    daily_signal_count[sid] += 1
                    recent_signals[sid][signal.symbol] = signal.timestamp

                    # Evaluate trade
                    trade = evaluate_trade(
                        signal, prices,
                        stop_pct=cfg["stop"],
                        target_pct=cfg["target"],
                        max_hold_minutes=cfg["max_hold"],
                    )
                    if trade:
                        all_trades[sid].append(trade)
                        open_trades[sid] += 1

                        # Track when trades close for concurrent limit
                        if trade.exit_time and trade.exit_time <= last_ts:
                            open_trades[sid] = max(0, open_trades[sid] - 1)

            current_time += timedelta(minutes=sample_interval_minutes)

        # Track prior day symbols for S30
        day_states = build_symbol_state(snapshots, last_ts, window_minutes=480)
        prior_day_symbols = set(day_states.keys())

        # Log daily summary
        day_trades = {sid: [t for t in trades if t.entry_time.strftime("%Y%m%d") == date]
                      for sid, trades in all_trades.items()}
        for sid, trades in day_trades.items():
            if trades:
                wins = sum(1 for t in trades if t.pnl_pct > 0)
                total_pnl = sum(t.pnl_pct for t in trades)
                logger.info(f"  {sid}: {len(trades)} trades, {wins}W, "
                           f"P&L: {total_pnl*100:.2f}%")

    # ── Compute final results ──────────────────────
    logger.info("\n" + "=" * 80)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 80)

    results = []
    for sid, cfg in strategies.items():
        trades = all_trades.get(sid, [])
        r = compute_strategy_results(sid, cfg["name"], trades)
        r.total_signals = all_signals.get(sid, 0)
        results.append(r)

    # Sort by expectancy
    results.sort(key=lambda r: r.expectancy, reverse=True)

    # Print results table
    print(f"\n{'Strategy':<25} {'Signals':>8} {'Trades':>7} {'WinRate':>8} "
          f"{'AvgWin%':>8} {'AvgLoss%':>9} {'Expect%':>8} {'PF':>6} "
          f"{'Sharpe':>7} {'MaxDD%':>7} {'AvgHold':>8}")
    print("-" * 120)

    for r in results:
        print(f"{r.strategy_id + ' ' + r.strategy_name:<25} "
              f"{r.total_signals:>8} {r.total_trades:>7} "
              f"{r.win_rate*100:>7.1f}% "
              f"{r.avg_win_pct*100:>7.2f}% "
              f"{r.avg_loss_pct*100:>8.2f}% "
              f"{r.expectancy*100:>7.3f}% "
              f"{r.profit_factor:>6.2f} "
              f"{r.sharpe_ratio:>7.2f} "
              f"{r.max_drawdown_pct*100:>6.2f}% "
              f"{r.avg_hold_minutes:>7.1f}m")

    # Print trade breakdown by exit reason
    print(f"\n{'Strategy':<20} {'StopLoss':>10} {'TakeProfit':>12} {'TimeStop':>10} {'Total':>7}")
    print("-" * 65)
    for r in results:
        if r.total_trades == 0:
            continue
        stops = sum(1 for t in r.trades if t.exit_reason == "stop_loss")
        targets = sum(1 for t in r.trades if t.exit_reason == "take_profit")
        time_stops = sum(1 for t in r.trades if t.exit_reason == "time_stop")
        print(f"{r.strategy_id:<20} {stops:>10} {targets:>12} {time_stops:>10} {r.total_trades:>7}")

    # Print forward return analysis
    print(f"\n{'Strategy':<20} {'Avg 15m%':>10} {'Avg 30m%':>10} {'Avg 60m%':>10} {'Sig->Trades':>15}")
    print("-" * 70)
    for r in results:
        if r.total_trades == 0:
            continue
        r15 = [t.return_15m for t in r.trades if t.return_15m is not None]
        r30 = [t.return_30m for t in r.trades if t.return_30m is not None]
        r60 = [t.return_60m for t in r.trades if t.return_60m is not None]
        avg15 = sum(r15) / len(r15) * 100 if r15 else 0
        avg30 = sum(r30) / len(r30) * 100 if r30 else 0
        avg60 = sum(r60) / len(r60) * 100 if r60 else 0
        conversion = r.total_trades / r.total_signals * 100 if r.total_signals > 0 else 0
        print(f"{r.strategy_id:<20} {avg15:>9.3f}% {avg30:>9.3f}% {avg60:>9.3f}% "
              f"{conversion:>13.1f}%")

    # Print top 10 best and worst individual trades
    all_trade_list = []
    for r in results:
        for t in r.trades:
            all_trade_list.append((r.strategy_id, t))

    if all_trade_list:
        all_trade_list.sort(key=lambda x: x[1].pnl_pct, reverse=True)

        print(f"\n{'Top 10 Best Trades':=^80}")
        print(f"{'Strategy':<10} {'Symbol':<8} {'Date':<12} {'P&L%':>8} {'Exit':>12} {'Hold':>6}")
        for sid, t in all_trade_list[:10]:
            print(f"{sid:<10} {t.signal.symbol:<8} "
                  f"{t.entry_time.strftime('%Y-%m-%d'):<12} "
                  f"{t.pnl_pct*100:>7.2f}% {t.exit_reason:>12} "
                  f"{t.hold_minutes:>5.0f}m")

        print(f"\n{'Top 10 Worst Trades':=^80}")
        for sid, t in all_trade_list[-10:]:
            print(f"{sid:<10} {t.signal.symbol:<8} "
                  f"{t.entry_time.strftime('%Y-%m-%d'):<12} "
                  f"{t.pnl_pct*100:>7.2f}% {t.exit_reason:>12} "
                  f"{t.hold_minutes:>5.0f}m")

    # Save to DB
    save_results_to_db(results)
    logger.info(f"\nResults saved to {Path('D:/src/ai/mcp/ib/backtest/backtest_results.db')}")

    # Print IB fetch stats
    from backtest.engine import BAR_DATA_BASE
    if prices._fetch_failures:
        logger.info(f"\nIB fetch failures ({len(prices._fetch_failures)} symbols): "
                    f"{', '.join(sorted(list(prices._fetch_failures)[:20]))}")
    ib_fetched = len(prices._cache) - len([
        s for s in prices._cache
        if (BAR_DATA_BASE / f"{s}_STK_M.csv").exists()
    ])
    if ib_fetched > 0:
        logger.info(f"Fetched {ib_fetched} symbols from IB (not in local CSV)")

    # Disconnect IB if connected
    if prices._ib:
        try:
            prices._ib.disconnect()
            logger.info("Disconnected from IB")
        except Exception:
            pass

    return results


def main():
    parser = argparse.ArgumentParser(description="Run strategy backtests")
    parser.add_argument("--strategies", type=str, default=None,
                        help="Comma-separated strategy IDs (e.g. S12,S32,S27)")
    parser.add_argument("--dates", type=str, default=None,
                        help="Comma-separated dates (e.g. 20260303,20260304)")
    parser.add_argument("--interval", type=int, default=10,
                        help="Sample interval in minutes (default 10)")
    parser.add_argument("--max-signals", type=int, default=20,
                        help="Max signals per strategy per day (default 20)")
    parser.add_argument("--max-concurrent", type=int, default=6,
                        help="Max concurrent trades per strategy (default 6)")
    parser.add_argument("--no-ib", action="store_true",
                        help="Disable IB connection, use only local CSV bars")

    args = parser.parse_args()

    strategy_ids = args.strategies.split(",") if args.strategies else None
    dates = args.dates.split(",") if args.dates else None

    run_backtest(
        no_ib=args.no_ib,
        strategy_ids=strategy_ids,
        dates=dates,
        sample_interval_minutes=args.interval,
        max_signals_per_day=args.max_signals,
        max_concurrent_trades=args.max_concurrent,
    )


if __name__ == "__main__":
    main()
