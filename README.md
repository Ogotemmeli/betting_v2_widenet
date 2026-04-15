questo è il read me per la versione 1 ma funziona in maniera molto simile, ci sono piu mercati e piu leghe di vari sport

# ⚽ Football Odds Analyzer

Sistema automatizzato su GitHub Actions che analizza quote calcistiche da molteplici bookmaker per identificare **arbitraggi (sure bet)** e **value bet** con margine positivo.

## 🧠 Come funziona

```
Ogni 3 ore (GitHub Actions cron)
        │
        ▼
┌──────────────────┐
│   SCRAPER        │  Raccoglie quote da 20+ bookmaker
│   (The Odds API) │  per 7 campionati × 3 mercati
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   ANALYZER       │  1. Cerca arbitraggi (sure bet)
│                  │  2. Stima probabilità "vere"
│                  │  3. Trova value bet (edge > 3%)
│                  │  4. Calcola stake con Kelly Criterion
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   NOTIFIER       │  Alert Telegram per le migliori
│   + REPORT       │  opportunità trovate
└──────────────────┘
```

## 🚀 Setup (10 minuti)

### 1. Fork del repository
Clicca **Fork** in alto a destra.

### 2. API Key (gratuita)
- Registrati su [The Odds API](https://the-odds-api.com/)
- Piano gratuito: **500 richieste/mese** (sufficiente per ~3 analisi/giorno)
- Copia la tua API key

### 3. Configura i Secrets di GitHub
Nel tuo repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Descrizione | Obbligatorio |
|--------|------------|:---:|
| `ODDS_API_KEY` | API key da the-odds-api.com | ✅ |
| `TELEGRAM_BOT_TOKEN` | Token del bot Telegram (da @BotFather) | ❌ |
| `TELEGRAM_CHAT_ID` | Il tuo chat ID Telegram (da @userinfobot) | ❌ |

### 4. Abilita le GitHub Actions
- Vai su **Actions** nel tuo repo
- Clicca **"I understand my workflows, go ahead and enable them"**
- Il workflow partirà automaticamente ogni 3 ore

### 5. (Opzionale) Setup Telegram
1. Cerca `@BotFather` su Telegram → `/newbot` → copia il token
2. Cerca `@userinfobot` su Telegram → copia il tuo ID numerico
3. Aggiungi entrambi come secrets (vedi tabella sopra)

## 📊 Cosa analizza

### Campionati
- 🏴 Premier League
- 🇮🇹 Serie A
- 🇪🇸 La Liga
- 🇩🇪 Bundesliga
- 🇫🇷 Ligue 1
- 🏆 Champions League
- 🥈 Europa League

### Mercati
- **1X2** — Risultato finale
- **Over/Under** — Totale gol
- **Handicap** — Spread

### Tipi di analisi

#### 🎯 Arbitraggio (Sure Bet)
Sfrutta differenze di quote tra bookmaker diversi per garantire un profitto indipendentemente dal risultato. Il sistema:
- Confronta le quote migliori per ogni esito
- Calcola se la somma delle probabilità implicite è < 100%
- Fornisce lo stake esatto per ogni esito

#### 📈 Value Bet
Identifica quote che sottostimano la reale probabilità di un esito:
- Stima la probabilità "vera" dal consenso del mercato (media normalizzata)
- Confronta con le quote di ogni bookmaker
- Segnala quando l'edge supera il 3%
- Calcola lo stake ottimale con il Kelly Criterion (¼ Kelly)

## ⚙️ Configurazione avanzata

Modifica `src/config.py` per calibrare:

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `MIN_ARB_MARGIN_PCT` | 0.5% | Margine minimo per segnalare un arbitraggio |
| `MIN_VALUE_EDGE_PCT` | 3.0% | Edge minimo per segnalare una value bet |
| `MAX_ODDS_VALUE_BET` | 5.0 | Quota massima accettabile |
| `KELLY_FRACTION` | 0.25 | Frazione di Kelly (più basso = più conservativo) |
| `DEFAULT_BANKROLL` | €1000 | Bankroll di riferimento per calcolo stake |
| `MAX_STAKE_PCT` | 5% | Stake massimo su singola giocata |

## 📁 Output

Il sistema genera nella cartella `reports/`:
- `latest_report.md` — Report completo leggibile
- `latest_odds.json` — Dati grezzi delle quote
- `latest_summary.json` — Riepilogo per il notifier
- `history.csv` — Storico di tutte le opportunità trovate

## ⚠️ Disclaimer importante

Questo è uno **strumento di analisi statistica**, non una macchina per fare soldi.

- **Gli arbitraggi** sono rari (0-2 al giorno), durano pochi minuti, e i bookmaker limitano attivamente chi li sfrutta
- **Le value bet** si basano su stime probabilistiche che possono essere errate
- **Nessuna strategia** elimina completamente il rischio
- **I bookmaker** possono limitare/chiudere conti che vincono costantemente
- Gioca **solo ciò che puoi permetterti di perdere**
- Il gioco d'azzardo può creare dipendenza — se hai un problema, chiama il **numero verde 800 558 822** (TVNGA)

## 📄 Licenza
MIT — Usa come vuoi, a tuo rischio.
