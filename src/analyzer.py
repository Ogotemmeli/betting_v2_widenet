"""
Motore di analisi v2.0: Multi-sport, soglie per sport, filtro outlier,
diversificazione portafoglio, decorrelazione.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import (
    REPORTS_DIR, HISTORY_FILE,
    DEFAULT_BANKROLL, KELLY_FRACTION, MAX_STAKE_PCT,
    MAX_SINGLE_ODDS_DEVIATION_PCT, CORRELATED_MARKETS,
    MAX_SPORT_EXPOSURE_PCT, MAX_LEAGUE_EXPOSURE_PCT, MAX_CONCURRENT_BETS,
    get_thresholds, get_enabled_sports
)


# ════════════════════════════════════════════════════════════════════
#  FILTRI QUALITÀ
# ════════════════════════════════════════════════════════════════════

def is_odds_outlier(odds_value: float, all_odds: list[float]) -> bool:
    """
    Verifica se una quota è un outlier rispetto alle altre.
    Un outlier è probabilmente una quota stale non ancora aggiornata.
    """
    if len(all_odds) < 3:
        return False
    sorted_odds = sorted(all_odds)
    median = sorted_odds[len(sorted_odds) // 2]
    if median == 0:
        return False
    deviation = abs(odds_value - median) / median * 100
    return deviation > MAX_SINGLE_ODDS_DEVIATION_PCT


# ════════════════════════════════════════════════════════════════════
#  ARBITRAGGIO
# ════════════════════════════════════════════════════════════════════

def find_arbitrage(event: dict) -> dict | None:
    """Cerca arbitraggi con soglie sport-specific e filtro outlier."""
    sport = event.get("sport_category", "soccer")
    thresholds = get_thresholds(sport)
    bookmakers = event["bookmakers"]

    if len(bookmakers) < thresholds["min_bookmakers"]:
        return None

    all_outcomes = set()
    for bk in bookmakers:
        all_outcomes.update(bk["outcomes"].keys())

    if len(all_outcomes) < 2:
        return None

    # Per ogni esito, raccogli tutte le quote e trova la migliore
    best_odds = {}
    for outcome in all_outcomes:
        all_odds_for_outcome = []
        for bk in bookmakers:
            odd = bk["outcomes"].get(outcome)
            if odd and odd > 1.0:
                all_odds_for_outcome.append(odd)

        # Trova la migliore, ma verifica che non sia un outlier
        best = None
        for bk in bookmakers:
            odd = bk["outcomes"].get(outcome)
            if not odd or odd <= 1.0:
                continue
            # Filtro outlier
            if is_odds_outlier(odd, all_odds_for_outcome):
                continue
            if best is None or odd > best["odds"]:
                best = {"odds": odd, "bookmaker": bk["title"], "key": bk["bookmaker"]}

        if best:
            best_odds[outcome] = best

    if len(best_odds) < len(all_outcomes):
        return None

    implied_sum = sum(1.0 / v["odds"] for v in best_odds.values())

    if implied_sum >= 1.0:
        return None

    margin_pct = (1.0 - implied_sum) * 100

    if margin_pct < thresholds["min_arb_margin"]:
        return None
    if margin_pct > thresholds["max_arb_margin"]:
        return None  # Probabile errore

    stakes = {}
    for outcome, data in best_odds.items():
        stake_fraction = (1.0 / data["odds"]) / implied_sum
        stakes[outcome] = {
            "bookmaker": data["bookmaker"],
            "odds": data["odds"],
            "stake_pct": round(stake_fraction * 100, 2),
            "stake_amount": round(stake_fraction * DEFAULT_BANKROLL, 2)
        }

    return {
        "type": "ARBITRAGE",
        "event_id": event["id"],
        "sport": sport,
        "league": event["league"],
        "match": f"{event['home_team']} vs {event['away_team']}",
        "commence": event["commence_time"],
        "market": event["market"],
        "margin_pct": round(margin_pct, 3),
        "implied_probability_sum": round(implied_sum, 5),
        "guaranteed_profit": round(margin_pct / 100 * DEFAULT_BANKROLL, 2),
        "stakes": stakes,
        "num_bookmakers_checked": len(bookmakers),
        "fresh_bookmakers": event.get("fresh_bookmakers", 0),
        "found_at": datetime.now(timezone.utc).isoformat()
    }


# ════════════════════════════════════════════════════════════════════
#  VALUE BET
# ════════════════════════════════════════════════════════════════════

def find_value_bets(event: dict) -> list[dict]:
    """Value bet con soglie sport-specific e filtro outlier."""
    sport = event.get("sport_category", "soccer")
    thresholds = get_thresholds(sport)
    bookmakers = event["bookmakers"]

    if len(bookmakers) < thresholds["min_bookmakers"]:
        return []

    all_outcomes = set()
    for bk in bookmakers:
        all_outcomes.update(bk["outcomes"].keys())

    # Overround medio per normalizzazione
    total_implied_per_bk = []
    for bk in bookmakers:
        total = sum(1.0 / o for o in bk["outcomes"].values() if o > 1.0)
        if total > 0:
            total_implied_per_bk.append(total)

    if not total_implied_per_bk:
        return []

    avg_overround = sum(total_implied_per_bk) / len(total_implied_per_bk)

    value_bets = []
    for outcome in all_outcomes:
        # Raccogli quote per questo esito (per outlier detection)
        all_odds_for_outcome = []
        implied_probs = []
        for bk in bookmakers:
            odd = bk["outcomes"].get(outcome)
            if odd and odd > 1.0:
                all_odds_for_outcome.append(odd)
                implied_probs.append(1.0 / odd)

        if len(implied_probs) < thresholds["min_bookmakers"]:
            continue

        avg_implied = sum(implied_probs) / len(implied_probs)
        true_prob = avg_implied / avg_overround
        fair_odds = 1.0 / true_prob if true_prob > 0 else 999

        for bk in bookmakers:
            odd = bk["outcomes"].get(outcome)
            if not odd:
                continue
            if odd < thresholds["min_odds"] or odd > thresholds["max_odds"]:
                continue
            # Scarta outlier
            if is_odds_outlier(odd, all_odds_for_outcome):
                continue

            implied_prob = 1.0 / odd
            edge = (true_prob - implied_prob) / implied_prob * 100

            if edge >= thresholds["min_value_edge"]:
                kelly_full = (true_prob * odd - 1) / (odd - 1)
                kelly_stake = max(0, kelly_full * KELLY_FRACTION)
                kelly_stake = min(kelly_stake, MAX_STAKE_PCT / 100)

                value_bets.append({
                    "type": "VALUE_BET",
                    "event_id": event["id"],
                    "sport": sport,
                    "league": event["league"],
                    "match": f"{event['home_team']} vs {event['away_team']}",
                    "commence": event["commence_time"],
                    "market": event["market"],
                    "outcome": outcome,
                    "bookmaker": bk["title"],
                    "odds": odd,
                    "fair_odds": round(fair_odds, 3),
                    "true_prob_pct": round(true_prob * 100, 2),
                    "implied_prob_pct": round(implied_prob * 100, 2),
                    "edge_pct": round(edge, 2),
                    "kelly_stake_pct": round(kelly_stake * 100, 2),
                    "suggested_stake": round(kelly_stake * DEFAULT_BANKROLL, 2),
                    "expected_value": round((true_prob * odd - 1) * 100, 2),
                    "confidence": classify_confidence(
                        edge, len(bookmakers), thresholds["min_value_edge"]
                    ),
                    "found_at": datetime.now(timezone.utc).isoformat()
                })

    return value_bets


def classify_confidence(edge: float, num_bookmakers: int,
                        min_edge: float) -> str:
    """Confidenza relativa alla soglia dello sport."""
    score = 0
    if edge >= min_edge * 2.5:
        score += 3
    elif edge >= min_edge * 1.5:
        score += 2
    else:
        score += 1

    if num_bookmakers >= 8:
        score += 2
    elif num_bookmakers >= 5:
        score += 1

    if score >= 4:
        return "ALTA"
    elif score >= 3:
        return "MEDIA"
    return "BASSA"


# ════════════════════════════════════════════════════════════════════
#  DIVERSIFICAZIONE PORTAFOGLIO
# ════════════════════════════════════════════════════════════════════

def filter_correlated(bets: list[dict]) -> list[dict]:
    """
    Rimuove bet correlate sullo stesso evento.
    Se su un evento ci sono bet su mercati correlati (es: h2h + spreads),
    tiene solo quella con edge migliore.
    """
    # Raggruppa per evento
    by_event = {}
    for bet in bets:
        key = bet["event_id"]
        by_event.setdefault(key, []).append(bet)

    filtered = []
    for event_id, event_bets in by_event.items():
        markets_used = set()
        # Ordina per edge decrescente
        sorted_bets = sorted(event_bets, key=lambda x: x.get("edge_pct", 0),
                             reverse=True)

        for bet in sorted_bets:
            market = bet["market"]
            # Controlla se un mercato correlato è già stato preso
            is_correlated = False
            for m1, m2 in CORRELATED_MARKETS:
                if (market == m1 and m2 in markets_used) or \
                   (market == m2 and m1 in markets_used):
                    is_correlated = True
                    break

            if not is_correlated:
                filtered.append(bet)
                markets_used.add(market)

    return filtered


def apply_portfolio_limits(bets: list[dict]) -> list[dict]:
    """
    Applica limiti di esposizione per sport e lega.
    Restituisce le bet entro i limiti, ordinate per edge.
    """
    if not bets:
        return []

    enabled = get_enabled_sports()
    sorted_bets = sorted(bets, key=lambda x: x.get("edge_pct", 0),
                         reverse=True)

    selected = []
    sport_stake = {}
    league_stake = {}
    total_stake = 0
    max_sport_stake = DEFAULT_BANKROLL * MAX_SPORT_EXPOSURE_PCT / 100
    max_league_stake = DEFAULT_BANKROLL * MAX_LEAGUE_EXPOSURE_PCT / 100

    for bet in sorted_bets:
        if len(selected) >= MAX_CONCURRENT_BETS:
            break

        sport = bet.get("sport", "unknown")
        league = bet.get("league", "unknown")
        stake = bet.get("suggested_stake", 0)

        cur_sport = sport_stake.get(sport, 0)
        cur_league = league_stake.get(league, 0)

        if cur_sport + stake > max_sport_stake:
            continue
        if cur_league + stake > max_league_stake:
            continue

        selected.append(bet)
        sport_stake[sport] = cur_sport + stake
        league_stake[league] = cur_league + stake
        total_stake += stake

    return selected


# ════════════════════════════════════════════════════════════════════
#  REPORT
# ════════════════════════════════════════════════════════════════════

def generate_report(arbitrages: list, value_bets: list, timestamp: str,
                    metadata: dict = None):
    """Genera report Markdown + CSV storico + summary JSON."""
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    enabled = get_enabled_sports()

    report_path = os.path.join(REPORTS_DIR, "latest_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 🏟️ Report Analisi Multi-Sport\n")
        f.write(f"**Generato:** {timestamp}\n\n")
        f.write(f"**Bankroll:** €{DEFAULT_BANKROLL:.0f} | ")
        f.write(f"**Sport:** {', '.join(s['display_name'] for s in enabled.values())}\n\n")

        if metadata:
            f.write(f"**Dati:** {metadata.get('total_events', '?')} record da "
                    f"{metadata.get('leagues_active', '?')} leghe attive | "
                    f"API calls: {metadata.get('api_calls_used', '?')}\n\n")

        # ── Statistiche per sport ──
        f.write("---\n## 📊 Riepilogo per sport\n\n")
        f.write("| Sport | Arbitraggi | Value bet | Miglior margine |\n")
        f.write("|-------|-----------|-----------|----------------|\n")
        for sport_key, sport_cfg in enabled.items():
            arbs_sport = [a for a in arbitrages if a.get("sport") == sport_key]
            vbs_sport = [v for v in value_bets if v.get("sport") == sport_key]
            best = max((a["margin_pct"] for a in arbs_sport), default=0)
            best_v = max((v["edge_pct"] for v in vbs_sport), default=0)
            best_str = f"{best:.2f}% arb" if best > 0 else (
                f"{best_v:.1f}% edge" if best_v > 0 else "—")
            f.write(f"| {sport_cfg['display_name']} | {len(arbs_sport)} | "
                    f"{len(vbs_sport)} | {best_str} |\n")
        f.write("\n")

        # ── Arbitraggi ──
        f.write("---\n## 🎯 Arbitraggi (Sure Bet)\n\n")
        if arbitrages:
            arbitrages.sort(key=lambda x: x["margin_pct"], reverse=True)
            for i, arb in enumerate(arbitrages, 1):
                sport_name = enabled.get(arb.get("sport", ""), {}).get(
                    "display_name", arb.get("sport", ""))
                f.write(f"### #{i} — {arb['match']}\n")
                f.write(f"- **Sport:** {sport_name} | **Lega:** {arb['league']}\n")
                f.write(f"- **Mercato:** {arb['market']} | "
                        f"**Inizio:** {arb['commence']}\n")
                f.write(f"- **Margine:** {arb['margin_pct']:.2f}% "
                        f"(€{arb['guaranteed_profit']:.2f} su €{DEFAULT_BANKROLL:.0f})\n")
                f.write(f"- **Book freschi:** {arb.get('fresh_bookmakers', '?')}\n\n")
                f.write("| Esito | Bookmaker | Quota | Stake % | Stake € |\n")
                f.write("|-------|-----------|-------|---------|---------|\n")
                for outcome, data in arb["stakes"].items():
                    f.write(f"| {outcome} | {data['bookmaker']} | "
                            f"{data['odds']:.2f} | {data['stake_pct']:.1f}% | "
                            f"€{data['stake_amount']:.2f} |\n")
                f.write("\n")
        else:
            f.write("_Nessun arbitraggio trovato. Normale — sono rari e brevi._\n\n")

        # ── Value Bet ──
        f.write("---\n## 📈 Value Bet (con diversificazione)\n\n")
        if value_bets:
            value_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
            f.write("| # | Sport | Match | Esito | Book | Quota | Edge% | "
                    "Conf | Stake |\n")
            f.write("|---|-------|-------|-------|------|-------|-------|"
                    "-----|-------|\n")
            conf_emoji = {"ALTA": "🟢", "MEDIA": "🟡", "BASSA": "🔴"}
            for i, vb in enumerate(value_bets[:40], 1):
                sport_name = enabled.get(vb.get("sport", ""), {}).get(
                    "display_name", "?")[:6]
                emoji = conf_emoji.get(vb["confidence"], "⚪")
                f.write(
                    f"| {i} | {sport_name} | {vb['match'][:25]} | "
                    f"{vb['outcome'][:15]} | {vb['bookmaker'][:12]} | "
                    f"{vb['odds']:.2f} | {vb['edge_pct']:.1f}% | "
                    f"{emoji} | €{vb['suggested_stake']:.0f} |\n"
                )
            f.write(f"\n_Top {min(40, len(value_bets))} "
                    f"su {len(value_bets)} (filtrate per correlazione e limiti)._\n\n")
        else:
            f.write("_Nessuna value bet sopra soglia._\n\n")

        # ── Diversificazione ──
        if value_bets:
            f.write("---\n## 🔄 Diversificazione portafoglio\n\n")
            by_sport = {}
            for vb in value_bets:
                s = vb.get("sport", "?")
                by_sport.setdefault(s, 0)
                by_sport[s] += vb.get("suggested_stake", 0)
            total = sum(by_sport.values())
            if total > 0:
                for s, amt in sorted(by_sport.items(),
                                     key=lambda x: x[1], reverse=True):
                    pct = amt / total * 100
                    name = enabled.get(s, {}).get("display_name", s)
                    bar = "█" * int(pct / 3) + "░" * (33 - int(pct / 3))
                    f.write(f"- **{name}**: {bar} {pct:.0f}% (€{amt:.0f})\n")
                f.write("\n")

        # ── Disclaimer ──
        f.write("---\n## ⚠️ Disclaimer\n\n")
        f.write("Strumento di analisi statistica. **NON garantisce profitti.** "
                "Gioca responsabilmente.\n")

    print(f"📄 Report: {report_path}")

    # ── CSV storico ──
    history_rows = []
    for arb in arbitrages:
        history_rows.append({
            "timestamp": timestamp, "type": "ARBITRAGE", "sport": arb.get("sport"),
            "match": arb["match"], "league": arb["league"], "market": arb["market"],
            "edge_pct": arb["margin_pct"], "confidence": "SURE",
            "suggested_stake": arb["guaranteed_profit"],
            "details": json.dumps(arb["stakes"], ensure_ascii=False)
        })
    for vb in value_bets:
        history_rows.append({
            "timestamp": timestamp, "type": "VALUE_BET", "sport": vb.get("sport"),
            "match": vb["match"], "league": vb["league"], "market": vb["market"],
            "edge_pct": vb["edge_pct"], "confidence": vb["confidence"],
            "suggested_stake": vb["suggested_stake"],
            "details": f"{vb['outcome']}@{vb['odds']} ({vb['bookmaker']})"
        })

    if history_rows:
        file_exists = os.path.exists(HISTORY_FILE)
        with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as csvf:
            writer = csv.DictWriter(csvf, fieldnames=history_rows[0].keys())
            if not file_exists:
                writer.writeheader()
            writer.writerows(history_rows)
        print(f"📊 Storico: +{len(history_rows)} righe")

    # ── Summary JSON ──
    summary = {
        "timestamp": timestamp,
        "arbitrages_found": len(arbitrages),
        "value_bets_found": len(value_bets),
        "by_sport": {
            k: {
                "arbs": len([a for a in arbitrages if a.get("sport") == k]),
                "vbs": len([v for v in value_bets if v.get("sport") == k]),
            }
            for k in enabled
        },
        "best_arb_margin": max((a["margin_pct"] for a in arbitrages), default=0),
        "best_value_edge": max((v["edge_pct"] for v in value_bets), default=0),
        "arbitrages": arbitrages[:5],
        "value_bets": [vb for vb in value_bets
                       if vb.get("confidence") in ("ALTA", "MEDIA")][:10]
    }
    with open(os.path.join(REPORTS_DIR, "latest_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


# ════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════

def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    odds_path = os.path.join(REPORTS_DIR, "latest_odds.json")
    if not os.path.exists(odds_path):
        print("❌ Nessun dato. Esegui lo scraper prima.")
        sys.exit(1)

    with open(odds_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data["events"]
    metadata = {k: v for k, v in data.items() if k != "events"}
    enabled = get_enabled_sports()

    print(f"\n{'='*60}")
    print(f"📊 ANALISI MULTI-SPORT — {timestamp}")
    print(f"{'='*60}")
    print(f"Record da analizzare: {len(events)}")
    for k, v in enabled.items():
        count = len([e for e in events if e.get("sport_category") == k])
        print(f"  {v['display_name']:15s} {count:4d}")
    print()

    # ── Analisi ──
    all_arbs = []
    all_values_raw = []

    for event in events:
        arb = find_arbitrage(event)
        if arb:
            all_arbs.append(arb)

        values = find_value_bets(event)
        all_values_raw.extend(values)

    print(f"Risultati grezzi:")
    print(f"  🎯 Arbitraggi:   {len(all_arbs)}")
    print(f"  📈 Value bet:    {len(all_values_raw)}")

    # ── Filtri post-analisi ──
    # 1. Rimuovi value bet correlate sullo stesso evento
    values_decorrelated = filter_correlated(all_values_raw)
    print(f"  → Dopo decorrelazione: {len(values_decorrelated)}")

    # 2. Applica limiti di portafoglio
    values_final = apply_portfolio_limits(values_decorrelated)
    print(f"  → Dopo limiti portafoglio: {len(values_final)}")

    if all_arbs:
        best = max(all_arbs, key=lambda x: x["margin_pct"])
        sport_name = enabled.get(best.get("sport", ""), {}).get(
            "display_name", "?")
        print(f"\n  ⭐ Miglior arb: {best['margin_pct']:.2f}% — "
              f"{best['match']} ({sport_name})")

    if values_final:
        best_v = max(values_final, key=lambda x: x["edge_pct"])
        sport_name = enabled.get(best_v.get("sport", ""), {}).get(
            "display_name", "?")
        print(f"  ⭐ Miglior value: {best_v['edge_pct']:.1f}% — "
              f"{best_v['match']} ({sport_name})")

    summary = generate_report(all_arbs, values_final, timestamp, metadata)

    print(f"\n✅ Analisi completata.")
    return summary


if __name__ == "__main__":
    main()
