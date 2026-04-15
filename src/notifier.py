"""
Notifiche Telegram v2.0 — Multi-sport con breakdown per sport.
"""

import json
import os
import sys

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REPORTS_DIR, get_enabled_sports


SPORT_EMOJI = {
    "soccer": "⚽", "tennis": "🎾", "basketball": "🏀", "hockey": "🏒"
}


def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram non configurato, skip.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"❌ Errore Telegram: {e}")
        return False


def format_arbitrage_alert(arb: dict) -> str:
    emoji = SPORT_EMOJI.get(arb.get("sport", ""), "🏟️")
    lines = [
        f"🎯 <b>[v2 WIDE] ARBITRAGGIO</b> {emoji}",
        f"",
        f"<b>{arb['match']}</b>",
        f"🏆 {arb['league']} — {arb['market']}",
        f"📅 {arb['commence']}",
        f"",
        f"💰 <b>Margine: {arb['margin_pct']:.2f}%</b> (€{arb['guaranteed_profit']:.2f})",
        f"",
    ]
    for outcome, data in arb["stakes"].items():
        lines.append(
            f"  • {outcome}: <b>{data['odds']:.2f}</b> su {data['bookmaker']}"
            f" → €{data['stake_amount']:.2f}"
        )
    lines.append(f"\n⏰ <i>Quote cambiano rapidamente!</i>")
    return "\n".join(lines)


def format_value_bet_alert(vb: dict) -> str:
    emoji = SPORT_EMOJI.get(vb.get("sport", ""), "🏟️")
    conf_emoji = {"ALTA": "🟢", "MEDIA": "🟡", "BASSA": "🔴"}

    return (
        f"📈 <b>[v2 WIDE] VALUE BET</b> {emoji} {conf_emoji.get(vb['confidence'], '⚪')} "
        f"{vb['confidence']}\n\n"
        f"<b>{vb['match']}</b>\n"
        f"🏆 {vb['league']} — {vb['market']}\n\n"
        f"🎲 <b>{vb['outcome']}</b>\n"
        f"📊 Quota: <b>{vb['odds']:.2f}</b> su {vb['bookmaker']}\n"
        f"📐 Fair: {vb['fair_odds']:.2f} | Edge: <b>{vb['edge_pct']:.1f}%</b>\n"
        f"💶 Stake: €{vb['suggested_stake']:.0f}\n\n"
        f"<i>EV: +{vb['expected_value']:.1f}% | "
        f"Prob: {vb['true_prob_pct']:.1f}%</i>"
    )


def format_summary(summary: dict) -> str:
    enabled = get_enabled_sports()
    lines = [
        f"📊 <b>[v2 WIDE] RIEPILOGO MULTI-SPORT</b>",
        f"🕐 {summary['timestamp']}",
        f"",
    ]

    by_sport = summary.get("by_sport", {})
    for sport_key, counts in by_sport.items():
        emoji = SPORT_EMOJI.get(sport_key, "🏟️")
        name = enabled.get(sport_key, {}).get("display_name", sport_key)
        arbs = counts.get("arbs", 0)
        vbs = counts.get("vbs", 0)
        if arbs > 0 or vbs > 0:
            lines.append(f"{emoji} <b>{name}</b>: {arbs} arb, {vbs} value bet")

    lines.append("")
    total_arbs = summary.get("arbitrages_found", 0)
    total_vbs = summary.get("value_bets_found", 0)
    lines.append(f"<b>Totale: {total_arbs} arb + {total_vbs} value bet</b>")

    if summary.get("best_arb_margin", 0) > 0:
        lines.append(f"💰 Miglior arb: {summary['best_arb_margin']:.2f}%")
    if summary.get("best_value_edge", 0) > 0:
        lines.append(f"📊 Miglior edge: {summary['best_value_edge']:.1f}%")

    if total_arbs == 0 and total_vbs == 0:
        lines.append(f"\n😴 Nessuna opportunità. Riprovo al prossimo ciclo.")

    return "\n".join(lines)


def main():
    summary_path = os.path.join(REPORTS_DIR, "latest_summary.json")
    if not os.path.exists(summary_path):
        print("❌ Nessun summary.")
        sys.exit(0)

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    send_telegram(format_summary(summary))

    for arb in summary.get("arbitrages", []):
        send_telegram(format_arbitrage_alert(arb))

    high_conf = [vb for vb in summary.get("value_bets", [])
                 if vb.get("confidence") == "ALTA"]
    for vb in high_conf[:5]:
        send_telegram(format_value_bet_alert(vb))

    count = len(summary.get("arbitrages", [])) + len(high_conf[:5])
    print(f"📬 {count + 1} notifiche inviate")


if __name__ == "__main__":
    main()
