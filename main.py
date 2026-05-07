
"""
╔══════════════════════════════════════════════════════════════════════╗
║          SMC SIGNAL ENGINE  v11  — Smart Money Concepts PRO         ║
║   BOS · FVG · OB · Breaker Block · OTE DWO · Clean PA · AMD · D1   ║
║   BTC/GOLD PRIORITY  |  TREND FOLLOWING D1  |  AMD CYCLE DETECTOR   ║
║                                                                      ║
║   FOREX  |  INDICES  |  CRYPTO  |  COMMODITIES  |  MATIERES 1ERES   ║
╚══════════════════════════════════════════════════════════════════════╝

Nouveautes v11 — AMD CYCLE + TENDANCE DE FOND + BTC/GOLD PRIORITE :

  1. TENDANCE DE FOND D1 (Daily Trend Filter) :
       daily_trend() → EMA50 + structure HH/HL sur Daily
       Signal ALIGNÉ D1   : +12 pts bonus
       Signal CONTRE D1   : BLOQUÉ — pas d'entrée counter-trend
       Neutre (NEUTRAL)   : pas d'impact, signal passe normalement

  2. AMD CYCLE DETECTOR :
       detect_amd_cycle() → analyse sur H1 (AMD) + M15 (Manipulation)
       ACCUMULATION (≥70%) : signal BLOQUÉ (range = entrée risquée)
       MANIPULATION (≥60%) : +15 pts  ← meilleur moment d'entrée
       DISTRIBUTION (≥55%) : +10 pts si dans le sens du move
       Phase AMD affichée dans le message Telegram avec badge dédié

  3. BTC + GOLD PRIORITE ABSOLUE :
       Quel que soit le mode (forex/all/priority),
       BTC-USD et GC=F sont TOUJOURS scannés EN PREMIER.
       Positionnés en tête de liste à chaque cycle.

  CYCLE DE VIE COMPLET v11 :
    D1 trend aligné → AMD Phase M ou D → BOS propre
    → Clean PA → OTE/OB → M5 trigger → ENTRY ✅

Nouveautes v10 — CLEAN PA MODULE (fusion smc_clean_pa_v1) :

  CLEAN PA FILTER (4 axes) :
    1. STRUCTURE   — HH/HL ou LH/LL clairs (pas de zigzag)
    2. DISPLACEMENT— Vraie impulsion forte avant la zone (CRITIQUE)
    3. PULLBACK    — Retour calme dans la zone (pas chaotique)
    4. CHOP FILTER — Bloque les marchés sans direction

  CYCLE DE VIE D'UN SIGNAL CLEAN :
    DISPLACEMENT fort → BOS propre → PULLBACK calme → Confirmation → ENTRY ✅

  SCORING CLEAN PA :
    PA parfait  (score ≥8) : +15 pts
    PA propre   (score ≥6) : +8 pts
    PA ok       (score ≥5) : +3 pts
    Choppy            : −5 pts  (pénalité directe)
    Pas de displacement : −8 pts (bloquant)

  BLOCAGE AUTOMATIQUE :
    clean_score < 5 OU pas de displacement → signal rejeté (return None)

Nouveautes v9 — OTE FIBONACCI DWO + BREAKER BLOCK ELITE :

  OTE FIBONACCI RÉEL :
    detect_ote_zone() → ancré sur BOS réel (Dealing Range DWO)
    Move ≥ 2× ATR obligatoire — exclut ranges et micro-structures
    Bonus score +12 si prix dans OTE 62%–79%
    Bonus score +8 additionnel si OTE + OB confluence
    Bonus score +10 si OTE + FVG confluence (setup sniper triple)

  BREAKER BLOCK ELITE :
    detect_breaker_blocks() → 3 conditions strictes
    • BOS a physiquement traversé l'OB
    • Prix actuel dans la zone (retest confirmé)
    • Bonus score +18 — Breaker > OB classique

Nouveautes v8 — LOGIQUE INSTITUTIONNELLE REELLE :

  ARCHITECTURE TRIPOLAIRE (H1 → M15 → M5) :
    H1  → BIAIS directionnel (macro)
    M15 → ZONE institutionnelle (OB / FVG / Liquidity)
    M5  → TRIGGER d'entrée précis — OBLIGATOIRE

  RR MINIMUM : 3.0  |  SCORE MINIMUM : 80/100

  Marchés couverts :
    FOREX      — 28 paires majeures + mineures + exotiques
    CRYPTO     — BTC, ETH, XRP, SOL, BNB, DOGE, ADA, AVAX, LTC, LINK
    INDICES    — SPX, NAS, DAX, CAC, FTSE, Nikkei, HSI
    COMMODITÉS — Gold, Silver, Oil WTI, Oil Brent, Gaz Naturel, Cuivre

  Usage :
    python smc_signals_v11.py                       # scan complet
    python smc_signals_v11.py --cat forex
    python smc_signals_v11.py --symbol EURUSD=X
    python smc_signals_v11.py --min-score 80
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
    <tr><td>Timeframes</td><td>H1 biais → M15 zone → M5 trigger obligatoire (v8)</td></tr>
    <tr><td>Agent IA Claude</td><td>{'✅ Actif' if AI_VERIFY_ENABLED and ANTHROPIC_API_KEY else '⚠️ Désactivé (clé API manquante)' if AI_VERIFY_ENABLED else '⏸ Désactivé (mode test)'}</td></tr>
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
LTF             = "15m"    # Zone institutionnelle (OB / FVG / Liquidity)
MTF_M5          = "5m"     # Trigger d'entrée précis — OBLIGATOIRE en v8
# ─── NOTE v8 ─────────────────────────────────────────────────
# Architecture tripolaire RÉELLE :
#   H1  → BIAIS macro directionnel
#   M15 → ZONE institutionnelle (OB / FVG / Liquidity sweep)
#   M5  → TRIGGER obligatoire — sans trigger M5, pas de signal
# ─────────────────────────────────────────────────────────────

# ── Agent IA Claude — DÉSACTIVÉ en v8 ───────────────────────
# L'agent IA Anthropic est retiré du pipeline de validation.
# Le score SMC (≥80) + RR (≥3.0) + trigger M5 sont les seuls juges.
ANTHROPIC_API_KEY = ""          # Non utilisé en v8
AI_VERIFY_ENABLED = False       # Désactivé définitivement

FVG_MIN_RATIO   = 0.0002   # FVG plus sensible sur M5/M1
OB_LOOKBACK     = 5
LIQ_THRESHOLD   = 0.0004
SCORE_THRESHOLD = 80       # Seuil élevé → signaux élite uniquement
MIN_RR          = 3.0      # RR net spread minimum — élite uniquement
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
    "SOL-USD":  0.50,
    "BNB-USD":  0.50,
    "XRP-USD":  0.003,
    "ADA-USD":  0.002,
    "AVAX-USD": 0.20,
    "LINK-USD": 0.05,
    "DOGE-USD": 0.001,
    "LTC-USD":  0.30,
    # Indices
    "^GSPC":    8.0,
    "^NDX":     30.0,
    "^DJI":     80.0,
    "^GDAXI":   40.0,
    "^FCHI":    15.0,
    "^FTSE":    15.0,
    "^N225":    80.0,
    "^HSI":     80.0,
}
ATR_MIN_DEFAULT = 0.00050  # fallback pour symboles non listés

# ─────────────────────────────────────────────────────────────
#  SESSIONS — SCAN 07h–17h UTC (fenetre large)
#
#  Le bot scanne de 07h à 17h UTC sans interruption.
#  Londres + NY couverts. Pas de blocage mid-session.
#
#  HEURES SENSIBLES — signal envoyé AVEC avertissement :
#    08:30–09:00 UTC  → NFP / CPI UK  (spike possible)
#    10:00–13:00 UTC  → Mid-London dull zone  (faible volume)
#    13:30–14:00 UTC  → NFP / CPI / PPI US  (spike possible)
#    15:00–15:30 UTC  → FOMC / ISM  (spike possible)
#
#  Ces fenêtres ne bloquent PAS le signal — elles ajoutent
#  un panneau ⚠️ visible dans le message Telegram.
# ─────────────────────────────────────────────────────────────
SESSION_START_UTC = 7    # 07:00 UTC
SESSION_END_UTC   = 17   # 17:00 UTC

# Fenêtres sensibles — WARNING dans le signal, pas de blocage
# Format : (h_debut, m_debut, h_fin, m_fin, label)
SENSITIVE_WINDOWS_UTC: list[tuple[int, int, int, int, str]] = [
    (8,  30, 9,  0,  "NFP / CPI UK"),
    (10,  0, 13,  0, "Mid-London dull zone (faible volume)"),
    (13, 30, 14,  0, "NFP / CPI / PPI US"),
    (15,  0, 15, 30, "FOMC / ISM"),
]

# Ratio spread/ATR max
MAX_SPREAD_ATR_RATIO = 0.25

# ─────────────────────────────────────────────────────────────
#  v10 — CLEAN PA FILTER (fusion smc_clean_pa_v1)
# ─────────────────────────────────────────────────────────────
CLEAN_MIN_SCORE           = 5      # clean_score < 5 → signal bloqué
CLEAN_DISPLACEMENT_BODY   = 1.5    # corps > avg_body × 1.5 = impulsion forte
CLEAN_DISPLACEMENT_CONSEC = 2      # N bougies consécutives minimum
CLEAN_DISPLACEMENT_ATR    = 1.1    # corps > 110% ATR = Marubozu/displacement
CLEAN_CHOP_ALT_RATIO      = 0.62   # 62% alternance couleurs = choppy
CLEAN_CHOP_BODY_RATIO     = 0.38   # body/range moyen < 38% = indécision
CLEAN_CHOP_WINDOW         = 12     # fenêtre bougies pour analyse chop
CLEAN_PULLBACK_BODY_MAX   = 0.75   # corps pullback < 75% avg_body = calme
CLEAN_PULLBACK_WINDOW     = 8      # bougies max à analyser dans le pullback
CLEAN_STRUCTURE_MIN_SWINGS = 2     # swings HH/HL ou LH/LL minimum

# ─────────────────────────────────────────────────────────────
#  v10 — SEUILS CLEAN PA ADAPTATIFS PAR INSTRUMENT
#
#  Gold et BTC ont des bougies beaucoup plus grandes que le Forex.
#  Un "displacement" Gold = 1.5–2$ de corps sur M15.
#  Si on applique les mêmes ratios qu'en Forex → trop de faux positifs
#  ou au contraire tout est bloqué.
#
#  Solution : override des seuils par groupe d'instruments.
# ─────────────────────────────────────────────────────────────
# Symboles nécessitant des seuils adaptés (haute volatilité)
CLEAN_PA_HIGH_VOL = frozenset({
    "GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "PL=F", "PA=F",  # commodités
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",              # crypto
    "^GSPC", "^NDX", "^DJI", "^GDAXI", "^FCHI", "^FTSE", "^N225",      # indices
})
# Seuils haute volatilité — plus permissifs sur l'alternance chop
# (Gold alterne naturellement plus que l'EURUSD)
CLEAN_CHOP_ALT_RATIO_HV   = 0.72   # tolérance alternance élevée pour or/btc
CLEAN_CHOP_BODY_RATIO_HV  = 0.30   # body/range min plus faible (bougies à mèches)
CLEAN_DISPLACEMENT_ATR_HV = 0.90   # displacement = 0.9× ATR suffit sur Gold/BTC

# Fréquence de scan prioritaire Tier 1 (Gold/BTC/Indices)
# TIER_1_SCAN_EVERY_N = 1 → chaque cycle
# TIER_1_SCAN_EVERY_N = 2 → un cycle sur deux intercalé
TIER_1_SCAN_EVERY_N = 1   # Gold/BTC scannés à CHAQUE cycle (déjà en tête)


def is_session_active(symbol: str = "") -> bool:
    """
    Retourne True si le scan est autorisé pour ce symbole.

    ─ Forex / Indices / Commodités :
        Actif entre 07h et 17h UTC (London + NY).
        Bloqué le week-end (marchés fermés).

    ─ BTC-USD (crypto) :
        Actif 24h/24, 7j/7 — Bitcoin ne ferme jamais.
        Aucune restriction de session ni de jour.
    """
    now = datetime.now(timezone.utc)

    # Crypto → BTC-USD uniquement autorisé 24h/24, 7j/7 (week-end inclus)
    # Les autres cryptos suivent les mêmes restrictions que le Forex le week-end.
    if symbol == "BTC-USD":
        return True

    # Week-end → marchés Forex/Indices fermés (samedi=5, dimanche=6)
    if now.weekday() >= 5:
        return False

    return SESSION_START_UTC <= now.hour < SESSION_END_UTC


def get_session_warning() -> str:
    """
    Retourne un label d'avertissement si l'heure courante est dans
    une fenêtre sensible (news, manipulation, faible volume).
    Retourne '' si heure neutre — aucun avertissement.
    """
    now = datetime.now(timezone.utc)
    now_min = now.hour * 60 + now.minute
    for (h1, m1, h2, m2, label) in SENSITIVE_WINDOWS_UTC:
        if h1 * 60 + m1 <= now_min < h2 * 60 + m2:
            return label
    return ""


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

    if atr < atr_min * 0.60:
        return False, f"ATR trop faible ({round(atr, 5)} < {round(atr_min*0.60,5)})"

    ratio = spread / atr if atr > 0 else 1.0
    if ratio > MAX_SPREAD_ATR_RATIO:
        return False, f"spread/ATR={round(ratio*100,1)}% > {int(MAX_SPREAD_ATR_RATIO*100)}%"

    if not is_session_active(symbol):
        return False, "hors session (avant 07h ou apres 17h UTC) / week-end"

    return True, ""

# ─────────────────────────────────────────────────────────────
#  v8 — FILTRE MARCHÉ : TREND vs RANGE
# ─────────────────────────────────────────────────────────────
def market_condition(df_m15: pd.DataFrame) -> str:
    """
    Détecte si le marché est en TREND ou en RANGE sur M15.

    Méthode :
      ATR(14) mesure la volatilité moyenne d'une bougie.
      Range 20 = distance entre le plus haut et le plus bas des 20 dernières bougies.
      Si ATR < 15% du range → marché comprimé → RANGE.
      Sinon → marché directionnel → TREND.

    En RANGE :
      • Les OB classiques sont invalides (trop de faux signaux)
      • Seuls les sweeps des extrêmes du range sont tradables
      → pipeline bloqué partiellement (OB ignorés, FVG aux extrêmes seulement)

    Retourne : "TREND" ou "RANGE"
    """
    if df_m15 is None or len(df_m15) < 20:
        return "TREND"  # fallback → laisse passer le pipeline

    atr = (df_m15["high"] - df_m15["low"]).rolling(14).mean().iloc[-1]
    range_size = (
        df_m15["high"].rolling(20).max().iloc[-1]
        - df_m15["low"].rolling(20).min().iloc[-1]
    )

    if range_size <= 0 or np.isnan(atr) or np.isnan(range_size):
        return "TREND"

    if atr < range_size * 0.15:
        return "RANGE"
    return "TREND"


# ─────────────────────────────────────────────────────────────
#  v8 — ZONE FRAÎCHE : OB / FVG non mitiqué
# ─────────────────────────────────────────────────────────────
def is_zone_fresh(df: pd.DataFrame, zone_top: float, zone_bottom: float,
                  formed_index: int) -> bool:
    """
    Vérifie qu'une zone (OB ou FVG) est FRAÎCHE :
    le prix n'a PAS clôturé À L'INTÉRIEUR de la zone depuis sa formation.

    Une zone traversée = zone mitiquée = invalide pour une entrée institutionnelle.

    Args:
        df           : DataFrame complet
        zone_top     : limite haute de la zone
        zone_bottom  : limite basse de la zone
        formed_index : index de formation de la zone dans df

    Retourne True si la zone est intacte (jamais mitiquée depuis formation).
    """
    if formed_index + 1 >= len(df):
        return True  # aucune bougie après la formation → considérée fraîche

    lo = min(zone_top, zone_bottom)
    hi = max(zone_top, zone_bottom)

    for i in range(formed_index + 1, len(df)):
        close = df["close"].iloc[i]
        if lo <= close <= hi:
            return False  # mitiquée — zone brûlée

    return True  # toujours vierge — zone fraîche


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
    "SOL-USD":  0.05,
    "BNB-USD":  0.10,
    "XRP-USD":  0.0003,
    "ADA-USD":  0.0002,
    "AVAX-USD": 0.05,
    "LINK-USD": 0.01,
    "DOGE-USD": 0.0001,
    "LTC-USD":  0.05,
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
SIGNAL_COOLDOWN  = 900           # 15 minutes par (symbol, direction)
_signal_cache: dict[str, float] = {}   # clé → timestamp dernier envoi

# ── Un seul signal par setup — clé basée sur le SL (pas le score) ──
# Le SL identifie l'OB/swing utilisé. Même biais + même SL = même setup.
# Réinitialisé si le biais H1 change ou après SETUP_TTL secondes.
_setup_sent: dict[str, float] = {}    # clé → timestamp d'envoi
SETUP_TTL = 1800                       # 30 min — après ça, re-send autorisé si setup toujours actif

def _setup_key(symbol: str, direction: str, sl: float) -> str:
    """Clé unique de setup : paire + direction + SL arrondi à 3 décimales significatives."""
    sl_rounded = round(sl, 3) if sl > 10 else round(sl, 5)
    return f"{symbol}:{direction}:{sl_rounded}"

def is_setup_already_sent(symbol: str, direction: str, sl: float) -> bool:
    key = _setup_key(symbol, direction, sl)
    if key not in _setup_sent:
        return False
    # Expire après SETUP_TTL
    if time.time() - _setup_sent[key] > SETUP_TTL:
        del _setup_sent[key]
        return False
    return True

def mark_setup_sent(symbol: str, direction: str, sl: float) -> None:
    _setup_sent[_setup_key(symbol, direction, sl)] = time.time()

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
    tier_badge = "🥇 PRIORITE" if "TIER 1" in tier else ("🥈 FOREX" if "TIER 2" in tier else "🥉")
    rr_bar     = "⭐" * min(int(sig.rr), 5)
    score_bar  = "█" * (sig.score // 10) + "░" * (10 - sig.score // 10)

    dec = 2 if sig.entry > 100 else 5
    risk  = round(abs(sig.entry - sig.sl),  dec)
    gain  = round(abs(sig.tp  - sig.entry), dec)
    spread_val = get_spread(sig.symbol)
    spread_disp = round(spread_val, dec)

    ts = sig.timestamp.strftime("%d/%m/%Y %H:%M UTC")
    gain_usd = round(sig.risk_usd * sig.rr, 2)

    # ── Bannière avertissement heure sensible ──────────────────
    warning_label = get_session_warning()
    if warning_label:
        warning_banner = (
            f"\n⚠️ <b>ATTENTION — HEURE SENSIBLE</b> ⚠️\n"
            f"<i>Fenetre : {warning_label}</i>\n"
            f"<i>Risque de spike / faux mouvement. Attendre confirmation supplementaire ou reduire la taille.</i>\n"
            f"{'─'*30}\n"
        )
    else:
        warning_banner = ""

    # ── Badges setup (OTE / Breaker Elite / Clean PA / AMD) ────────
    setup_badges = ""
    has_breaker = any("BREAKER BLOCK ELITE" in r or "Breaker Block" in r
                      for r in sig.reasons)
    has_ote     = any("OTE Fibonacci" in r for r in sig.reasons)
    has_pa_perfect = any("PRICE ACTION PARFAIT" in r for r in sig.reasons)
    has_pa_clean   = any("PRICE ACTION PROPRE" in r for r in sig.reasons)
    has_displacement = any("Impulsion" in r for r in sig.reasons)
    has_amd_manip  = any("AMD — Phase Manipulation" in r for r in sig.reasons)
    has_amd_dist   = any("AMD — Phase Distribution" in r for r in sig.reasons)
    has_d1_aligned = any("Tendance D1" in r for r in sig.reasons)

    if has_breaker and has_ote:
        setup_badges += "🔥 <b>BREAKER BLOCK ELITE + OTE DWO</b> — Setup A+ institutionnel\n"
    elif has_breaker:
        setup_badges += "🔥 <b>BREAKER BLOCK ELITE</b> — Zone flippée retestée\n"
    elif has_ote:
        setup_badges += "📐 <b>OTE 62%–79% (DWO)</b> — Dealing Range Fibonacci\n"

    if has_pa_perfect:
        setup_badges += "💎 <b>PRICE ACTION INSTITUTIONNEL</b> — Displacement + Structure + Pullback\n"
    elif has_pa_clean:
        setup_badges += "🎯 <b>PRICE ACTION PROPRE</b> — Setup lisible et propre\n"
    elif not has_displacement:
        setup_badges += "⚠️ <i>Zone sans impulsion confirmée</i>\n"

    # ── Badges AMD + D1 trend ────────────────────────────────
    if has_amd_manip:
        setup_badges += "🔄 <b>AMD — PHASE MANIPULATION</b> — Stop hunt + retour dans le range\n"
    elif has_amd_dist:
        setup_badges += "🔄 <b>AMD — PHASE DISTRIBUTION</b> — Move impulsif post-manipulation\n"
    if has_d1_aligned:
        d1_dir = "BULLISH" if "BULLISH" in next((r for r in sig.reasons if "Tendance D1" in r), "") else "BEARISH"
        setup_badges += f"📅 <b>TENDANCE D1 {d1_dir}</b> — Trade dans le sens du fond\n"

    msg = (
        f"<b>⚡ SMC SIGNAL ELITE  —  {tier_badge}</b>\n"
        f"{'─'*30}\n"
        f"{warning_banner}"
        f"{setup_badges}"
        f"<b>Marche   :</b>  <code>{sig.symbol}</code>\n"
        f"<b>Direction:</b>  <b>{dir_emoji}</b>\n"
        f"<b>Biais H1 :</b>  {sig.htf_bias}\n"
        f"<b>TF Analyse:</b>  H1 biais → M15 zone → M5 trigger (v9)\n"
        f"{'─'*30}\n"
        f"<b>📍 Entree    :</b>  <code>{sig.entry}</code>  ← <i>prix marche actuel</i>\n"
        f"<b>🔴 Stop Loss :</b>  <code>{sig.sl}</code>   <i>(risk {risk})</i>\n"
        f"<b>🟢 Take Profit:</b> <code>{sig.tp}</code>   <i>(gain brut {gain})</i>\n"
        f"<b>📊 Spread    :</b>  <code>{spread_disp}</code>   <i>(deduit du RR)</i>\n"
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

    # ── Guard 1 : Validation SL — jamais envoyer un SL inversé ──
    if sig.direction == "LONG" and sig.sl >= sig.entry:
        log.warning(f"  [TG] ⛔ BLOQUÉ — SL LONG inversé ({sig.sl} >= {sig.entry})")
        return
    if sig.direction == "SHORT" and sig.sl <= sig.entry:
        log.warning(f"  [TG] ⛔ BLOQUÉ — SL SHORT inversé ({sig.sl} <= {sig.entry})")
        return
    if abs(sig.entry - sig.sl) < 0.00003:
        log.warning(f"  [TG] ⛔ BLOQUÉ — SL trop serré (distance < 0.3 pip)")
        return

    # ── Guard 2 : Déduplication par SL (même setup = même SL) ──
    if is_setup_already_sent(sig.symbol, sig.direction, sig.sl):
        print(c(f"  [TG] ⏭ Setup déjà envoyé — {sig.symbol} {sig.direction} "
                f"SL={sig.sl} — ignoré.", "yellow"))
        return
    mark_setup_sent(sig.symbol, sig.direction, sig.sl)

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


# ═════════════════════════════════════════════════════════════
#  AGENT IA CLAUDE — VÉRIFICATEUR DE SETUP SMC
#
#  Rôle : avant tout envoi Telegram, Claude analyse le signal
#  et vérifie la cohérence SMC (biais, confluence, RR, structure).
#  Si le setup est douteux → signal bloqué, raison loggée.
#
#  Modèle : claude-sonnet-4-20250514  (rapide, précis, économique)
#  Timeout : 12s (le scan ne doit pas être ralenti)
# ═════════════════════════════════════════════════════════════

def claude_verify_signal(sig: "Signal") -> tuple[bool, str]:
    """
    Envoie le signal à l'agent Claude pour vérification SMC.
    Retourne (validated: bool, comment: str).

    validated = True  → signal cohérent, envoi autorisé
    validated = False → signal rejeté, raison dans comment
    """
    if not AI_VERIFY_ENABLED:
        return True, "IA désactivée (mode test)"

    if not ANTHROPIC_API_KEY:
        log.warning("  [IA] ⚠ ANTHROPIC_API_KEY manquante — vérification IA ignorée.")
        return True, "Clé API manquante"

    dec = 2 if sig.entry > 100 else 5
    risk_pts = round(abs(sig.entry - sig.sl), dec)
    gain_pts = round(abs(sig.tp - sig.entry), dec)
    confluence_text = "\n".join(f"  - {r}" for r in sig.reasons)

    prompt = f"""Tu es un expert en Smart Money Concepts (SMC) / ICT.
Analyse ce signal de trading M15 et dis-moi s'il est valide.

=== SIGNAL ===
Marché    : {sig.symbol}
Direction : {sig.direction}
Biais H1  : {sig.htf_bias}
Entrée    : {sig.entry}
Stop Loss : {sig.sl}  (risque {risk_pts})
Take Profit: {sig.tp}  (gain {gain_pts})
R:R net   : 1:{sig.rr}
Score     : {sig.score}/100
TF Entrée : M15 (plus de M5 ni M1)

=== CONFLUENCE ===
{confluence_text}

=== RÈGLES DE VALIDATION ===
1. Le biais H1 doit être aligné avec la direction du trade.
2. Il faut au minimum BOS M15 OU un Order Block M15 validé.
3. Un FVG actif ou un Breaker Block renforce le setup.
4. Le RR net doit être ≥ 3.0 — en dessous c'est insuffisant.
5. Un score < 70 est insuffisant.
6. Le Stop Loss doit être du bon côté (LONG → SL < entrée, SHORT → SL > entrée).

Réponds UNIQUEMENT en JSON valide, sans markdown, sans explication, format exact :
{{"validated": true/false, "comment": "Raison courte en français (1-2 phrases max)"}}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key"        : ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type"     : "application/json",
            },
            json={
                "model"      : "claude-sonnet-4-20250514",
                "max_tokens" : 150,
                "messages"   : [{"role": "user", "content": prompt}],
            },
            timeout=12,
        )

        if resp.status_code != 200:
            log.warning(f"  [IA] ✗ API Claude {resp.status_code} — signal autorisé par défaut.")
            return True, f"Erreur API {resp.status_code}"

        raw = resp.json()["content"][0]["text"].strip()
        # Nettoyage JSON (retire éventuels ```json ... ```)
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = __import__("json").loads(raw)

        validated = bool(result.get("validated", True))
        comment   = str(result.get("comment", ""))

        icon = "✅" if validated else "❌"
        log.info(f"  [IA] {icon} {comment}")
        return validated, comment

    except __import__("json").JSONDecodeError as e:
        log.warning(f"  [IA] ⚠ JSON invalide de Claude : {e} — signal autorisé.")
        return True, "Réponse IA non parseable"
    except Exception as e:
        log.warning(f"  [IA] ⚠ Erreur agent Claude : {e} — signal autorisé par défaut.")
        return True, f"Erreur : {e}"


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
#  v10 — CLEAN PA CONTEXT (fusion smc_clean_pa_v1)
# ─────────────────────────────────────────────────────────────
@dataclass
class CleanPAContext:
    """
    Résultat de l'analyse qualité Price Action (Clean PA).

    Évalue la propreté du marché sur 4 dimensions :
      1. STRUCTURE    — HH/HL ou LH/LL clairs (pas de zigzag)
      2. DISPLACEMENT — Vraie impulsion forte avant la zone (CRITIQUE)
      3. LIQUIDITÉ    — Equal highs/lows sweepés avant le move
      4. PULLBACK     — Retour calme dans la zone (pas chaotique)
      + CHOP FILTER   — Bloque les marchés sans direction

    clean_score ≥ CLEAN_MIN_SCORE ET displacement_ok → signal autorisé
    Sinon → return None dans analyse()
    """
    structure_ok      : bool  = False
    swing_count       : int   = 0
    structure_type    : str   = ""
    displacement_ok   : bool  = False
    impulse_strength  : float = 0.0
    impulse_consec    : int   = 0
    bars_since_impulse: int   = 0
    liquidity_swept   : bool  = False
    sweep_level       : float = 0.0
    sweep_type        : str   = ""
    pullback_ok       : bool  = False
    pullback_quality  : float = 0.0
    pullback_bars     : int   = 0
    is_choppy         : bool  = False
    chop_score        : float = 0.0
    chop_reason       : str   = ""

    @property
    def clean_score(self) -> int:
        s = 0
        if self.structure_ok    : s += 2
        if self.displacement_ok : s += 3
        if self.liquidity_swept : s += 2
        if self.pullback_ok     : s += 2
        if self.is_choppy       : s -= 3
        return max(s, 0)

    @property
    def is_valid(self) -> bool:
        return self.clean_score >= CLEAN_MIN_SCORE and self.displacement_ok

    @property
    def label(self) -> str:
        s = self.clean_score
        if s >= 8 : return "PRICE ACTION PARFAIT — Setup A+"
        if s >= 6 : return "PRICE ACTION PROPRE — Setup B+"
        if s >= CLEAN_MIN_SCORE : return "PRICE ACTION ACCEPTABLE"
        return "PRICE ACTION INSUFFISANT — Bloqué"

    @property
    def bonus_score(self) -> int:
        s = self.clean_score
        if s >= 8 : return 15
        if s >= 6 : return 8
        if s >= CLEAN_MIN_SCORE : return 3
        return 0


# ─────────────────────────────────────────────────────────────
#  v10 — FONCTIONS CLEAN PA
# ─────────────────────────────────────────────────────────────

def detect_market_structure_quality(df: pd.DataFrame,
                                     direction: str,
                                     lookback: int = 40) -> dict:
    """HH/HL ou LH/LL clairs sur les N dernières bougies."""
    result = {"found": False, "swing_count": 0, "structure_type": "UNCLEAR"}
    if len(df) < 20:
        return result

    window = df.iloc[-lookback:-1]
    highs, lows = [], []
    for i in range(2, len(window) - 2):
        h = window["high"].iloc[i]
        l = window["low"].iloc[i]
        if (h > window["high"].iloc[i-1] and h > window["high"].iloc[i-2]
                and h > window["high"].iloc[i+1] and h > window["high"].iloc[i+2]):
            highs.append((i, h))
        if (l < window["low"].iloc[i-1]  and l < window["low"].iloc[i-2]
                and l < window["low"].iloc[i+1] and l < window["low"].iloc[i+2]):
            lows.append((i, l))

    if len(highs) < 2 or len(lows) < 2:
        return result

    hh_hl_count, lh_ll_count = 0, 0
    for i in range(1, len(highs)):
        if highs[i][1] > highs[i-1][1]: hh_hl_count += 1
        if highs[i][1] < highs[i-1][1]: lh_ll_count += 1
    for i in range(1, len(lows)):
        if lows[i][1] > lows[i-1][1]: hh_hl_count += 1
        elif lows[i][1] < lows[i-1][1]: lh_ll_count += 1

    if direction == "LONG":
        swing_count = hh_hl_count
        struct_type = "BULLISH_TREND" if swing_count >= CLEAN_STRUCTURE_MIN_SWINGS else "UNCLEAR"
    else:
        swing_count = lh_ll_count
        struct_type = "BEARISH_TREND" if swing_count >= CLEAN_STRUCTURE_MIN_SWINGS else "UNCLEAR"

    found = swing_count >= CLEAN_STRUCTURE_MIN_SWINGS
    result.update({"found": found, "swing_count": swing_count, "structure_type": struct_type})
    return result


def detect_displacement(df: pd.DataFrame, direction: str, lookback: int = 15) -> dict:
    """
    Détecte une vraie impulsion forte récente (critère le plus important).
    Critère A : corps > avg_body × 1.5 pendant N bougies consécutives.
    Critère B : une seule bougie avec corps > ATR × 1.1 (Marubozu).
    """
    result = {"found": False, "strength": 0.0, "consec": 0, "bars_ago": 99}
    if len(df) < 15:
        return result

    window   = df.iloc[-(lookback + 5):-1]
    n        = len(window)
    atr      = (window["high"] - window["low"]).rolling(14).mean().iloc[-1]
    if np.isnan(atr) or atr <= 0:
        return result

    bodies   = abs(window["close"] - window["open"])
    avg_body = bodies.mean()
    if avg_body <= 0:
        return result

    is_bull_dir   = (direction == "LONG")
    best_strength = 0.0
    best_consec   = 0
    best_bars_ago = 99

    for i in range(n - 1, -1, -1):
        is_bull = window["close"].iloc[i] > window["open"].iloc[i]
        body    = bodies.iloc[i]
        strength = body / atr if atr > 0 else 0

        if (is_bull_dir != is_bull):
            continue

        if body > atr * CLEAN_DISPLACEMENT_ATR:
            consec = 1
            for j in range(i - 1, max(i - 5, -1), -1):
                if (window["close"].iloc[j] > window["open"].iloc[j]) == is_bull_dir:
                    consec += 1
                else:
                    break
            bars_ago = n - 1 - i
            if strength > best_strength:
                best_strength, best_consec, best_bars_ago = strength, consec, bars_ago

        elif body > avg_body * CLEAN_DISPLACEMENT_BODY:
            consec = 1
            for j in range(i - 1, max(i - CLEAN_DISPLACEMENT_CONSEC - 2, -1), -1):
                b_is_bull = window["close"].iloc[j] > window["open"].iloc[j]
                b_body    = abs(window["close"].iloc[j] - window["open"].iloc[j])
                if b_is_bull == is_bull_dir and b_body > avg_body:
                    consec += 1
                else:
                    break
            if consec >= CLEAN_DISPLACEMENT_CONSEC:
                bars_ago = n - 1 - i
                if strength > best_strength:
                    best_strength, best_consec, best_bars_ago = strength, consec, bars_ago

    found = (
        best_strength >= CLEAN_DISPLACEMENT_ATR
        or (best_consec >= CLEAN_DISPLACEMENT_CONSEC
            and best_strength >= CLEAN_DISPLACEMENT_BODY * 0.8)
    )
    if found:
        result.update({"found": True, "strength": round(best_strength, 2),
                        "consec": best_consec, "bars_ago": best_bars_ago})
    return result


def detect_choppy_market(df: pd.DataFrame,
                          window_size: int = CLEAN_CHOP_WINDOW) -> dict:
    """
    3 signaux de chop : alternance couleurs, corps/range faible, range total faible.
    2/3 critères confirmés = marché choppy → signal bloqué.
    """
    result = {"is_choppy": False, "chop_score": 0.0, "reason": ""}
    if len(df) < window_size + 5:
        return result

    window = df.iloc[-(window_size + 3):-1]
    n      = len(window)
    chop_signals = []

    colors = [window["close"].iloc[i] > window["open"].iloc[i] for i in range(n)]
    alternations = sum(1 for i in range(1, n) if colors[i] != colors[i-1])
    alt_ratio = alternations / max(n - 1, 1)
    if alt_ratio >= CLEAN_CHOP_ALT_RATIO:
        chop_signals.append(f"alternance {round(alt_ratio*100)}%")

    bodies = abs(window["close"] - window["open"])
    ranges = window["high"] - window["low"]
    body_ratio_mean = (bodies / ranges.replace(0, np.nan)).mean()
    if pd.isna(body_ratio_mean):
        body_ratio_mean = 0.5
    if body_ratio_mean < CLEAN_CHOP_BODY_RATIO:
        chop_signals.append(f"body/range={round(body_ratio_mean, 2)}")

    atr = (window["high"] - window["low"]).rolling(7).mean().iloc[-1]
    total_range = window["high"].max() - window["low"].min()
    if not np.isnan(atr) and atr > 0:
        range_vs_atr = total_range / atr
        if range_vs_atr < 2.0:
            chop_signals.append(f"range={round(range_vs_atr, 1)}×ATR")

    chop_score = len(chop_signals) / 3.0
    is_choppy  = len(chop_signals) >= 2
    result.update({
        "is_choppy" : is_choppy,
        "chop_score": round(chop_score, 2),
        "reason"    : " | ".join(chop_signals) if chop_signals else "clean",
    })
    return result


def detect_clean_pullback(df: pd.DataFrame, direction: str,
                           zone_high: float, zone_low: float) -> dict:
    """
    Pullback propre = retour calme dans la zone (petites bougies, pas de
    contre-impulsion violente). quality ≥ 0.45 ET violent_counter ≤ 1 → valide.
    """
    result = {"found": False, "quality": 0.0, "bars": 0}
    if len(df) < 10 or zone_high <= zone_low:
        return result

    window  = df.iloc[-(CLEAN_PULLBACK_WINDOW + 3):-1]
    n       = len(window)
    price   = df["close"].iloc[-1]
    atr     = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    if np.isnan(atr) or atr <= 0:
        return result

    bodies   = abs(window["close"] - window["open"])
    avg_body = bodies.mean()
    if avg_body <= 0:
        return result

    zone_mid  = (zone_high + zone_low) / 2
    in_zone   = zone_low <= price <= zone_high
    near_zone = abs(price - zone_mid) <= atr * 1.5
    if not (in_zone or near_zone):
        return result

    is_bull_dir     = direction == "LONG"
    calm_bars       = 0
    violent_counter = 0
    for i in range(n):
        body    = bodies.iloc[i]
        is_bull = window["close"].iloc[i] > window["open"].iloc[i]
        if body < avg_body * CLEAN_PULLBACK_BODY_MAX:
            calm_bars += 1
        is_counter = (is_bull_dir and not is_bull) or (not is_bull_dir and is_bull)
        if is_counter and body > avg_body * CLEAN_DISPLACEMENT_BODY:
            violent_counter += 1

    quality = max(0.0, round(calm_bars / max(n, 1) - violent_counter * 0.3, 2))
    found   = quality >= 0.45 and violent_counter <= 1
    result.update({"found": found, "quality": quality, "bars": n})
    return result


def detect_liquidity_sweep_pa(df: pd.DataFrame, direction: str,
                               lookback: int = 25) -> dict:
    """
    Equal highs/lows sweepés récemment = liquidity grab avant le move.
    SHORT → sweep high évident. LONG → sweep low évident.
    """
    result = {"found": False, "level": 0.0, "sweep_type": ""}
    if len(df) < lookback + 5:
        return result

    window    = df.iloc[-(lookback + 5):-1]
    atr       = (window["high"] - window["low"]).rolling(14).mean().iloc[-1]
    if np.isnan(atr) or atr <= 0:
        return result

    tolerance = atr * 0.25

    if direction == "SHORT":
        highs = window["high"].values
        for i in range(len(highs) - 3):
            for j in range(i + 2, len(highs)):
                if abs(highs[i] - highs[j]) <= tolerance:
                    level = max(highs[i], highs[j])
                    if df["high"].iloc[-1] > level and df["close"].iloc[-1] < level:
                        result.update({"found": True, "level": round(level, 5), "sweep_type": "EQH"})
                        return result
        swing_high = window["high"].max()
        if df["high"].iloc[-1] > swing_high and df["close"].iloc[-1] < swing_high:
            result.update({"found": True, "level": round(swing_high, 5), "sweep_type": "SWING_H"})
    else:
        lows = window["low"].values
        for i in range(len(lows) - 3):
            for j in range(i + 2, len(lows)):
                if abs(lows[i] - lows[j]) <= tolerance:
                    level = min(lows[i], lows[j])
                    if df["low"].iloc[-1] < level and df["close"].iloc[-1] > level:
                        result.update({"found": True, "level": round(level, 5), "sweep_type": "EQL"})
                        return result
        swing_low = window["low"].min()
        if df["low"].iloc[-1] < swing_low and df["close"].iloc[-1] > swing_low:
            result.update({"found": True, "level": round(swing_low, 5), "sweep_type": "SWING_L"})

    return result


def detect_clean_pa_context(df: pd.DataFrame, direction: str,
                              zone_high: float = 0.0,
                              zone_low:  float = 0.0) -> CleanPAContext:
    """
    Orchestrateur Clean PA — évalue les 4 dimensions et retourne un
    CleanPAContext complet.
    Appeler dans analyse() APRÈS détection zones (OB/FVG/Breaker)
    et AVANT compute_score().
    """
    ctx = CleanPAContext()

    struct = detect_market_structure_quality(df, direction)
    if struct["found"]:
        ctx.structure_ok   = True
        ctx.swing_count    = struct["swing_count"]
        ctx.structure_type = struct["structure_type"]

    disp = detect_displacement(df, direction)
    if disp["found"]:
        ctx.displacement_ok    = True
        ctx.impulse_strength   = disp["strength"]
        ctx.impulse_consec     = disp["consec"]
        ctx.bars_since_impulse = disp["bars_ago"]

    liq = detect_liquidity_sweep_pa(df, direction)
    if liq["found"]:
        ctx.liquidity_swept = True
        ctx.sweep_level     = liq["level"]
        ctx.sweep_type      = liq["sweep_type"]

    if zone_high > 0 and zone_low > 0:
        pull = detect_clean_pullback(df, direction, zone_high, zone_low)
        if pull["found"]:
            ctx.pullback_ok      = True
            ctx.pullback_quality = pull["quality"]
            ctx.pullback_bars    = pull["bars"]

    chop = detect_choppy_market(df)
    ctx.is_choppy   = chop["is_choppy"]
    ctx.chop_score  = chop["chop_score"]
    ctx.chop_reason = chop["reason"]

    return ctx


def _clean_pa_scoring_block(score: int, reasons: list,
                              clean_ctx: Optional[CleanPAContext]) -> tuple:
    """
    Bloc scoring Clean PA — appeler dans compute_score() après AMD, avant return.

    PA parfait  (≥8)  : +15
    PA propre   (≥6)  : +8
    PA ok       (≥5)  : +3
    Choppy            : −5
    Pas de displacement: −8 (return immédiat)
    Score < seuil     : −10
    """
    if clean_ctx is None:
        return score, reasons

    if clean_ctx.is_choppy:
        score = max(score - 5, 0)
        reasons.append(f"🚫 MARCHÉ CHOPPY — {clean_ctx.chop_reason}  (−5)")

    if not clean_ctx.displacement_ok:
        score = max(score - 8, 0)
        reasons.append("⚠️ AUCUNE IMPULSION — Zone sans displacement  (−8)")
        return score, reasons

    cs = clean_ctx.clean_score
    if cs >= 8:
        score = min(score + 15, 100)
        reasons.append(f"✨ PRICE ACTION PARFAIT — score {cs}/9  (+15)")
    elif cs >= 6:
        score = min(score + 8, 100)
        reasons.append(f"✅ PRICE ACTION PROPRE — score {cs}/9  (+8)")
    elif cs >= CLEAN_MIN_SCORE:
        score = min(score + 3, 100)
        reasons.append(f"🟡 PRICE ACTION ACCEPTABLE — score {cs}/9  (+3)")
    else:
        score = max(score - 10, 0)
        reasons.append(f"❌ PRICE ACTION INSUFFISANT — score {cs}/9  (−10)")

    details = []
    if clean_ctx.displacement_ok:
        details.append(f"Impulsion {clean_ctx.impulse_strength}×ATR"
                       + (f"×{clean_ctx.impulse_consec}b" if clean_ctx.impulse_consec > 1 else ""))
    if clean_ctx.structure_ok:
        details.append(f"Structure {clean_ctx.swing_count} swings")
    if clean_ctx.liquidity_swept:
        details.append(f"Liq {clean_ctx.sweep_type}")
    if clean_ctx.pullback_ok:
        details.append(f"Pullback q={clean_ctx.pullback_quality}")
    if details:
        reasons.append("  └ " + " | ".join(details))

    return score, reasons


def detect_clean_pa_adaptive(df: pd.DataFrame, direction: str,
                               symbol: str = "",
                               zone_high: float = 0.0,
                               zone_low:  float = 0.0) -> CleanPAContext:
    """
    Wrapper adaptatif de detect_clean_pa_context() pour Gold, BTC et hautes
    volatilités.

    Pour Gold/BTC/Indices/Commodités :
      • Seuil alternance chop relevé : 0.72 (vs 0.62 Forex) — Gold alterne naturellement plus
      • Seuil body/range chop abaissé : 0.30 (vs 0.38) — bougies à mèches normales sur Gold
      • Seuil displacement ATR abaissé : 0.90 (vs 1.10) — impulsion reste forte, ATR réel adapté

    Pour Forex standard : seuils originaux inchangés.
    """
    global CLEAN_CHOP_ALT_RATIO, CLEAN_CHOP_BODY_RATIO, CLEAN_DISPLACEMENT_ATR

    is_high_vol = symbol in CLEAN_PA_HIGH_VOL

    if is_high_vol:
        _orig_alt  = CLEAN_CHOP_ALT_RATIO
        _orig_body = CLEAN_CHOP_BODY_RATIO
        _orig_atr  = CLEAN_DISPLACEMENT_ATR
        CLEAN_CHOP_ALT_RATIO   = CLEAN_CHOP_ALT_RATIO_HV
        CLEAN_CHOP_BODY_RATIO  = CLEAN_CHOP_BODY_RATIO_HV
        CLEAN_DISPLACEMENT_ATR = CLEAN_DISPLACEMENT_ATR_HV

    ctx = detect_clean_pa_context(df, direction, zone_high=zone_high, zone_low=zone_low)

    if is_high_vol:
        CLEAN_CHOP_ALT_RATIO   = _orig_alt
        CLEAN_CHOP_BODY_RATIO  = _orig_body
        CLEAN_DISPLACEMENT_ATR = _orig_atr

    return ctx

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
    elif sym in ("BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD",
                 "ADAUSD", "AVAXUSD", "LINKUSD", "DOGEUSD", "LTCUSD") \
         or symbol in ("BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
                       "ADA-USD", "AVAX-USD", "LINK-USD", "DOGE-USD", "LTC-USD"):
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
#  v11 — TENDANCE DE FOND D1 (Daily Trend Filter)
#
#  Détermine la tendance macro sur Daily (D1).
#  Tout signal contre la tendance D1 → pénalité score −15.
#  Signal dans le sens D1 → bonus +15.
#
#  Méthode : EMA 50 + structure HH/HL (BULLISH) ou LH/LL (BEARISH)
#  Retourne : 'BULLISH', 'BEARISH', ou 'NEUTRAL'
# ─────────────────────────────────────────────────────────────
def daily_trend(df_d1: pd.DataFrame) -> str:
    """
    Analyse la tendance de fond sur le timeframe Daily (D1).

    Critères :
      1. EMA 50 — prix > EMA50 → tendance haussière
      2. Structure HH/HL sur 14 dernières bougies (BULLISH)
                 LH/LL sur 14 dernières bougies (BEARISH)
      3. Les deux doivent concorder pour un biais fort.

    Retourne 'BULLISH', 'BEARISH' ou 'NEUTRAL'.
    """
    if df_d1 is None or len(df_d1) < 55:
        return "NEUTRAL"

    closes = df_d1["close"].values
    highs  = df_d1["high"].values
    lows   = df_d1["low"].values

    # EMA 50 simple (convolution)
    ema50_vals = np.convolve(closes, np.ones(50) / 50, mode="valid")
    if len(ema50_vals) < 2:
        return "NEUTRAL"
    ema50_last = ema50_vals[-1]
    price_vs_ema = closes[-1] > ema50_last

    # Structure sur les 14 dernières bougies
    w_h = highs[-14:]
    w_l = lows[-14:]
    hh = w_h[-1] > w_h[:-1].max()       # nouveau highest high
    hl = w_l[-1] > w_l[-7:].min()        # higher low récent

    ll = w_l[-1] < w_l[:-1].min()        # nouveau lowest low
    lh = w_h[-1] < w_h[-7:].max()        # lower high récent

    if price_vs_ema and (hh or hl):
        return "BULLISH"
    if not price_vs_ema and (ll or lh):
        return "BEARISH"
    return "NEUTRAL"


# ─────────────────────────────────────────────────────────────
#  v11 — AMD CYCLE DETECTOR
#  (Accumulation · Manipulation · Distribution)
#
#  Logique Wyckoff / ICT sur H4 + H1 :
#
#  ACCUMULATION  → Range latéral H4 avec stop hunts successifs
#                   des lows (equal lows / spring) + volumes bas
#
#  MANIPULATION  → Spike brusque contra-trend suivi d'une clôture
#                   inverse (stop hunt d'un côté = manipulation)
#                   Détecté sur M15/H1 : wick extrême + retour fort
#
#  DISTRIBUTION  → Move impulsif H1 dans le sens du biais après
#                   la manipulation + BOS de structure courte
#
#  Retourne un dict :
#    phase      : 'ACCUMULATION' | 'MANIPULATION' | 'DISTRIBUTION' | 'UNKNOWN'
#    confidence : int 0–100
#    details    : str (description lisible)
#    direction  : str 'BULLISH' | 'BEARISH' | ''
# ─────────────────────────────────────────────────────────────
def detect_amd_cycle(df_h1: pd.DataFrame,
                     df_m15: pd.DataFrame) -> dict:
    """
    Détecte la phase AMD (Accumulation / Manipulation / Distribution)
    sur H1 et M15.

    Retourne :
        phase      — 'ACCUMULATION' | 'MANIPULATION' | 'DISTRIBUTION' | 'UNKNOWN'
        confidence — score 0–100
        details    — description de la phase pour le message Telegram
        direction  — biais probable de la Distribution ('BULLISH'|'BEARISH'|'')
    """
    result = {
        "phase"     : "UNKNOWN",
        "confidence": 0,
        "details"   : "Phase AMD indéterminée",
        "direction" : "",
    }

    if df_h1 is None or len(df_h1) < 30:
        return result
    if df_m15 is None or len(df_m15) < 30:
        return result

    atr_h1 = (df_h1["high"] - df_h1["low"]).rolling(14).mean().iloc[-1]
    if atr_h1 == 0 or np.isnan(atr_h1):
        return result

    w_h1    = df_h1.iloc[-30:]
    highs   = w_h1["high"].values
    lows    = w_h1["low"].values
    closes  = w_h1["close"].values
    opens   = w_h1["open"].values

    range_high = highs.max()
    range_low  = lows.min()
    range_size = range_high - range_low
    if range_size <= 0:
        return result

    last_close = closes[-1]

    # ── 1. Détection ACCUMULATION ─────────────────────────────
    # Critères :
    #   a) Range H1 comprimé (ATR < 30% du range des 30 dernières bougies)
    #   b) Equal lows / spring : 2+ lows quasi-identiques (tolerance 0.5% ATR)
    #   c) Clôtures restent dans le range (peu de breakouts)
    acc_score = 0

    # a) Range comprimé
    body_sizes = np.abs(closes - opens)
    avg_body   = body_sizes.mean()
    if avg_body < atr_h1 * 0.55:
        acc_score += 30

    # b) Equal lows (spring potential)
    tol_low = atr_h1 * 0.40
    equal_lows = sum(1 for i in range(len(lows) - 1)
                     for j in range(i + 1, len(lows))
                     if abs(lows[i] - lows[j]) < tol_low
                     and lows[i] < range_low + range_size * 0.25)
    if equal_lows >= 2:
        acc_score += 35

    # c) Prix dans le range 80% du temps
    in_range_count = sum(1 for c in closes
                         if range_low + range_size * 0.10 <= c <= range_high - range_size * 0.10)
    if in_range_count >= len(closes) * 0.75:
        acc_score += 20

    # d) Dernière bougie haussière après equal lows (spring + reversal)
    if lows[-2] < range_low + range_size * 0.15 and closes[-1] > closes[-2]:
        acc_score += 15

    # ── 2. Détection MANIPULATION ─────────────────────────────
    # Critères sur M15 :
    #   a) Wick extrême > ATR × 1.8 dans un sens
    #   b) Close à l'opposé du wick (rejet + return)
    #   c) Stop hunt confirmé (sweep + return dans le range)
    manip_score = 0
    manip_direction = ""

    atr_m15 = (df_m15["high"] - df_m15["low"]).rolling(14).mean().iloc[-1]
    if atr_m15 > 0 and not np.isnan(atr_m15):
        for i in range(-2, -6, -1):
            if abs(i) + 1 > len(df_m15):
                break
            h  = df_m15["high"].iloc[i]
            l  = df_m15["low"].iloc[i]
            o  = df_m15["open"].iloc[i]
            c  = df_m15["close"].iloc[i]
            uw = h - max(o, c)   # upper wick
            lw = min(o, c) - l   # lower wick

            # Manipulation bearish → spike haussier rejeté (future short)
            if uw > atr_m15 * 1.8 and c < o and lw < uw * 0.30:
                manip_score += 50
                manip_direction = "BEARISH"
                break

            # Manipulation bullish → spike baissier rejeté (future long)
            if lw > atr_m15 * 1.8 and c > o and uw < lw * 0.30:
                manip_score += 50
                manip_direction = "BULLISH"
                break

        # Confirmation : bougie suivante dans le sens opposé à la manipulation
        if manip_score > 0 and len(df_m15) >= 3:
            c_last  = df_m15["close"].iloc[-2]
            c_prev  = df_m15["close"].iloc[-3]
            if manip_direction == "BEARISH" and c_last < c_prev:
                manip_score += 30
            elif manip_direction == "BULLISH" and c_last > c_prev:
                manip_score += 30

            # Volume relatif (si disponible) — bougie manipulation = volume fort
            if "volume" in df_m15.columns:
                avg_vol = df_m15["volume"].iloc[-20:].mean()
                if df_m15["volume"].iloc[-3] > avg_vol * 1.5:
                    manip_score += 20

    manip_score = min(manip_score, 100)

    # ── 3. Détection DISTRIBUTION ─────────────────────────────
    # Critères sur H1 :
    #   a) BOS récent (close > swing_high des 10 dernières en BULLISH)
    #   b) Corps impulsif > ATR × 1.3 dans le sens du biais
    #   c) Prix au-dessus du range moyen (pour LONG) ou dessous (SHORT)
    dist_score   = 0
    dist_direction = ""

    # BOS H1 simple
    swing_high_10 = highs[-11:-1].max()
    swing_low_10  = lows[-11:-1].min()

    if closes[-1] > swing_high_10:
        dist_direction = "BULLISH"
        dist_score += 40
    elif closes[-1] < swing_low_10:
        dist_direction = "BEARISH"
        dist_score += 40

    # Corps de la dernière bougie H1
    last_body = abs(closes[-1] - opens[-1])
    if last_body > atr_h1 * 1.3:
        dist_score += 30

    # Prix dans la moitié haute/basse
    mid_range = (range_high + range_low) / 2
    if dist_direction == "BULLISH" and closes[-1] > mid_range + range_size * 0.15:
        dist_score += 20
    elif dist_direction == "BEARISH" and closes[-1] < mid_range - range_size * 0.15:
        dist_score += 20

    # Bougies récentes toutes dans le même sens
    last3_bull = all(closes[-i] > opens[-i] for i in range(1, 4) if i < len(closes))
    last3_bear = all(closes[-i] < opens[-i] for i in range(1, 4) if i < len(closes))
    if dist_direction == "BULLISH" and last3_bull:
        dist_score += 10
    elif dist_direction == "BEARISH" and last3_bear:
        dist_score += 10

    dist_score = min(dist_score, 100)

    # ── Décision finale — phase dominante ─────────────────────
    best = max(acc_score, manip_score, dist_score)

    if best < 35:
        return result  # Pas assez d'evidence

    if best == dist_score and dist_score > 50:
        direction = dist_direction
        return {
            "phase"     : "DISTRIBUTION",
            "confidence": dist_score,
            "details"   : (f"Phase D — Move impulsif {'haussier' if direction == 'BULLISH' else 'baissier'} "
                           f"| BOS H1 {'au-dessus' if direction == 'BULLISH' else 'en-dessous'} du swing | "
                           f"Corps > ATR×1.3"),
            "direction" : direction,
        }

    if best == manip_score and manip_score > 45:
        return {
            "phase"     : "MANIPULATION",
            "confidence": manip_score,
            "details"   : (f"Phase M — Stop hunt {'baissier' if manip_direction == 'BEARISH' else 'haussier'} "
                           f"| Wick extreme + rejet | Setup pre-Distribution probable"),
            "direction" : "BULLISH" if manip_direction == "BEARISH" else "BEARISH",
        }

    if best == acc_score and acc_score > 45:
        return {
            "phase"     : "ACCUMULATION",
            "confidence": acc_score,
            "details"   : "Phase A — Range lateral | Equal lows | Compression avant move",
            "direction" : "BULLISH",  # Post-accumulation → move haussier probable
        }

    return result


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
#  BREAKER BLOCK ELITE  (v9 — logique de flip complète)
# ─────────────────────────────────────────────────────────────
def detect_breaker_blocks(df: pd.DataFrame, bos_list: list[dict]) -> list[dict]:
    """
    Breaker Block ELITE = ancien OB qui a ÉCHOUÉ (prix l'a traversé via BOS)
    et qui devient une zone INVERSE.

    Logique v9 — 3 conditions obligatoires :
      1. Identifier l'OB source (dernière bougie dans le sens opposé avant le BOS)
      2. Vérifier que le BOS a CASSÉ cet OB (prix a clôturé au-delà)
      3. Vérifier que le prix REVIENT ACTUELLEMENT dans cette zone

    SELL Breaker :
      • BOS bearish détecté
      • Dernier OB bullish avant ce BOS → c'est l'ancien support
      • Le BOS a cassé cet OB → il devient résistance
      • Prix revient DANS la zone (retest) → SELL

    BUY Breaker :
      • BOS bullish détecté
      • Dernier OB bearish avant ce BOS → c'est l'ancienne résistance
      • Le BOS a cassé cet OB → il devient support
      • Prix revient DANS la zone (retest) → BUY

    Différence v9 vs v8 :
      v8 : vérifiait post_high dans la zone (approximatif)
      v9 : vérifie que le PRIX ACTUEL est dans la zone (confirmation réelle)
           + vérifie que le BOS a physiquement traversé l'OB (not just nearby)
    """
    if len(df) < OB_LOOKBACK + 5:
        return []

    breakers   = []
    price_now  = df["close"].iloc[-1]
    atr        = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    # Tolérance : ±15% de l'ATR pour les prix qui effleurent la zone
    tolerance  = atr * 0.15 if not np.isnan(atr) else 0.0

    for bos in bos_list[-8:]:
        idx      = bos["index"]
        bos_type = bos["type"]
        bos_lvl  = bos["level"]

        if idx < OB_LOOKBACK + 2:
            continue

        for j in range(idx - 1, max(idx - OB_LOOKBACK - 1, 0), -1):
            is_bull = df["close"].iloc[j] > df["open"].iloc[j]
            ob_hi   = df["high"].iloc[j]
            ob_lo   = df["low"].iloc[j]

            if bos_type == "bearish" and is_bull:
                # Condition 2 : le BOS bearish a CASSÉ l'OB bullish
                # → le BOS level doit être SOUS le bas de l'OB
                if bos_lvl > ob_lo:
                    continue   # BOS n'a pas vraiment traversé l'OB → pas un vrai Breaker

                # Condition 3 : le prix ACTUEL est dans la zone (retest en cours)
                in_zone = (ob_lo - tolerance) <= price_now <= (ob_hi + tolerance)
                if in_zone:
                    breakers.append({
                        "direction": "bearish",
                        "top"      : ob_hi,
                        "bottom"   : ob_lo,
                        "index"    : j,
                        "bos_level": bos_lvl,
                        "elite"    : True,     # flag pour bonus score supplémentaire
                    })
                    break

            elif bos_type == "bullish" and not is_bull:
                # Condition 2 : le BOS bullish a CASSÉ l'OB bearish
                # → le BOS level doit être AU-DESSUS du haut de l'OB
                if bos_lvl < ob_hi:
                    continue   # pas un vrai Breaker

                # Condition 3 : prix dans la zone en ce moment
                in_zone = (ob_lo - tolerance) <= price_now <= (ob_hi + tolerance)
                if in_zone:
                    breakers.append({
                        "direction": "bullish",
                        "top"      : ob_hi,
                        "bottom"   : ob_lo,
                        "index"    : j,
                        "bos_level": bos_lvl,
                        "elite"    : True,
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
#  OTE FIBONACCI  (v9.1 — DWO / Dealing Range ancré sur BOS réel)
#
#  Règle DWO (Draw on Liquidity) :
#    Le Fibo NE part PAS d'un pivot quelconque.
#    Il part du DERNIER DEALING RANGE valide = move qui a produit un BOS.
#
#    LONG  : ancrage LOW → HIGH du move qui a cassé la structure bullish
#    SHORT : ancrage HIGH → LOW du move qui a cassé la structure bearish
#
#    Contraintes supplémentaires :
#      1. Le BOS doit être confirmé (close au-delà du swing)
#      2. Le move doit avoir une impulsion réelle (≥ 2× ATR)
#         → exclut les ranges et micro-structures
#      3. Le retracement ACTUEL doit être en cours
#         → prix en pullback (entre HIGH et OTE_BOTTOM pour LONG)
#         → pas déjà reparti au-delà du HIGH d'origine
#
#  Zone OTE = [62% , 79%] du dealing range
#  Niveau clé : 70.5% = midpoint OTE (entrée sniper)
# ─────────────────────────────────────────────────────────────
OTE_LOW  = 0.62   # 62% du dealing range
OTE_HIGH = 0.79   # 79% du dealing range (≈ fib 0.786)


def detect_ote_zone(df: pd.DataFrame, direction: str,
                    bos_list: Optional[list] = None) -> Optional[dict]:
    """
    Détecte la zone OTE sur le dernier Dealing Range ancré sur un BOS réel.

    ═══ LOGIQUE DWO COMPLÈTE ═══════════════════════════════════════
    Étape 1 — Trouver le BOS valide le plus récent aligné avec direction
    Étape 2 — Remonter AVANT ce BOS pour trouver le swing origine
              → LONG  : swing low le plus bas AVANT le BOS bullish
              → SHORT : swing high le plus haut AVANT le BOS bearish
    Étape 3 — Le swing terminus = point extrême créé par l'impulsion
              → LONG  : highest high entre swing_low et BOS
              → SHORT : lowest low entre swing_high et BOS
    Étape 4 — Vérifier l'impulsion : move ≥ 2× ATR (pas un range)
    Étape 5 — Calculer OTE = [62%–79%] du dealing range
    Étape 6 — Vérifier que le prix EST en retracement dans la zone

    Retourne dict ou None si aucun dealing range valide.
    """
    if len(df) < 25:
        return None

    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    if np.isnan(atr) or atr <= 0:
        return None

    price_now = df["close"].iloc[-1]
    dec       = 2 if price_now > 100 else 5

    # ── Étape 1 : BOS valide le plus récent ──────────────────
    # On utilise bos_list passé en paramètre (déjà calculé dans analyse())
    # ou on le recalcule ici si absent.
    if bos_list is None:
        bos_list = detect_bos(df)

    target_bos_type = "bullish" if direction == "LONG" else "bearish"
    recent_bos = None
    for bos in reversed(bos_list):
        if bos["type"] == target_bos_type:
            recent_bos = bos
            break

    if recent_bos is None:
        return None   # Pas de BOS aligné → pas de dealing range valide

    bos_idx = recent_bos["index"]
    bos_lvl = recent_bos["level"]

    # Lookback : 40 bougies max avant le BOS pour trouver l'origine
    lookback_start = max(0, bos_idx - 40)
    window_pre_bos = df.iloc[lookback_start:bos_idx]

    if len(window_pre_bos) < 5:
        return None

    # ── Étape 2 & 3 : Dealing Range origine → terminus ───────
    if direction == "LONG":
        # Origine = swing LOW le plus bas avant le BOS bullish
        # (= la vraie base de l'impulsion, souvent avec liquidité prise)
        swing_lo_idx_rel = window_pre_bos["low"].idxmin()
        # idxmin retourne l'index absolu dans df
        swing_lo = df["low"].loc[swing_lo_idx_rel]

        # Terminus = highest HIGH entre le swing low et le BOS
        try:
            sl_pos = df.index.get_loc(swing_lo_idx_rel)
        except Exception:
            sl_pos = lookback_start
        window_impulse = df.iloc[sl_pos:bos_idx + 1]
        swing_hi       = window_impulse["high"].max()

        # ── Étape 4 : Impulsion réelle ≥ 2× ATR ──────────────
        move = swing_hi - swing_lo
        if move < atr * 2.0:
            return None   # Micro-structure ou range → fibo invalide

        # ── Étape 5 : OTE = retracement de swing_hi vers swing_lo ──
        # 62% retracement depuis le HIGH (haut du dealing range)
        ote_top    = round(swing_hi - move * OTE_LOW,  dec)   # 62%
        ote_bottom = round(swing_hi - move * OTE_HIGH, dec)   # 79%
        fib_500    = round(swing_hi - move * 0.500, dec)
        fib_618    = round(swing_hi - move * 0.618, dec)
        fib_705    = round(swing_hi - move * 0.705, dec)
        fib_786    = round(swing_hi - move * 0.786, dec)

        # ── Étape 6 : Prix en retracement dans la zone ───────
        # Condition : prix sous le HIGH (retracement en cours)
        #             ET dans la bande OTE
        retracing  = price_now < swing_hi
        in_ote     = retracing and (ote_bottom <= price_now <= ote_top)

    else:  # SHORT
        # Origine = swing HIGH le plus haut avant le BOS bearish
        swing_hi_idx_rel = window_pre_bos["high"].idxmax()
        swing_hi         = df["high"].loc[swing_hi_idx_rel]

        try:
            sh_pos = df.index.get_loc(swing_hi_idx_rel)
        except Exception:
            sh_pos = lookback_start
        window_impulse = df.iloc[sh_pos:bos_idx + 1]
        swing_lo       = window_impulse["low"].min()

        move = swing_hi - swing_lo
        if move < atr * 2.0:
            return None

        # OTE = retracement haussier de swing_lo vers swing_hi
        ote_bottom = round(swing_lo + move * OTE_LOW,  dec)   # 62%
        ote_top    = round(swing_lo + move * OTE_HIGH, dec)   # 79%
        fib_500    = round(swing_lo + move * 0.500, dec)
        fib_618    = round(swing_lo + move * 0.618, dec)
        fib_705    = round(swing_lo + move * 0.705, dec)
        fib_786    = round(swing_lo + move * 0.786, dec)

        retracing  = price_now > swing_lo
        in_ote     = retracing and (ote_bottom <= price_now <= ote_top)

    return {
        "ote_top"       : max(ote_bottom, ote_top),
        "ote_bottom"    : min(ote_bottom, ote_top),
        "swing_high"    : swing_hi,
        "swing_low"     : swing_lo,
        "fib_500"       : fib_500,
        "fib_618"       : fib_618,
        "fib_705"       : fib_705,   # midpoint OTE — entrée sniper
        "fib_786"       : fib_786,
        "in_ote"        : in_ote,
        "retracing"     : retracing,
        "move_size"     : round(move, dec),
        "bos_level"     : bos_lvl,
        "dealing_range" : f"{round(swing_lo, dec)} → {round(swing_hi, dec)}",
    }


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
    ltf_fvg: bool = False,       # FVG actif sur M15
    ltf_confirm: bool = False,   # Bougie confirmation M15
    entry_m1: bool = False,      # Trigger M1 (legacy — inactif en v8)
    # ── Bonus setups avancés ────────────────────
    breaker_block: bool  = False,
    breaker_elite: bool  = False,  # v9 : Breaker avec prix dans la zone confirmé
    fvg_30m: bool        = False,
    fvg_unmitigated: bool = False,
    trendline_liq: bool  = False,
    older_block: bool    = False,
    # ── v9 OTE Fibonacci ────────────────────────
    ote_in_zone: bool    = False,  # Prix dans OTE 62%–79%
    ote_plus_ob: bool    = False,  # OTE + OB confluence
    ote_plus_fvg: bool   = False,  # OTE + FVG confluence (setup sniper)
    # ── v8 NEW ──────────────────────────────────
    m5_trigger_ok: bool  = False,   # Trigger M5 confirmé (OBLIGATOIRE en v8)
    zone_fresh_ob: bool  = True,    # OB zone fraîche (non mitiquée)
    zone_fresh_fvg: bool = True,    # FVG zone fraîche (non mitiquée)
    market_trend: bool   = True,    # True = TREND, False = RANGE
    # ── v10 CLEAN PA ────────────────────────────
    clean_context: Optional[CleanPAContext] = None,
) -> tuple[int, list[str]]:
    """
    Score composite sur 100 — architecture tripolaire v8 avec setups avancés.

    v8 : M5 trigger obligatoire (+10 si présent, signal bloqué si absent).
         Zones fraîches récompensées (+5 par zone intacte).
         RANGE pénalisé (OB en range = -10 points).
    """
    score   = 0
    reasons = []

    # ── Pénalité marché RANGE ─────────────────────────────────
    if not market_trend:
        score -= 10
        reasons.append("⚠️ Marché en RANGE — OB moins fiables  (-10)")

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
        reasons.append("☑️ BOS M15 détecté  (+8)")

    if mtf_ob:
        score += 10
        reasons.append("✅ Order Block M15 validé  (+10)")
    elif has_ob:
        score += 5
        reasons.append("☑️ Order Block M15  (+5)")

    # ── Zones fraîches (v8) ───────────────────────────────────
    if mtf_ob and zone_fresh_ob:
        score += 5
        reasons.append("🟢 OB M15 zone fraîche (non mitiquée)  (+5)")
    elif mtf_ob and not zone_fresh_ob:
        score -= 5
        reasons.append("🔴 OB M15 zone mitiquée — zone brûlée  (-5)")

    if ltf_fvg and zone_fresh_fvg:
        score += 5
        reasons.append("🟢 FVG M15 zone fraîche (non mitiquée)  (+5)")

    # ── Liquidité prise ──────────────────────────────────────
    if liquidity_taken:
        score += 12
        reasons.append("✅ Stop Hunt / Liquidité prise  (+12)")

    # ── FVG actif ─────────────────────────────────────────────
    if ltf_fvg:
        score += 10
        reasons.append("✅ FVG M15 actif — prix dans la zone  (+10)")
    elif has_fvg:
        score += 5
        reasons.append("☑️ FVG M15 détecté  (+5)")

    if ltf_confirm:
        score += 8
        reasons.append("✅ Bougie de confirmation M15 (Engulfing / Morning·Evening Star / Pin Bar rejet)  (+8)")

    # ── v8 : Trigger M5 OBLIGATOIRE ──────────────────────────
    if m5_trigger_ok:
        score += 10
        reasons.append("⚡ Trigger M5 confirmé — entrée sniper  (+10)")
    # Note : si m5_trigger_ok=False, le signal est bloqué dans analyse() avant ce score

    # ══════════════════════════════════════════════════════════
    #  SETUPS AVANCÉS  (Breaker Block · OTE · FVG 30m · EUR/USD)
    # ══════════════════════════════════════════════════════════

    if breaker_elite:
        score += 18
        reasons.append("🔥 BREAKER BLOCK ELITE — zone flippée + retest confirmé  (+18)")
    elif breaker_block:
        score += 12
        reasons.append("🔥 Breaker Block détecté — zone flippée  (+12)")

    # ── OTE Fibonacci (v9) ───────────────────────────────────
    if ote_in_zone:
        score += 12
        reasons.append("📐 OTE Fibonacci 62%–79% — zone institutionnelle  (+12)")
    if ote_plus_ob:
        score += 8
        reasons.append("🎯 OTE + Order Block confluence — setup A+  (+8)")
    if ote_plus_fvg:
        score += 10
        reasons.append("🔥 OTE + FVG confluence — setup sniper triple  (+10)")

    if fvg_30m:
        score += 10
        reasons.append("📍 FVG 30min actif — zone 45min POI  (+10)")

    if fvg_unmitigated:
        score += 8
        reasons.append("✅ FVG valide non mitiqué — entrée propre  (+8)")

    if trendline_liq:
        score += 10
        reasons.append("🎯 Trendline Liquidity sweepée — stop hunt  (+10)")

    if older_block:
        score += 10
        reasons.append("🏛️ Older Block HTF actif — confluence HTF  (+10)")

    # ── v10 : Clean PA scoring ───────────────────────────────
    score, reasons = _clean_pa_scoring_block(score, reasons, clean_context)

    return min(max(score, 0), 100), reasons

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

    # ── 1. ENTRÉE — prix actuel si dans la zone FVG, sinon midpoint ──
    # CONCORDANCE : l'utilisateur entre au prix actuel du marché.
    # On utilise le close M5 courant s'il est dans la zone FVG active.
    # Le midpoint FVG n'est utilisé que si le prix n'est pas encore dedans
    # (signal anticipé — rare avec nos filtres).
    if fvg is not None:
        fvg_hi  = max(fvg.top, fvg.bottom)
        fvg_lo  = min(fvg.top, fvg.bottom)
        if fvg_lo <= close <= fvg_hi:
            # Prix DANS la zone → entrée = prix actuel (concordance parfaite)
            entry = round(close, dec)
        else:
            # Prix pas encore dans la zone → midpoint comme cible d'entrée limite
            entry = round((fvg_hi + fvg_lo) / 2.0, dec)
    else:
        entry   = round(close, dec)

    # ── 2. STOP LOSS — buffer wick-proof ──────────────────────────
    # buf = max(75% ATR, 4× spread)
    # SL positionné sous le plus bas wick des 5 dernières bougies (LONG)
    # ou au-dessus du plus haut wick (SHORT) pour résister aux mèches.
    buf = max(atr * 0.75, spread * 4.0)
    if direction == "LONG":
        if ob:
            raw_sl     = ob.bottom - buf
            recent_low = df["low"].iloc[-5:].min()
            # Prend le plus bas entre l'OB-buf et le wick récent-buf*0.5
            sl = round(min(raw_sl, recent_low - buf * 0.5), dec)
        else:
            sl = round(entry - atr * 1.8, dec)
    else:
        if ob:
            raw_sl      = ob.top + buf
            recent_high = df["high"].iloc[-5:].max()
            sl = round(max(raw_sl, recent_high + buf * 0.5), dec)
        else:
            sl = round(entry + atr * 1.8, dec)

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

# ═════════════════════════════════════════════════════════════
#  BIBLIOTHÈQUE DE PATTERNS DE CONFIRMATION  v7
#
#  ARCHITECTURE D'ENTRÉE : H1 biais → M15 structure → M5 entrée précise
#
#  PATTERNS M15 (confirmation de zone) :
#    1.  Bullish / Bearish Engulfing
#    2.  Morning Star / Evening Star
#    3.  Pin Bar de rejet (mèche ≥ 2.5× corps, corps dans 1/3 opposé)
#    4.  Doji de retournement (Dragonfly / Gravestone)
#    5.  Tweezer Bottom / Top (double test d'une zone)
#    6.  Three White Soldiers / Three Black Crows
#    7.  Hammer / Hanging Man  (corps compact + longue mèche)
#    8.  Shooting Star / Inverted Hammer
#    9.  Harami (corps interne à la bougie précédente)
#   10.  Inside Bar Break (cassure d'une inside bar = compression + expansion)
#
#  PATTERNS M5 (trigger d'entrée précis) :
#    Mêmes patterns mais sur df_m5 — donne le signal d'entrée exact
#    après confirmation M15 de la zone.
#
#  RÈGLE ANTI-BRUIT :
#    - Toutes les bougies testées sont CLÔTURÉES (iloc[-2] et avant)
#    - iloc[-1] = bougie vivante → IGNORÉE systématiquement
#    - Fenêtre de recherche : 5 dernières bougies clôturées
# ═════════════════════════════════════════════════════════════

def _candle_metrics(df: pd.DataFrame, i: int) -> dict:
    """Retourne les métriques d'une bougie à l'index i (négatif)."""
    o  = df["open"].iloc[i]
    h  = df["high"].iloc[i]
    l  = df["low"].iloc[i]
    cl = df["close"].iloc[i]
    body       = abs(cl - o)
    candle_rng = h - l
    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l
    bull = cl >= o
    return dict(o=o, h=h, l=l, cl=cl, body=body, rng=candle_rng,
                uw=upper_wick, lw=lower_wick, bull=bull)


def detect_confirmation_candle(df: pd.DataFrame, direction: str,
                                label_out: list = None) -> bool:
    """
    Détecte une bougie de confirmation parmi 10 patterns institutionnels.

    LONG  = cherche patterns haussiers
    SHORT = cherche patterns baissiers

    label_out : si fourni (liste vide []), y ajoute le nom du pattern détecté.
    Retourne True dès le premier pattern validé.
    """
    if len(df) < 8:
        return False

    # On inspecte les 5 dernières bougies CLÔTURÉES : [-2] à [-6]
    # ([-1] = bougie vivante → ignorée)
    for i in range(-2, -7, -1):
        if abs(i) + 2 > len(df):
            break

        c0 = _candle_metrics(df, i)
        if c0["body"] == 0 or c0["rng"] == 0:
            continue

        # Bougie précédente (pour patterns à 2+ bougies)
        c1 = _candle_metrics(df, i - 1) if abs(i - 1) <= len(df) - 1 else None
        c2 = _candle_metrics(df, i - 2) if abs(i - 2) <= len(df) - 1 else None

        # ──────────────────────────────────────────────────────
        #  PATTERN 1 — ENGULFING  (2 bougies)
        #  Corps courant englobe intégralement le corps précédent.
        #  Corps courant ≥ 1.3× corps précédent (force minimale).
        # ──────────────────────────────────────────────────────
        if c1 is not None and c1["body"] > 0:
            if direction == "LONG" and c0["bull"] and not c1["bull"]:
                if (c0["cl"] >= max(c1["o"], c1["cl"])
                        and c0["o"] <= min(c1["o"], c1["cl"])
                        and c0["body"] >= c1["body"] * 1.3):
                    if label_out is not None:
                        label_out.append("Bullish Engulfing")
                    return True
            if direction == "SHORT" and not c0["bull"] and c1["bull"]:
                if (c0["cl"] <= min(c1["o"], c1["cl"])
                        and c0["o"] >= max(c1["o"], c1["cl"])
                        and c0["body"] >= c1["body"] * 1.3):
                    if label_out is not None:
                        label_out.append("Bearish Engulfing")
                    return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 2 — MORNING STAR / EVENING STAR  (3 bougies)
        #  B-2 : forte impulsion contraire
        #  B-1 : indécision (corps < 35% de B-2)
        #  B0  : confirmation ≥ 50% du corps de B-2
        # ──────────────────────────────────────────────────────
        if c1 is not None and c2 is not None and c2["body"] > 0:
            indecision = c1["body"] < c2["body"] * 0.35
            if direction == "LONG":
                b2_mid = (c2["o"] + c2["cl"]) / 2
                if (not c2["bull"]                  # B-2 baissière forte
                        and indecision
                        and c0["bull"]              # B0 haussière
                        and c0["cl"] > b2_mid       # récupère > 50% de B-2
                        and c0["body"] >= c2["body"] * 0.5):
                    if label_out is not None:
                        label_out.append("Morning Star")
                    return True
            if direction == "SHORT":
                b2_mid = (c2["o"] + c2["cl"]) / 2
                if (c2["bull"]                      # B-2 haussière forte
                        and indecision
                        and not c0["bull"]          # B0 baissière
                        and c0["cl"] < b2_mid
                        and c0["body"] >= c2["body"] * 0.5):
                    if label_out is not None:
                        label_out.append("Evening Star")
                    return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 3 — PIN BAR DE REJET  (1 bougie)
        #  Mèche de rejet ≥ 2.5× corps
        #  Corps dans le tiers OPPOSÉ à la mèche (≥ 55% de la hauteur totale)
        #  Mèche opposée courte (< 30% du corps)
        # ──────────────────────────────────────────────────────
        if direction == "LONG":
            body_pos = (min(c0["o"], c0["cl"]) - c0["l"]) / c0["rng"]
            if (c0["lw"] >= c0["body"] * 2.5
                    and c0["uw"] < c0["body"] * 0.30
                    and body_pos >= 0.55):
                if label_out is not None:
                    label_out.append("Bullish Pin Bar")
                return True
        if direction == "SHORT":
            body_pos = (c0["h"] - max(c0["o"], c0["cl"])) / c0["rng"]
            if (c0["uw"] >= c0["body"] * 2.5
                    and c0["lw"] < c0["body"] * 0.30
                    and body_pos >= 0.55):
                if label_out is not None:
                    label_out.append("Bearish Pin Bar")
                return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 4 — DOJI DE RETOURNEMENT  (1 bougie)
        #  Dragonfly Doji (LONG) : corps quasi nul + longue mèche basse
        #  Gravestone Doji (SHORT) : corps quasi nul + longue mèche haute
        #  Corps ≤ 5% du range total
        # ──────────────────────────────────────────────────────
        if c0["rng"] > 0 and c0["body"] / c0["rng"] <= 0.05:
            if direction == "LONG" and c0["lw"] >= c0["rng"] * 0.65:
                if label_out is not None:
                    label_out.append("Dragonfly Doji")
                return True
            if direction == "SHORT" and c0["uw"] >= c0["rng"] * 0.65:
                if label_out is not None:
                    label_out.append("Gravestone Doji")
                return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 5 — TWEEZER BOTTOM / TOP  (2 bougies)
        #  Double test exact d'une zone (lows / highs quasi identiques)
        #  Tolérance : 20% de l'ATR sur 14 périodes
        # ──────────────────────────────────────────────────────
        if c1 is not None:
            atr_tw = (df["high"] - df["low"]).rolling(14).mean().iloc[i]
            tol    = atr_tw * 0.20 if not np.isnan(atr_tw) else c0["rng"] * 0.15
            if direction == "LONG":
                if (abs(c0["l"] - c1["l"]) <= tol      # mêmes lows
                        and c0["bull"]                  # bougie courante haussière
                        and not c1["bull"]):            # bougie précédente baissière
                    if label_out is not None:
                        label_out.append("Tweezer Bottom")
                    return True
            if direction == "SHORT":
                if (abs(c0["h"] - c1["h"]) <= tol
                        and not c0["bull"]
                        and c1["bull"]):
                    if label_out is not None:
                        label_out.append("Tweezer Top")
                    return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 6 — THREE WHITE SOLDIERS / THREE BLACK CROWS
        #  3 bougies consécutives dans le même sens
        #  Chaque corps ≥ 60% du range, clôtures progressives
        #  Corps ≥ ATR×0.5 chacun (pas de micro-bougies)
        # ──────────────────────────────────────────────────────
        if i <= -4 and c1 is not None and c2 is not None:
            atr_3 = (df["high"] - df["low"]).rolling(14).mean().iloc[i]
            if not np.isnan(atr_3) and atr_3 > 0:
                solid = lambda m: m["body"] / m["rng"] >= 0.60 and m["body"] >= atr_3 * 0.5
                if direction == "LONG":
                    if (c0["bull"] and c1["bull"] and c2["bull"]
                            and solid(c0) and solid(c1) and solid(c2)
                            and c0["cl"] > c1["cl"] > c2["cl"]):
                        if label_out is not None:
                            label_out.append("Three White Soldiers")
                        return True
                if direction == "SHORT":
                    if (not c0["bull"] and not c1["bull"] and not c2["bull"]
                            and solid(c0) and solid(c1) and solid(c2)
                            and c0["cl"] < c1["cl"] < c2["cl"]):
                        if label_out is not None:
                            label_out.append("Three Black Crows")
                        return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 7 — HAMMER / HANGING MAN  (1 bougie)
        #  Corps compact dans le tiers supérieur (LONG) ou inférieur (SHORT)
        #  Mèche inférieure (LONG) ou supérieure (SHORT) ≥ 2× corps
        #  Corps ≤ 40% du range total
        #  Différence avec Pin Bar : le corps peut être légèrement plus grand
        # ──────────────────────────────────────────────────────
        if c0["body"] / c0["rng"] <= 0.40:
            if direction == "LONG":
                body_pos_h = (min(c0["o"], c0["cl"]) - c0["l"]) / c0["rng"]
                if c0["lw"] >= c0["body"] * 2.0 and body_pos_h >= 0.50:
                    if label_out is not None:
                        label_out.append("Hammer")
                    return True
            if direction == "SHORT":
                body_pos_h = (c0["h"] - max(c0["o"], c0["cl"])) / c0["rng"]
                if c0["uw"] >= c0["body"] * 2.0 and body_pos_h >= 0.50:
                    if label_out is not None:
                        label_out.append("Hanging Man / Shooting Star")
                    return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 8 — SHOOTING STAR / INVERTED HAMMER  (1 bougie)
        #  Corps dans le tiers bas avec longue mèche haute (SHORT)
        #  Corps dans le tiers haut avec longue mèche basse (LONG)
        #  Confirmation de rejet de résistance / support
        # ──────────────────────────────────────────────────────
        if direction == "SHORT" and c0["uw"] >= c0["body"] * 3.0:
            body_pos_ss = (c0["h"] - max(c0["o"], c0["cl"])) / c0["rng"]
            if body_pos_ss >= 0.60 and c0["lw"] < c0["body"] * 0.50:
                if label_out is not None:
                    label_out.append("Shooting Star")
                return True
        if direction == "LONG" and c0["lw"] >= c0["body"] * 3.0:
            body_pos_ih = (min(c0["o"], c0["cl"]) - c0["l"]) / c0["rng"]
            if body_pos_ih >= 0.60 and c0["uw"] < c0["body"] * 0.50:
                if label_out is not None:
                    label_out.append("Inverted Hammer")
                return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 9 — HARAMI  (2 bougies)
        #  Corps courant INCLUS dans le corps précédent
        #  Retournement après forte bougie extérieure
        # ──────────────────────────────────────────────────────
        if c1 is not None and c1["body"] > 0:
            c0_hi_body = max(c0["o"], c0["cl"])
            c0_lo_body = min(c0["o"], c0["cl"])
            c1_hi_body = max(c1["o"], c1["cl"])
            c1_lo_body = min(c1["o"], c1["cl"])
            if (c0_hi_body <= c1_hi_body and c0_lo_body >= c1_lo_body
                    and c0["body"] < c1["body"] * 0.60):
                if direction == "LONG" and not c1["bull"] and c0["bull"]:
                    if label_out is not None:
                        label_out.append("Bullish Harami")
                    return True
                if direction == "SHORT" and c1["bull"] and not c0["bull"]:
                    if label_out is not None:
                        label_out.append("Bearish Harami")
                    return True

        # ──────────────────────────────────────────────────────
        #  PATTERN 10 — INSIDE BAR BREAK  (3 bougies)
        #  B-2 : grande bougie impulsive (mère)
        #  B-1 : inside bar (high < mère.high ET low > mère.low) → compression
        #  B0  : cassure dans le sens du biais → expansion
        # ──────────────────────────────────────────────────────
        if c1 is not None and c2 is not None and c2["body"] > 0:
            # B-1 est une inside bar par rapport à B-2
            inside = (c1["h"] <= c2["h"] and c1["l"] >= c2["l"])
            if inside:
                if direction == "LONG":
                    # Cassure haussière : close au-dessus du high de B-1
                    if c0["cl"] > c1["h"] and c0["bull"]:
                        if label_out is not None:
                            label_out.append("Inside Bar Bullish Break")
                        return True
                if direction == "SHORT":
                    # Cassure baissière : close en-dessous du low de B-1
                    if c0["cl"] < c1["l"] and not c0["bull"]:
                        if label_out is not None:
                            label_out.append("Inside Bar Bearish Break")
                        return True

    return False


# ─────────────────────────────────────────────────────────────
#  TRIGGER M5 — ENTRÉE PRÉCISE POST-CONFIRMATION M15
#
#  Architecture : M15 confirme la zone → M5 donne l'entrée exacte
#  Retourne (trigger_ok, pattern_name, entry_price)
#
#  Utilise les mêmes 10 patterns mais sur le df M5.
#  Entrée = close de la bougie M5 de confirmation.
# ─────────────────────────────────────────────────────────────
def detect_m5_entry_trigger(df_m5: pd.DataFrame,
                             direction: str) -> tuple[bool, str, float]:
    """
    Cherche un trigger d'entrée précis sur M5 après confirmation M15.
    Retourne (ok, pattern_name, entry_price).
    """
    if df_m5 is None or df_m5.empty or len(df_m5) < 8:
        return False, "", 0.0

    label = []
    found = detect_confirmation_candle(df_m5, direction, label_out=label)
    if found:
        entry_px = df_m5["close"].iloc[-2]   # dernière bougie clôturée
        return True, (label[0] if label else "Pattern M5"), entry_px

    return False, "", 0.0


# ─────────────────────────────────────────────────────────────
#  MOTEUR PRINCIPAL v8 — 3 TIMEFRAMES (H1 biais → M15 zone → M5 trigger)
#  M5 trigger OBLIGATOIRE — sans confirmation M5, signal rejeté.
# ─────────────────────────────────────────────────────────────
def analyse(symbol: str, htf: str = HTF, ltf: str = LTF,
            silent: bool = False) -> Optional[Signal]:

    if not silent:
        print(f"\n{c('═'*60, 'cyan')}")
        print(f"  {c('SMC ENGINE v10', 'yellow')}  —  {c(symbol, 'white')}  "
              f"{c(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'cyan')}")
        print(f"  {c('H1 biais → M15 zone → M5 trigger + OTE DWO + Breaker Elite + Clean PA (v10)', 'cyan')}")
        print(c("═" * 60, "cyan"))

    # ── Téléchargement 3 TF : H1 / M15 / M5 + D1 tendance fond ──
    if not silent:
        print(f"  {c('↓', 'cyan')} Data  {htf} / {ltf} / 5m / 1d (tripolaire v8 + tendance fond)…")
    df_htf = fetch(symbol, htf, period="10d")
    df_ltf = fetch(symbol, ltf, period="5d")   # M15 : zone institutionnelle
    df_m5  = fetch(symbol, "5m", period="2d")  # M5  : trigger obligatoire
    df_d1  = fetch(symbol, "1d", period="90d") # D1  : tendance de fond (v11)

    df_mtf = df_ltf   # alias M15

    if df_htf.empty or df_ltf.empty:
        if not silent:
            print(c("  ✗ Données indisponibles.", "red"))
        return None

    # ── FILTRES VOLATILITÉ — skip si marché mort ─────────────
    vol_ok, vol_reason = check_volatility(symbol, df_ltf)
    if not vol_ok:
        if not silent:
            print(c(f"  ⛔ Marché ignoré : {vol_reason}", "yellow"))
        return None

    # ── v8 : FILTRE MARCHÉ (TREND / RANGE) ───────────────────
    mkt_cond   = market_condition(df_ltf)
    market_is_trend = (mkt_cond == "TREND")
    if not silent:
        cond_color = "green" if market_is_trend else "yellow"
        print(f"  {'🏗 Condition marché':<26} {c(mkt_cond, cond_color)}")

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
    #  v11 — TENDANCE DE FOND D1 + AMD CYCLE
    # ══════════════════════════════════════════════════════════

    # ── Tendance Daily ────────────────────────────────────────
    d1_trend = daily_trend(df_d1)
    d1_aligned = (d1_trend == "NEUTRAL" or
                  (d1_trend == "BULLISH" and direction == "LONG") or
                  (d1_trend == "BEARISH" and direction == "SHORT"))
    d1_counter = not d1_aligned and d1_trend != "NEUTRAL"

    if not silent:
        d1_color = "green" if d1_aligned else ("red" if d1_counter else "yellow")
        d1_label = (f"✓ D1 {d1_trend} — aligné avec {direction}"
                    if d1_aligned and d1_trend != "NEUTRAL"
                    else f"⚠ D1 {d1_trend} — CONTRE-TENDANCE {direction}"
                    if d1_counter else f"D1 {d1_trend} — neutre")
        print(f"  {'📅 Tendance D1':<26} {c(d1_label, d1_color)}")

    # Blocage si contre-tendance D1 forte
    if d1_counter:
        if not silent:
            print(c(f"  ⛔ Signal contre la tendance de fond D1 ({d1_trend}) — "
                    f"direction {direction} rejetée.", "red"))
        return None

    # ── AMD Cycle ─────────────────────────────────────────────
    amd = detect_amd_cycle(df_htf, df_ltf)
    if not silent:
        amd_color = {
            "ACCUMULATION": "cyan",
            "MANIPULATION": "magenta",
            "DISTRIBUTION": "green",
        }.get(amd["phase"], "white")
        print(f"  {'🔄 AMD Cycle':<26} "
              f"{c(amd['phase'] + ' (' + str(amd['confidence']) + '%)', amd_color)}"
              + (f"  ← {amd['details']}" if amd['phase'] != 'UNKNOWN' else ""))

    # ── Filtrage AMD : on n'entre PAS en pleine Accumulation ──
    # L'Accumulation = range = entrée hasardeuse. On attend M ou D.
    if amd["phase"] == "ACCUMULATION" and amd["confidence"] >= 70:
        if not silent:
            print(c("  ⛔ Phase Accumulation confirmée (range) — "
                    "entrée rejetée, attendre Manipulation.", "yellow"))
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

    # ── M15 : Structure + zone institutionnelle ──────────────
    df_mtf = df_ltf   # alias

    # ── v8 : Trigger M5 OBLIGATOIRE ──────────────────────────
    m5_trigger_ok, m5_pattern, m5_entry_px = detect_m5_entry_trigger(
        df_m5 if not df_m5.empty else None, direction
    )
    if not silent:
        if m5_trigger_ok:
            print(f"  {c('⚡ Trigger M5', 'magenta'):<26} {c(m5_pattern, 'yellow')}")
        else:
            print(f"  {'Trigger M5':<26} {c('⛔ ABSENT — requis en v8', 'red')}")

    # ── v8 : BLOCAGE si pas de trigger M5 ────────────────────
    if not m5_trigger_ok:
        if not silent:
            print(c("\n  ✗ v8 : Trigger M5 absent — signal rejeté.\n"
                    "    (La confirmation M5 est OBLIGATOIRE en v8 — pas d'entrée sans trigger)", "red"))
        return None

    bos_mtf = detect_bos(df_mtf)
    obs_mtf = detect_order_blocks(df_mtf, bos_mtf)
    liq_mtf = detect_liquidity_sweep(df_mtf)

    last_bos_mtf = bos_mtf[-1] if bos_mtf else None
    mtf_bos  = last_bos_mtf is not None and last_bos_mtf["type"] == bias.lower()
    mtf_ob   = any(o.direction == bias.lower() for o in obs_mtf)
    liq_taken = liq_mtf["bearish_sweep"] if direction == "SHORT" else liq_mtf["bullish_sweep"]

    # OB M15 pour SL précis
    ob_mtf_match = next((o for o in reversed(obs_mtf) if o.direction == bias.lower()), None)

    # ── M15 : FVG + OB entrée (même df) ──────────────────────
    bos_ltf  = bos_mtf
    fvgs_ltf = detect_fvg(df_ltf)
    obs_ltf  = obs_mtf

    last_bos_ltf = last_bos_mtf
    has_bos_ltf  = mtf_bos

    fvg_active = active_fvg(df_ltf, fvgs_ltf, bias.lower())
    ltf_fvg    = fvg_active is not None
    has_ob_ltf = mtf_ob
    ob_ltf_match = ob_mtf_match

    # OB utilisé pour le SL : M15 uniquement
    ob_for_sl = ob_ltf_match or ob_mtf_match

    # ── v8 : ZONE FRAÎCHE — OB et FVG ────────────────────────
    zone_fresh_ob = True
    if ob_mtf_match is not None:
        zone_fresh_ob = is_zone_fresh(
            df_ltf,
            ob_mtf_match.top,
            ob_mtf_match.bottom,
            ob_mtf_match.index,
        )
        if not silent:
            freshness_color = "green" if zone_fresh_ob else "red"
            freshness_label = "✓ Fraîche" if zone_fresh_ob else "✗ Mitiquée — brûlée"
            print(f"  {'Zone OB M15':<26} {c(freshness_label, freshness_color)}")

    zone_fresh_fvg = True
    if fvg_active is not None:
        zone_fresh_fvg = is_zone_fresh(
            df_ltf,
            fvg_active.top,
            fvg_active.bottom,
            fvg_active.index,
        )
        if not silent:
            freshness_color = "green" if zone_fresh_fvg else "yellow"
            freshness_label = "✓ Fraîche" if zone_fresh_fvg else "△ Partiellement mitiquée"
            print(f"  {'Zone FVG M15':<26} {c(freshness_label, freshness_color)}")

    # ── Bougie de confirmation M15 ───────────────────────────
    m15_label = []
    ltf_confirm = detect_confirmation_candle(df_ltf, direction, label_out=m15_label)
    m15_pattern_name = m15_label[0] if m15_label else "confirmation M15"

    # ══════════════════════════════════════════════════════════
    #  SETUPS AVANCÉS — M15
    # ══════════════════════════════════════════════════════════

    # Breaker Block sur M15
    bkr_mtf       = detect_breaker_blocks(df_mtf, bos_mtf)
    breaker_block  = any(b["direction"] == bias.lower() for b in bkr_mtf)
    breaker_elite  = any(b["direction"] == bias.lower() and b.get("elite", False)
                         for b in bkr_mtf)

    # ── v9 : OTE Fibonacci DWO — ancré sur BOS réel ─────────
    ote_result  = detect_ote_zone(df_mtf, direction, bos_list=bos_mtf)
    ote_in_zone = ote_result is not None and ote_result["in_ote"]

    # FVG Valid non mitiqué sur M5
    fvg_unmitigated = False
    if fvg_active is not None:
        fvg_unmitigated = is_fvg_unmitigated(df_ltf, fvg_active)

    # ── v9 : OTE confluence flags ─────────────────────────────
    # Note : in_ob_m15 est calculé dans le bloc "Filtre Zone Entrée" plus bas.
    # On calcule ici un check direct du prix dans l'OB pour l'OTE confluence.
    _ote_ob_check = False
    if ob_mtf_match is not None and ote_in_zone:
        ob_lo_chk = min(ob_mtf_match.top, ob_mtf_match.bottom)
        ob_hi_chk = max(ob_mtf_match.top, ob_mtf_match.bottom)
        tol_chk   = (ob_hi_chk - ob_lo_chk) * 0.10
        _ote_ob_check = (ob_lo_chk - tol_chk) <= df_ltf["close"].iloc[-1] <= (ob_hi_chk + tol_chk)
    ote_plus_ob  = ote_in_zone and _ote_ob_check
    ote_plus_fvg = ote_in_zone and ltf_fvg

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

    # ── Score multi-TF + setups avancés v9 ───────────────────

    # ── v10 : CLEAN PA — qualité price action ─────────────────
    # Calculer zone_h / zone_l depuis l'OB ou FVG principal
    if ob_mtf_match is not None:
        _zone_h = max(ob_mtf_match.top, ob_mtf_match.bottom)
        _zone_l = min(ob_mtf_match.top, ob_mtf_match.bottom)
    elif fvg_active is not None:
        _zone_h = max(fvg_active.top, fvg_active.bottom)
        _zone_l = min(fvg_active.top, fvg_active.bottom)
    else:
        _zone_h = _zone_l = 0.0

    clean_ctx = detect_clean_pa_adaptive(
        df        = df_mtf,
        direction = direction,
        symbol    = symbol,
        zone_high = _zone_h,
        zone_low  = _zone_l,
    )

    # Bloquer le signal si PA insuffisant
    if not clean_ctx.is_valid:
        if not silent:
            pa_block_reason = (
                "choppy" if clean_ctx.is_choppy
                else "no displacement" if not clean_ctx.displacement_ok
                else f"clean_score={clean_ctx.clean_score}"
            )
            print(c(f"  [CLEAN PA] Setup bloqué — {pa_block_reason}", "red"))
        return None

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
        entry_m1         = False,
        breaker_block    = breaker_block,
        breaker_elite    = breaker_elite,
        fvg_30m          = False,
        fvg_unmitigated  = fvg_unmitigated,
        trendline_liq    = trendline_liq,
        older_block      = older_block,
        # v9 OTE
        ote_in_zone      = ote_in_zone,
        ote_plus_ob      = ote_plus_ob,
        ote_plus_fvg     = ote_plus_fvg,
        # v8
        m5_trigger_ok    = m5_trigger_ok,
        zone_fresh_ob    = zone_fresh_ob,
        zone_fresh_fvg   = zone_fresh_fvg,
        market_trend     = market_is_trend,
        # v10 CLEAN PA
        clean_context    = clean_ctx,
    )

    # ── v11 : Bonus/Pénalité Tendance D1 ─────────────────────
    if d1_aligned and d1_trend != "NEUTRAL":
        score = min(score + 12, 100)
        reasons.append(f"📅 Tendance D1 {d1_trend} alignée — trade dans le sens du fond  (+12)")

    # ── v11 : Bonus AMD phase ─────────────────────────────────
    if amd["phase"] == "MANIPULATION" and amd["confidence"] >= 60:
        score = min(score + 15, 100)
        reasons.append(f"🔄 AMD — Phase Manipulation détectée ({amd['confidence']}%)  (+15)")
    elif amd["phase"] == "DISTRIBUTION" and amd["confidence"] >= 55:
        # Distribution dans le sens du trade = confirmation forte
        if amd["direction"] == direction:
            score = min(score + 10, 100)
            reasons.append(f"🔄 AMD — Phase Distribution {amd['direction']} confirmée ({amd['confidence']}%)  (+10)")

    # ── Remplace le label générique par le nom du pattern réel ──
    for idx, r in enumerate(reasons):
        if "Bougie de confirmation" in r:
            reasons[idx] = (
                f"✅ Confirmation M15 : {m15_pattern_name}  (+8)"
            )
            break

    # ── Bonus M5 trigger — entrée précise sniper ──────────────
    if m5_trigger_ok:
        score = min(score + 7, 100)
        reasons.append(f"⚡ Trigger M5 : {m5_pattern}  — entrée sniper  (+7)")

    # ── Affichage détails ────────────────────────────────────
    def tick(v): return c("✓", "green") if v else c("✗", "red")
    if not silent:
        print(f"  {'BOS M15':<26} {tick(mtf_bos)}")
        print(f"  {'OB M15':<26} {tick(mtf_ob)}")
        print(f"  {'Liquidité prise (M15)':<26} {tick(liq_taken)}")
        print(f"  {'FVG M15 actif':<26} {tick(ltf_fvg)}")
        print(f"  {'FVG Valid (non mitiqué)':<26} {tick(fvg_unmitigated)}")
        print(f"  {'Confirmation M15':<26} {tick(ltf_confirm)}")
        print(f"  {'Trigger M1':<26} {c('DÉSACTIVÉ', 'yellow')}")
        print(f"  {c('── Setups Avancés ──', 'cyan')}")
        print(f"  {'Breaker Block M15':<26} {tick(breaker_block)}"
              + (c("  ← ELITE", "yellow") if breaker_elite else ""))
        # ── OTE Fibonacci DWO (v9.1) ─────────────────────────
        if ote_result is not None:
            dec_ote = 2 if df_ltf["close"].iloc[-1] > 100 else 5
            ote_color = "green" if ote_in_zone else "white"
            ote_label = (f"✓ Prix dans OTE  [{round(ote_result['ote_bottom'], dec_ote)}"
                         f" – {round(ote_result['ote_top'], dec_ote)}]"
                         if ote_in_zone else
                         f"✗ Hors OTE  [{round(ote_result['ote_bottom'], dec_ote)}"
                         f" – {round(ote_result['ote_top'], dec_ote)}]")
            print(f"  {'OTE 62%–79% (DWO)':<26} {c(ote_label, ote_color)}")
            print(f"    {'Dealing Range':<22} {ote_result['dealing_range']}")
            print(f"    {'Move size':<22} {ote_result['move_size']}"
                  f"  (≥ 2× ATR requis)")
            if ote_result.get("retracing"):
                print(f"    {'Fib 50.0%':<22} {ote_result['fib_500']}")
                print(f"    {'Fib 61.8%':<22} {ote_result['fib_618']}")
                print(f"    {'Fib 70.5% ← OTE mid':<22} {c(str(ote_result['fib_705']), 'magenta')}")
                print(f"    {'Fib 78.6%':<22} {ote_result['fib_786']}")
        else:
            print(f"  {'OTE 62%–79% (DWO)':<26} {c('✗ Pas de BOS valide / move trop petit', 'white')}")
        print(f"  {'FVG 30min (≈45min)':<26} {tick(fvg_30m)}")
        print(f"  {'Trendline Liq. sweepée':<26} {tick(trendline_liq)}")
        print(f"  {'Older Block HTF':<26} {tick(older_block)}")
        # ── v10 : Clean PA ───────────────────────────────────────
        print(f"  {c('── Clean PA ──', 'cyan')}")
        pa_color = ("green" if clean_ctx.clean_score >= 6
                    else "yellow" if clean_ctx.clean_score >= CLEAN_MIN_SCORE
                    else "red")
        print(f"  {'Structure':<26} {tick(clean_ctx.structure_ok)}"
              + (f"  {clean_ctx.swing_count} swings {clean_ctx.structure_type}"
                 if clean_ctx.structure_ok else ""))
        print(f"  {'Displacement':<26} {tick(clean_ctx.displacement_ok)}"
              + (f"  {clean_ctx.impulse_strength}×ATR"
                 + (f" × {clean_ctx.impulse_consec}b" if clean_ctx.impulse_consec > 1 else "")
                 if clean_ctx.displacement_ok else "  ❌ AUCUNE IMPULSION"))
        print(f"  {'Liquidité sweepée':<26} {tick(clean_ctx.liquidity_swept)}"
              + (f"  {clean_ctx.sweep_type} @ {clean_ctx.sweep_level}"
                 if clean_ctx.liquidity_swept else ""))
        print(f"  {'Pullback propre':<26} {tick(clean_ctx.pullback_ok)}"
              + (f"  qualité {clean_ctx.pullback_quality}" if clean_ctx.pullback_ok else ""))
        chop_c = "red" if clean_ctx.is_choppy else "green"
        print(f"  {'Marché choppy':<26} {c('OUI — BLOQUANT' if clean_ctx.is_choppy else 'NON', chop_c)}"
              + (f"  {clean_ctx.chop_reason}" if clean_ctx.is_choppy else ""))
        print(f"  {'Clean PA Score':<26} {c(str(clean_ctx.clean_score) + '/9 — ' + clean_ctx.label, pa_color)}")
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
        fvg=fvg_active,
    )

    # ── v8 : Priorité à l'entrée M5 trigger si disponible ────
    # Le trigger M5 donne le prix de clôture réel de la bougie de confirmation.
    # C'est l'entrée la plus précise possible.
    if m5_trigger_ok and m5_entry_px > 0:
        entry_v8 = round(m5_entry_px, decimals)
        # Recalcule le RR avec la nouvelle entrée M5 si dans tolérance ±5% du risque
        risk_orig = abs(entry_v8 - sl)
        if risk_orig > 0:
            spread = get_spread(symbol)
            if direction == "LONG":
                gain_v8 = (tp - entry_v8) - spread
            else:
                gain_v8 = (entry_v8 - tp) - spread
            rr_v8 = round(gain_v8 / risk_orig, 2) if gain_v8 > 0 else 0.0
            if rr_v8 >= MIN_RR:
                entry = entry_v8
                rr    = rr_v8

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
        entry_mode  = "⚡ M5 trigger" if m5_trigger_ok else "📍 M15 close"

        print(f"\n  {c('━'*56, 'cyan')}")
        print(f"  {c('⚡ SIGNAL v8 ÉLITE DÉTECTÉ', 'yellow')}  →  {c(direction, dir_color)}  {entry_mode}")
        print(f"  {c('━'*56, 'cyan')}")
        entry_src = (f"⚡ M5 {m5_pattern}" if m5_trigger_ok else
                     ("🎯 FVG mid" if fvg_active else "📍 close M15"))
        print(f"  {'Symbole':<18} {c(signal.symbol, 'white')}")
        print(f"  {'Direction':<18} {c(signal.direction, dir_color)}")
        print(f"  {'Marché':<18} {c(mkt_cond, 'green' if market_is_trend else 'yellow')}")
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

# ─────────────────────────────────────────────────────────────
#  WATCHLIST — PRIORITÉS PAR TIER  (v10)
#
#  TIER 1  🥇  Gold · BTC · Silver · Oil · ETH + Indices majeurs
#              Scannés EN PREMIER à CHAQUE cycle + cycle dédié intercalé
#  TIER 2  🥈  Forex majeures (7 paires)
#  TIER 3  🥉  Forex croisées + exotiques + autres commodités
# ─────────────────────────────────────────────────────────────

TIER_1_PRIORITY: list[tuple[str, str]] = [
    # ── 🥇 GOLD — priorité absolue, haute volatilité ──────────
    ("GC=F",     "Gold"),
    # ── 🥇 BTC — crypto unique, scan 24/7 week-end inclus ────
    ("BTC-USD",  "Bitcoin"),
    # ── 🥇 ETH — deuxième crypto principale ──────────────────
    ("ETH-USD",  "Ethereum"),
    # ── 🥇 SILVER — suit Gold, volatilité élevée ─────────────
    ("SI=F",     "Silver"),
    # ── 🥇 OIL WTI — très liquide, bons setups SMC ───────────
    ("CL=F",     "Oil WTI"),
    # ── 🥇 OIL BRENT ──────────────────────────────────────────
    ("BZ=F",     "Oil Brent"),
    # ── 🥇 INDICES MAJEURS ────────────────────────────────────
    ("^GSPC",    "S&P 500"),
    ("^NDX",     "Nasdaq 100"),
    ("^DJI",     "Dow Jones"),
    ("^GDAXI",   "DAX"),
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
    # ── 🥉 AUTRES INDICES ─────────────────────────────────────
    ("^FCHI",    "CAC 40"),
    ("^FTSE",    "FTSE 100"),
    ("^N225",    "Nikkei 225"),
    ("^HSI",     "Hang Seng"),
    # ── 🥉 AUTRES CRYPTO ─────────────────────────────────────
    ("XRP-USD",  "Ripple"),
    ("SOL-USD",  "Solana"),
    ("BNB-USD",  "BNB"),
    ("ADA-USD",  "Cardano"),
    ("AVAX-USD", "Avalanche"),
    ("LINK-USD", "Chainlink"),
    ("DOGE-USD", "Dogecoin"),
    ("LTC-USD",  "Litecoin"),
]

# Correspondance catégorie → liste de symboles
CATEGORY_MAP: dict[str, list[tuple[str, str]]] = {
    "priority"    : TIER_1_PRIORITY,                                          # Gold/BTC/ETH/Indices
    "forex"       : TIER_2_FOREX,                                             # 7 majeures seulement
    "forex_all"   : TIER_2_FOREX + [s for s in TIER_3_EXTRA if "=X" in s[0]],
    "crypto"      : [s for s in TIER_1_PRIORITY + TIER_3_EXTRA if "-USD" in s[0]],
    "commodities" : [s for s in TIER_1_PRIORITY + TIER_3_EXTRA
                     if s[0] in ("GC=F","SI=F","CL=F","BZ=F","NG=F","HG=F","PL=F","PA=F")],
    "indices"     : [s for s in TIER_1_PRIORITY + TIER_3_EXTRA if s[0].startswith("^")],
    "all"         : TIER_1_PRIORITY + TIER_2_FOREX + TIER_3_EXTRA,
}
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
    print(f"{c('║', 'cyan')}  {c('SMC SCAN — PRIORITÉ GOLD 🥇 / BTC 🥇 / FOREX', 'yellow'):<63}{c('║', 'cyan')}")
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

    # ── v11 : BTC + Gold toujours en tête de liste ────────────
    # Quel que soit le mode (forex, all, priority…), BTC-USD et GC=F
    # sont déplacés en première position pour être scannés en priorité absolue.
    _PRIORITY_FIRST = ["BTC-USD", "GC=F"]
    _sym_dict = {s: m for s, m in symbols}
    priority_items = [(s, _sym_dict[s]) for s in _PRIORITY_FIRST if s in _sym_dict]
    rest_items     = [(s, m) for s, m in symbols if s not in _PRIORITY_FIRST]
    symbols = priority_items + rest_items

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

            # ── Hors session → BTC-USD uniquement (week-end / nuit) ──
            # Les marchés Forex/Indices/Commodités sont bloqués hors London/NY.
            # Le week-end, seul BTC-USD est scanné (crypto 24/7 restreinte à BTC).
            CRYPTO_SYMBOLS = frozenset({"BTC-USD"})
            btc_only_mode = not is_session_active()
            if btc_only_mode:
                crypto_syms = [(s, m) for s, m in symbols if s in CRYPTO_SYMBOLS]
                if not crypto_syms:
                    if cycle_n % 10 == 1:
                        log.info(f"  💤 [{cycle_n}] {now_hhmm} — Hors session — Script actif ✓")
                    with _STATUS_LOCK:
                        _STATUS["cycle"]        = cycle_n
                        _STATUS["last_scan"]    = now_str
                        _STATUS["scan_running"] = False
                    time.sleep(interval)
                    continue
                symbols_this_cycle = crypto_syms
                if cycle_n % 5 == 1:
                    log.info(f"  🟡 [{cycle_n}] {now_hhmm} — Hors session — Crypto scan continu ({len(crypto_syms)} marchés)")
            else:
                symbols_this_cycle = symbols

            with _STATUS_LOCK:
                _STATUS["scan_running"] = True
                _STATUS["cycle"]        = cycle_n
                _STATUS["last_scan"]    = now_str

            log.info(f"  🔍 [{cycle_n}] {now_hhmm} — Scan {len(symbols_this_cycle)} paires"
                     + (" [BTC only — week-end/nuit]" if btc_only_mode else ""))

            # ── Reset garde corrélation pour ce cycle ──────────
            correlation_guard_reset()

            # ── ② Entête tableau ───────────────────────────────
            W = 90
            mode_label = "🟡 BTC ONLY — week-end/nuit" if btc_only_mode else "🟢 SESSION ACTIVE"
            n_scan = len(symbols_this_cycle)
            print(f"\n{'╔' + '═'*W + '╗'}")
            print(f"║  🔍  CYCLE #{cycle_n}  —  {now_str}  —  {n_scan} MARCHÉS  {mode_label}"
                  + " " * max(0, W - 4 - 8 - len(now_str) - len(str(n_scan)) - 17 - len(mode_label)) + "║")
            print(f"║  Score min : {min_score}/100   RR min : 1:{min_rr}   "
                  + "Confirmations requises : BOS + FVG + OB + Liquidité + M5 trigger"
                  + " " * max(0, W - 4 - 13 - len(str(min_score)) - 3 -
                               len(str(min_rr)) - 58) + "║")
            print(f"{'╠' + '═'*W + '╣'}")

            # En-têtes colonnes
            hdr = (f"  {'N°':<4} {'Tier':<4} {'Marché':<14} {'Symbole':<12}"
                   f"  {'Prix':>14}  {'Biais':>7}  "
                   f"{'BOS':>4} {'FVG':>4} {'OB':>4} {'LIQ':>4}"
                   f"  {'Score':>6}  {'RR':>6}  Statut")
            print(hdr)
            print(f"  {'─'*88}")

            signals_found: list[tuple[str, str, "Signal", str]] = []   # (mkt, sym, sig, tier_label)

            # ── Scan marché par marché ────────────────────────
            # ORDRE DE PRIORITÉ : TIER 1 (Gold/BTC/Indices) apparaît
            # toujours EN TÊTE de la liste symbols_this_cycle.
            # Les TIER 1 ont déjà été placés premiers dans TIER_1_PRIORITY
            # → scan_watchlist les traite dans l'ordre naturel.
            #
            # Mode "priority burst" : si cycle_n % 3 == 1 → rescan
            # immédiat Tier 1 seul en début de cycle, AVANT les autres.
            if not btc_only_mode and cycle_n % 3 == 1:
                t1_syms = [(s, m) for s, m in symbols_this_cycle
                           if any(s == x[0] for x in TIER_1_PRIORITY)]
                if t1_syms and len(t1_syms) > 0:
                    log.info(f"  ★ Burst TIER 1 ({len(t1_syms)} marchés) — cycle {cycle_n}")

            for i, (sym, mkt) in enumerate(symbols_this_cycle, 1):
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

                # ══════════════════════════════════════════════
                #  AGENT IA CLAUDE — Log informatif (non bloquant)
                #  Le signal passe si score ≥ seuil + RR ≥ min + corrélation OK.
                #  Claude donne un avis secondaire loggé mais ne bloque plus.
                # ══════════════════════════════════════════════
                if AI_VERIFY_ENABLED and ANTHROPIC_API_KEY:
                    ai_ok, ai_reason = claude_verify_signal(sig)
                    if ai_ok:
                        log.info(f"  🤖 [IA] ✅ Avis positif : {ai_reason}")
                        print(c(f"  🤖 AGENT IA → ✅ {ai_reason}", "green"))
                    else:
                        log.warning(f"  🤖 [IA] ⚠ Avis négatif (non bloquant) : {ai_reason}")
                        print(c(f"  🤖 AGENT IA → ⚠ (avis) {ai_reason}", "yellow"))
                    # ⚠ Ne pas 'continue' ici — l'IA n'est plus juge final

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
        description="SMC Signal Engine v8 — H1→M15→M5 · M5 Trigger Obligatoire · Zone Fraîche · London/NY",
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

