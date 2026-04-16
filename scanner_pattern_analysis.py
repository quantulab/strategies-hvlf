"""
Scanner Pattern Analysis - Processes HVLF rotating scanner data across all days
to discover hidden patterns, behaviors, and tradeable signals.
"""
import os
import re
import json
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = r"\\Station001\DATA\hvlf\rotating"

SCANNER_TYPES = [
    "GainSinceOpen", "HighOpenGap", "HotByPrice", "HotByPriceRange",
    "HotByVolume", "LossSinceOpen", "LowOpenGap", "MostActive",
    "TopGainers", "TopLosers", "TopVolumeRate"
]
CAP_SIZES = ["SmallCap", "MidCap", "LargeCap"]

GAIN_SCANNERS = {"TopGainers", "GainSinceOpen", "HighOpenGap"}
LOSS_SCANNERS = {"TopLosers", "LossSinceOpen", "LowOpenGap"}
VOLUME_SCANNERS = {"HotByVolume", "MostActive", "TopVolumeRate"}
PRICE_SCANNERS = {"HotByPrice", "HotByPriceRange"}


def parse_scanner_file(filepath):
    """Parse a single scanner CSV. Returns list of (timestamp, [(rank, ticker), ...])"""
    records = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',', 1)
                if len(parts) < 2:
                    continue
                ts_str = parts[0]
                try:
                    ts = datetime.strptime(ts_str, "%Y%m%d %H:%M:%S.%f")
                except ValueError:
                    continue
                tickers = []
                for entry in parts[1].split(','):
                    entry = entry.strip()
                    m = re.match(r'(\d+):(.+?)_STK', entry)
                    if m:
                        rank = int(m.group(1))
                        ticker = m.group(2).strip()
                        if ticker and not any(c in ticker for c in [' ', '/']):
                            tickers.append((rank, ticker))
                records.append((ts, tickers))
    except Exception:
        pass
    return records


def parse_scanner_filename(filename):
    """Extract cap_size and scanner_type from filename."""
    for cap in CAP_SIZES:
        if filename.startswith(cap):
            remainder = filename[len(cap)+1:]  # skip the '-'
            scanner_type = remainder.replace("_Scanner.csv", "")
            return cap, scanner_type
    return None, None


def load_all_data():
    """Load all scanner data across all days."""
    print("Loading scanner data...")
    # day -> scanner_key -> [(ts, [(rank, ticker)])]
    all_data = {}
    day_folders = sorted([d for d in os.listdir(BASE_DIR) if d.isdigit() and len(d) == 8])
    print(f"  Found {len(day_folders)} day folders")

    for day in day_folders:
        day_path = os.path.join(BASE_DIR, day)
        all_data[day] = {}
        for fname in os.listdir(day_path):
            if not fname.endswith("_Scanner.csv"):
                continue
            cap, stype = parse_scanner_filename(fname)
            if not cap or not stype:
                continue
            key = f"{cap}-{stype}"
            records = parse_scanner_file(os.path.join(day_path, fname))
            if records:
                all_data[day][key] = records
    print(f"  Loaded data for {len(all_data)} days")
    return all_data, day_folders


def analyze_ticker_frequency(all_data, day_folders):
    """Which tickers appear most frequently across all days and scanners."""
    # ticker -> {days_seen, total_appearances, scanners_seen, avg_rank, cap_sizes}
    ticker_stats = defaultdict(lambda: {
        'days': set(), 'total_appearances': 0, 'scanners': set(),
        'cap_sizes': set(), 'ranks': [], 'first_seen': None, 'last_seen': None
    })

    for day in day_folders:
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            # Use only first and last snapshot per scanner per day to avoid over-counting
            if not records:
                continue
            # Deduplicate: unique tickers seen in this scanner on this day
            day_tickers = set()
            for ts, tickers in records:
                for rank, ticker in tickers:
                    day_tickers.add(ticker)
                    stats = ticker_stats[ticker]
                    stats['total_appearances'] += 1
                    stats['ranks'].append(rank)
            for ticker in day_tickers:
                stats = ticker_stats[ticker]
                stats['days'].add(day)
                stats['scanners'].add(stype)
                stats['cap_sizes'].add(cap)
                if stats['first_seen'] is None or day < stats['first_seen']:
                    stats['first_seen'] = day
                if stats['last_seen'] is None or day > stats['last_seen']:
                    stats['last_seen'] = day

    # Sort by number of unique days
    ranked = sorted(ticker_stats.items(),
                    key=lambda x: (len(x[1]['days']), x[1]['total_appearances']),
                    reverse=True)
    return ranked[:100], ticker_stats


def analyze_whipsaw_tickers(all_data, day_folders):
    """Find tickers appearing on BOTH gain and loss scanners same day (whipsaw)."""
    whipsaw_events = []  # (day, ticker, gain_scanners, loss_scanners)
    whipsaw_counts = Counter()

    for day in day_folders:
        # Per day: track which tickers appear on gain vs loss scanners
        ticker_gain = defaultdict(set)
        ticker_loss = defaultdict(set)
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    if stype in GAIN_SCANNERS:
                        ticker_gain[ticker].add(f"{cap}-{stype}")
                    elif stype in LOSS_SCANNERS:
                        ticker_loss[ticker].add(f"{cap}-{stype}")
        # Find overlap
        for ticker in set(ticker_gain.keys()) & set(ticker_loss.keys()):
            whipsaw_events.append((day, ticker, ticker_gain[ticker], ticker_loss[ticker]))
            whipsaw_counts[ticker] += 1

    return whipsaw_events, whipsaw_counts


def analyze_volume_leads_price(all_data, day_folders):
    """Detect tickers appearing on volume scanners BEFORE gain scanners (predictive signal)."""
    signals = []  # (day, ticker, vol_first_ts, gain_first_ts, lead_minutes)

    for day in day_folders:
        ticker_vol_first = {}
        ticker_gain_first = {}
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    if stype in VOLUME_SCANNERS:
                        if ticker not in ticker_vol_first or ts < ticker_vol_first[ticker]:
                            ticker_vol_first[ticker] = ts
                    elif stype in GAIN_SCANNERS:
                        if ticker not in ticker_gain_first or ts < ticker_gain_first[ticker]:
                            ticker_gain_first[ticker] = ts

        for ticker in set(ticker_vol_first.keys()) & set(ticker_gain_first.keys()):
            vol_ts = ticker_vol_first[ticker]
            gain_ts = ticker_gain_first[ticker]
            if vol_ts < gain_ts:
                lead_min = (gain_ts - vol_ts).total_seconds() / 60
                if lead_min > 1:  # at least 1 minute lead
                    signals.append((day, ticker, vol_ts, gain_ts, lead_min))

    return signals


def analyze_multi_day_streaks(all_data, day_folders):
    """Find tickers appearing on the same scanner type for consecutive days."""
    # For each (ticker, scanner_type): list of days
    ticker_scanner_days = defaultdict(list)

    for day in day_folders:
        day_ticker_scanners = defaultdict(set)
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            tickers_seen = set()
            for ts, tickers in records:
                for rank, ticker in tickers:
                    tickers_seen.add(ticker)
            for ticker in tickers_seen:
                day_ticker_scanners[ticker].add(stype)
        for ticker, stypes in day_ticker_scanners.items():
            for stype in stypes:
                ticker_scanner_days[(ticker, stype)].append(day)

    # Find consecutive streaks
    streaks = []
    for (ticker, stype), days in ticker_scanner_days.items():
        days_sorted = sorted(days)
        if len(days_sorted) < 3:
            continue
        # Find consecutive sequences using day_folders index
        day_indices = [day_folders.index(d) for d in days_sorted if d in day_folders]
        day_indices.sort()

        current_streak_start = day_indices[0]
        current_streak_end = day_indices[0]
        best_streaks = []

        for i in range(1, len(day_indices)):
            if day_indices[i] == current_streak_end + 1:
                current_streak_end = day_indices[i]
            else:
                streak_len = current_streak_end - current_streak_start + 1
                if streak_len >= 3:
                    best_streaks.append((
                        day_folders[current_streak_start],
                        day_folders[current_streak_end],
                        streak_len
                    ))
                current_streak_start = day_indices[i]
                current_streak_end = day_indices[i]

        streak_len = current_streak_end - current_streak_start + 1
        if streak_len >= 3:
            best_streaks.append((
                day_folders[current_streak_start],
                day_folders[current_streak_end],
                streak_len
            ))

        for start_day, end_day, slen in best_streaks:
            streaks.append((ticker, stype, start_day, end_day, slen, len(days_sorted)))

    streaks.sort(key=lambda x: x[4], reverse=True)
    return streaks[:100]


def analyze_cap_crossover(all_data, day_folders):
    """Find tickers crossing from SmallCap to LargeCap scanners (or vice versa)."""
    crossovers = []

    for day in day_folders:
        ticker_caps = defaultdict(set)
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    ticker_caps[ticker].add(cap)

        for ticker, caps in ticker_caps.items():
            if "SmallCap" in caps and "LargeCap" in caps:
                crossovers.append((day, ticker, "Small<->Large"))
            elif "SmallCap" in caps and "MidCap" in caps:
                crossovers.append((day, ticker, "Small<->Mid"))
            elif "MidCap" in caps and "LargeCap" in caps:
                crossovers.append((day, ticker, "Mid<->Large"))

    crossover_counts = Counter()
    for day, ticker, direction in crossovers:
        crossover_counts[(ticker, direction)] += 1
    return crossovers, crossover_counts


def analyze_day_of_week_patterns(all_data, day_folders):
    """Analyze scanner activity by day of week."""
    dow_stats = defaultdict(lambda: {'unique_tickers': [], 'scanner_counts': Counter()})

    for day in day_folders:
        dt = datetime.strptime(day, "%Y%m%d")
        dow = dt.strftime("%A")
        day_tickers = set()
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    day_tickers.add(ticker)
            dow_stats[dow]['scanner_counts'][stype] += 1
        dow_stats[dow]['unique_tickers'].append(len(day_tickers))

    return dow_stats


def analyze_premarket_movers(all_data, day_folders):
    """Find tickers that appear pre-market (before 9:30) and track if they persist."""
    premarket_signals = []

    for day in day_folders:
        premarket_tickers = set()
        market_tickers = set()
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                hour = ts.hour
                for rank, ticker in tickers:
                    if hour < 9 or (hour == 9 and ts.minute < 30):
                        premarket_tickers.add(ticker)
                    else:
                        market_tickers.add(ticker)

        persist = premarket_tickers & market_tickers
        fade = premarket_tickers - market_tickers
        if premarket_tickers:
            premarket_signals.append({
                'day': day,
                'premarket_count': len(premarket_tickers),
                'persist_count': len(persist),
                'fade_count': len(fade),
                'persist_rate': len(persist) / len(premarket_tickers) * 100 if premarket_tickers else 0,
                'persist_tickers': list(persist)[:10],
                'fade_tickers': list(fade)[:10]
            })

    return premarket_signals


def analyze_scanner_migration(all_data, day_folders):
    """Track how tickers migrate across scanner types within a day."""
    migration_patterns = Counter()  # (from_scanner, to_scanner) -> count

    for day in day_folders:
        # Build timeline per ticker
        ticker_timeline = defaultdict(list)
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    ticker_timeline[ticker].append((ts, stype, rank))

        for ticker, timeline in ticker_timeline.items():
            timeline.sort(key=lambda x: x[0])
            # Find scanner transitions (deduplicated)
            prev_scanner = None
            for ts, stype, rank in timeline:
                if stype != prev_scanner and prev_scanner is not None:
                    migration_patterns[(prev_scanner, stype)] += 1
                prev_scanner = stype

    return migration_patterns


def analyze_rank_improvement(all_data, day_folders):
    """Find tickers with strong rank improvement within a day (momentum acceleration)."""
    accelerators = []

    for day in day_folders:
        ticker_ranks = defaultdict(list)
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            if stype not in GAIN_SCANNERS:
                continue
            for ts, tickers in records:
                for rank, ticker in tickers:
                    ticker_ranks[ticker].append((ts, rank))

        for ticker, rank_history in ticker_ranks.items():
            if len(rank_history) < 5:
                continue
            rank_history.sort()
            first_rank = rank_history[0][1]
            best_rank = min(r for _, r in rank_history)
            last_rank = rank_history[-1][1]
            improvement = first_rank - best_rank
            if improvement >= 10 and best_rank <= 5:
                accelerators.append({
                    'day': day, 'ticker': ticker,
                    'start_rank': first_rank, 'best_rank': best_rank,
                    'end_rank': last_rank, 'improvement': improvement,
                    'snapshots': len(rank_history)
                })

    accelerators.sort(key=lambda x: x['improvement'], reverse=True)
    return accelerators[:50]


def analyze_market_breadth(all_data, day_folders):
    """Daily breadth: unique tickers across all scanners per day."""
    breadth = []
    for day in day_folders:
        all_tickers = set()
        gain_tickers = set()
        loss_tickers = set()
        vol_tickers = set()
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    all_tickers.add(ticker)
                    if stype in GAIN_SCANNERS:
                        gain_tickers.add(ticker)
                    elif stype in LOSS_SCANNERS:
                        loss_tickers.add(ticker)
                    elif stype in VOLUME_SCANNERS:
                        vol_tickers.add(ticker)

        dt = datetime.strptime(day, "%Y%m%d")
        breadth.append({
            'day': day, 'dow': dt.strftime("%a"),
            'total': len(all_tickers),
            'gainers': len(gain_tickers),
            'losers': len(loss_tickers),
            'volume': len(vol_tickers),
            'gain_loss_ratio': len(gain_tickers) / max(len(loss_tickers), 1)
        })
    return breadth


def analyze_repeat_top_ranks(all_data, day_folders):
    """Tickers that consistently hold top-5 rank across multiple days."""
    top5_days = defaultdict(lambda: defaultdict(int))  # ticker -> scanner -> count of days in top 5

    for day in day_folders:
        day_top5 = defaultdict(set)
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            for ts, tickers in records:
                for rank, ticker in tickers:
                    if rank <= 4:  # top 5 (0-indexed)
                        day_top5[(ticker, stype)].add(day)

        for (ticker, stype), days in day_top5.items():
            pass  # built above

    # Rebuild properly
    top5_tracker = defaultdict(lambda: defaultdict(set))
    for day in day_folders:
        for scanner_key, records in all_data.get(day, {}).items():
            cap, stype = scanner_key.split('-', 1)
            tickers_in_top5 = set()
            for ts, tickers in records:
                for rank, ticker in tickers:
                    if rank <= 4:
                        tickers_in_top5.add(ticker)
            for ticker in tickers_in_top5:
                top5_tracker[ticker][stype].add(day)

    # Filter to tickers with 5+ days in top 5
    elite = []
    for ticker, scanner_days in top5_tracker.items():
        for stype, days in scanner_days.items():
            if len(days) >= 5:
                elite.append((ticker, stype, len(days), sorted(days)))
    elite.sort(key=lambda x: x[2], reverse=True)
    return elite[:50]


def generate_report(all_data, day_folders):
    """Generate the full analysis report."""
    print("\n=== Running Analysis ===\n")

    print("1/10 Ticker frequency...")
    top_tickers, ticker_stats = analyze_ticker_frequency(all_data, day_folders)

    print("2/10 Whipsaw detection...")
    whipsaw_events, whipsaw_counts = analyze_whipsaw_tickers(all_data, day_folders)

    print("3/10 Volume-leads-price signals...")
    vlp_signals = analyze_volume_leads_price(all_data, day_folders)

    print("4/10 Multi-day streaks...")
    streaks = analyze_multi_day_streaks(all_data, day_folders)

    print("5/10 Cap-size crossovers...")
    crossovers, crossover_counts = analyze_cap_crossover(all_data, day_folders)

    print("6/10 Day-of-week patterns...")
    dow_stats = analyze_day_of_week_patterns(all_data, day_folders)

    print("7/10 Pre-market analysis...")
    premarket = analyze_premarket_movers(all_data, day_folders)

    print("8/10 Scanner migration...")
    migrations = analyze_scanner_migration(all_data, day_folders)

    print("9/10 Rank acceleration...")
    accelerators = analyze_rank_improvement(all_data, day_folders)

    print("10/10 Market breadth & elite tickers...")
    breadth = analyze_market_breadth(all_data, day_folders)
    elite = analyze_repeat_top_ranks(all_data, day_folders)

    # Build report
    report = []
    report.append("# HVLF Scanner Pattern Analysis Report")
    report.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"**Data Range**: {day_folders[0]} to {day_folders[-1]} ({len(day_folders)} trading days)")
    report.append(f"**Scanners**: {len(CAP_SIZES)} cap sizes x {len(SCANNER_TYPES)} types = {len(CAP_SIZES)*len(SCANNER_TYPES)} scanner feeds")
    report.append("")

    # ===== EXECUTIVE SUMMARY =====
    report.append("---")
    report.append("## Executive Summary")
    report.append("")
    total_unique = len(ticker_stats)
    avg_breadth = sum(b['total'] for b in breadth) / len(breadth)
    total_whipsaws = len(whipsaw_events)
    total_vlp = len(vlp_signals)
    avg_vlp_lead = sum(s[4] for s in vlp_signals) / max(len(vlp_signals), 1)
    report.append(f"- **{total_unique:,}** unique tickers observed across {len(day_folders)} days")
    report.append(f"- **{avg_breadth:.0f}** average daily unique tickers (market breadth)")
    report.append(f"- **{total_whipsaws}** whipsaw events detected (gain+loss same day)")
    report.append(f"- **{total_vlp}** volume-leads-price signals ({avg_vlp_lead:.0f} min avg lead time)")
    report.append(f"- **{len(streaks)}** multi-day momentum streaks (3+ consecutive days)")
    report.append(f"- **{len(crossovers)}** cap-size crossover events")
    report.append("")

    # ===== 1. MOST PERSISTENT TICKERS =====
    report.append("---")
    report.append("## 1. Most Persistent Tickers (Institutional Favorites)")
    report.append("")
    report.append("Tickers appearing on scanners across the most trading days — these are the names that keep coming back.")
    report.append("")
    report.append("| Ticker | Days Seen | Total Scans | Scanner Types | Cap Sizes | Avg Rank | First Seen | Last Seen |")
    report.append("|--------|-----------|-------------|---------------|-----------|----------|------------|-----------|")
    for ticker, stats in top_tickers[:30]:
        avg_rank = sum(stats['ranks']) / len(stats['ranks']) if stats['ranks'] else 0
        report.append(f"| {ticker} | {len(stats['days'])} | {stats['total_appearances']:,} | {len(stats['scanners'])} | {', '.join(sorted(stats['cap_sizes']))} | {avg_rank:.1f} | {stats['first_seen']} | {stats['last_seen']} |")
    report.append("")

    report.append("**Trading Insight**: Tickers appearing 30+ days across multiple scanner types represent persistent institutional flow. ")
    report.append("These are NOT one-day runners — they have sustained interest. Consider these for swing trades with wider stops.")
    report.append("")

    # ===== 2. WHIPSAW DANGER ZONE =====
    report.append("---")
    report.append("## 2. Whipsaw Danger Zone (Gain + Loss Same Day)")
    report.append("")
    report.append("Tickers appearing on BOTH gain AND loss scanners on the same day — high reversal risk.")
    report.append("")
    top_whipsaws = whipsaw_counts.most_common(25)
    report.append("| Ticker | Whipsaw Days | Danger Level |")
    report.append("|--------|-------------|--------------|")
    for ticker, count in top_whipsaws:
        danger = "EXTREME" if count >= 10 else "HIGH" if count >= 5 else "MODERATE"
        report.append(f"| {ticker} | {count} | {danger} |")
    report.append("")

    report.append("**Trading Insight**: These tickers are unreliable directional plays. They gap up then reverse, or vice versa. ")
    report.append("Strategy: Either AVOID them for directional trades, or use them for mean-reversion/fade strategies with tight stops.")
    report.append("")

    # Sample whipsaw events
    report.append("### Recent Whipsaw Events")
    report.append("")
    recent_ws = [e for e in whipsaw_events if e[0] >= day_folders[-5]]
    for day, ticker, gains, losses in recent_ws[:15]:
        report.append(f"- **{day}** {ticker}: Gain scanners={gains} | Loss scanners={losses}")
    report.append("")

    # ===== 3. VOLUME LEADS PRICE (PREDICTIVE) =====
    report.append("---")
    report.append("## 3. Volume-Leads-Price Signals (Predictive)")
    report.append("")
    report.append("Tickers appearing on VOLUME scanners BEFORE appearing on GAIN scanners — early momentum detection.")
    report.append("")

    # Aggregate by ticker
    vlp_ticker_counts = Counter()
    vlp_ticker_leads = defaultdict(list)
    for day, ticker, vol_ts, gain_ts, lead_min in vlp_signals:
        vlp_ticker_counts[ticker] += 1
        vlp_ticker_leads[ticker].append(lead_min)

    report.append("### Top Predictable Tickers (Volume consistently leads price)")
    report.append("")
    report.append("| Ticker | Signal Count | Avg Lead (min) | Min Lead | Max Lead |")
    report.append("|--------|-------------|----------------|----------|----------|")
    for ticker, count in vlp_ticker_counts.most_common(25):
        leads = vlp_ticker_leads[ticker]
        report.append(f"| {ticker} | {count} | {sum(leads)/len(leads):.0f} | {min(leads):.0f} | {max(leads):.0f} |")
    report.append("")

    report.append("**Trading Insight**: When these tickers appear on HotByVolume/MostActive/TopVolumeRate, ")
    report.append("expect them on TopGainers/GainSinceOpen within the average lead time. This is your entry window.")
    report.append("")

    # Lead time distribution
    all_leads = [s[4] for s in vlp_signals]
    if all_leads:
        buckets = {"<5min": 0, "5-15min": 0, "15-30min": 0, "30-60min": 0, ">60min": 0}
        for lead in all_leads:
            if lead < 5: buckets["<5min"] += 1
            elif lead < 15: buckets["5-15min"] += 1
            elif lead < 30: buckets["15-30min"] += 1
            elif lead < 60: buckets["30-60min"] += 1
            else: buckets[">60min"] += 1
        report.append("### Lead Time Distribution")
        report.append("")
        for bucket, count in buckets.items():
            pct = count / len(all_leads) * 100
            bar = "#" * int(pct / 2)
            report.append(f"  {bucket:>10}: {bar} {count} ({pct:.0f}%)")
        report.append("")

    # ===== 4. MULTI-DAY MOMENTUM STREAKS =====
    report.append("---")
    report.append("## 4. Multi-Day Momentum Streaks")
    report.append("")
    report.append("Tickers appearing on the same scanner type for 3+ consecutive trading days — sustained momentum.")
    report.append("")
    report.append("| Ticker | Scanner | Streak Start | Streak End | Streak Days | Total Days on Scanner |")
    report.append("|--------|---------|-------------|-----------|-------------|----------------------|")
    for ticker, stype, start, end, slen, total in streaks[:30]:
        report.append(f"| {ticker} | {stype} | {start} | {end} | {slen} | {total} |")
    report.append("")

    report.append("**Trading Insight**: Streaks of 5+ days on gain scanners indicate strong institutional accumulation. ")
    report.append("Enter on day 2-3 of the streak with confirmation. Exit when streak breaks (ticker disappears from scanner).")
    report.append("")

    # Streak length distribution
    streak_lens = [s[4] for s in streaks]
    if streak_lens:
        report.append("### Streak Length Distribution")
        len_counts = Counter(streak_lens)
        for slen in sorted(len_counts.keys()):
            bar = "#" * min(len_counts[slen], 50)
            report.append(f"  {slen} days: {bar} ({len_counts[slen]})")
        report.append("")

    # ===== 5. CAP-SIZE CROSSOVER =====
    report.append("---")
    report.append("## 5. Cap-Size Crossover Patterns")
    report.append("")
    report.append("Tickers appearing across different cap-size scanners — indicates misclassification or rapid growth.")
    report.append("")
    top_crossovers = crossover_counts.most_common(25)
    report.append("| Ticker | Direction | Crossover Days |")
    report.append("|--------|-----------|---------------|")
    for (ticker, direction), count in top_crossovers:
        report.append(f"| {ticker} | {direction} | {count} |")
    report.append("")
    report.append("**Trading Insight**: Small->Large crossovers signal breakout growth. These are often low-float names ")
    report.append("getting promoted due to volume/price expansion. Watch for sustained crossover (3+ days) as a confirmation signal.")
    report.append("")

    # ===== 6. DAY-OF-WEEK SEASONALITY =====
    report.append("---")
    report.append("## 6. Day-of-Week Seasonality")
    report.append("")
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    report.append("| Day | Avg Unique Tickers | Days Sampled |")
    report.append("|-----|-------------------|--------------|")
    for dow in dow_order:
        if dow in dow_stats:
            tickers_list = dow_stats[dow]['unique_tickers']
            avg = sum(tickers_list) / len(tickers_list) if tickers_list else 0
            report.append(f"| {dow} | {avg:.0f} | {len(tickers_list)} |")
    report.append("")
    report.append("**Trading Insight**: Days with higher average unique tickers indicate broader participation and more opportunities. ")
    report.append("Lower breadth days tend to favor focused momentum in fewer names — concentrate capital on those days.")
    report.append("")

    # ===== 7. PRE-MARKET vs REGULAR HOURS =====
    report.append("---")
    report.append("## 7. Pre-Market Movers: Persist or Fade?")
    report.append("")
    if premarket:
        avg_persist = sum(p['persist_rate'] for p in premarket) / len(premarket)
        report.append(f"**Overall pre-market persistence rate**: {avg_persist:.1f}% of pre-market movers continue into regular hours")
        report.append("")
        report.append("| Day | Pre-Market | Persisted | Faded | Persist Rate |")
        report.append("|-----|-----------|-----------|-------|-------------|")
        for p in premarket[-15:]:
            report.append(f"| {p['day']} | {p['premarket_count']} | {p['persist_count']} | {p['fade_count']} | {p['persist_rate']:.0f}% |")
        report.append("")
        report.append("**Trading Insight**: Pre-market names that persist into regular hours have validated momentum. ")
        report.append("Those that fade are traps — avoid chasing pre-market gaps without regular-session confirmation.")
        report.append("")

        # Most persistent pre-market tickers
        persist_counter = Counter()
        for p in premarket:
            for t in p['persist_tickers']:
                persist_counter[t] += 1
        report.append("### Most Reliable Pre-Market Persisters")
        report.append("")
        for ticker, count in persist_counter.most_common(15):
            report.append(f"- **{ticker}**: persisted {count} days")
        report.append("")

    # ===== 8. SCANNER MIGRATION FLOWS =====
    report.append("---")
    report.append("## 8. Scanner Migration Flows (Intra-Day Lifecycle)")
    report.append("")
    report.append("How tickers flow between scanner types within a day — reveals the lifecycle of a mover.")
    report.append("")
    top_migrations = migrations.most_common(20)
    report.append("| From Scanner | To Scanner | Transitions |")
    report.append("|-------------|-----------|-------------|")
    for (from_s, to_s), count in top_migrations:
        report.append(f"| {from_s} | {to_s} | {count:,} |")
    report.append("")
    report.append("**Trading Insight**: The most common migration path reveals the typical mover lifecycle:")
    report.append("1. Volume scanner first (accumulation phase)")
    report.append("2. Price scanner next (breakout phase)")
    report.append("3. Gain scanner (trend phase)")
    report.append("4. Loss scanner (reversal/profit-taking)")
    report.append("")
    report.append("Enter during phase 1-2, ride through phase 3, exit before phase 4.")
    report.append("")

    # ===== 9. RANK ACCELERATORS =====
    report.append("---")
    report.append("## 9. Rank Accelerators (Fastest Movers)")
    report.append("")
    report.append("Tickers that climb 10+ ranks to reach top-5 within a single day on gain scanners.")
    report.append("")
    report.append("| Day | Ticker | Start Rank | Best Rank | End Rank | Improvement | Snapshots |")
    report.append("|-----|--------|-----------|-----------|----------|-------------|-----------|")
    for a in accelerators[:25]:
        report.append(f"| {a['day']} | {a['ticker']} | {a['start_rank']} | {a['best_rank']} | {a['end_rank']} | +{a['improvement']} | {a['snapshots']} |")
    report.append("")

    # Track which tickers are repeat accelerators
    accel_counts = Counter(a['ticker'] for a in accelerators)
    repeat_accels = [(t, c) for t, c in accel_counts.most_common(15) if c >= 2]
    if repeat_accels:
        report.append("### Repeat Accelerators (multiple acceleration days)")
        report.append("")
        for ticker, count in repeat_accels:
            report.append(f"- **{ticker}**: {count} acceleration events")
        report.append("")
    report.append("**Trading Insight**: Rank accelerators are the day's big movers. Repeat accelerators are names that ")
    report.append("consistently attract aggressive buying. Build a watchlist of repeat accelerators for gap-and-go setups.")
    report.append("")

    # ===== 10. MARKET BREADTH TRENDS =====
    report.append("---")
    report.append("## 10. Market Breadth Trends")
    report.append("")
    report.append("Daily unique tickers and gain/loss ratios — market regime indicator.")
    report.append("")
    report.append("| Day | DOW | Total | Gainers | Losers | Volume | G/L Ratio |")
    report.append("|-----|-----|-------|---------|--------|--------|-----------|")
    for b in breadth[-20:]:
        gl_indicator = "BULL" if b['gain_loss_ratio'] > 1.2 else "BEAR" if b['gain_loss_ratio'] < 0.8 else "NEUTRAL"
        report.append(f"| {b['day']} | {b['dow']} | {b['total']} | {b['gainers']} | {b['losers']} | {b['volume']} | {b['gain_loss_ratio']:.2f} ({gl_indicator}) |")
    report.append("")

    # Breadth trends
    if len(breadth) >= 10:
        recent_breadth = breadth[-10:]
        older_breadth = breadth[-20:-10] if len(breadth) >= 20 else breadth[:10]
        recent_avg = sum(b['total'] for b in recent_breadth) / len(recent_breadth)
        older_avg = sum(b['total'] for b in older_breadth) / len(older_breadth)
        trend = "EXPANDING" if recent_avg > older_avg * 1.05 else "CONTRACTING" if recent_avg < older_avg * 0.95 else "STABLE"
        report.append(f"**Breadth Trend**: {trend} (Recent 10d avg: {recent_avg:.0f} vs Prior 10d avg: {older_avg:.0f})")
        report.append("")

    report.append("**Trading Insight**: Expanding breadth = more opportunities, use wider scanning. ")
    report.append("Contracting breadth = fewer movers, concentrate on top-ranked names only.")
    report.append("")

    # ===== 11. ELITE TOP-5 HOLDERS =====
    report.append("---")
    report.append("## 11. Elite Top-5 Holders")
    report.append("")
    report.append("Tickers holding top-5 rank on a scanner for 5+ trading days — dominant names.")
    report.append("")
    report.append("| Ticker | Scanner | Days in Top 5 |")
    report.append("|--------|---------|--------------|")
    for ticker, stype, count, days in elite[:30]:
        report.append(f"| {ticker} | {stype} | {count} |")
    report.append("")
    report.append("**Trading Insight**: Elite holders are the market's strongest names in their category. ")
    report.append("For gain scanners: these are accumulation targets. For volume scanners: these have sustained institutional interest. ")
    report.append("For loss scanners: these are persistent shorts/decliners — potential short-squeeze or avoid candidates.")
    report.append("")

    # ===== 12. ACTIONABLE STRATEGIES =====
    report.append("---")
    report.append("## 12. Actionable Trading Strategies Derived from Data")
    report.append("")

    report.append("### Strategy 1: Volume Surge Entry")
    report.append("- **Signal**: Ticker appears on HotByVolume/MostActive but NOT yet on TopGainers/GainSinceOpen")
    report.append(f"- **Avg lead time**: {avg_vlp_lead:.0f} minutes before price move")
    report.append(f"- **Signal frequency**: {total_vlp} events across {len(day_folders)} days ({total_vlp/len(day_folders):.0f}/day)")
    report.append("- **Entry**: Buy when ticker first appears on volume scanner")
    report.append("- **Target**: Hold until ticker appears on gain scanner (avg lead time)")
    report.append("- **Stop**: Exit if ticker appears on loss scanner or drops off volume scanner within 15 min")
    report.append("")

    report.append("### Strategy 2: Streak Continuation")
    report.append("- **Signal**: Ticker on same gain scanner for 2+ consecutive days")
    avg_streak = sum(s[4] for s in streaks) / max(len(streaks), 1)
    report.append(f"- **Average streak length**: {avg_streak:.1f} days")
    report.append("- **Entry**: Buy on day 2-3 of streak with increasing rank")
    report.append("- **Target**: Hold until streak breaks or rank deteriorates >10 positions")
    report.append("- **Stop**: Exit same day if ticker appears on loss scanner")
    report.append("")

    report.append("### Strategy 3: Whipsaw Fade")
    report.append("- **Signal**: Known whipsaw ticker (5+ whipsaw days) appears on TopGainers")
    report.append(f"- **Universe**: {sum(1 for t,c in whipsaw_counts.most_common() if c >= 5)} tickers with 5+ whipsaw days")
    report.append("- **Entry**: Short/fade at open when ticker gaps up (or buy puts)")
    report.append("- **Target**: Mean reversion to prior close")
    report.append("- **Stop**: New high of day +2%")
    report.append("")

    report.append("### Strategy 4: Pre-Market Persistence Filter")
    if premarket:
        report.append(f"- **Signal**: Ticker on scanners pre-market AND persists into regular hours ({avg_persist:.0f}% persist rate)")
    report.append("- **Entry**: Buy at 9:35 if ticker still on gain scanner after open")
    report.append("- **Filter**: SKIP if ticker is known whipsaw name")
    report.append("- **Target**: Ride momentum for 30-60 minutes")
    report.append("- **Stop**: Below VWAP or drops off scanner")
    report.append("")

    report.append("### Strategy 5: Cap-Size Breakout")
    report.append(f"- **Signal**: Ticker crosses from SmallCap to MidCap/LargeCap scanners ({len(crossovers)} events)")
    report.append("- **Thesis**: Small-cap graduating to larger scanners = explosive growth phase")
    report.append("- **Entry**: Buy on first day of crossover with volume confirmation")
    report.append("- **Target**: Multi-day hold (these often run for a week+)")
    report.append("- **Stop**: Return to only SmallCap scanners")
    report.append("")

    report.append("### Strategy 6: Elite Accumulation")
    report.append("- **Signal**: Ticker in top-5 on gain scanner for 3+ consecutive days")
    report.append(f"- **Universe**: {len([e for e in elite if e[2] >= 5])} elite tickers identified")
    report.append("- **Entry**: Buy pullback to day's VWAP on day 3+")
    report.append("- **Target**: New multi-day high")
    report.append("- **Stop**: Close below prior day's low")
    report.append("")

    # ===== APPENDIX =====
    report.append("---")
    report.append("## Appendix: Data Summary")
    report.append("")
    report.append(f"- Data period: {day_folders[0]} to {day_folders[-1]}")
    report.append(f"- Trading days analyzed: {len(day_folders)}")
    report.append(f"- Total unique tickers: {total_unique:,}")
    report.append(f"- Scanner types: {', '.join(SCANNER_TYPES)}")
    report.append(f"- Cap sizes: {', '.join(CAP_SIZES)}")
    report.append(f"- Total scanner feeds per day: {len(CAP_SIZES) * len(SCANNER_TYPES)}")
    report.append("")

    return "\n".join(report)


if __name__ == "__main__":
    all_data, day_folders = load_all_data()
    report = generate_report(all_data, day_folders)

    output_path = os.path.join(os.path.dirname(__file__), "scanner_pattern_report.md")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\nReport written to: {output_path}")
    print(f"Report size: {len(report):,} characters")
