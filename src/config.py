"""
Configurazione centrale del sistema di analisi quote.
v2.0 — Multi-sport con soglie calibrate per sport e ottimizzazione budget API.
"""

import os

# ─── API ────────────────────────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ─── Budget API ─────────────────────────────────────────────────────
# Free: 500 req/mese | Starter $20/mese: 10.000 req/mese
API_MONTHLY_BUDGET = int(os.getenv("API_MONTHLY_BUDGET", "500"))

# ─── Bookmaker ──────────────────────────────────────────────────────
REGIONS = ["eu", "uk"]
ODDS_FORMAT = "decimal"

# ─── SPORT E MERCATI ────────────────────────────────────────────────
# Struttura unificata: ogni sport ha leghe, mercati e soglie proprie.
# I mercati vengono aggregati in una singola chiamata API per lega.
#
# EFFICIENZA MERCATO (più basso = più opportunità):
#   Tennis ML: ~91.5%  |  Hockey ML: ~91.8%  |  Basket tot: ~93.2%
#   Calcio BTTS: ~93.8%  |  Calcio DC: ~94.3%  |  Calcio 1X2: ~96.2%

SPORTS_CONFIG = {
    "soccer": {
        "enabled": True,
        "display_name": "Calcio",
        "leagues": [
            "soccer_epl",
            "soccer_italy_serie_a",
            "soccer_spain_la_liga",
            "soccer_germany_bundesliga",
            "soccer_france_ligue_one",
            "soccer_uefa_champs_league",
            "soccer_uefa_europa_league",
        ],
        "markets": ["h2h", "totals", "spreads"],
        "thresholds": {
            "min_arb_margin": 0.5,
            "min_value_edge": 3.0,
            "max_odds": 5.0,
            "min_odds": 1.30,
            "min_bookmakers": 4,
            "max_arb_margin": 12.0,
        },
        "portfolio_weight": 0.35,
    },

    "tennis": {
        "enabled": True,
        "display_name": "Tennis",
        "leagues": [
            "tennis_atp_french_open",
            "tennis_atp_wimbledon",
            "tennis_atp_us_open",
            "tennis_atp_australian_open",
            "tennis_wta_french_open",
            "tennis_wta_wimbledon",
            "tennis_wta_us_open",
            "tennis_wta_australian_open",
        ],
        "markets": ["h2h", "totals", "spreads"],
        "thresholds": {
            "min_arb_margin": 0.3,
            "min_value_edge": 2.5,
            "max_odds": 4.0,
            "min_odds": 1.20,
            "min_bookmakers": 3,
            "max_arb_margin": 10.0,
        },
        "portfolio_weight": 0.25,
    },

    "basketball": {
        "enabled": True,
        "display_name": "Basket",
        "leagues": [
            "basketball_nba",
            "basketball_euroleague",
        ],
        "markets": ["h2h", "totals", "spreads"],
        "thresholds": {
            "min_arb_margin": 0.4,
            "min_value_edge": 2.5,
            "max_odds": 4.5,
            "min_odds": 1.25,
            "min_bookmakers": 4,
            "max_arb_margin": 10.0,
        },
        "portfolio_weight": 0.25,
    },

    "hockey": {
        "enabled": True,
        "display_name": "Hockey",
        "leagues": [
            "icehockey_nhl",
        ],
        "markets": ["h2h", "totals", "spreads"],
        "thresholds": {
            "min_arb_margin": 0.3,
            "min_value_edge": 2.0,
            "max_odds": 5.0,
            "min_odds": 1.25,
            "min_bookmakers": 3,
            "max_arb_margin": 12.0,
        },
        "portfolio_weight": 0.15,
    },
}

# ─── Filtro freshness (anti falsi positivi) ────────────────────────
MAX_ODDS_AGE_SECONDS = 600  # Scarta quote > 10 min
MAX_SINGLE_ODDS_DEVIATION_PCT = 25.0  # Quota outlier = probabile stale

# ─── Soglie globali (fallback) ─────────────────────────────────────
MIN_ARB_MARGIN_PCT = float(os.getenv("MIN_ARB_MARGIN", "0.5"))
MAX_ARB_MARGIN_PCT = 15.0
MIN_VALUE_EDGE_PCT = 3.0
MAX_ODDS_VALUE_BET = 5.0
MIN_ODDS_VALUE_BET = 1.30
MIN_BOOKMAKERS = 4

# ─── Kelly Criterion ───────────────────────────────────────────────
KELLY_FRACTION = 0.25
MAX_STAKE_PCT = 5.0
DEFAULT_BANKROLL = float(os.getenv("BANKROLL", "1000.0"))

# ─── Diversificazione portafoglio ──────────────────────────────────
MAX_SPORT_EXPOSURE_PCT = 40.0
MAX_LEAGUE_EXPOSURE_PCT = 25.0
MAX_CONCURRENT_BETS = 15

CORRELATED_MARKETS = [
    ("h2h", "spreads"),
    ("totals", "btts"),
]

# ─── Output ─────────────────────────────────────────────────────────
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
HISTORY_FILE = os.path.join(REPORTS_DIR, "history.csv")

# ─── Telegram ──────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ─── Helper functions ──────────────────────────────────────────────

def get_enabled_sports() -> dict:
    return {k: v for k, v in SPORTS_CONFIG.items() if v.get("enabled")}


def get_thresholds(sport_key: str) -> dict:
    sport = SPORTS_CONFIG.get(sport_key, {})
    t = sport.get("thresholds", {})
    return {
        "min_arb_margin": t.get("min_arb_margin", MIN_ARB_MARGIN_PCT),
        "max_arb_margin": t.get("max_arb_margin", MAX_ARB_MARGIN_PCT),
        "min_value_edge": t.get("min_value_edge", MIN_VALUE_EDGE_PCT),
        "max_odds": t.get("max_odds", MAX_ODDS_VALUE_BET),
        "min_odds": t.get("min_odds", MIN_ODDS_VALUE_BET),
        "min_bookmakers": t.get("min_bookmakers", MIN_BOOKMAKERS),
    }


def estimate_api_calls_per_cycle() -> int:
    total = 0
    for sport in get_enabled_sports().values():
        total += len(sport["leagues"])
    return total


def recommend_cycles_per_day() -> int:
    calls_per_cycle = estimate_api_calls_per_cycle()
    if calls_per_cycle == 0:
        return 0
    daily_budget = API_MONTHLY_BUDGET / 30
    return max(1, int(daily_budget / calls_per_cycle))
