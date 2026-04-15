"""
Scraper quote multi-sport da The Odds API.
v2.0 — Supporta calcio, tennis, basket, hockey con ottimizzazione budget API.

Strategia budget:
  - Aggrega più mercati in una singola chiamata (markets=h2h,totals,spreads)
  - Calcola automaticamente quanti cicli/giorno permettersi
  - Salta leghe fuori stagione (nessun evento = nessuna chiamata sprecata)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from config import (
    ODDS_API_KEY, ODDS_API_BASE, REGIONS, ODDS_FORMAT,
    REPORTS_DIR, MAX_ODDS_AGE_SECONDS,
    get_enabled_sports, estimate_api_calls_per_cycle, recommend_cycles_per_day
)


def fetch_odds(sport_key: str, markets: list[str]) -> list[dict] | None:
    """
    Recupera quote per uno sport/lega.
    Aggrega tutti i mercati in UNA singola chiamata API.
    """
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ",".join(REGIONS),
        "markets": ",".join(markets),  # Aggregati = 1 sola richiesta
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)

        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"    API: {used} usate, {remaining} rimanenti")

        if resp.status_code == 401:
            print("❌ API key non valida.")
            sys.exit(1)
        if resp.status_code == 429:
            print("⚠️  Rate limit. Attendo 60s...")
            time.sleep(60)
            return fetch_odds(sport_key, markets)
        if resp.status_code == 404:
            # Lega non attiva/fuori stagione
            print("    ⏸️  Lega non attiva, skip")
            return None

        resp.raise_for_status()
        data = resp.json()
        return data if data else None

    except requests.RequestException as e:
        print(f"    ⚠️  Errore: {e}")
        return None


def is_odds_fresh(last_update: str) -> bool:
    """Verifica che la quota non sia stale (> MAX_ODDS_AGE_SECONDS)."""
    if not last_update:
        return False
    try:
        update_time = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - update_time).total_seconds()
        return age <= MAX_ODDS_AGE_SECONDS
    except (ValueError, TypeError):
        return False


def normalize_events(raw_events: list[dict], sport_category: str,
                     markets: list[str]) -> list[dict]:
    """
    Normalizza gli eventi grezzi in formato uniforme per l'analyzer.
    Ogni combinazione evento×mercato diventa un record separato.
    Filtra quote stale.
    """
    normalized = []

    for event in raw_events:
        for market in markets:
            bookmakers_data = []
            fresh_count = 0
            stale_count = 0

            for bk in event.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt["key"] != market:
                        continue

                    # Filtro freshness
                    if is_odds_fresh(bk.get("last_update", "")):
                        fresh_count += 1
                    else:
                        stale_count += 1
                        continue  # Scarta quote vecchie

                    outcomes = {}
                    for outcome in mkt["outcomes"]:
                        label = outcome["name"]
                        if market == "totals":
                            label = f"{outcome['name']} {outcome.get('point', '')}"
                        elif market == "spreads":
                            label = f"{outcome['name']} ({outcome.get('point', '')})"
                        outcomes[label] = outcome["price"]

                    bookmakers_data.append({
                        "bookmaker": bk["key"],
                        "title": bk["title"],
                        "last_update": bk.get("last_update", ""),
                        "outcomes": outcomes,
                    })

            if bookmakers_data:
                normalized.append({
                    "id": event["id"],
                    "sport": event["sport_key"],
                    "sport_category": sport_category,
                    "league": event.get("sport_title", event["sport_key"]),
                    "home_team": event["home_team"],
                    "away_team": event["away_team"],
                    "commence_time": event["commence_time"],
                    "market": market,
                    "bookmakers": bookmakers_data,
                    "fresh_bookmakers": fresh_count,
                    "stale_filtered": stale_count,
                })

    return normalized


def scrape_all() -> list[dict]:
    """Scraping completo di tutti gli sport e leghe configurati."""
    all_events = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    enabled = get_enabled_sports()

    calls_per_cycle = estimate_api_calls_per_cycle()
    recommended_cycles = recommend_cycles_per_day()

    print("=" * 60)
    print(f"🔍 SCRAPING MULTI-SPORT — {timestamp}")
    print(f"=" * 60)
    print(f"Sport attivi: {', '.join(s['display_name'] for s in enabled.values())}")
    print(f"Chiamate API stimate: {calls_per_cycle} per ciclo")
    print(f"Cicli/giorno consigliati: {recommended_cycles}")
    print()

    api_calls = 0
    leagues_active = 0
    leagues_inactive = 0

    for sport_key, sport_cfg in enabled.items():
        display = sport_cfg["display_name"]
        markets = sport_cfg["markets"]
        print(f"{'─'*40}")
        print(f"🏟️  {display} ({len(sport_cfg['leagues'])} leghe, "
              f"mercati: {', '.join(markets)})")

        for league in sport_cfg["leagues"]:
            print(f"  📡 {league}")
            raw = fetch_odds(league, markets)
            api_calls += 1

            if not raw:
                leagues_inactive += 1
                continue

            leagues_active += 1
            events = normalize_events(raw, sport_key, markets)
            all_events.extend(events)
            print(f"    ✅ {len(raw)} eventi → {len(events)} record "
                  f"(con mercati separati)")

            time.sleep(0.5)  # Gentile col rate limit

    # Salva
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    raw_path = os.path.join(REPORTS_DIR, "latest_odds.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "api_calls_used": api_calls,
            "leagues_active": leagues_active,
            "leagues_inactive": leagues_inactive,
            "total_events": len(all_events),
            "by_sport": {
                k: len([e for e in all_events if e["sport_category"] == k])
                for k in enabled
            },
            "events": all_events
        }, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"📊 RIEPILOGO SCRAPING")
    print(f"  Chiamate API:     {api_calls}")
    print(f"  Leghe attive:     {leagues_active}")
    print(f"  Leghe inattive:   {leagues_inactive}")
    print(f"  Record totali:    {len(all_events)}")
    for k, v in enabled.items():
        count = len([e for e in all_events if e["sport_category"] == k])
        print(f"    {v['display_name']:15s} {count:4d} record")
    print(f"  Salvato in:       {raw_path}")
    print(f"{'='*60}")

    return all_events


if __name__ == "__main__":
    if not ODDS_API_KEY:
        print("❌ ODDS_API_KEY non configurata!")
        print("   → https://the-odds-api.com/ (free: 500 req/mese)")
        sys.exit(1)

    scrape_all()
