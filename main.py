
"""
╔══════════════════════════════════════════════════════════════════════╗
║          SMC SIGNAL ENGINE  v2  — Smart Money Concepts              ║
║   BOS · FVG · Order Block · Liquidity · Multi-TF · 50+ Markets      ║
║                                                                      ║
║   FOREX  |  INDICES  |  CRYPTO  |  COMMODITIES  |  MATIÈRES 1ÈRES   ║
╚══════════════════════════════════════════════════════════════════════╝

Marchés couverts :
  FOREX      — 28 paires majeures + mineures + exotiques
  CRYPTO     — BTC, ETH, XRP, SOL, BNB, DOGE, ADA, AVAX, LTC, LINK
  INDICES    — SPX, NAS, DAX, CAC, FTSE, Nikkei, HSI
  COMMODITÉS — Gold, Silver, Oil WTI, Oil Brent, Gaz Naturel, Cuivre

Installation :
    pip install yfinance pandas numpy colorama tabulate

Usage :
    python smc_signals.py                         # scan complet
    python smc_signals.py --cat forex             # seulement forex
    python smc_signals.py --cat crypto            # seulement crypto
    python smc_signals.py --cat commodities       # gold/pétrole/...
    python smc_signals.py --symbol EURUSD=X       # symbol unique
    python smc_signals.py --live                  # boucle continue
    python smc_signals.py --htf 4h --ltf 1h       # timeframes perso
    python smc_signals.py --min-score 80          # filtre score élevé
"""

import argparse
import threading
import time
import os
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── Flask — serveur HTTP pour Render (Web Service) ────────────
from flask import Flask, jsonify

flask_app = Flask(__name__)

# ── État partagé — mis à jour par run_live() ─────────────────
_STATUS: dict = {
    "started_at"     : None,
    "last_scan"      : None,
    "cycle"          : 0,
    "symbols_count"  : 0,
    "last_signals"   : [],     # liste des derniers signaux envoyés
    "scan_running"   : False,
}
_STATUS_LOCK = threading.Lock()


@flask_app.route("/")
def index():
    """Dashboard de statut HTML — lisible dans le navigateur Render."""
    with _STATUS_LOCK:
        st = dict(_STATUS)

    signals_html = ""
    for s in reversed(st["last_signals"][-10:]):
        color     = "#e74c3c" if s["direction"] == "SHORT" else "#2ecc71"
        mode_tag  = s.get("mode", "SMC")
        mode_col  = "#f39c12" if mode_tag == "PRE-BOS" else "#58a6ff"
        signals_html += (
            f'<tr>'
            f'<td>{s["ts"]}</td>'
            f'<td><b>{s["market"]}</b></td>'
            f'<td style="color:{color};font-weight:bold">{s["direction"]}</td>'
            f'<td><span style="background:{mode_col};color:#000;padding:2px 6px;'
            f'border-radius:4px;font-size:.8em;font-weight:bold">{mode_tag}</span></td>'
            f'<td>{s["entry"]}</td>'
            f'<td style="color:#e74c3c">{s["sl"]}</td>'
            f'<td style="color:#2ecc71">{s["tp"]}</td>'
            f'<td>1:{s["rr"]}</td>'
            f'<td>{s["score"]}/100</td>'
            f'<td>{s["lot"]} lot</td>'
            f'</tr>'
        )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="30">
  <title>SMC Signal Engine</title>
  <style>
    body  {{ font-family: monospace; background:#0d1117; color:#c9d1d9; margin:2em; }}
    h1    {{ color:#58a6ff; }}
    h2    {{ color:#8b949e; border-bottom:1px solid #30363d; padding-bottom:.3em; }}
    table {{ border-collapse:collapse; width:100%; }}
    th    {{ background:#161b22; color:#8b949e; padding:.5em 1em; text-align:left; }}
    td    {{ padding:.4em 1em; border-bottom:1px solid #21262d; }}
    .ok   {{ color:#2ecc71; }} .warn {{ color:#f39c12; }} .err {{ color:#e74c3c; }}
    .badge{{ display:inline-block; padding:.2em .6em; border-radius:4px;
             font-size:.85em; font-weight:bold; }}
    .live {{ background:#2ecc71; color:#000; }}
    .idle {{ background:#f39c12; color:#000; }}
  </style>
</head>
<body>
  <h1>⚡ SMC Signal Engine</h1>
  <p>
    Statut : <span class="badge {'live' if st['scan_running'] else 'idle'}">
      {'🟢 SCAN ACTIF' if st['scan_running'] else '🟡 EN ATTENTE'}
    </span>
    &nbsp;|&nbsp;
    Démarré : <b>{st['started_at'] or '—'}</b>
    &nbsp;|&nbsp;
    Cycle : <b>#{st['cycle']}</b>
    &nbsp;|&nbsp;
    Marchés : <b>{st['symbols_count']}</b>
    &nbsp;|&nbsp;
    Dernier scan : <b>{st['last_scan'] or '—'}</b>
  </p>
  <p style="color:#8b949e;font-size:.85em">⟳ Page rafraîchie toutes les 30 secondes</p>

  <h2>📋 Derniers signaux envoyés</h2>
  {'<p class="warn">Aucun signal validé pour le moment.</p>' if not st['last_signals'] else f"""
  <table>
    <tr>
      <th>Heure UTC</th><th>Marché</th><th>Direction</th>
      <th>Mode</th>
      <th>Entrée</th><th>SL 🔴</th><th>TP 🟢</th>
      <th>R:R</th><th>Score</th><th>Lot</th>
    </tr>
    {signals_html}
  </table>"""}

  <h2>⚙️ Configuration</h2>
  <table>
    <tr><th>Paramètre</th><th>Valeur</th></tr>
    <tr><td>Score minimum</td><td>{SCORE_THRESHOLD}/100</td></tr>
    <tr><td>RR minimum</td><td>1:{MIN_RR}</td></tr>
    <tr><td>Risque par trade</td><td>${RISK_USD}</td></tr>
    <tr><td>Timeframes</td><td>H1 → M15 → M5 / M1</td></tr>
    <tr><td>Intervalle scan</td><td>30 secondes</td></tr>
  </table>
</body>
</html>"""
    return html


@flask_app.route("/status")
def status_json():
    """Endpoint JSON — pour monitoring externe."""
    with _STATUS_LOCK:
        return jsonify(_STATUS)


def start_flask(port: int = 10000) -> None:
    """Lance Flask dans un thread daemon (ne bloque pas run_live)."""
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def start_self_ping(port: int = 10000) -> None:
    """
    Self-ping toutes les 4 minutes pour empêcher Render (plan gratuit)
    de mettre le container en veille.
    Le ping cible /status (JSON léger) pour ne pas surcharger.
    """
    url = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{port}")
    ping_url = f"{url}/status"

    def _ping_loop():
        # Attend 30s au démarrage que Flask soit bien up
        time.sleep(30)
        while True:
            try:
                r = requests.get(ping_url, timeout=10)
                # Log discret — seulement si échec
                if r.status_code != 200:
                    log.warning(f"  ⚠ Self-ping HTTP {r.status_code} → {ping_url}")
            except Exception as e:
                log.warning(f"  ⚠ Self-ping échoué : {e}")
            time.sleep(240)   # toutes les 4 minutes

    t = threading.Thread(target=_ping_loop, daemon=True, name="self-ping")
    t.start()
    log.info(f"  ✓ Self-ping actif → {ping_url} (toutes les 4 min)")

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    COLOR = True
except ImportError:
    COLOR = False

# ─────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────
DEFAULT_SYMBOL  = "GBPUSD=X"
HTF             = "1h"     # Biais directionnel
MTF             = "15m"    # Confirmation structure (BOS + OB)
LTF             = "5m"     # Entrée précise (FVG M5 + OB M5)

FVG_MIN_RATIO   = 0.0002   # FVG plus sensible sur M5/M1
OB_LOOKBACK     = 5
LIQ_THRESHOLD   = 0.0004
SCORE_THRESHOLD = 80       # Seuil élevé → signaux élite uniquement
MIN_RR          = 2.0      # RR net spread minimum — abaissé pour plus de trades
RISK_USD        = 25.0     # Risque fixe par position en USD

# ─────────────────────────────────────────────────────────────
#  FILTRES VOLATILITÉ — marchés morts exclus automatiquement
# ─────────────────────────────────────────────────────────────
# ATR M5 minimum par paire (en prix brut).
# Si l'ATR M5 est sous ce seuil → marché trop plat → skip.
# Calibré pour que risk × 3 + spread soit atteignable en M5/M15.
ATR_MIN: dict[str, float] = {
    # Forex majeures
    "EURUSD=X": 0.00060,   # 6 pips min
    "GBPUSD=X": 0.00080,   # 8 pips
    "USDJPY=X": 0.080,     # 8 pips JPY
    "USDCHF=X": 0.00060,
    "AUDUSD=X": 0.00055,
    "NZDUSD=X": 0.00050,
    "USDCAD=X": 0.00060,
    # Croisées — plus larges
    "GBPJPY=X": 0.120,
    "EURJPY=X": 0.090,
    "GBPAUD=X": 0.00110,
    "GBPCAD=X": 0.00110,
    "GBPNZD=X": 0.00130,
    "EURGBP=X": 0.00045,
    "EURAUD=X": 0.00090,
    "EURCAD=X": 0.00090,
    "AUDJPY=X": 0.070,
    "CADJPY=X": 0.070,
    "CHFJPY=X": 0.080,
    "NZDJPY=X": 0.065,
    # Gold / Silver
    "GC=F":     1.50,      # $1.5/oz min
    "SI=F":     0.05,
    # Pétrole
    "CL=F":     0.30,
    "BZ=F":     0.30,
    # Crypto
    "BTC-USD":  200.0,
    "ETH-USD":  10.0,
    # Indices
    "^GSPC":    8.0,
    "^NDX":     30.0,
    "^DJI":     80.0,
    "^GDAXI":   40.0,
}
ATR_MIN_DEFAULT = 0.00050  # fallback pour symboles non listés

# ─────────────────────────────────────────────────────────────
#  SESSIONS ACTIVES (UTC) — fenêtres de liquidité réelle uniquement
#
#  London open   : 07:00 → 10:00 UTC  (run initial + vraie liquidité)
#  NY open       : 13:00 → 16:00 UTC  (US session + overlap London)
#
#  Exclus intentionnellement :
#    03:00–07:00 UTC  → Asia late / pre-London  : manipulation, faible volume
#    10:00–13:00 UTC  → Mid-London dull zone     : range comprimé
#    16:00–21:00 UTC  → NY post-open / fin NY    : fades & consolidation
#    21:00–03:00 UTC  → Asie early / nuit        : marché mort
# ─────────────────────────────────────────────────────────────
SESSION_WINDOWS_UTC: list[tuple[int, int]] = [
    (7,  10),   # London open
    (13, 16),   # NY open + overlap
]

# Ratio spread/ATR max — si spread > X% de l'ATR → skip (RR impossible)
MAX_SPREAD_ATR_RATIO = 0.25   # spread ne doit pas dépasser 25% de l'ATR M5


def is_session_active() -> bool:
    """
    Retourne True uniquement pendant les fenêtres haute-liquidité :
      London open  07:00–10:00 UTC
      NY open      13:00–16:00 UTC
    Tout le reste (pre-London, mid-London dull, post-NY, Asia) → False.
    """
    hour = datetime.now(timezone.utc).hour
    return any(start <= hour < end for start, end in SESSION_WINDOWS_UTC)


def check_volatility(symbol: str, df_ltf: pd.DataFrame) -> tuple[bool, str]:
    """
    Vérifie si le marché est suffisamment volatil pour trader.
    Retourne (ok, raison_si_rejeté).

    Critères :
      1. ATR M5 ≥ seuil minimum du symbole
      2. Spread ≤ 25% de l'ATR (RR 3 mathématiquement atteignable)
      3. Session active (London ou NY)
    """
    if df_ltf.empty or len(df_ltf) < 14:
        return False, "données insuffisantes"

    atr = (df_ltf["high"] - df_ltf["low"]).rolling(14).mean().iloc[-1]
    atr_min = ATR_MIN.get(symbol, ATR_MIN_DEFAULT)
    spread  = get_spread(symbol)

    if atr < atr_min * 0.7:
        return False, f"ATR trop faible ({round(atr, 5)} < {round(atr_min*0.7,5)})"

    ratio = spread / atr if atr > 0 else 1.0
    if ratio > MAX_SPREAD_ATR_RATIO:
        return False, f"spread/ATR={round(ratio*100,1)}% > {int(MAX_SPREAD_ATR_RATIO*100)}%"

    if not is_session_active():
        return False, "hors session (London/NY)"

    return True, ""

# ─────────────────────────────────────────────────────────────
#  SPREADS TYPIQUES PAR INSTRUMENT  (en prix brut, pas en pips)
#  Source : spreads moyens broker ECN hors news
#  Intégrés au RR : le vrai gain net = TP - (entry + spread)
# ─────────────────────────────────────────────────────────────
SPREAD_TABLE: dict[str, float] = {
    # ── Forex majeures (pips × 0.0001) ──────────────────────
    "EURUSD=X": 0.00008,   # 0.8 pip
    "GBPUSD=X": 0.00010,   # 1.0 pip
    "USDJPY=X": 0.009,     # 0.9 pip  (× 0.01)
    "USDCHF=X": 0.00010,   # 1.0 pip
    "AUDUSD=X": 0.00010,   # 1.0 pip
    "NZDUSD=X": 0.00013,   # 1.3 pip
    "USDCAD=X": 0.00012,   # 1.2 pip
    # ── Forex croisées ───────────────────────────────────────
    "EURGBP=X": 0.00013,
    "EURJPY=X": 0.012,
    "EURCHF=X": 0.00018,
    "EURAUD=X": 0.00020,
    "EURCAD=X": 0.00020,
    "EURNZD=X": 0.00025,
    "GBPJPY=X": 0.018,
    "GBPCHF=X": 0.00022,
    "GBPAUD=X": 0.00025,
    "GBPCAD=X": 0.00025,
    "GBPNZD=X": 0.00030,
    "AUDJPY=X": 0.012,
    "CADJPY=X": 0.015,
    "CHFJPY=X": 0.015,
    "NZDJPY=X": 0.015,
    "AUDCAD=X": 0.00018,
    "AUDCHF=X": 0.00018,
    "AUDNZD=X": 0.00020,
    "NZDCAD=X": 0.00020,
    "NZDCHF=X": 0.00020,
    "CADCHF=X": 0.00018,
    # ── Exotiques ────────────────────────────────────────────
    "USDMXN=X": 0.003,
    "USDZAR=X": 0.005,
    "USDTRY=X": 0.010,
    "USDSEK=X": 0.004,
    "USDNOK=X": 0.004,
    "USDDKK=X": 0.003,
    "USDSGD=X": 0.00020,
    "USDHKD=X": 0.00030,
    # ── Gold / Silver ────────────────────────────────────────
    "GC=F":     0.30,      # $0.30 / oz
    "SI=F":     0.015,
    # ── Pétrole ──────────────────────────────────────────────
    "CL=F":     0.03,
    "BZ=F":     0.04,
    "NG=F":     0.003,
    "HG=F":     0.003,
    "PL=F":     0.50,
    "PA=F":     1.00,
    # ── Crypto ───────────────────────────────────────────────
    "BTC-USD":  15.0,      # ~$15 spread moyen
    "ETH-USD":  0.80,
    # ── Indices (valeur indice) ───────────────────────────────
    "^GSPC":    0.30,
    "^NDX":     0.50,
    "^DJI":     2.00,
    "^GDAXI":   1.00,
    "^FCHI":    1.00,
    "^FTSE":    1.00,
    "^N225":    5.00,
    "^HSI":     5.00,
}

def get_spread(symbol: str) -> float:
    """Retourne le spread estimé pour un symbole (défaut 1.5 pip si inconnu)."""
    return SPREAD_TABLE.get(symbol, 0.00015)

# ─────────────────────────────────────────────────────────────
#  CORRÉLATION — GARDE ANTI-SUREXPOSITION DEVISE
#
#  Problème : EURUSD LONG + GBPUSD LONG + NZDUSD LONG simultanément
#  = 3× le risque USD sur le même mouvement macro.
#  Risque réel = 3 × $25 = $75 sur un seul facteur (DXY).
#
#  Solution : un seul trade actif par "groupe devise dominante".
#  Groupes :
#    USD_LONG  → paires où USD est coté (EURUSD, GBPUSD, AUDUSD, NZDUSD)
#                 + USD/XXX sens contraire (USDCHF SHORT, USDCAD SHORT)
#    USD_SHORT → idem sens inverse
#    JPY_LONG / JPY_SHORT → toutes paires JPY
#    GBP / EUR / AUD / NZD groupes secondaires
#
#  Règle : si un signal de même groupe+direction est déjà actif → BLOQUÉ.
# ─────────────────────────────────────────────────────────────

# Mapping symbole → devise dominante exposée
# Convention : la devise DOMINANTE est celle qui subit le mouvement macro.
_CORR_GROUPS: dict[str, str] = {
    # ── USD comme terme coté (EUR/USD, GBP/USD…) → exposition USD ──
    "EURUSD=X": "USD", "GBPUSD=X": "USD", "AUDUSD=X": "USD",
    "NZDUSD=X": "USD",
    # ── USD comme base (USD/JPY…) → exposition USD inverse ──────────
    "USDJPY=X": "USD", "USDCHF=X": "USD", "USDCAD=X": "USD",
    "USDMXN=X": "USD", "USDZAR=X": "USD", "USDTRY=X": "USD",
    "USDSEK=X": "USD", "USDNOK=X": "USD", "USDSGD=X": "USD",
    "USDHKD=X": "USD", "USDDKK=X": "USD",
    # ── JPY croisées → exposition JPY ────────────────────────────────
    "GBPJPY=X": "JPY", "EURJPY=X": "JPY", "AUDJPY=X": "JPY",
    "CADJPY=X": "JPY", "CHFJPY=X": "JPY", "NZDJPY=X": "JPY",
    # ── GBP croisées → exposition GBP ────────────────────────────────
    "GBPAUD=X": "GBP", "GBPCAD=X": "GBP", "GBPNZD=X": "GBP",
    "GBPCHF=X": "GBP", "EURGBP=X": "GBP",
    # ── EUR croisées → exposition EUR ────────────────────────────────
    "EURAUD=X": "EUR", "EURCAD=X": "EUR", "EURNZD=X": "EUR",
    "EURCHF=X": "EUR",
    # ── AUD croisées → exposition AUD ────────────────────────────────
    "AUDCAD=X": "AUD", "AUDCHF=X": "AUD", "AUDNZD=X": "AUD",
    # ── NZD croisées ─────────────────────────────────────────────────
    "NZDCAD=X": "NZD", "NZDCHF=X": "NZD",
    # ── Commodités / Crypto / Indices → groupes propres ──────────────
    "GC=F": "GOLD", "SI=F": "GOLD",
    "CL=F": "OIL",  "BZ=F": "OIL", "NG=F": "OIL",
    "BTC-USD": "BTC",
    "^GSPC": "US_IDX", "^NDX": "US_IDX", "^DJI": "US_IDX",
    "^GDAXI": "EU_IDX", "^FCHI": "EU_IDX", "^FTSE": "EU_IDX",
}

# État actif : groupe+direction → timestamp d'enregistrement
# Expiré après CORR_TTL secondes (15 min) pour ne pas bloquer trop longtemps
_active_corr_groups: dict[str, float] = {}
CORR_TTL = 900   # 15 minutes


def correlation_guard_reset() -> None:
    """Réinitialise le registre de corrélation — appeler au début de chaque cycle."""
    _active_corr_groups.clear()


def correlation_guard(symbol: str, direction: str) -> tuple[bool, str]:
    """
    Vérifie si un trade corrélé est déjà actif.
    Reset automatique après CORR_TTL secondes (15 min) — évite de bloquer trop de trades.
    """
    group = _CORR_GROUPS.get(symbol)
    if group is None:
        return True, ""

    key    = f"{group}:{direction}"
    now_ts = time.time()

    # Expire les entrées vieilles de > CORR_TTL
    if key in _active_corr_groups:
        if now_ts - _active_corr_groups[key] > CORR_TTL:
            del _active_corr_groups[key]   # expiré → libéré
        else:
            return False, f"corrélation {group} {direction} active ({CORR_TTL//60}min TTL)"

    _active_corr_groups[key] = now_ts
    return True, ""


TELEGRAM_TOKEN    = os.environ.get("TG_TOKEN", "8665812395:AAFO4BMTIrBCQJYVL8UytO028TcB1sDfgbI")
TELEGRAM_CHAT_ID  = None          # Auto-détecté au premier lancement (DM personnel)
TELEGRAM_GROUP_ID = "-1002335466840"  # Groupe Telegram

# ── Anti-spam : évite de renvoyer le même signal avant N secondes ──
SIGNAL_COOLDOWN  = 600           # 10 minutes par (symbol, direction)
_signal_cache: dict[str, float] = {}   # clé → timestamp dernier envoi

# ── Un seul signal par setup (symbol + direction + score_bucket) ──
# Réinitialisé uniquement quand le biais change ou manuellement.
# Clé : "{symbol}:{direction}:{score_bucket}"  — valeur : True
_setup_sent: dict[str, bool] = {}

def _setup_key(symbol: str, direction: str, score: int) -> str:
    """Clé unique de setup : paire + direction + palier de score (tranches de 5 pts)."""
    bucket = (score // 5) * 5   # ex: score 85 → bucket 85, score 87 → bucket 85
    return f"{symbol}:{direction}:{bucket}"

def is_setup_already_sent(symbol: str, direction: str, score: int) -> bool:
    return _setup_sent.get(_setup_key(symbol, direction, score), False)

def mark_setup_sent(symbol: str, direction: str, score: int) -> None:
    _setup_sent[_setup_key(symbol, direction, score)] = True

def reset_setup(symbol: str) -> None:
    """Réinitialise les setups d'un symbole (appeler si le biais H1 change)."""
    keys_to_del = [k for k in _setup_sent if k.startswith(f"{symbol}:")]
    for k in keys_to_del:
        del _setup_sent[k]


def _tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"


def tg_get_chat_id() -> Optional[str]:
    """
    Récupère automatiquement le chat_id du dernier message reçu.
    Détecte aussi les groupes (chat.type = 'group' | 'supergroup').
    → Ajoute le bot au groupe, envoie /start, puis relance le script.
    """
    global TELEGRAM_GROUP_ID
    try:
        r = requests.get(_tg_url("getUpdates"), timeout=10)
        updates = r.json().get("result", [])
        personal_id = None
        for upd in reversed(updates):
            msg = upd.get("message") or upd.get("channel_post", {})
            if not msg:
                continue
            chat      = msg.get("chat", {})
            chat_type = chat.get("type", "")
            cid       = str(chat.get("id", ""))
            if chat_type in ("group", "supergroup") and not TELEGRAM_GROUP_ID:
                TELEGRAM_GROUP_ID = cid
                print(c(f"  [TG] 👥 Groupe détecté : {chat.get('title', cid)}  (id={cid})", "cyan"))
            elif chat_type == "private" and not personal_id:
                personal_id = cid
        return personal_id
    except Exception:
        pass
    return None


def tg_send(text: str, chat_id: str) -> bool:
    """Envoie un message Markdown au bot Telegram."""
    try:
        r = requests.post(
            _tg_url("sendMessage"),
            json={
                "chat_id"    : chat_id,
                "text"       : text,
                "parse_mode" : "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(c(f"  [TG] Erreur envoi : {e}", "red"))
        return False


def tg_format_signal(sig: "Signal", tier: str = "") -> str:
    """Formate un signal en message HTML pour Telegram."""
    dir_emoji  = "🔴 SHORT" if sig.direction == "SHORT" else "🟢 LONG"
    tier_badge = "🥇 PRIORITÉ" if "TIER 1" in tier else ("🥈 FOREX" if "TIER 2" in tier else "🥉")
    rr_bar     = "⭐" * min(int(sig.rr), 5)
    score_bar  = "█" * (sig.score // 10) + "░" * (10 - sig.score // 10)

    dec = 2 if sig.entry > 100 else 5
    risk  = round(abs(sig.entry - sig.sl),  dec)
    gain  = round(abs(sig.tp  - sig.entry), dec)
    spread_val = get_spread(sig.symbol)
    spread_disp = round(spread_val, dec)

    ts = sig.timestamp.strftime("%d/%m/%Y %H:%M UTC")
    gain_usd = round(sig.risk_usd * sig.rr, 2)

    msg = (
        f"<b>⚡ SMC SIGNAL ÉLITE  —  {tier_badge}</b>\n"
        f"{'─'*30}\n"
        f"<b>Marché   :</b>  <code>{sig.symbol}</code>\n"
        f"<b>Direction:</b>  <b>{dir_emoji}</b>\n"
        f"<b>Biais H1 :</b>  {sig.htf_bias}\n"
        f"<b>TF Entrée:</b>  M5 / M15\n"
        f"{'─'*30}\n"
        f"<b>📍 Entrée    :</b>  <code>{sig.entry}</code>\n"
        f"<b>🔴 Stop Loss :</b>  <code>{sig.sl}</code>   <i>(risk {risk})</i>\n"
        f"<b>🟢 Take Profit:</b> <code>{sig.tp}</code>   <i>(gain brut {gain})</i>\n"
        f"<b>📊 Spread    :</b>  <code>{spread_disp}</code>   <i>(déduit du RR)</i>\n"
        f"<b>⚖  R : R net :</b>  <b>1 : {sig.rr}</b>  {rr_bar}\n"
        f"{'─'*30}\n"
        f"<b>💰 LOT SIZE  :</b>  <b><code>{sig.lot} lot</code></b>\n"
        f"<b>⚠  Risque    :</b>  <b>${sig.risk_usd}</b>  →  gain ≈ <b>${gain_usd}</b>\n"
        f"{'─'*30}\n"
        f"<b>Score :</b>  [{score_bar}]  {sig.score}/100\n"
        f"<b>Confluence :</b>\n"
    )
    for r in sig.reasons:
        msg += f"  • {r}\n"
    msg += f"{'─'*30}\n<i>🕐 {ts}</i>"
    return msg


def tg_notify(sig: "Signal", tier: str = "", chat_id: Optional[str] = None) -> None:
    """Envoie la notification Telegram au DM personnel ET au groupe."""
    global TELEGRAM_CHAT_ID, TELEGRAM_GROUP_ID, _signal_cache

    # ── Garde-fou : un seul signal par setup (paire + direction + score_bucket) ──
    if is_setup_already_sent(sig.symbol, sig.direction, sig.score):
        print(c(f"  [TG] ⏭ Setup déjà envoyé — {sig.symbol} {sig.direction} "
                f"score≈{(sig.score // 5) * 5} — ignoré.", "yellow"))
        return
    mark_setup_sent(sig.symbol, sig.direction, sig.score)

    # ── Résolution chat_id personnel ──────────────────────────
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        cid = tg_get_chat_id()
        if cid:
            TELEGRAM_CHAT_ID = cid
            print(c(f"  [TG] Chat ID personnel détecté : {cid}", "cyan"))
        else:
            print(c("  [TG] ⚠ Chat ID introuvable. Envoyez /start au bot dans Telegram.", "yellow"))

    msg = tg_format_signal(sig, tier)

    # ── Envoi DM personnel ────────────────────────────────────
    if cid:
        ok = tg_send(msg, cid)
        status = "✓ DM envoyé" if ok else "✗ Échec DM"
        print(c(f"  [TG] {status}", "green" if ok else "red"))

    # ── Envoi Groupe ──────────────────────────────────────────
    if not TELEGRAM_GROUP_ID:
        tg_get_chat_id()   # tente de détecter le groupe si pas encore fait

    if TELEGRAM_GROUP_ID:
        ok_grp = tg_send(msg, TELEGRAM_GROUP_ID)
        status = "✓ Groupe envoyé" if ok_grp else "✗ Échec groupe"
        print(c(f"  [TG] {status}", "green" if ok_grp else "red"))
    else:
        print(c("  [TG] ⚠ Groupe non détecté — ajoutez @leaderodg_bot au groupe et envoyez un message.", "yellow"))

# ─────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────
@dataclass
class FVG:
    direction : str          # "bullish" | "bearish"
    top       : float
    bottom    : float
    index     : int          # index dans le DataFrame
    filled    : bool = False

@dataclass
class OrderBlock:
    direction : str          # "bullish" | "bearish"
    top       : float
    bottom    : float
    index     : int
    mitigated : bool = False

@dataclass
class Signal:
    symbol      : str
    direction   : str        # "LONG" | "SHORT"
    entry       : float
    sl          : float
    tp          : float
    rr          : float      # Risk/Reward réel calculé
    score       : int
    timestamp   : datetime
    htf_bias    : str
    lot         : float = 0.0   # Taille de lot calculée
    risk_usd    : float = RISK_USD
    reasons     : list = field(default_factory=list)

# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────
def c(text: str, color: str = "green") -> str:
    if not COLOR:
        return text
    colors = {
        "green"  : Fore.GREEN,
        "red"    : Fore.RED,
        "yellow" : Fore.YELLOW,
        "cyan"   : Fore.CYAN,
        "white"  : Fore.WHITE,
        "magenta": Fore.MAGENTA,
    }
    return colors.get(color, "") + text + Style.RESET_ALL


def compute_lot(symbol: str, entry: float, sl: float,
                risk_usd: float = RISK_USD) -> float:
    """
    Taille de lot pour risque fixe en USD.
    Basé sur la distance entry→SL (risque réel de la position).

    Formule universelle : lot = risk_usd / (sl_distance × pip_value_per_lot)

    pip_value_per_lot par type :
      XXX/USD (EUR,GBP,AUD,NZD + USD)  → pip=0.0001  val=$10/lot
      USD/XXX (CHF,CAD)                → pip=0.0001  val=$10/entry
      XXX/JPY ou USD/JPY               → pip=0.01    val=$1000/entry (≈ $10/0.01/lot à rate≈100)
      Gold GC=F                        → $1 = $100/lot  (100 oz)
      Silver SI=F                      → $1 = $50/lot   (5000 oz)
      Oil CL/BZ                        → $1 = $1000/lot (1000 barils)
      Indices                          → point = $50/lot (approx SPX)
      BTC/ETH                          → lot = risk_usd / sl_distance
    """
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return 0.0

    sym = symbol.upper().replace("=X", "").replace("-", "").replace("^", "")

    # ── Commodités ───────────────────────────────────────────
    if symbol in ("GC=F",) or sym == "XAUUSD":
        lot = risk_usd / (sl_distance * 100.0)
    elif symbol in ("SI=F",) or sym == "XAGUSD":
        lot = risk_usd / (sl_distance * 50.0)
    elif symbol in ("CL=F", "BZ=F"):
        lot = risk_usd / (sl_distance * 1000.0)
    elif symbol in ("NG=F", "HG=F", "PL=F", "PA=F"):
        lot = risk_usd / (sl_distance * 100.0)

    # ── Crypto ───────────────────────────────────────────────
    elif sym in ("BTCUSD", "ETHUSD") or symbol in ("BTC-USD", "ETH-USD"):
        lot = round(risk_usd / sl_distance, 6)
        return lot

    # ── Indices ──────────────────────────────────────────────
    elif sym in ("GSPC", "NDX", "DJI", "GDAXI", "FCHI", "FTSE", "N225", "HSI"):
        lot = risk_usd / (sl_distance * 10.0)

    # ── JPY (toutes paires) ──────────────────────────────────
    elif sym.endswith("JPY"):
        sl_pips = sl_distance / 0.01
        pip_val = 1000.0 / entry      # ~$10/pip/lot quand rate≈100
        lot = risk_usd / (sl_pips * pip_val)

    # ── USD comme base (USDCHF, USDCAD, USDHKD, USDSGD…) ───
    elif sym.startswith("USD"):
        sl_pips = sl_distance / 0.0001
        pip_val = 10.0 / entry
        lot = risk_usd / (sl_pips * pip_val)

    # ── XXX/USD standard (EUR, GBP, AUD, NZD, NZD…) ────────
    else:
        sl_pips = sl_distance / 0.0001
        lot = risk_usd / (sl_pips * 10.0)

    lot = max(0.01, round(lot, 2))
    return lot


def fetch(symbol: str, interval: str, period: str = "5d",
          retries: int = 3, retry_delay: int = 15) -> pd.DataFrame:
    """
    Télécharge les OHLCV via yfinance avec retry automatique.

    CORRECTIF yfinance >= 0.2.x :
    yf.download() retourne un MultiIndex de colonnes meme pour 1 seul symbole.
    On aplatit avant de passer en minuscules.

    CORRECTIF Rate Limit :
    En cas de YFRateLimitError, on attend retry_delay secondes et on reessaie
    jusqu'a retries fois avant de retourner un DataFrame vide.
    """
    for attempt in range(1, retries + 1):
        try:
            try:
                df = yf.download(
                    symbol,
                    interval=interval,
                    period=period,
                    auto_adjust=True,
                    progress=False,
                    multi_level_index=False,
                )
            except TypeError:
                df = yf.download(
                    symbol,
                    interval=interval,
                    period=period,
                    auto_adjust=True,
                    progress=False,
                )

            if df.empty:
                return df

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0).str.lower()
            else:
                df.columns = df.columns.str.lower()

            df.dropna(inplace=True)
            return df

        except Exception as e:
            err_str = str(e).lower()
            if ("rate" in err_str or "too many" in err_str or "429" in err_str) \
                    and attempt < retries:
                time.sleep(retry_delay * attempt)
                continue
            return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
#  ANALYSE HTF — BIAIS DIRECTIONNEL
# ─────────────────────────────────────────────────────────────
def htf_bias(df: pd.DataFrame) -> str:
    """
    Détermine le biais H1 via Higher Highs / Lower Lows (20 dernières bougies).
    Retourne 'BEARISH', 'BULLISH' ou 'NEUTRAL'.
    """
    highs  = df["high"].iloc[-20:].values
    lows   = df["low"].iloc[-20:].values
    closes = df["close"].iloc[-20:].values

    # EMA 20 rapide
    ema = np.convolve(closes, np.ones(8) / 8, mode="valid")
    trend_up   = closes[-1] > ema[-1]

    # Swing High / Low comparaison
    last_hh = highs[-1] < highs[-5:].max()    # prix récent sous dernier HH → bearish
    last_ll  = lows[-1] < lows[-10:].min() * 1.002

    if not trend_up and last_hh:
        return "BEARISH"
    elif trend_up and not last_hh:
        return "BULLISH"
    return "NEUTRAL"

# ─────────────────────────────────────────────────────────────
#  DÉTECTION BOS — Break of Structure
# ─────────────────────────────────────────────────────────────
def detect_bos(df: pd.DataFrame) -> list[dict]:
    """
    Détecte les cassures de structure (BOS).
    Un BOS bearish = close < swing low des N dernières bougies.
    """
    bos_list  = []
    lookback  = 10

    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        close  = df["close"].iloc[i]
        swing_low  = window["low"].min()
        swing_high = window["high"].max()

        if close < swing_low:
            bos_list.append({"index": i, "type": "bearish", "level": swing_low})
        elif close > swing_high:
            bos_list.append({"index": i, "type": "bullish", "level": swing_high})

    return bos_list

# ─────────────────────────────────────────────────────────────
#  DÉTECTION FVG — Fair Value Gap
# ─────────────────────────────────────────────────────────────
def detect_fvg(df: pd.DataFrame) -> list[FVG]:
    """
    FVG = gap entre bougie[i-2].high et bougie[i].low  (bearish)
        ou bougie[i-2].low  et bougie[i].high (bullish)
    Filtre par taille minimum.
    """
    fvgs = []
    for i in range(2, len(df)):
        mid_price = df["close"].iloc[i]
        # Bearish FVG
        top    = df["high"].iloc[i - 2]
        bottom = df["low"].iloc[i]
        if bottom > top and (bottom - top) / mid_price > FVG_MIN_RATIO:
            fvgs.append(FVG("bearish", bottom, top, i))
        # Bullish FVG
        top    = df["high"].iloc[i]
        bottom = df["low"].iloc[i - 2]
        if top > bottom and (top - bottom) / mid_price > FVG_MIN_RATIO:
            fvgs.append(FVG("bullish", top, bottom, i))

    return fvgs

# ─────────────────────────────────────────────────────────────
#  DÉTECTION ORDER BLOCK
# ─────────────────────────────────────────────────────────────
def detect_order_blocks(df: pd.DataFrame, bos_list: list[dict]) -> list[OrderBlock]:
    """
    OB = dernière bougie haussière avant un BOS baissier (et vice-versa).
    """
    obs = []
    for bos in bos_list[-5:]:          # 5 derniers BOS seulement
        idx = bos["index"]
        if idx < OB_LOOKBACK:
            continue

        if bos["type"] == "bearish":
            # Cherche la dernière bougie bullish avant le BOS
            for j in range(idx - 1, idx - OB_LOOKBACK - 1, -1):
                if df["close"].iloc[j] > df["open"].iloc[j]:
                    obs.append(OrderBlock(
                        "bearish",
                        df["high"].iloc[j],
                        df["low"].iloc[j],
                        j
                    ))
                    break
        elif bos["type"] == "bullish":
            for j in range(idx - 1, idx - OB_LOOKBACK - 1, -1):
                if df["close"].iloc[j] < df["open"].iloc[j]:
                    obs.append(OrderBlock(
                        "bullish",
                        df["high"].iloc[j],
                        df["low"].iloc[j],
                        j
                    ))
                    break

    return obs

# ─────────────────────────────────────────────────────────────
#  PRISE DE LIQUIDITÉ (Stop Hunt)
# ─────────────────────────────────────────────────────────────
def detect_liquidity_sweep(df: pd.DataFrame) -> dict:
    """
    Stop Hunt = price dépasse un swing H/L récent puis revient.
    Retourne le dernier sweep détecté.
    """
    result = {"bullish_sweep": False, "bearish_sweep": False, "level": None}
    window  = df.iloc[-30:]
    swing_high = window["high"].max()
    swing_low  = window["low"].min()
    last_high  = df["high"].iloc[-1]
    last_low   = df["low"].iloc[-1]
    last_close = df["close"].iloc[-1]

    # Sweep haussier (price spike above high puis repli)
    if last_high > swing_high * (1 + LIQ_THRESHOLD) and last_close < swing_high:
        result["bearish_sweep"] = True
        result["level"]         = swing_high

    # Sweep baissier (price spike below low puis rebond)
    if last_low < swing_low * (1 - LIQ_THRESHOLD) and last_close > swing_low:
        result["bullish_sweep"] = True
        result["level"]         = swing_low

    return result

# ─────────────────────────────────────────────────────────────
#  BREAKER BLOCK  (OB mitiqué qui flippe de direction)
# ─────────────────────────────────────────────────────────────
def detect_breaker_blocks(df: pd.DataFrame, bos_list: list[dict]) -> list[dict]:
    """
    Breaker Block = Order Block qui a été mitiqué (prix a traversé la zone)
    puis retesté → flippe en zone opposée.

    Logique :
      BOS baissier → cherche la dernière bougie bullish avant le BOS
                     Si le prix est revenu tester cette zone par en haut → Breaker bearish
      BOS haussier → cherche la dernière bougie bearish avant le BOS
                     Si le prix est revenu tester cette zone par en bas → Breaker bullish

    Utilisé comme setup clé (voir charts BTC 45MIN FVG + Breaker).
    """
    breakers = []
    for bos in bos_list[-6:]:
        idx = bos["index"]
        if idx < OB_LOOKBACK + 2 or idx + 3 >= len(df):
            continue
        bos_type = bos["type"]

        for j in range(idx - 1, max(idx - OB_LOOKBACK - 1, 0), -1):
            is_bull = df["close"].iloc[j] > df["open"].iloc[j]
            ob_hi   = df["high"].iloc[j]
            ob_lo   = df["low"].iloc[j]

            if bos_type == "bearish" and is_bull:
                # OB bullish retesté par en haut = Breaker bearish
                post_high = df["high"].iloc[idx: min(idx + 15, len(df))].max()
                if ob_lo <= post_high <= ob_hi * 1.001:
                    breakers.append({
                        "direction": "bearish",
                        "top"      : ob_hi,
                        "bottom"   : ob_lo,
                        "index"    : j,
                    })
                    break

            elif bos_type == "bullish" and not is_bull:
                # OB bearish retesté par en bas = Breaker bullish
                post_low = df["low"].iloc[idx: min(idx + 15, len(df))].min()
                if ob_lo * 0.999 <= post_low <= ob_hi:
                    breakers.append({
                        "direction": "bullish",
                        "top"      : ob_hi,
                        "bottom"   : ob_lo,
                        "index"    : j,
                    })
                    break

    return breakers


# ─────────────────────────────────────────────────────────────
#  TRENDLINE LIQUIDITY  (liquidité au-dessus/dessous d'une TL)
# ─────────────────────────────────────────────────────────────
def detect_trendline_liquidity(df: pd.DataFrame, direction: str) -> bool:
    """
    Trendline Liquidity = série de 3+ swing highs/lows formant une trendline
    avec des stops accumulés au-dessus/en-dessous.
    Retourne True si le prix vient de sweeper cette trendline (stop hunt).

    Vu sur le chart EUR/USD : Trendline liquidity sweep avant short.
    """
    if len(df) < 25:
        return False

    window = df.iloc[-25:]

    def swing_highs(w):
        sh = []
        for i in range(1, len(w) - 1):
            if w["high"].iloc[i] > w["high"].iloc[i-1] and w["high"].iloc[i] > w["high"].iloc[i+1]:
                sh.append((i, w["high"].iloc[i]))
        return sh

    def swing_lows(w):
        sl = []
        for i in range(1, len(w) - 1):
            if w["low"].iloc[i] < w["low"].iloc[i-1] and w["low"].iloc[i] < w["low"].iloc[i+1]:
                sl.append((i, w["low"].iloc[i]))
        return sl

    last_close = window["close"].iloc[-1]

    if direction == "bearish":
        shs = swing_highs(window)
        if len(shs) >= 2:
            # Highs descendants = trendline baissière = liquidité au-dessus
            if shs[-1][1] < shs[-2][1]:
                tl_level = shs[-1][1]
                last_high = window["high"].iloc[-1]
                # Sweep = dernier high dépasse la TL puis close en dessous
                if last_high > tl_level and last_close < tl_level:
                    return True

    elif direction == "bullish":
        sls = swing_lows(window)
        if len(sls) >= 2:
            # Lows ascendants = trendline haussière = liquidité en dessous
            if sls[-1][1] > sls[-2][1]:
                tl_level = sls[-1][1]
                last_low = window["low"].iloc[-1]
                # Sweep = dernier low passe sous la TL puis close au-dessus
                if last_low < tl_level and last_close > tl_level:
                    return True

    return False


# ─────────────────────────────────────────────────────────────
#  FVG VALIDE (non mitiqué)
# ─────────────────────────────────────────────────────────────
def is_fvg_unmitigated(df: pd.DataFrame, fvg: "FVG") -> bool:
    """
    Un FVG est 'valid' si le prix n'a PAS fermé à l'intérieur de la zone
    depuis sa formation. Vu sur EUR/USD : 'Valid FVG' comme zone d'entrée.
    """
    if fvg.index + 1 >= len(df):
        return True

    lo = min(fvg.top, fvg.bottom)
    hi = max(fvg.top, fvg.bottom)

    for i in range(fvg.index + 1, len(df)):
        close = df["close"].iloc[i]
        if lo <= close <= hi:
            return False   # Mitiqué — prix a fermé dedans

    return True   # Toujours valide


# ─────────────────────────────────────────────────────────────
#  FVG 30min  (équivalent 45MIN FVG des charts BTC)
# ─────────────────────────────────────────────────────────────
def detect_fvg_30m(df_30m: pd.DataFrame, direction: str) -> Optional["FVG"]:
    """
    Détecte un FVG actif sur le 30min (substitut du 45min que yfinance
    ne supporte pas). Prix actuel doit être dans la zone du FVG.
    Logique identique à active_fvg() mais sur le 30m.
    """
    fvgs = detect_fvg(df_30m)
    return active_fvg(df_30m, fvgs, direction)


# ─────────────────────────────────────────────────────────────
#  UPCOMING BOS  (prochain niveau de structure à casser = cible TP)
# ─────────────────────────────────────────────────────────────
def detect_upcoming_bos(df: pd.DataFrame, direction: str) -> Optional[float]:
    """
    Upcoming BOS = prochain swing low (pour short) ou swing high (pour long)
    qui n'a pas encore été cassé. Utilisé comme niveau cible (TP).
    Vu sur EUR/USD chart : 'Upcoming BOS' comme target final.
    """
    if len(df) < 15:
        return None

    window = df.iloc[-30:]

    if direction == "SHORT":
        # Cherche le swing low le plus récent non cassé = prochain BOS baissier
        candidate = None
        for i in range(len(window) - 2, 0, -1):
            lo = window["low"].iloc[i]
            if lo < window["low"].iloc[i-1] and lo < window["low"].iloc[i+1]:
                # Vérifie que ce low n'a pas encore été cassé
                subsequent = window["low"].iloc[i+1:]
                if (subsequent > lo).all():
                    candidate = lo
                    break
        return candidate

    elif direction == "LONG":
        candidate = None
        for i in range(len(window) - 2, 0, -1):
            hi = window["high"].iloc[i]
            if hi > window["high"].iloc[i-1] and hi > window["high"].iloc[i+1]:
                subsequent = window["high"].iloc[i+1:]
                if (subsequent < hi).all():
                    candidate = hi
                    break
        return candidate

    return None


# ═════════════════════════════════════════════════════════════
#  PRE-BOS INTENT DETECTOR  — v1.0
#  Détecte l'intention institutionnelle AVANT la cassure BOS.
#
#  Logique : Sweep → Displacement → Micro-FVG → Momentum Shift
#  Scoring (100 pts) :
#    Sweep liquidité          = 30 pts
#    Displacement ≥ ATR×1.5  = 25 pts   ← filtre anti-faux signal
#    Micro-FVG présent        = 20 pts
#    Momentum shift / mini-BOS= 15 pts
#    Biais HTF aligné         = 10 pts
#  Trade si score ≥ 70 (3 signaux sur 4 + HTF)
# ═════════════════════════════════════════════════════════════

PRE_BOS_SCORE_MIN     = 80      # seuil relevé : 70 → 80 (évite signaux faibles sans HTF)
PRE_BOS_SWEEP_THRESH  = 0.0003  # spike min au-delà du swing (3 pips)
PRE_BOS_DISP_ATR_MULT = 1.5     # displacement ≥ ATR × 1.5
PRE_BOS_MICRO_FVG_MIN = 0.0001  # ratio gap minimal (plus sensible que FVG classique)
PRE_BOS_MOM_LOOKBACK  = 6       # bougies pour détecter le mini-BOS interne


@dataclass
class PreBosSignal:
    """Résultat d'une analyse Pre-BOS. Converti en Signal standard avant envoi."""
    symbol          : str
    direction       : str
    score           : int
    entry           : float
    sl              : float
    tp              : float
    rr              : float
    sweep_level     : float
    displacement_ok : bool
    micro_fvg_ok    : bool
    momentum_ok     : bool
    htf_aligned     : bool
    timestamp       : datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reasons         : list = field(default_factory=list)


def _prebos_detect_sweep(df: pd.DataFrame, direction: str) -> tuple[bool, Optional[float]]:
    """
    Détecte un sweep de liquidité récent (stop hunt).

    Seuil adaptatif : ATR × 0.2 (s'adapte automatiquement à chaque marché :
    BTC, Forex, Gold, Indices — plus besoin de threshold fixe en pips).

    BEARISH sweep :
      wick au-dessus du swing high des 20 dernières bougies
      + clôture EN-DESSOUS du swing high.

    BULLISH sweep :
      wick en-dessous du swing low
      + clôture AU-DESSUS.

    Retourne (sweep_ok, niveau_sweepé).
    """
    if len(df) < 25:
        return False, None

    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    if atr == 0 or np.isnan(atr):
        return False, None

    # Seuil adaptatif marché (remplace PRE_BOS_SWEEP_THRESH fixe)
    adaptive_thresh = atr * 0.20

    window     = df.iloc[-25:-1]
    swing_high = window["high"].max()
    swing_low  = window["low"].min()

    last_h = df["high"].iloc[-2]
    last_l = df["low"].iloc[-2]
    last_c = df["close"].iloc[-2]

    if direction == "SHORT":
        if last_h > swing_high + adaptive_thresh and last_c < swing_high:
            return True, swing_high

    elif direction == "LONG":
        if last_l < swing_low - adaptive_thresh and last_c > swing_low:
            return True, swing_low

    return False, None


def _prebos_detect_displacement(df: pd.DataFrame, direction: str) -> tuple[bool, float]:
    """
    Détecte une bougie impulsive (displacement) post-sweep.

    Critères :
      • Corps ≥ ATR × PRE_BOS_DISP_ATR_MULT (1.5×)  ← FILTRE ANTI-FAUX SIGNAL
      • Corps ≥ 60% de la bougie totale (peu de mèches)
      • Clôture dans le sens du move prévu

    Si aucune des 3 dernières bougies clôturées ne valide → False.
    Retourne (displacement_ok, body_size).
    """
    if len(df) < 16:
        return False, 0.0

    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    if atr == 0 or np.isnan(atr):
        return False, 0.0

    for i in range(-2, -5, -1):
        o   = df["open"].iloc[i]
        h   = df["high"].iloc[i]
        l   = df["low"].iloc[i]
        cl  = df["close"].iloc[i]
        body      = abs(cl - o)
        candle_rng = h - l
        if body == 0 or candle_rng == 0:
            continue
        # Filtre anti-faux signal (du brief) : body < ATR×1.5 → rejeté
        if body < atr * PRE_BOS_DISP_ATR_MULT:
            continue
        # Ratio corps/total ≥ 60%
        if body / candle_rng < 0.60:
            continue
        # Direction cohérente
        if direction == "LONG"  and cl <= o:
            continue
        if direction == "SHORT" and cl >= o:
            continue
        return True, body

    return False, 0.0


def _prebos_detect_micro_fvg(df: pd.DataFrame, direction: str) -> Optional[dict]:
    """
    Détecte le micro Fair Value Gap créé par la bougie impulsive.
    Plus sensible que le FVG classique (ratio minimal réduit).

    FVG bullish : gap entre bougie[i-2].low et bougie[i].high (zone non traversée).
    FVG bearish : gap entre bougie[i-2].high et bougie[i].low.

    Retourne un dict {top, bottom, mid} ou None.
    """
    if len(df) < 6:
        return None

    for i in range(len(df) - 1, max(len(df) - 9, 2), -1):
        h_prev2 = df["high"].iloc[i - 2]
        l_prev2 = df["low"].iloc[i - 2]
        h_curr  = df["high"].iloc[i]
        l_curr  = df["low"].iloc[i]
        ref     = df["close"].iloc[i]

        if direction == "SHORT":
            gap_bottom = h_prev2
            gap_top    = l_curr
            if gap_top > gap_bottom and ref > 0:
                if (gap_top - gap_bottom) / ref > PRE_BOS_MICRO_FVG_MIN:
                    return {"top": gap_top, "bottom": gap_bottom,
                            "mid": (gap_top + gap_bottom) / 2}

        elif direction == "LONG":
            gap_top    = l_prev2
            gap_bottom = h_curr
            if gap_top > gap_bottom and ref > 0:
                if (gap_top - gap_bottom) / ref > PRE_BOS_MICRO_FVG_MIN:
                    return {"top": gap_top, "bottom": gap_bottom,
                            "mid": (gap_top + gap_bottom) / 2}

    return None


def _prebos_detect_momentum(df: pd.DataFrame, direction: str) -> bool:
    """
    Détecte un changement de momentum (mini-BOS interne).

    SHORT : ≥ 2 Lower Highs consécutifs  OU  cassure d'un micro swing low.
    LONG  : ≥ 2 Higher Lows consécutifs  OU  cassure d'un micro swing high.
    """
    n = PRE_BOS_MOM_LOOKBACK + 2
    if len(df) < n + 2:
        return False

    window = df.iloc[-(n + 2):]
    highs  = window["high"].values
    lows   = window["low"].values
    closes = window["close"].values
    sz     = len(highs)

    if direction == "SHORT":
        lh_count = sum(1 for i in range(1, sz) if highs[i] < highs[i - 1])
        if lh_count >= 2:
            return True
        micro_low = lows[-PRE_BOS_MOM_LOOKBACK:-2].min()
        if closes[-1] < micro_low:
            return True

    elif direction == "LONG":
        hl_count = sum(1 for i in range(1, sz) if lows[i] > lows[i - 1])
        if hl_count >= 2:
            return True
        micro_high = highs[-PRE_BOS_MOM_LOOKBACK:-2].max()
        if closes[-1] > micro_high:
            return True

    return False


def _prebos_score(sweep_ok, displacement_ok, micro_fvg_ok,
                  momentum_ok, htf_aligned) -> tuple[int, list]:
    """Scoring Pre-BOS sur 100. Trade si ≥ 70."""
    score, reasons = 0, []
    if sweep_ok:
        score += 30
        reasons.append("🔥 Sweep de liquidité (stop hunt)  (+30)")
    if displacement_ok:
        score += 25
        reasons.append("⚡ Displacement impulsif ≥ ATR×1.5  (+25)")
    if micro_fvg_ok:
        score += 20
        reasons.append("📍 Micro-FVG (déséquilibre post-impulsion)  (+20)")
    if momentum_ok:
        score += 15
        reasons.append("📈 Momentum shift / mini-BOS interne  (+15)")
    if htf_aligned:
        score += 10
        reasons.append("✅ Biais HTF aligné  (+10)")
    return min(score, 100), reasons


def _prebos_levels(df: pd.DataFrame, direction: str,
                   sweep_level: float, micro_fvg: Optional[dict],
                   symbol: str = "") -> tuple[float, float, float, float]:
    """
    Calcule entry / SL / TP / RR pour un signal Pre-BOS.

    ENTRÉE   → 50% du micro-FVG  (ou close si pas de FVG)
    STOP LOSS→ au-delà du niveau sweepé + buffer défensif
    TP       → prochaine zone de liquidité (swing H/L opposé sur 30 bougies)
               garantit RR net ≥ 3 après spread.
    """
    atr    = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    close  = df["close"].iloc[-1]
    spread = get_spread(symbol) if symbol else 0.0
    dec    = 2 if close > 100 else 5

    # Buffer SL défensif : 55% ATR minimum (était 35% → trop serré)
    # Garantit que le bruit normal du marché ne touche pas le SL
    buf = max(atr * 0.55, spread * 3.0)

    # 1. Entrée
    entry = round(micro_fvg["mid"] if micro_fvg else close, dec)

    # 2. Stop Loss — placé au-delà du sweep avec buffer défensif réel
    if direction == "LONG":
        sl = round(sweep_level - buf, dec)
    else:
        sl = round(sweep_level + buf, dec)

    risk = abs(entry - sl)
    if risk <= 0:
        return entry, sl, entry, 0.0

    # 3. Take Profit — basé sur la prochaine zone de liquidité RÉELLE
    # On cherche les swing highs/lows sur 50 bougies (plus large = meilleur TP)
    # On ne force JAMAIS un TP artificiel : si la liquidité est loin → RR élevé,
    # si elle est proche et le RR < MIN_RR → signal rejeté en aval.
    window = df.iloc[-50:]
    if direction == "SHORT":
        candidates = sorted([
            window["low"].iloc[i]
            for i in range(len(window) - 2, 0, -1)
            if (window["low"].iloc[i] < window["low"].iloc[i - 1]
                and window["low"].iloc[i] < window["low"].iloc[i + 1]
                and window["low"].iloc[i] < entry - risk)  # TP doit dépasser le risk
        ])
        # Prend le swing low le plus proche atteignable (pas forcément le plus bas)
        tp_nat = candidates[0] if candidates else entry - atr * 5
        tp = round(tp_nat, dec)
        gain = (entry - tp) - spread
    else:
        candidates = sorted([
            window["high"].iloc[i]
            for i in range(len(window) - 2, 0, -1)
            if (window["high"].iloc[i] > window["high"].iloc[i - 1]
                and window["high"].iloc[i] > window["high"].iloc[i + 1]
                and window["high"].iloc[i] > entry + risk)
        ], reverse=True)
        tp_nat = candidates[-1] if candidates else entry + atr * 5
        tp = round(tp_nat, dec)
        gain = (tp - entry) - spread

    # RR réel — pas de plancher artificiel, pas de plafond
    rr = round(gain / risk, 2) if gain > 0 and risk > 0 else 0.0
    return entry, sl, tp, rr


def analyse_pre_bos(symbol: str, df_ltf: pd.DataFrame,
                    df_htf: pd.DataFrame, direction: str,
                    silent: bool = False) -> Optional[PreBosSignal]:
    """
    Moteur Pre-BOS : détecte l'intention institutionnelle AVANT le BOS.

    Appelé depuis analyse() AVANT les filtres BOS classiques.
    Si un signal Pre-BOS est détecté avec score ≥ 70, il est retourné
    comme Signal standard et envoyé via tg_notify() exactement comme
    un signal SMC classique.

    Flow :
      1. Session active ?          → sinon None
      2. Sweep détecté ?           → sinon None  (condition sine qua non)
      3. Displacement ≥ ATR×1.5 ? → +25 pts (filtre anti-faux signal)
      4. Micro-FVG présent ?       → +20 pts
      5. Momentum shift ?          → +15 pts
      6. HTF aligné ?              → +10 pts
      7. Score ≥ 70 ?              → signal valide
    """
    if df_ltf.empty or df_htf.empty or len(df_ltf) < 25:
        return None

    # ── 1. SWEEP (condition sine qua non) ─────────────────────
    sweep_ok, sweep_level = _prebos_detect_sweep(df_ltf, direction)
    if not sweep_ok or sweep_level is None:
        return None

    # ── 2. DISPLACEMENT ───────────────────────────────────────
    displacement_ok, _ = _prebos_detect_displacement(df_ltf, direction)

    # ── 3. MICRO-FVG ──────────────────────────────────────────
    micro_fvg    = _prebos_detect_micro_fvg(df_ltf, direction)
    micro_fvg_ok = micro_fvg is not None

    # ── 4. MOMENTUM SHIFT ─────────────────────────────────────
    momentum_ok = _prebos_detect_momentum(df_ltf, direction)

    # ── 5. BIAIS HTF — OBLIGATOIRE (pas juste un bonus) ──────────
    # Un Pre-BOS contre le biais HTF = trade suicidaire → rejet immédiat
    htf_bias_val = htf_bias(df_htf)
    htf_aligned  = (
        (direction == "SHORT" and htf_bias_val == "BEARISH")
        or (direction == "LONG"  and htf_bias_val == "BULLISH")
    )
    if not htf_aligned:
        return None   # Contre le biais HTF → pas de signal, peu importe le score

    # ── 6. SCORING ────────────────────────────────────────────
    score, reasons = _prebos_score(
        sweep_ok, displacement_ok, micro_fvg_ok, momentum_ok, htf_aligned
    )

    if score < PRE_BOS_SCORE_MIN:
        return None

    # ── 7. NIVEAUX ────────────────────────────────────────────
    try:
        entry, sl, tp, rr = _prebos_levels(
            df_ltf, direction, sweep_level, micro_fvg, symbol
        )
    except Exception:
        atr   = (df_ltf["high"] - df_ltf["low"]).rolling(14).mean().iloc[-1]
        close = df_ltf["close"].iloc[-1]
        dec   = 2 if close > 100 else 5
        entry = round(micro_fvg["mid"] if micro_fvg else close, dec)
        buf   = atr * 0.35
        sl    = round(sweep_level + buf if direction == "SHORT" else sweep_level - buf, dec)
        tp    = round(entry - atr * 4   if direction == "SHORT" else entry + atr * 4,   dec)
        risk  = abs(entry - sl)
        rr    = round(abs(tp - entry) / risk, 2) if risk > 0 else 0.0

    if rr < MIN_RR:
        return None

    if not silent:
        dec_d = 2 if entry > 100 else 5
        print(f"\n  {c('⚡ PRE-BOS SIGNAL', 'yellow')}  →  {c(direction, 'red' if direction == 'SHORT' else 'green')}")
        print(f"  Sweep @ {round(sweep_level, dec_d)}  |  Score {score}/100")
        print(f"  Entry {round(entry, dec_d)}  SL {round(sl, dec_d)}  TP {round(tp, dec_d)}  RR 1:{rr}")

    return PreBosSignal(
        symbol=symbol, direction=direction, score=score,
        entry=entry, sl=sl, tp=tp, rr=rr,
        sweep_level=sweep_level,
        displacement_ok=displacement_ok, micro_fvg_ok=micro_fvg_ok,
        momentum_ok=momentum_ok, htf_aligned=htf_aligned,
        reasons=reasons,
    )


def tg_format_pre_bos(sig: PreBosSignal, tier: str = "") -> str:
    """Formate un PreBosSignal en message HTML Telegram (même style que tg_format_signal)."""
    dir_emoji  = "🔴 SHORT" if sig.direction == "SHORT" else "🟢 LONG"
    score_bar  = "█" * (sig.score // 10) + "░" * (10 - sig.score // 10)
    rr_bar     = "⭐" * min(int(sig.rr), 5)
    ts         = sig.timestamp.strftime("%d/%m/%Y %H:%M UTC")
    dec        = 2 if sig.entry > 100 else 5
    risk_d     = round(abs(sig.entry - sig.sl), dec)
    gain_d     = round(abs(sig.tp - sig.entry), dec)
    gain_usd   = round(RISK_USD * sig.rr, 2)
    spread_d   = round(get_spread(sig.symbol), dec)

    msg = (
        f"<b>⚡ PRE-BOS SIGNAL  —  AVANT LE BOS</b>\n"
        f"{'─'*30}\n"
        f"<b>Marché   :</b>  <code>{sig.symbol}</code>\n"
        f"<b>Direction:</b>  <b>{dir_emoji}</b>\n"
        f"<b>Mode     :</b>  <i>Sweep + Impulsion (avant BOS)</i>\n"
        f"{'─'*30}\n"
        f"<b>📍 Entrée    :</b>  <code>{sig.entry}</code>  ← 50% Micro-FVG\n"
        f"<b>🔴 Stop Loss :</b>  <code>{sig.sl}</code>   <i>(risk {risk_d})</i>\n"
        f"<b>🟢 Take Profit:</b> <code>{sig.tp}</code>   <i>(gain brut {gain_d})</i>\n"
        f"<b>📊 Spread    :</b>  <code>{spread_d}</code>\n"
        f"<b>⚖  R : R net :</b>  <b>1 : {sig.rr}</b>  {rr_bar}\n"
        f"{'─'*30}\n"
        f"<b>🎯 Sweep @  :</b>  <code>{sig.sweep_level}</code>\n"
        f"<b>💰 Risque   :</b>  ${RISK_USD}  →  gain ≈ <b>${gain_usd}</b>\n"
        f"<b>Score :</b>  [{score_bar}]  {sig.score}/100\n"
        f"<b>Confluence :</b>\n"
    )
    for r in sig.reasons:
        msg += f"  • {r}\n"
    msg += (
        f"{'─'*30}\n"
        f"<i>⚠ Attends le retour sur le micro-FVG — PAS d'entrée au marché</i>\n"
        f"<i>🕐 {ts}</i>"
    )
    return msg


# ─── FIN PRE-BOS INTENT DETECTOR ────────────────────────────

# ─────────────────────────────────────────────────────────────
#  VÉRIFICATION FVG ACTIF (prix dans la zone)
# ─────────────────────────────────────────────────────────────
def active_fvg(df: pd.DataFrame, fvgs: list[FVG], direction: str) -> Optional[FVG]:
    """Retourne le FVG le plus récent dans lequel le prix se trouve."""
    price = df["close"].iloc[-1]
    for fvg in reversed(fvgs):
        if fvg.direction != direction:
            continue
        lo, hi = min(fvg.top, fvg.bottom), max(fvg.top, fvg.bottom)
        if lo <= price <= hi:
            return fvg
    return None

# ─────────────────────────────────────────────────────────────
#  MOTEUR DE SCORE
# ─────────────────────────────────────────────────────────────
def compute_score(
    bias: str,
    direction: str,
    has_bos: bool,
    has_fvg: bool,
    has_ob: bool,
    liquidity_taken: bool,
    bias_aligned: bool,
    # ── Bonus 3-TF ──────────────────────────────
    mtf_bos: bool = False,       # BOS confirmé sur M15
    mtf_ob: bool  = False,       # OB confirmé sur M15
    ltf_fvg: bool = False,       # FVG actif sur M5
    ltf_confirm: bool = False,   # Bougie confirmation M5 (engulfing / pin bar)
    entry_m1: bool = False,      # Trigger M1 actif
    # ── Bonus setups avancés (charts BTC + EUR/USD) ──────────
    breaker_block: bool  = False,  # Breaker Block détecté (OB mitiqué flipé)
    fvg_30m: bool        = False,  # FVG 30min actif (équivalent 45MIN FVG BTC)
    fvg_unmitigated: bool = False, # FVG Valid (non mitiqué) — EUR/USD setup
    trendline_liq: bool  = False,  # Trendline Liquidity sweepée
    older_block: bool    = False,  # Older Block HTF confirmé (H1 OB actif)
) -> tuple[int, list[str]]:
    """
    Score composite sur 100 — architecture multi-TF avec setups avancés.

    Setups intégrés :
      • BTC  1H  : 45MIN FVG + Breaker Block + Liquidity Sweep
      • EUR/USD 15m : Older Block + Trendline Liq + Valid FVG + Upcoming BOS
    """
    score   = 0
    reasons = []

    # ── H1 Biais (base) ──────────────────────────────────────
    if bias_aligned:
        score += 20
        reasons.append(f"✅ Biais H1 {bias} aligné  (+20)")

    # ── M15 Structure ─────────────────────────────────────────
    if mtf_bos:
        score += 15
        reasons.append("✅ BOS M15 confirmé  (+15)")
    elif has_bos:
        score += 8
        reasons.append("☑️ BOS M5 détecté  (+8)")

    if mtf_ob:
        score += 10
        reasons.append("✅ Order Block M15 validé  (+10)")
    elif has_ob:
        score += 5
        reasons.append("☑️ Order Block M5  (+5)")

    # ── Liquidité prise ──────────────────────────────────────
    if liquidity_taken:
        score += 12
        reasons.append("✅ Stop Hunt / Liquidité prise  (+12)")

    # ── M5 FVG + confirmation bougie ─────────────────────────
    if ltf_fvg:
        score += 10
        reasons.append("✅ FVG M5 actif — prix dans la zone  (+10)")
    elif has_fvg:
        score += 5
        reasons.append("☑️ FVG détecté  (+5)")

    if ltf_confirm:
        score += 8
        reasons.append("✅ Bougie de confirmation M5 (engulfing/pin)  (+8)")

    # ── Trigger M1 ───────────────────────────────────────────
    if entry_m1:
        score += 5
        reasons.append("⚡ Trigger M1 actif — entrée précise  (+5)")

    # ══════════════════════════════════════════════════════════
    #  SETUPS AVANCÉS  (BTC 45MIN FVG + EUR/USD Trendline)
    # ══════════════════════════════════════════════════════════

    # Breaker Block (OB mitiqué flipé — setup BTC chart)
    if breaker_block:
        score += 12
        reasons.append("🔥 Breaker Block détecté — zone flippée  (+12)")

    # FVG 30min / équivalent 45MIN FVG (chart BTC)
    if fvg_30m:
        score += 10
        reasons.append("📍 FVG 30min actif — zone 45min POI  (+10)")

    # FVG Valid non mitiqué (chart EUR/USD — 'Valid FVG')
    if fvg_unmitigated:
        score += 8
        reasons.append("✅ FVG valide non mitiqué — entrée propre  (+8)")

    # Trendline Liquidity sweepée (chart EUR/USD)
    if trendline_liq:
        score += 10
        reasons.append("🎯 Trendline Liquidity sweepée — stop hunt  (+10)")

    # Older Block HTF actif (chart EUR/USD — résistance H1)
    if older_block:
        score += 10
        reasons.append("🏛️ Older Block HTF actif — confluence HTF  (+10)")

    return min(score, 100), reasons

# ─────────────────────────────────────────────────────────────
#  CALCUL ENTRÉE / SL / TP — RR NET SPREAD GARANTI ≥ 3
# ─────────────────────────────────────────────────────────────
def compute_sl_tp(
    df: pd.DataFrame,
    direction: str,
    ob: Optional[OrderBlock],
    min_rr: float = MIN_RR,
    symbol: str = "",
    fvg: Optional["FVG"] = None,
) -> tuple[float, float, float, float]:
    """
    Retourne (entry, sl, tp, rr_net) avec RR net spread GARANTI ≥ min_rr.

    ═══ LOGIQUE RÉELLE ═══════════════════════════════════════════

    Le trader paie le spread UNE FOIS à l'ouverture (buy ask / sell bid).
    Quand le TP est touché, le P&L réel est :
        LONG  : P&L = (TP - entry) - spread   [achat au ask = entry + spread/2 × 2]
        SHORT : P&L = (entry - TP) - spread

    Pour garantir P&L = risk × min_rr quand TP est touché :
        LONG  : TP = entry + risk × min_rr + spread
        SHORT : TP = entry - risk × min_rr - spread

    Le TP ATR × 4 est pris s'il est encore plus favorable (plus loin).

    ═══ ENTRÉE ════════════════════════════════════════════════════
    Priorité 1 : milieu du FVG M5/M15 actif  → zone de valeur optimale
    Priorité 2 : close M5 courant            → fallback

    ═══ STOP LOSS ═════════════════════════════════════════════════
    LONG  : sl = ob.bottom - atr × 0.25   (sous le bas de l'OB)
    SHORT : sl = ob.top    + atr × 0.25   (au-dessus du haut de l'OB)
    Sans OB : sl = entry ∓ atr × 1.5
    """
    atr    = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    close  = df["close"].iloc[-1]
    spread = get_spread(symbol) if symbol else 0.0
    dec    = 2 if close > 100 else 5

    # ── 1. ENTRÉE ────────────────────────────────────────────
    if fvg is not None:
        fvg_hi  = max(fvg.top, fvg.bottom)
        fvg_lo  = min(fvg.top, fvg.bottom)
        entry   = round((fvg_hi + fvg_lo) / 2.0, dec)
    else:
        entry   = round(close, dec)

    # ── 2. STOP LOSS (bord OB + buffer défensif réel) ────────────
    # buf = max(55% ATR, 3× spread) — protège contre le bruit normal
    # Était 40% ATR → trop serré, prix touchait le SL avant le TP
    buf = max(atr * 0.55, spread * 3.0)
    if direction == "LONG":
        sl = round((ob.bottom - buf) if ob else (entry - atr * 1.8), dec)
    else:
        sl = round((ob.top    + buf) if ob else (entry + atr * 1.8), dec)

    risk = round(abs(entry - sl), dec + 2)
    if risk <= 0:
        return entry, sl, entry, 0.0

    # ── 3. TAKE PROFIT — basé sur la liquidité réelle (50 bougies) ──
    # Logique : cherche le prochain swing H/L non cassé comme cible naturelle.
    # On ne force PLUS de TP minimal artificiel (tp_rr_net supprimé).
    # Si la liquidité est loin → RR élevé (4, 5, 6...) → c'est bien.
    # Si la liquidité est trop proche → RR < min_rr → signal rejeté en aval.
    window50 = df.iloc[-50:]
    if direction == "LONG":
        tp_candidates = sorted([
            window50["high"].iloc[i]
            for i in range(len(window50) - 2, 0, -1)
            if (window50["high"].iloc[i] > window50["high"].iloc[i - 1]
                and window50["high"].iloc[i] > window50["high"].iloc[i + 1]
                and window50["high"].iloc[i] > entry + risk)
        ], reverse=True)
        tp_nat = tp_candidates[-1] if tp_candidates else entry + atr * 5
        tp = round(max(tp_nat, entry + atr * 4), dec)
        gain_net = (tp - entry) - spread
    else:
        tp_candidates = sorted([
            window50["low"].iloc[i]
            for i in range(len(window50) - 2, 0, -1)
            if (window50["low"].iloc[i] < window50["low"].iloc[i - 1]
                and window50["low"].iloc[i] < window50["low"].iloc[i + 1]
                and window50["low"].iloc[i] < entry - risk)
        ])
        tp_nat = tp_candidates[0] if tp_candidates else entry - atr * 5
        tp = round(min(tp_nat, entry - atr * 4), dec)
        gain_net = (entry - tp) - spread

    # ── 4. RR net réel (recalculé sur le TP final) ───────────
    rr_net = round(gain_net / risk, 2) if gain_net > 0 and risk > 0 else 0.0

    return entry, sl, tp, rr_net

# ─────────────────────────────────────────────────────────────
#  BOUGIE DE CONFIRMATION M5/M1
# ─────────────────────────────────────────────────────────────
def detect_confirmation_candle(df: pd.DataFrame, direction: str) -> bool:
    """
    Détecte une bougie de confirmation sur les 3 dernières bougies CLÔTURÉES.
      LONG  → Bullish Engulfing ou Pin Bar haussière (mèche basse > corps × 2)
      SHORT → Bearish Engulfing ou Pin Bar baissière (mèche haute > corps × 2)

    NOTE : on commence à iloc[-2] (dernière bougie clôturée).
    iloc[-1] est la bougie en cours de formation → données incomplètes → bruit.
    """
    if len(df) < 4:
        return False

    for i in range(-2, -5, -1):   # [-2, -3, -4] — bougies clôturées uniquement
        o = df["open"].iloc[i]
        h = df["high"].iloc[i]
        l = df["low"].iloc[i]
        cl = df["close"].iloc[i]
        body    = abs(cl - o)
        if body == 0:
            continue
        upper_wick = h - max(o, cl)
        lower_wick = min(o, cl) - l

        if direction == "LONG":
            # Bullish engulfing
            if cl > o and i > -3:
                prev_o = df["open"].iloc[i - 1]
                prev_c = df["close"].iloc[i - 1]
                if prev_c < prev_o and cl > prev_o and o < prev_c:
                    return True
            # Pin bar haussière
            if lower_wick >= body * 2 and cl > o:
                return True

        elif direction == "SHORT":
            # Bearish engulfing
            if cl < o and i > -3:
                prev_o = df["open"].iloc[i - 1]
                prev_c = df["close"].iloc[i - 1]
                if prev_c > prev_o and cl < prev_o and o > prev_c:
                    return True
            # Pin bar baissière
            if upper_wick >= body * 2 and cl < o:
                return True

    return False


# ─────────────────────────────────────────────────────────────
#  MOTEUR PRINCIPAL — 3 TIMEFRAMES (H1 → M15 → M5/M1)
# ─────────────────────────────────────────────────────────────
def analyse(symbol: str, htf: str = HTF, ltf: str = LTF,
            silent: bool = False) -> Optional[Signal]:
    mtf = MTF   # M15 confirmation structure

    if not silent:
        print(f"\n{c('═'*60, 'cyan')}")
        print(f"  {c('SMC ENGINE', 'yellow')}  —  {c(symbol, 'white')}  "
              f"{c(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'cyan')}")
        print(f"  {c(f'H1 → {mtf} → {ltf}', 'cyan')}")
        print(c("═" * 60, "cyan"))

    # ── Téléchargement 3 TF uniquement : H1 / M15 / M5 ─────────
    if not silent:
        print(f"  {c('↓', 'cyan')} Data  {htf} / {mtf} / {ltf} …")
    df_htf = fetch(symbol, htf, period="10d")
    df_mtf = fetch(symbol, mtf, period="5d")
    df_ltf = fetch(symbol, ltf, period="2d")

    if df_htf.empty or df_mtf.empty or df_ltf.empty:
        if not silent:
            print(c("  ✗ Données indisponibles.", "red"))
        return None

    # ── FILTRES VOLATILITÉ — skip si marché mort ─────────────
    vol_ok, vol_reason = check_volatility(symbol, df_ltf)
    if not vol_ok:
        if not silent:
            print(c(f"  ⛔ Marché ignoré : {vol_reason}", "yellow"))
        return None

    # ── H1 : Biais directionnel ──────────────────────────────
    bias = htf_bias(df_htf)
    direction = "SHORT" if bias == "BEARISH" else ("LONG" if bias == "BULLISH" else None)
    color_bias = "red" if bias == "BEARISH" else ("green" if bias == "BULLISH" else "yellow")
    if not silent:
        print(f"\n  {'📊 Biais H1':<22} {c(bias, color_bias)}")

    if direction is None:
        if not silent:
            print(c("  ✗ Biais NEUTRAL — signal ignoré.", "yellow"))
        return None

    # ══════════════════════════════════════════════════════════
    #  PRE-BOS CHECK — Détection AVANT la cassure BOS
    #  Lancé en premier pour capter les setups précoces.
    #  Si un Pre-BOS est validé (score >= 70) ET que les filtres
    #  principaux (RR, daily limit, cooldown) passent,
    #  on retourne directement ce signal sans attendre le BOS.
    # ══════════════════════════════════════════════════════════
    pre_bos = analyse_pre_bos(symbol, df_ltf, df_htf, direction, silent=True)
    if pre_bos is not None:
        if not silent:
            print(c(f"\n  PRE-BOS detecte  score={pre_bos.score}/100  "
                    f"RR=1:{pre_bos.rr}  sweep@{round(pre_bos.sweep_level,5)}", "yellow"))
        lot_pb = compute_lot(symbol, pre_bos.entry, pre_bos.sl)
        pre_bos_signal = Signal(
            symbol    = pre_bos.symbol,
            direction = pre_bos.direction,
            entry     = pre_bos.entry,
            sl        = pre_bos.sl,
            tp        = pre_bos.tp,
            rr        = pre_bos.rr,
            score     = pre_bos.score,
            timestamp = pre_bos.timestamp,
            htf_bias  = bias,
            lot       = lot_pb,
            risk_usd  = RISK_USD,
            reasons   = pre_bos.reasons,
        )
        return pre_bos_signal

    # ── M15 : Structure intermédiaire ────────────────────────
    bos_mtf = detect_bos(df_mtf)
    obs_mtf = detect_order_blocks(df_mtf, bos_mtf)
    liq_mtf = detect_liquidity_sweep(df_mtf)

    last_bos_mtf = bos_mtf[-1] if bos_mtf else None
    mtf_bos  = last_bos_mtf is not None and last_bos_mtf["type"] == bias.lower()
    mtf_ob   = any(o.direction == bias.lower() for o in obs_mtf)
    liq_taken = liq_mtf["bearish_sweep"] if direction == "SHORT" else liq_mtf["bullish_sweep"]

    # OB M15 pour SL précis
    ob_mtf_match = next((o for o in reversed(obs_mtf) if o.direction == bias.lower()), None)

    # ── M5 : FVG + OB entrée ─────────────────────────────────
    bos_ltf  = detect_bos(df_ltf)
    fvgs_ltf = detect_fvg(df_ltf)
    obs_ltf  = detect_order_blocks(df_ltf, bos_ltf)

    last_bos_ltf = bos_ltf[-1] if bos_ltf else None
    has_bos_ltf  = last_bos_ltf is not None and last_bos_ltf["type"] == bias.lower()

    fvg_active = active_fvg(df_ltf, fvgs_ltf, bias.lower())
    ltf_fvg    = fvg_active is not None
    has_ob_ltf = any(o.direction == bias.lower() for o in obs_ltf)
    ob_ltf_match = next((o for o in reversed(obs_ltf) if o.direction == bias.lower()), None)

    # OB utilisé pour le SL : M5 si dispo, sinon M15
    ob_for_sl = ob_ltf_match or ob_mtf_match

    # ── Bougie de confirmation M5 ────────────────────────────
    ltf_confirm = detect_confirmation_candle(df_ltf, direction)

    # ══════════════════════════════════════════════════════════
    #  SETUPS AVANCÉS — M15
    # ══════════════════════════════════════════════════════════

    # Breaker Block sur M15
    bkr_mtf       = detect_breaker_blocks(df_mtf, bos_mtf)
    breaker_block  = any(b["direction"] == bias.lower() for b in bkr_mtf)

    # FVG Valid non mitiqué sur M5
    fvg_unmitigated = False
    if fvg_active is not None:
        fvg_unmitigated = is_fvg_unmitigated(df_ltf, fvg_active)

    # Trendline Liquidity sweepée sur M15
    trendline_liq = detect_trendline_liquidity(df_mtf, bias.lower())

    # Older Block HTF = OB H1 actif sur la zone actuelle
    bos_htf    = detect_bos(df_htf)
    obs_htf    = detect_order_blocks(df_htf, bos_htf)
    price_now  = df_ltf["close"].iloc[-1]
    older_block = any(
        o.direction == bias.lower() and
        min(o.top, o.bottom) <= price_now <= max(o.top, o.bottom)
        for o in obs_htf
    )

    # Upcoming BOS comme niveau TP additionnel
    upcoming_bos = detect_upcoming_bos(df_mtf, direction)

    # ── Score multi-TF + setups avancés ──────────────────────
    score, reasons = compute_score(
        bias, direction,
        has_bos  = has_bos_ltf,
        has_fvg  = ltf_fvg,
        has_ob   = has_ob_ltf,
        liquidity_taken  = liq_taken,
        bias_aligned     = True,
        mtf_bos          = mtf_bos,
        mtf_ob           = mtf_ob,
        ltf_fvg          = ltf_fvg,
        ltf_confirm      = ltf_confirm,
        entry_m1         = False,        # M1 désactivé — entrée M5
        breaker_block    = breaker_block,
        fvg_30m          = False,        # 30m désactivé — 3 TF seulement
        fvg_unmitigated  = fvg_unmitigated,
        trendline_liq    = trendline_liq,
        older_block      = older_block,
    )

    # ── Affichage détails ────────────────────────────────────
    def tick(v): return c("✓", "green") if v else c("✗", "red")
    if not silent:
        print(f"  {'BOS M15':<26} {tick(mtf_bos)}")
        print(f"  {'OB M15':<26} {tick(mtf_ob)}")
        print(f"  {'Liquidité prise (M15)':<26} {tick(liq_taken)}")
        print(f"  {'FVG M5 actif':<26} {tick(ltf_fvg)}")
        print(f"  {'FVG Valid (non mitiqué)':<26} {tick(fvg_unmitigated)}")
        print(f"  {'Confirmation M5':<26} {tick(ltf_confirm)}")
        print(f"  {'Trigger M1':<26} {tick(entry_m1)}")
        print(f"  {c('── Setups Avancés ──', 'cyan')}")
        print(f"  {'Breaker Block M15':<26} {tick(breaker_block)}")
        print(f"  {'FVG 30min (≈45min)':<26} {tick(fvg_30m)}")
        print(f"  {'Trendline Liq. sweepée':<26} {tick(trendline_liq)}")
        print(f"  {'Older Block HTF':<26} {tick(older_block)}")
        if upcoming_bos:
            dec_u = 2 if price_now > 100 else 5
            print(f"  {'Upcoming BOS (target)':<26} {c(str(round(upcoming_bos, dec_u)), 'magenta')}") 
        bar_filled = int(score / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        sc  = "green" if score >= 80 else ("yellow" if score >= 60 else "red")
        print(f"\n  Score  [{c(bar, sc)}]  {c(str(score) + '/100', sc)}")

    # ══════════════════════════════════════════════════════════
    #  FILTRE CRITIQUE — PRIX DANS LA ZONE D'ENTRÉE M15
    #
    #  Règle : le signal n'est valide que si le prix actuel est
    #  physiquement DANS une zone structurelle M15 :
    #    • OB M15 aligné avec le biais  (priorité 1)
    #    • FVG M5 actif non mitiqué     (priorité 2)
    #    • Zone Fibonacci 61.8% du range M15 (retracement 0.5–0.786)
    #
    #  Si aucune condition n'est remplie → signal rejeté.
    #  C'est le filtre qui empêche les entrées "dans le vide".
    # ══════════════════════════════════════════════════════════
    price_now_check = df_ltf["close"].iloc[-1]

    # ── Zone OB M15 ──────────────────────────────────────────
    in_ob_m15 = False
    if ob_mtf_match is not None:
        ob_lo = min(ob_mtf_match.top, ob_mtf_match.bottom)
        ob_hi = max(ob_mtf_match.top, ob_mtf_match.bottom)
        # Tolérance : ±10% de la hauteur de l'OB (pour pin bars qui effleurent)
        tolerance = (ob_hi - ob_lo) * 0.10
        in_ob_m15 = (ob_lo - tolerance) <= price_now_check <= (ob_hi + tolerance)

    # ── Zone FVG M5 actif ─────────────────────────────────────
    in_fvg_m5 = False
    if fvg_active is not None:
        fvg_lo = min(fvg_active.top, fvg_active.bottom)
        fvg_hi = max(fvg_active.top, fvg_active.bottom)
        in_fvg_m5 = fvg_lo <= price_now_check <= fvg_hi

    # ── Zone Fibonacci 50%–78.6% du range M15 ────────────────
    # Retracement de Fibonacci sur les 50 dernières bougies M15
    # Cherche le dernier swing significatif opposé au biais
    in_fib_zone = False
    if len(df_mtf) >= 20:
        mtf_window = df_mtf.iloc[-50:]
        if direction == "SHORT":
            # Pour un SHORT : swing high récent → retracement haussier → zone SHORT
            swing_hi = mtf_window["high"].max()
            swing_lo = mtf_window["low"].min()
            # Zone 50%–78.6% = prix entre 50% et 78.6% du mouvement haussier
            fib_50   = swing_hi - (swing_hi - swing_lo) * 0.500
            fib_786  = swing_hi - (swing_hi - swing_lo) * 0.214   # 100-78.6=21.4%
            in_fib_zone = fib_50 <= price_now_check <= fib_786
        else:
            # Pour un LONG : swing low récent → retracement baissier → zone LONG
            swing_hi = mtf_window["high"].max()
            swing_lo = mtf_window["low"].min()
            fib_50   = swing_lo + (swing_hi - swing_lo) * 0.500
            fib_786  = swing_lo + (swing_hi - swing_lo) * 0.786
            in_fib_zone = fib_50 <= price_now_check <= fib_786

    # ── Décision finale : au moins UNE zone doit être validée ─
    price_in_valid_zone = in_ob_m15 or in_fvg_m5 or in_fib_zone

    if not silent:
        print(f"\n  {c('── Filtre Zone Entrée M15 ──', 'cyan')}")
        print(f"  {'Prix dans OB M15':<30} {tick(in_ob_m15)}")
        print(f"  {'Prix dans FVG M5 actif':<30} {tick(in_fvg_m5)}")
        print(f"  {'Prix dans zone Fibo 50–78.6%':<30} {tick(in_fib_zone)}")
        zone_color = "green" if price_in_valid_zone else "red"
        print(f"  {'→ Zone valide':<30} {c('OUI ✓' if price_in_valid_zone else 'NON ✗ — signal rejeté', zone_color)}")

    if not price_in_valid_zone:
        if not silent:
            print(c("\n  ✗ Prix hors zone structurelle M15 — signal rejeté.", "red"))
            print(c("    (OB M15 / FVG M5 / Fibonacci 50–78.6% requis)", "yellow"))
        return None

    # ── Bonus score confluence de zones ──────────────────────
    zone_count = sum([in_ob_m15, in_fvg_m5, in_fib_zone])
    if zone_count >= 2:
        score = min(score + 5, 100)
        reasons.append(f"📐 Double confluence zone ({zone_count}/3)  (+5)")
    if zone_count == 3:
        score = min(score + 5, 100)
        reasons.append("🎯 Triple confluence zone (OB + FVG + Fibo)  (+5)")

    # ── Filtre score ─────────────────────────────────────────
    if score < SCORE_THRESHOLD:
        if not silent:
            print(c(f"\n  ✗ Score {score} < {SCORE_THRESHOLD} — setup insuffisant.", "yellow"))
        return None

    price        = df_ltf["close"].iloc[-1]
    decimals     = 2 if price > 100 else 5
    entry, sl, tp, rr = compute_sl_tp(
        df_ltf, direction, ob_for_sl,
        symbol=symbol,
        fvg=fvg_active,          # entrée au milieu du FVG M5
    )

    # Si un Upcoming BOS est détecté et offre un meilleur RR net → utilise-le comme TP
    if upcoming_bos is not None:
        spread = get_spread(symbol)
        risk   = abs(entry - sl)
        if risk > 0:
            if direction == "SHORT" and upcoming_bos < entry:
                gain_net_bos = (entry - upcoming_bos) - spread
                rr_bos = round(gain_net_bos / risk, 2)
                if rr_bos > rr:
                    tp  = round(upcoming_bos, decimals)
                    rr  = rr_bos
            elif direction == "LONG" and upcoming_bos > entry:
                gain_net_bos = (upcoming_bos - entry) - spread
                rr_bos = round(gain_net_bos / risk, 2)
                if rr_bos > rr:
                    tp  = round(upcoming_bos, decimals)
                    rr  = rr_bos

    # ── Filtre RR minimum ────────────────────────────────────
    if rr < MIN_RR:
        if not silent:
            print(c(f"\n  ✗ RR insuffisant ({rr} < {MIN_RR}) — signal rejeté.", "yellow"))
        return None

    lot = compute_lot(symbol, entry, sl)

    signal = Signal(
        symbol    = symbol,
        direction = direction,
        entry     = entry,
        sl        = sl,
        tp        = tp,
        rr        = rr,
        score     = score,
        timestamp = datetime.now(timezone.utc),
        htf_bias  = bias,
        lot       = lot,
        risk_usd  = RISK_USD,
        reasons   = reasons,
    )

    # ── Affichage signal ─────────────────────────────────────
    if not silent:
        score_color = "green" if score >= 80 else ("yellow" if score >= 60 else "red")
        dir_color   = "red" if direction == "SHORT" else "green"
        rr_color    = "green" if rr >= 3 else ("yellow" if rr >= 2 else "red")
        entry_mode  = "⚡ M1" if entry_m1 else "📍 M5"

        print(f"\n  {c('━'*56, 'cyan')}")
        print(f"  {c('⚡ SIGNAL ÉLITE DÉTECTÉ', 'yellow')}  →  {c(direction, dir_color)}  {entry_mode}")
        print(f"  {c('━'*56, 'cyan')}")
        entry_src   = "🎯 FVG mid" if fvg_active else "📍 close M5"
        print(f"  {'Symbole':<18} {c(signal.symbol, 'white')}")
        print(f"  {'Direction':<18} {c(signal.direction, dir_color)}")
        print(f"  {'─'*40}")
        print(f"  {'📍 Entrée':<18} {c(str(signal.entry), 'white')}   ← {entry_src}")
        print(f"  {'🔴 Stop Loss':<18} {c(str(signal.sl), 'red')}   "
              f"← risk = {c(str(round(abs(signal.entry - signal.sl), decimals)), 'red')}")
        print(f"  {'🟢 Take Profit':<18} {c(str(signal.tp), 'green')}   "
              f"← gain = {c(str(round(abs(signal.tp - signal.entry), decimals)), 'green')}")
        print(f"  {'─'*40}")
        print(f"  {'⚖  R : R':<18} {c('1 : ' + str(signal.rr), rr_color)}  "
              f"{'✓ RR OK' if rr >= MIN_RR else '✗'}  "
              f"{c('(spread déduit: ' + str(round(get_spread(symbol)*10000 if signal.entry < 10 else get_spread(symbol), 5)) + ')', 'yellow')}")
        print(f"  {'Score':<18} {c(str(signal.score) + ' / 100', score_color)}")
        print(f"  {'Biais H1':<18} {c(signal.htf_bias, dir_color)}")
        print(f"  {'─'*40}")
        print(f"  {'💰 LOT SIZE':<18} {c(str(signal.lot) + ' lot', 'magenta')}")
        print(f"  {'⚠  Risque':<18} {c('$' + str(signal.risk_usd), 'yellow')}  "
              f"← gain ≈ {c('$' + str(round(signal.risk_usd * signal.rr, 2)), 'green')}")
        print(f"  {'─'*40}")
        print(f"\n  Confluence :")
        for r in signal.reasons:
            print(f"    • {r}")
        print(f"  {c('━'*56, 'cyan')}\n")

    return signal


# ─────────────────────────────────────────────────────────────
#  ENTRÉE CLI
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
#  WATCHLIST COMPLÈTE — 50+ MARCHÉS
# ─────────────────────────────────────────────────────────────
MARKETS: dict[str, list[tuple[str, str]]] = {

    # ── FOREX MAJEURES ──────────────────────────────────────
    "forex_major": [
        ("EURUSD=X",  "EUR/USD"),
        ("GBPUSD=X",  "GBP/USD"),
        ("USDJPY=X",  "USD/JPY"),
        ("USDCHF=X",  "USD/CHF"),
        ("AUDUSD=X",  "AUD/USD"),
        ("NZDUSD=X",  "NZD/USD"),
        ("USDCAD=X",  "USD/CAD"),
    ],

    # ── FOREX CROISÉES ──────────────────────────────────────
    "forex_cross": [
        ("EURGBP=X",  "EUR/GBP"),
        ("EURJPY=X",  "EUR/JPY"),
        ("EURCHF=X",  "EUR/CHF"),
        ("EURAUD=X",  "EUR/AUD"),
        ("EURCAD=X",  "EUR/CAD"),
        ("EURNZD=X",  "EUR/NZD"),
        ("GBPJPY=X",  "GBP/JPY"),
        ("GBPCHF=X",  "GBP/CHF"),
        ("GBPAUD=X",  "GBP/AUD"),
        ("GBPCAD=X",  "GBP/CAD"),
        ("GBPNZD=X",  "GBP/NZD"),
        ("AUDJPY=X",  "AUD/JPY"),
        ("CADJPY=X",  "CAD/JPY"),
        ("CHFJPY=X",  "CHF/JPY"),
        ("NZDJPY=X",  "NZD/JPY"),
        ("AUDCAD=X",  "AUD/CAD"),
        ("AUDCHF=X",  "AUD/CHF"),
        ("AUDNZD=X",  "AUD/NZD"),
        ("NZDCAD=X",  "NZD/CAD"),
        ("NZDCHF=X",  "NZD/CHF"),
        ("CADCHF=X",  "CAD/CHF"),
    ],

    # ── FOREX EXOTIQUES ─────────────────────────────────────
    "forex_exotic": [
        ("USDMXN=X",  "USD/MXN"),
        ("USDZAR=X",  "USD/ZAR"),
        ("USDTRY=X",  "USD/TRY"),
        ("USDSEK=X",  "USD/SEK"),
        ("USDNOK=X",  "USD/NOK"),
        ("USDDKK=X",  "USD/DKK"),
        ("USDSGD=X",  "USD/SGD"),
        ("USDHKD=X",  "USD/HKD"),
    ],

    # ── CRYPTO (BTC uniquement) ──────────────────────────────
    "crypto": [
        ("BTC-USD",   "Bitcoin"),
    ],

    # ── COMMODITÉS ──────────────────────────────────────────
    "commodities": [
        ("GC=F",      "Gold"),
        ("SI=F",      "Silver"),
        ("CL=F",      "Oil WTI"),
        ("BZ=F",      "Oil Brent"),
        ("NG=F",      "Gaz Naturel"),
        ("HG=F",      "Cuivre"),
        ("PL=F",      "Platine"),
        ("PA=F",      "Palladium"),
    ],

    # ── INDICES ─────────────────────────────────────────────
    "indices": [
        ("^GSPC",     "S&P 500"),
        ("^NDX",      "Nasdaq 100"),
        ("^DJI",      "Dow Jones"),
        ("^GDAXI",    "DAX"),
        ("^FCHI",     "CAC 40"),
        ("^FTSE",     "FTSE 100"),
        ("^N225",     "Nikkei 225"),
        ("^HSI",      "Hang Seng"),
    ],
}

# ─────────────────────────────────────────────────────────────
#  WATCHLIST — PRIORITÉS PAR TIER
#
#  TIER 1  🥇  Gold + BTC       ← scanné en premier, toujours
#  TIER 2  🥈  Forex majeures   ← option secondaire
#  TIER 3  🥉  Forex croisées + reste
# ─────────────────────────────────────────────────────────────

TIER_1_PRIORITY: list[tuple[str, str]] = [
    # ── 🥇 GOLD ─────────────────────────────────────────────
    ("GC=F",     "Gold"),
    ("SI=F",     "Silver"),
    ("CL=F",     "Oil WTI"),
    ("BZ=F",     "Oil Brent"),
    # ── 🥇 BTC ──────────────────────────────────────────────
    ("BTC-USD",  "Bitcoin"),
]

TIER_2_FOREX: list[tuple[str, str]] = [
    # ── 🥈 MAJEURES ─────────────────────────────────────────────
    ("EURUSD=X", "EUR/USD"),
    ("GBPUSD=X", "GBP/USD"),
    ("USDJPY=X", "USD/JPY"),
    ("USDCHF=X", "USD/CHF"),
    ("AUDUSD=X", "AUD/USD"),
    ("NZDUSD=X", "NZD/USD"),
    ("USDCAD=X", "USD/CAD"),
]

TIER_3_EXTRA: list[tuple[str, str]] = [
    # ── 🥉 FOREX CROISÉES ────────────────────────────────────
    ("EURGBP=X", "EUR/GBP"),
    ("EURJPY=X", "EUR/JPY"),
    ("GBPJPY=X", "GBP/JPY"),
    ("EURAUD=X", "EUR/AUD"),
    ("GBPAUD=X", "GBP/AUD"),
    ("AUDJPY=X", "AUD/JPY"),
    ("CADJPY=X", "CAD/JPY"),
    ("CHFJPY=X", "CHF/JPY"),
    ("EURCAD=X", "EUR/CAD"),
    ("GBPCAD=X", "GBP/CAD"),
    ("NZDJPY=X", "NZD/JPY"),
    ("GBPCHF=X", "GBP/CHF"),
    ("EURCHF=X", "EUR/CHF"),
    ("EURNZD=X", "EUR/NZD"),
    ("GBPNZD=X", "GBP/NZD"),
    ("AUDCAD=X", "AUD/CAD"),
    ("AUDNZD=X", "AUD/NZD"),
    ("AUDCHF=X", "AUD/CHF"),
    ("NZDCAD=X", "NZD/CAD"),
    ("NZDCHF=X", "NZD/CHF"),
    ("CADCHF=X", "CAD/CHF"),
    # ── 🥉 EXOTIQUES ─────────────────────────────────────────
    ("USDMXN=X", "USD/MXN"),
    ("USDZAR=X", "USD/ZAR"),
    ("USDTRY=X", "USD/TRY"),
    ("USDSEK=X", "USD/SEK"),
    ("USDNOK=X", "USD/NOK"),
    ("USDSGD=X", "USD/SGD"),
    # ── 🥉 AUTRES COMMODITÉS ─────────────────────────────────
    ("NG=F",     "Gaz Naturel"),
    ("HG=F",     "Cuivre"),
    ("PL=F",     "Platine"),
    ("PA=F",     "Palladium"),
    # ── 🥉 INDICES ────────────────────────────────────────────
    ("^GSPC",    "S&P 500"),
    ("^NDX",     "Nasdaq 100"),
    ("^DJI",     "Dow Jones"),
    ("^GDAXI",   "DAX"),
    ("^FCHI",    "CAC 40"),
    ("^FTSE",    "FTSE 100"),
    ("^N225",    "Nikkei 225"),
]

# Correspondance catégorie → liste de symboles
CATEGORY_MAP: dict[str, list[tuple[str, str]]] = {
    "priority"   : TIER_1_PRIORITY,
    "forex"      : TIER_2_FOREX,                                              # 7 majeures
    "forex_all"  : TIER_2_FOREX + [s for s in TIER_3_EXTRA if "=X" in s[0]],
    "all"        : TIER_1_PRIORITY + TIER_2_FOREX + TIER_3_EXTRA,
}
# garde compat anciens alias
CATEGORY_ALIASES = CATEGORY_MAP


def get_symbols(cat: str) -> list[tuple[str, str]]:
    return CATEGORY_MAP.get(cat, TIER_1_PRIORITY + TIER_2_FOREX + TIER_3_EXTRA)


# ─────────────────────────────────────────────────────────────
#  AFFICHAGE LISTE DES MARCHÉS AU DÉMARRAGE
# ─────────────────────────────────────────────────────────────
def print_market_list(symbols: list[tuple[str, str]]) -> None:
    """
    Affiche au démarrage la liste complète des marchés qui vont être scannés,
    groupés par TIER (Gold/BTC → Forex majeures → Croisées/Indices),
    avec le symbole technique yfinance de chaque paire.
    """
    tier1_set = {s[0] for s in TIER_1_PRIORITY}
    tier2_set = {s[0] for s in TIER_2_FOREX}

    groups: list[tuple[str, list[tuple[str, str]]]] = [
        ("🥇  TIER 1  —  Gold / BTC / Commodités Prioritaires", []),
        ("🥈  TIER 2  —  Forex Majeures",                       []),
        ("🥉  TIER 3  —  Croisées / Exotiques / Indices",       []),
    ]

    for sym, name in symbols:
        if sym in tier1_set:
            groups[0][1].append((sym, name))
        elif sym in tier2_set:
            groups[1][1].append((sym, name))
        else:
            groups[2][1].append((sym, name))

    total   = len(symbols)
    W       = 68   # largeur intérieure du cadre

    sep_top = "╔" + "═" * W + "╗"
    sep_mid = "╠" + "═" * W + "╣"
    sep_bot = "╚" + "═" * W + "╝"

    def row(text: str) -> str:
        return "║  " + text + " " * max(0, W - 2 - len(text)) + "║"

    print(f"\n{sep_top}")
    print(row(f"📋  WATCHLIST COMPLÈTE  —  {total} MARCHÉS SCANNÉS"))
    print(row(f"   Score min : {SCORE_THRESHOLD}/100   |   RR min : 1:{MIN_RR}   |   Scan : toutes les 30s"))
    print(sep_mid)

    grand_i = 1
    for tier_name, group in groups:
        if not group:
            continue

        print(row(f"{tier_name}  ({len(group)} marchés)"))
        print(row("─" * (W - 4)))

        # 2 colonnes
        for j in range(0, len(group), 2):
            sym1, name1 = group[j]
            col1 = f"{grand_i:>2}. {name1:<18}  {sym1:<13}"
            grand_i += 1
            if j + 1 < len(group):
                sym2, name2 = group[j + 1]
                col2 = f"{grand_i:>2}. {name2:<18}  {sym2}"
                grand_i += 1
            else:
                col2 = ""
            line = col1 + col2
            print(row(line))

        print(row(""))   # ligne vide entre tiers

    print(sep_bot + "\n")


# ─────────────────────────────────────────────────────────────
#  SCAN PAR PRIORITÉ
# ─────────────────────────────────────────────────────────────
TIER_LABELS = {
    "TIER 1 🥇  GOLD + BTC"      : TIER_1_PRIORITY,
    "TIER 2 🥈  FOREX MAJEURES"  : TIER_2_FOREX,
    "TIER 3 🥉  CROISÉES + EXTRA": TIER_3_EXTRA,
}


def _scan_group(
    group: list[tuple[str, str]],
    label: str,
    htf: str,
    ltf: str,
    min_score: int,
    min_rr: float,
    index_offset: int = 0,
    total_global: int = 0,
) -> list[tuple[str, Signal, str]]:
    """Scanne un groupe, retourne les signaux valides avec leur tier."""
    results = []
    for i, (sym, mkt) in enumerate(group, 1):
        idx = index_offset + i
        print(f"  [{idx:>2}/{total_global}]  {mkt:<16} {c(sym, 'cyan')} … ",
              end="", flush=True)
        try:
            sig = analyse(sym, htf, ltf, silent=True)
            if sig and sig.score >= min_score and sig.rr >= min_rr:
                results.append((mkt, sig, label))
                d_color = "red" if sig.direction == "SHORT" else "green"
                print(c(f"⚡ {sig.direction}  score={sig.score}  RR=1:{sig.rr}", d_color))
                # ── Notification Telegram ──────────────────────
                tg_notify(sig, tier=label)
            else:
                note = ""
                if sig and sig.rr < min_rr:
                    note = c(f"  (RR={sig.rr} < {min_rr})", "red")
                print(c("—", "white") + note)
        except Exception as e:
            print(c(f"err: {e}", "red"))
    return results


def scan_watchlist(symbols: list[tuple[str, str]], htf: str, ltf: str,
                   min_score: int = SCORE_THRESHOLD, min_rr: float = MIN_RR):
    """Scan prioritaire : Gold/BTC → Forex majeures → reste."""
    all_results: list[tuple[str, Signal, str]] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Calcul total réel des symboles dans les tiers à scanner
    tiers_to_scan = [
        ("TIER 1 🥇  GOLD + BTC",       TIER_1_PRIORITY),
        ("TIER 2 🥈  FOREX MAJEURES",   TIER_2_FOREX),
        ("TIER 3 🥉  CROISÉES + EXTRA", TIER_3_EXTRA),
    ]
    # Si l'utilisateur a filtré par catégorie, on utilise symbols passé
    # mais on garde l'ordre tier par tier
    sym_set = {s[0] for s in symbols}
    tiers_filtered = [
        (lbl, [(s, m) for s, m in grp if s in sym_set])
        for lbl, grp in tiers_to_scan
    ]
    total = sum(len(g) for _, g in tiers_filtered)

    print(f"\n{c('╔' + '═'*64 + '╗', 'cyan')}")
    print(f"{c('║', 'cyan')}  {c('SMC SCAN — PRIORITÉ GOLD / BTC / FOREX', 'yellow'):<63}{c('║', 'cyan')}")
    print(f"{c('║', 'cyan')}  HTF={htf}  LTF={ltf}  "
          f"score≥{min_score}  RR≥{min_rr}   {ts:<27}{c('║', 'cyan')}")
    print(f"{c('╚' + '═'*64 + '╝', 'cyan')}")

    offset = 0
    for tier_label, group in tiers_filtered:
        if not group:
            continue
        print(f"\n  {c('▶ ' + tier_label, 'yellow')}  ({len(group)} marchés)")
        print(f"  {c('─'*60, 'cyan')}")
        tier_results = _scan_group(
            group, tier_label, htf, ltf, min_score, min_rr,
            index_offset=offset, total_global=total
        )
        all_results.extend(tier_results)
        offset += len(group)

        # Alerte immédiate si signal Tier 1
        if tier_results and "TIER 1" in tier_label:
            print(c(f"\n  ★ SIGNAL(S) PRIORITAIRE(S) DÉTECTÉ(S) SUR {tier_label} ★\n",
                    "yellow"))

    # ── Tableau final trié par TIER puis SCORE ───────────────
    if all_results:
        print(f"\n{c('╔' + '═'*72 + '╗', 'yellow')}")
        print(f"{c('║', 'yellow')}  {c('⚡ RÉSUMÉ — SIGNAUX VALIDES', 'yellow')} "
              f"({len(all_results)} signal(s))  RR min 1:{min_rr}"
              f"{'':<14}{c('║', 'yellow')}")
        print(f"{c('╚' + '═'*72 + '╝', 'yellow')}")

        # tri : tier d'abord (1<2<3), puis score décroissant
        tier_order = {"TIER 1": 0, "TIER 2": 1, "TIER 3": 2}
        all_results.sort(
            key=lambda x: (tier_order.get(x[2][:6], 9), -x[1].score)
        )

        header = f"  {'#':<3} {'Tier':<5} {'Marché':<16} {'Dir':<7} {'Score':>5}  " \
                 f"{'Entrée':>12}  {'SL 🔴':>12}  {'TP 🟢':>12}  {'R:R':>6}"
        print(header)
        print(f"  {'─'*80}")

        for rank, (mkt, s, tier) in enumerate(all_results, 1):
            d_color  = "red"   if s.direction == "SHORT" else "green"
            sc_color = "green" if s.score >= 80 else "yellow"
            rr_color = "green" if s.rr >= 4 else "yellow"
            tier_num = tier[:6].replace("TIER ", "T")
            star     = "★" if "TIER 1" in tier else " "
            print(
                f"  {rank:<3} {c(star + tier_num, 'yellow'):<5} "
                f"{mkt:<16} "
                f"{c(s.direction, d_color):<7} "
                f"{c(str(s.score), sc_color):>5}  "
                f"{str(s.entry):>12}  "
                f"{c(str(s.sl), 'red'):>12}  "
                f"{c(str(s.tp), 'green'):>12}  "
                f"{c('1:'+str(s.rr), rr_color):>6}"
            )
        print(f"  {'─'*80}\n")
    else:
        print(c(f"\n  Aucun signal  score≥{min_score}  RR≥{min_rr}  détecté.\n", "yellow"))

    return all_results


# ─────────────────────────────────────────────────────────────
#  ENTRÉE CLI
# ─────────────────────────────────────────────────────────────

# ── Sessions de trading actives (UTC) ────────────────────────
# Londres  : 07h–16h  |  New York : 12h–21h
# On ne trade PAS la session Asie (trop calme sur les majeures)
SESSIONS = {
    "London"  : (7,  16),
    "New York": (12, 21),
}

# ── Limite d'envoi journalière par paire ─────────────────────
MAX_SIGNALS_PER_DAY = 3          # max signaux envoyés par paire par jour
_daily_count: dict[str, int]  = {}   # paire → nb signaux aujourd'hui
_daily_date:  str             = ""   # date courante pour reset auto


import logging, sys

def setup_logging() -> logging.Logger:
    """Logger dual : fichier + console."""
    logger = logging.getLogger("smc")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    # Fichier (rotatif simple)
    fh = logging.FileHandler("smc_signals.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger

log = setup_logging()


def is_active_session() -> tuple[bool, str]:
    """
    Retourne (actif, nom_session).
    Actif si l'heure UTC est dans au moins une session configurée.
    """
    now_h = datetime.now(timezone.utc).hour
    active = []
    for name, (start, end) in SESSIONS.items():
        if start <= now_h < end:
            active.append(name)
    if active:
        return True, " + ".join(active)
    return False, "Hors session"


def check_daily_limit(symbol: str) -> bool:
    """
    Retourne True si on peut encore envoyer un signal pour cette paire aujourd'hui.
    Reset automatique à minuit UTC.
    """
    global _daily_count, _daily_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _daily_date:
        _daily_date  = today
        _daily_count = {}
    count = _daily_count.get(symbol, 0)
    return count < MAX_SIGNALS_PER_DAY


def increment_daily_count(symbol: str) -> None:
    _daily_count[symbol] = _daily_count.get(symbol, 0) + 1


def startup_check() -> bool:
    """
    Vérifie la connectivité Telegram et internet au démarrage.
    Retourne True si tout est OK.
    """
    log.info("=" * 60)
    log.info("  SMC SIGNAL ENGINE — Démarrage VPS")
    log.info(f"  Sessions actives : {list(SESSIONS.keys())}")
    log.info(f"  Score min        : {SCORE_THRESHOLD}/100")
    log.info(f"  RR min           : {MIN_RR}")
    log.info(f"  Risque/position  : ${RISK_USD}")
    log.info(f"  Max signaux/jour : {MAX_SIGNALS_PER_DAY} par paire")
    log.info(f"  Cooldown signal  : {SIGNAL_COOLDOWN}s")
    log.info("=" * 60)

    # Test Telegram
    try:
        r = requests.get(_tg_url("getMe"), timeout=10)
        if r.status_code == 200:
            bot_name = r.json()["result"]["username"]
            log.info(f"  ✓ Bot Telegram OK : @{bot_name}")
        else:
            log.error(f"  ✗ Bot Telegram KO : {r.status_code}")
            return False
    except Exception as e:
        log.error(f"  ✗ Connexion Telegram impossible : {e}")
        return False

    # Test groupe (ping silencieux — pas de message envoyé)
    try:
        r2 = requests.get(_tg_url("getChat"), params={"chat_id": TELEGRAM_GROUP_ID}, timeout=10)
        if r2.status_code == 200:
            log.info(f"  ✓ Message groupe OK (id={TELEGRAM_GROUP_ID})")
        else:
            log.warning(f"  ⚠ Groupe inaccessible : {r2.text}")
    except Exception as e:
        log.warning(f"  ⚠ Test groupe échoué : {e}")

    # Test données marché — non bloquant (rate limit possible au démarrage)
    yf_ok = False
    for attempt in range(1, 4):
        try:
            df = fetch("GBPUSD=X", "5m", period="1d")
            if not df.empty:
                log.info("  ✓ Données marché (yfinance) OK")
                yf_ok = True
                break
            else:
                log.warning(f"  ⚠ yfinance vide — tentative {attempt}/3")
                time.sleep(20 * attempt)
        except Exception as e:
            log.warning(f"  ⚠ yfinance erreur tentative {attempt}/3 : {e}")
            time.sleep(20 * attempt)

    if not yf_ok:
        log.warning("  ⚠ yfinance indisponible au démarrage — démarrage quand même.")
        log.warning("  ⚠ Le bot va attendre 60s puis relancer le scan.")

    log.info("  ✓ Démarrage du scan\n")
    return True  # On démarre toujours — erreur yfinance gérée dans la boucle


def _reasons_flags(reasons: list[str]) -> tuple[str, str, str, str]:
    """
    Extrait 4 drapeaux (BOS / FVG / OB / LIQ) depuis la liste reasons d'un Signal.
    Retourne une tuple de 4 chaînes "✓" ou "✗".
    """
    has_bos = any("BOS"      in r for r in reasons)
    has_fvg = any("FVG"      in r for r in reasons)
    has_ob  = any("Block"    in r or "Order" in r or "OB" in r for r in reasons)
    has_liq = any("Liquidit" in r or "Hunt"  in r or "Stop" in r for r in reasons)
    return (
        c("✓", "green") if has_bos else c("✗", "red"),
        c("✓", "green") if has_fvg else c("✗", "red"),
        c("✓", "green") if has_ob  else c("✗", "red"),
        c("✓", "green") if has_liq else c("✗", "red"),
    )


def _tier_of(sym: str) -> str:
    """Retourne le label tier court d'un symbole."""
    t1 = {s[0] for s in TIER_1_PRIORITY}
    t2 = {s[0] for s in TIER_2_FOREX}
    if sym in t1:
        return c("T1🥇", "yellow")
    if sym in t2:
        return c("T2🥈", "cyan")
    return c("T3🥉", "white")


def run_live(cat: str = "forex", min_score: int = SCORE_THRESHOLD,
             min_rr: float = MIN_RR, interval: int = 30) -> None:
    """
    Boucle principale VPS :
      ① Affiche la liste complète des marchés scannés au démarrage
      ② À chaque cycle (toutes les {interval}s) :
            - Tableau de statut  : prix actuel + confirmations SMC
              (BOS / FVG / OB / Liquidité / Score / RR) pour CHAQUE marché
            - Signal Telegram envoyé UNIQUEMENT si :
                score >= min_score  ET  RR >= min_rr  ET  toutes confirmations
      ③ Survie aux erreurs réseau sans crash
    """
    if not startup_check():
        log.error("  Startup check échoué — arrêt.")
        return

    symbols = get_symbols(cat)

    # ── ① Liste des marchés ────────────────────────────────────
    print_market_list(symbols)
    log.info(f"  Watchlist : {len(symbols)} paire(s) — cat={cat}")

    # ── Initialise le statut Flask ─────────────────────────────
    with _STATUS_LOCK:
        _STATUS["started_at"]    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        _STATUS["symbols_count"] = len(symbols)
        _STATUS["scan_running"]  = True

    consecutive_errors = 0
    cycle_n = 0
    # Mémorise le dernier biais H1 par symbole pour détecter les retournements
    _last_bias: dict[str, str] = {}

    while True:
        try:
            cycle_n += 1
            now_utc  = datetime.now(timezone.utc)
            now_str  = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
            now_hhmm = now_utc.strftime("%H:%M UTC")

            # ── Hors session → pause + heartbeat toutes les 5 min ──
            if not is_session_active():
                # Log toutes les 10 cycles (~5 min) pour confirmer que le script tourne
                if cycle_n % 10 == 1:
                    log.info(f"  💤 [{cycle_n}] {now_hhmm} — Hors session (London 07-10 / NY 13-16 UTC) — Script actif ✓")
                with _STATUS_LOCK:
                    _STATUS["cycle"]     = cycle_n
                    _STATUS["last_scan"] = now_str
                    _STATUS["scan_running"] = False
                time.sleep(interval)
                continue

            with _STATUS_LOCK:
                _STATUS["scan_running"] = True
                _STATUS["cycle"]        = cycle_n
                _STATUS["last_scan"]    = now_str

            log.info(f"  🔍 [{cycle_n}] {now_hhmm} — Scan {len(symbols)} paires")

            # ── Reset garde corrélation pour ce cycle ──────────
            correlation_guard_reset()

            # ── ② Entête tableau ───────────────────────────────
            W = 90
            print(f"\n{'╔' + '═'*W + '╗'}")
            print(f"║  🔍  CYCLE #{cycle_n}  —  {now_str}  —  {len(symbols)} MARCHÉS"
                  + " " * max(0, W - 4 - 8 - len(now_str) - len(str(len(symbols))) - 17) + "║")
            print(f"║  Score min : {min_score}/100   RR min : 1:{min_rr}   "
                  + "Confirmations requises : BOS + FVG + OB + Liquidité"
                  + " " * max(0, W - 4 - 13 - len(str(min_score)) - 3 -
                               len(str(min_rr)) - 50) + "║")
            print(f"{'╠' + '═'*W + '╣'}")

            # En-têtes colonnes
            hdr = (f"  {'N°':<4} {'Tier':<4} {'Marché':<14} {'Symbole':<12}"
                   f"  {'Prix':>14}  {'Biais':>7}  "
                   f"{'BOS':>4} {'FVG':>4} {'OB':>4} {'LIQ':>4}"
                   f"  {'Score':>6}  {'RR':>6}  Statut")
            print(hdr)
            print(f"  {'─'*88}")

            signals_found: list[tuple[str, str, "Signal", str]] = []   # (mkt, sym, sig, tier_label)

            # ── Scan marché par marché ─────────────────────────
            for i, (sym, mkt) in enumerate(symbols, 1):
                tier = _tier_of(sym)
                prefix = f"  {i:<4} {tier}  {mkt:<14} {c(sym, 'cyan'):<12}"
                print(prefix + "  … ", end="", flush=True)

                try:
                    sig = analyse(sym, silent=True)

                    # ── Détection retournement de biais → reset setups ──
                    if sig is not None:
                        new_bias = sig.htf_bias
                        if _last_bias.get(sym) and _last_bias[sym] != new_bias:
                            reset_setup(sym)
                            print(c(f"\n  [SETUP] ♻ Biais {sym} changé "
                                    f"{_last_bias[sym]}→{new_bias} — setups réinitialisés", "cyan"))
                        _last_bias[sym] = new_bias

                    if sig is None:
                        # Pas de setup — récupère le prix + raison si dispo
                        try:
                            df_peek = fetch(sym, LTF, period="1d")
                            if not df_peek.empty:
                                px   = df_peek["close"].iloc[-1]
                                dec  = 2 if px > 100 else 5
                                px_s = str(round(px, dec))
                                # Vérifie rapidement si rejet volatilité
                                vol_ok, vol_reason = check_volatility(sym, df_peek)
                                skip_label = f"⛔ {vol_reason}" if not vol_ok else "⚪ Pas de setup"
                            else:
                                px_s = "—"
                                skip_label = "⚪ Pas de setup"
                        except Exception:
                            px_s = "—"
                            skip_label = "⚪ Pas de setup"
                        print(f"\r{prefix}  {px_s:>14}  {'—':>7}  "
                              f"{'—':>4} {'—':>4} {'—':>4} {'—':>4}"
                              f"  {'—':>6}  {'—':>6}  {skip_label}")

                    else:
                        # Signal calculé — affichage détaillé
                        px   = sig.entry
                        dec  = 2 if px > 100 else 5
                        px_s = str(round(px, dec))

                        bos_f, fvg_f, ob_f, liq_f = _reasons_flags(sig.reasons)

                        sc_color = "green" if sig.score >= 80 else ("yellow" if sig.score >= 60 else "red")
                        rr_color = "green" if sig.rr >= 3 else ("yellow" if sig.rr >= 2 else "red")
                        dir_clr  = "red"   if sig.direction == "SHORT" else "green"
                        dir_icon = "🔴" if sig.direction == "SHORT" else "🟢"

                        if sig.score >= min_score and sig.rr >= min_rr:
                            # ── Garde corrélation ──────────────────────
                            corr_ok, corr_reason = correlation_guard(sym, sig.direction)
                            if not corr_ok:
                                status = c(f"🟠 Corrélé — {corr_reason}", "yellow")
                            else:
                                # Toutes les confirmations validées → signal valide
                                status = c(f"⚡ SIGNAL {sig.direction} — EN COURS D'ENVOI", dir_clr)

                                # Détermine le tier pour le label Telegram
                                raw_tier = next(
                                    (lbl for lbl, grp in TIER_LABELS.items()
                                     if any(s == sym for s, _ in grp)),
                                    "TIER 2 🥈  FOREX MAJEURES"
                                )
                                signals_found.append((mkt, sym, sig, raw_tier))

                        elif sig.score >= int(min_score * 0.75):
                            status = c(f"🟡 Proche  ({sig.score}/100)", "yellow")
                        else:
                            status = c(f"🔵 En attente  ({sig.score}/100)", "white")

                        print(f"\r{prefix}  {px_s:>14}  "
                              f"{c(sig.htf_bias[:4], dir_clr):>7}  "
                              f"{bos_f:>4} {fvg_f:>4} {ob_f:>4} {liq_f:>4}  "
                              f"{c(str(sig.score), sc_color):>6}  "
                              f"{c('1:'+str(sig.rr), rr_color):>6}  "
                              f"{status}")

                    time.sleep(1)   # anti-flood yfinance

                except Exception as e:
                    print(f"\r{prefix}  {'—':>14}  {'—':>7}  "
                          f"{'—':>4} {'—':>4} {'—':>4} {'—':>4}"
                          f"  {'—':>6}  {'—':>6}  "
                          + c(f"⚠ {str(e)[:38]}", "red"))
                    continue

            # ── Séparateur + résumé ────────────────────────────
            print(f"  {'─'*88}")

            # ── Cap : 2 meilleurs signaux par cycle (évite le flood) ──
            if len(signals_found) > 2:
                signals_found = sorted(signals_found, key=lambda x: x[2].score, reverse=True)[:2]
                print(c("  ⚠ Plus de 2 signaux — seuls les 2 meilleurs scores retenus.", "yellow"))

            if signals_found:
                print(c(f"\n  ⚡ {len(signals_found)} SIGNAL(S) VALIDÉ(S) — "
                        "Toutes les confirmations sont présentes :", "yellow"))
                for mkt, sym, sig, tier_lbl in signals_found:
                    dir_clr = "red" if sig.direction == "SHORT" else "green"
                    print(c(f"    → {mkt} ({sym})  {sig.direction}  "
                            f"score={sig.score}/100  RR=1:{sig.rr}  "
                            f"lot={sig.lot}  entry={sig.entry}", dir_clr))
            else:
                print(c("  ℹ️  Aucun signal valide ce cycle "
                        f"(score≥{min_score} + RR≥{min_rr} requis).", "white"))

            # ── Envoi Telegram des signaux validés ─────────────
            for mkt, sym, sig, tier_lbl in signals_found:
                log.info(f"  ⚡ SIGNAL {sig.direction} {mkt}  "
                         f"score={sig.score}  RR=1:{sig.rr}  lot={sig.lot}")
                tg_notify(sig, tier=tier_lbl)
                log.info(f"    ✓ Signal Telegram envoyé → {mkt}")

                # ── Mise à jour dashboard Flask ────────────────
                with _STATUS_LOCK:
                    _STATUS["last_signals"].append({
                        "ts"       : datetime.now(timezone.utc).strftime("%d/%m %H:%M"),
                        "market"   : mkt,
                        "direction": sig.direction,
                        "entry"    : sig.entry,
                        "sl"       : sig.sl,
                        "tp"       : sig.tp,
                        "rr"       : sig.rr,
                        "score"    : sig.score,
                        "lot"      : sig.lot,
                        "mode"     : ("PRE-BOS"
                                      if any("Sweep" in r or "sweep" in r
                                             for r in sig.reasons)
                                      else "SMC"),
                    })
                    # Garde seulement les 50 derniers signaux
                    _STATUS["last_signals"] = _STATUS["last_signals"][-50:]

            # ── Pied de tableau ────────────────────────────────
            print(f"\n{'╚' + '═'*W + '╝'}")

            consecutive_errors = 0
            log.info(f"  ⏳ Prochain scan dans {interval}s\n")
            time.sleep(interval)

        except KeyboardInterrupt:
            log.info("\n  Session live terminée par l'utilisateur.")
            requests.post(_tg_url("sendMessage"), json={
                "chat_id"   : TELEGRAM_GROUP_ID,
                "text"      : "🔴 <b>SMC Signal Engine arrêté</b>",
                "parse_mode": "HTML",
            }, timeout=5)
            break

        except Exception as e:
            consecutive_errors += 1
            log.error(f"  ✗ Erreur critique : {e}")
            wait = min(60 * consecutive_errors, 300)   # backoff 1→2→3→5 min max
            log.info(f"  ⏳ Reprise dans {wait}s (erreur #{consecutive_errors})")
            time.sleep(wait)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SMC Signal Engine — VPS Ready · London/NY · M1/M5",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--symbol",    default=None,
                        help="Symbole unique  (ex: EURUSD=X, BTC-USD, GC=F)")
    parser.add_argument("--cat",       default="forex",
                        choices=["priority", "forex", "forex_all", "all"],
                        help=(
                            "priority  = Gold + BTC seulement\n"
                            "forex     = Forex majeures seulement (défaut)\n"
                            "forex_all = Forex complet\n"
                            "all       = Tout scanner"
                        ))
    parser.add_argument("--scan",      action="store_true",
                        help="Scan unique (test local uniquement — quitte après 1 scan)")
    parser.add_argument("--min-score", type=int,   default=SCORE_THRESHOLD,
                        help=f"Score minimum  (défaut: {SCORE_THRESHOLD})")
    parser.add_argument("--min-rr",    type=float, default=MIN_RR,
                        help=f"R:R minimum  (défaut: {MIN_RR})")
    parser.add_argument("--interval",  type=int,   default=30,
                        help="Intervalle de scan en secondes (défaut: 30)")
    args = parser.parse_args()

    # ── Démarrage Flask en arrière-plan (port Render) ──────────
    # PORT est injecté par Render automatiquement.
    # En local, défaut = 10000.
    flask_port = int(os.environ.get("PORT", 10000))
    flask_thread = threading.Thread(
        target=start_flask,
        args=(flask_port,),
        daemon=True,      # s'arrête automatiquement si le process principal quitte
        name="flask-server",
    )
    flask_thread.start()
    # ── Attente 3s : laisse Flask binder le port avant que Render
    #    fasse son port-scan (évite "No open ports detected")
    time.sleep(3)
    log.info(f"  ✓ Flask dashboard actif sur le port {flask_port}")

    # ── Self-ping anti-veille Render (plan gratuit) ────────────
    start_self_ping(flask_port)

    # ── Mode selon les arguments ────────────────────────────────
    if args.symbol:
        sig = analyse(args.symbol)
        if sig:
            tg_notify(sig, tier="TIER 1")

    elif args.scan:
        symbols = get_symbols(args.cat)
        scan_watchlist(symbols, HTF, LTF, args.min_score, args.min_rr)

    else:
        # ── MODE LIVE — boucle infinie (Render Web Service) ────
        run_live(
            cat       = args.cat,
            min_score = args.min_score,
            min_rr    = args.min_rr,
            interval  = args.interval,
        )

