
#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   AlphaBot V7 — SMC + Claude AI + Trailing SL + Objectif $7/jour    ║
║   Binance Futures Demo | Analyse Fondamentale Web | Telegram         ║
║   Capital: $20 | Risque: $0.5/trade | Levier 20x | M1+M5            ║
╚══════════════════════════════════════════════════════════════════════╝
Dépendances : pip install requests
"""

import time
import hmac
import hashlib
import math
import json
import requests
import os
import threading
from datetime import datetime, date
from urllib.parse import urlencode
from flask import Flask, jsonify

# ═══════════════════════════════════════════════════════════════════
#  ██ CONFIG — MODIFIEZ CES VALEURS
# ═══════════════════════════════════════════════════════════════════

# ── Binance Demo Futures (remplacez par vos clés)
API_KEY    = "WxXiutDVQsnNWrYPu4Kyz7Pbwi8PC3edQBf9lSWJwL0Scz3EGNeWLsR6sdMRmPh0"
SECRET_KEY = "BAzQ0Lav1DMCrBZf4MFl2msLO45fdWXOPH5aCr0ZmzuQF7miIP9fVAYHkzDDfb7F"

BINANCE_URLS = [
    "https://testnet.binancefutures.com",
    "https://fapi.binance.com",
    "https://api.demo-trading.binance.com",
]
BASE_URL = None

# ── Anthropic Claude API
ANTHROPIC_API_KEY = "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"
ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-haiku-4-5-20251001"
USE_CLAUDE_AI     = True

# ── Telegram
TG_TOKEN   = "8665812395:AAFO4BMTIrBCQJYVL8UytO028TcB1sDfgbI"
TG_CHAT_ID = None

# ── Paramètres Trading
CAPITAL          = 20.0
RISK_USD         = 0.5       # Risque par trade
LEVERAGE         = 20
MAX_TRADES       = 5
TOP_N            = 15        # Scanner top 15 cryptos volatiles
TIMEFRAME        = "1m"
SL_ATR_MULT      = 1.5
TP_RATIO         = 2.0
SCAN_INTERVAL    = 60        # secondes entre scans
MIN_SCORE        = 4
MIN_VOLUME       = 10_000_000

# ── Objectif journalier
DAILY_TARGET     = 7.0       # $7 par jour
DAILY_MAX_LOSS   = 5.0       # Stop trading si perte > $5/jour

# ── Trailing Stop
TRAILING_ENABLED      = True
TRAILING_ACTIVATION   = 1.5  # Activer le trailing quand +1.5x ATR
TRAILING_DISTANCE_ATR = 1.0  # Distance du trailing = 1x ATR

# ── SMC
SWING_LEN    = 5
FVG_MIN_PCT  = 0.001
ATR_PERIOD   = 14
KLINES_LIMIT = 120

# ═══════════════════════════════════════════════════════════════════
#  ██ ÉTAT GLOBAL
# ═══════════════════════════════════════════════════════════════════
sess           = requests.Session()
sess.headers.update({"X-MBX-APIKEY": API_KEY})

_sym_cache      = {}
_update_offset  = 0
_claude_cache   = {}
_trailing_data  = {}   # {symbol: {"highest": float, "atr": float, "direction": str}}

# Compteurs journaliers
_daily_pnl      = 0.0
_daily_trades   = 0
_daily_date     = date.today()


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def now_ms():
    return int(time.time() * 1000)


def sign(params):
    params["timestamp"] = now_ms()
    q   = urlencode(params)
    sig = hmac.new(SECRET_KEY.encode(), q.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def bget(path, params=None, signed=False):
    if not BASE_URL:
        return None
    if params is None:
        params = {}
    if signed:
        params = sign(params)
    try:
        r = sess.get(BASE_URL + path, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"[BGET ERR] {path} → {e}")
        return None


def bpost(path, params=None):
    if not BASE_URL:
        return None
    if params is None:
        params = {}
    params = sign(params)
    try:
        r = sess.post(BASE_URL + path, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"[BPOST ERR] {path} → {e}")
        return None


def round_step(value, step):
    if step == 0:
        return round(value, 6)
    s   = str(step)
    dec = len(s.rstrip("0").split(".")[-1]) if "." in s else 0
    return round(math.floor(value / step) * step, dec)


def get_sym_info(symbol):
    if symbol in _sym_cache:
        return _sym_cache[symbol]
    info = bget("/fapi/v1/exchangeInfo")
    if not info:
        return {"step": 0.001, "tick": 0.01, "min_qty": 0.001}
    for s in info.get("symbols", []):
        if s["symbol"] == symbol:
            step, tick, min_qty = 0.001, 0.01, 0.001
            for f in s.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step    = float(f["stepSize"])
                    min_qty = float(f["minQty"])
                if f["filterType"] == "PRICE_FILTER":
                    tick = float(f["tickSize"])
            r = {"step": step, "tick": tick, "min_qty": min_qty}
            _sym_cache[symbol] = r
            return r
    return {"step": 0.001, "tick": 0.01, "min_qty": 0.001}


def price_str(price, tick):
    s   = str(tick)
    dec = len(s.rstrip("0").split(".")[-1]) if "." in s else 0
    return f"{round_step(price, tick):.{dec}f}"


# ═══════════════════════════════════════════════════════════════════
#  ██ CONNEXION BINANCE
# ═══════════════════════════════════════════════════════════════════
def detect_binance_url():
    global BASE_URL
    log("🔍 Recherche URL Binance...")
    for url in BINANCE_URLS:
        # Étape 1 : ping public
        try:
            r = requests.get(url + "/fapi/v1/ping", timeout=10)
            if r.status_code != 200:
                log(f"   ✗ {url} → ping {r.status_code}")
                continue
            log(f"   ✓ {url} → ping OK")
        except Exception as e:
            log(f"   ✗ {url} → {str(e)[:80]}")
            continue
        # Étape 2 : tester les clés
        try:
            ts  = int(time.time() * 1000)
            q   = f"timestamp={ts}"
            sig = hmac.new(SECRET_KEY.encode(), q.encode(), hashlib.sha256).hexdigest()
            ra  = requests.get(
                url + "/fapi/v2/balance",
                params={"timestamp": ts, "signature": sig},
                headers={"X-MBX-APIKEY": API_KEY},
                timeout=10
            )
            log(f"   ✓ {url} → auth status {ra.status_code}")
            if ra.status_code == 401:
                log(f"   ✗ {url} → Clés rejetées (401) — essai suivant")
                continue
            # 200 ou autre (400 = paramètre) = clés acceptées
            BASE_URL = url
            log(f"✅ Binance connecté → {url} (status auth: {ra.status_code})")
            return True
        except Exception as e:
            log(f"   ✗ {url} → auth erreur: {str(e)[:80]}")
            # Si ping OK mais auth échoue réseau → on tente quand même
            BASE_URL = url
            log(f"⚠️ {url} → ping OK, auth timeout — on tente quand même")
            return True
    log("❌ Aucune URL Binance accessible depuis ce VPS.")
    return False


# ═══════════════════════════════════════════════════════════════════
#  ██ CLAUDE AI — ANALYSE FONDAMENTALE + WEB SEARCH
# ═══════════════════════════════════════════════════════════════════
def claude_analyze(symbol, direction, setups, score, volatility_24h):
    """
    Appelle Claude avec web_search pour analyser les fondamentaux réels.
    Retourne: dict avec score_ai (0-3), verdict, raison, tendance, risque
    """
    if not USE_CLAUDE_AI or len(ANTHROPIC_API_KEY) < 20:
        return {
            "score_ai": 2, "verdict": "NEUTRE",
            "reason": "Claude AI non configuré",
            "trend_global": "NEUTRE", "risk_level": "MOYEN",
            "news_summary": "Pas d'analyse web disponible"
        }

    cache_key = f"{symbol}_{direction}_{int(time.time()//300)}"
    if cache_key in _claude_cache:
        return _claude_cache[cache_key]

    coin = symbol.replace("USDT", "")

    prompt = f"""Tu es un expert trader crypto. Analyse ce signal de trading en temps réel.

SIGNAL À ÉVALUER:
- Paire       : {symbol} ({coin})
- Direction   : {direction}
- Setups SMC  : {", ".join(setups)}
- Score SMC   : {score}/12
- Volatilité 24h : {volatility_24h:.2f}%
- Timeframe   : M1 (scalping Futures Levier 20x)

MISSION EN 2 ÉTAPES:
1. Recherche l'actualité récente sur {coin} (news, events, sentiment marché, on-chain data si dispo)
2. Évalue si les fondamentaux soutiennent ce signal {direction}

Critères score_ai:
- 3 = Fondamentaux très favorables (news positive + trend {direction} confirmé)
- 2 = Neutre (pas d'info contradictoire majeure)
- 1 = Légèrement contre (quelques signaux négatifs)
- 0 = BLOQUER ce trade (news très négative / manipulation / risk élevé)

Réponds UNIQUEMENT en JSON valide, sans texte avant ou après:
{{
  "score_ai": <0-3>,
  "verdict": "<FAVORABLE|NEUTRE|DÉFAVORABLE>",
  "reason": "<15 mots max>",
  "trend_global": "<BULL|BEAR|NEUTRE>",
  "risk_level": "<FAIBLE|MOYEN|ÉLEVÉ>",
  "news_summary": "<résumé news en 20 mots max>",
  "close_recommendation": "<ATTENDRE_TP|SL_SUIVEUR|CLOTURER_MAINTENANT>"
}}"""

    try:
        headers = {
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json"
        }
        # Utiliser web_search pour actualités crypto en temps réel
        body = {
            "model":      CLAUDE_MODEL,
            "max_tokens": 400,
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search"
                }
            ],
            "messages": [{"role": "user", "content": prompt}]
        }
        r = requests.post(ANTHROPIC_URL, headers=headers, json=body, timeout=25)
        r.raise_for_status()
        data = r.json()

        # Assembler la réponse (peut contenir tool_use + text)
        content_blocks = data.get("content", [])
        text_parts = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block["text"])

        content = " ".join(text_parts).strip()

        # Nettoyer markdown si présent
        if "```" in content:
            parts = content.split("```")
            for p in parts:
                if p.startswith("json"):
                    content = p[4:].strip()
                    break
                elif "{" in p:
                    content = p.strip()
                    break

        # Extraire JSON
        start = content.find("{")
        end   = content.rfind("}") + 1
        if start >= 0 and end > start:
            content = content[start:end]

        result = json.loads(content)
        result["score_ai"] = max(0, min(3, int(result.get("score_ai", 1))))
        if "close_recommendation" not in result:
            result["close_recommendation"] = "ATTENDRE_TP"
        _claude_cache[cache_key] = result
        return result

    except Exception as e:
        log(f"  [Claude ERR] {e}")
        return {
            "score_ai": 1, "verdict": "NEUTRE",
            "reason": "Erreur API Claude",
            "trend_global": "NEUTRE", "risk_level": "MOYEN",
            "news_summary": "Analyse non disponible",
            "close_recommendation": "ATTENDRE_TP"
        }


# ═══════════════════════════════════════════════════════════════════
#  ██ TELEGRAM — BOT INTERACTIF AVEC BOUTONS
# ═══════════════════════════════════════════════════════════════════
TG_BASE = f"https://api.telegram.org/bot{TG_TOKEN}"

# Historique des trades pour rapports
_trade_history = []   # liste de dicts {symbol, direction, pnl, reason, time}
_subscribers   = set()  # tous les chat_id abonnés (pour partage groupe)


def tg_send(text, chat_id=None, reply_markup=None):
    """Envoie un message à un ou tous les abonnés."""
    targets = [chat_id] if chat_id else (list(_subscribers) if _subscribers else ([TG_CHAT_ID] if TG_CHAT_ID else []))
    for cid in targets:
        if not cid:
            continue
        payload = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(f"{TG_BASE}/sendMessage", json=payload, timeout=8)
        except Exception as e:
            log(f"[TG ERR] {e}")


def tg_answer_callback(callback_id):
    try:
        requests.post(f"{TG_BASE}/answerCallbackQuery",
                      json={"callback_query_id": callback_id}, timeout=5)
    except Exception:
        pass


def tg_get_chat_id():
    global TG_CHAT_ID, _update_offset
    try:
        r = requests.get(f"{TG_BASE}/getUpdates",
                         params={"offset": _update_offset, "limit": 10}, timeout=8)
        updates = r.json().get("result", [])
        for u in updates:
            _update_offset = u["update_id"] + 1
            # Gérer les callbacks (boutons cliqués)
            if u.get("callback_query"):
                handle_callback(u["callback_query"])
                continue
            msg  = u.get("message") or u.get("channel_post") or {}
            chat = msg.get("chat", {})
            cid  = chat.get("id")
            if not cid:
                continue
            # Enregistrer tous les abonnés
            _subscribers.add(cid)
            if not TG_CHAT_ID:
                TG_CHAT_ID = cid
                log(f"✅ Telegram Chat ID: {TG_CHAT_ID}")
            # Gérer les commandes texte
            text_msg = msg.get("text", "")
            handle_command(text_msg, cid)
        return bool(TG_CHAT_ID)
    except Exception as e:
        log(f"[TG getUpdates ERR] {e}")
    return False


def handle_command(text, cid):
    """Gérer les commandes /start /menu /pnl /trades /solde /rapport /help"""
    t = text.strip().lower()
    if t in ["/start", "/menu", "menu", "start"]:
        send_main_menu(cid)
    elif t in ["/pnl", "pnl"]:
        send_pnl_report(cid)
    elif t in ["/trades", "trades"]:
        send_trade_history(cid)
    elif t in ["/solde", "solde", "/balance"]:
        send_balance(cid)
    elif t in ["/rapport", "rapport"]:
        send_daily_report(cid)
    elif t in ["/positions", "positions"]:
        send_positions(cid)
    elif t in ["/help", "help"]:
        send_help(cid)
    elif t in ["/start"]:
        send_main_menu(cid)


def handle_callback(cb):
    """Gérer les clics sur les boutons inline."""
    cid  = cb["from"]["id"]
    data = cb.get("data", "")
    tg_answer_callback(cb["id"])
    _subscribers.add(cid)

    if data == "menu":
        send_main_menu(cid)
    elif data == "pnl":
        send_pnl_report(cid)
    elif data == "trades":
        send_trade_history(cid)
    elif data == "solde":
        send_balance(cid)
    elif data == "rapport":
        send_daily_report(cid)
    elif data == "positions":
        send_positions(cid)
    elif data == "parametres":
        send_parametres(cid)


def btn(text, data):
    return {"text": text, "callback_data": data}


def send_main_menu(cid):
    pct  = (_daily_pnl / DAILY_TARGET * 100) if DAILY_TARGET > 0 else 0
    bar  = "🟩" * int(pct / 10) + "⬜" * (10 - int(pct / 10))
    lines = [
        "🤖 <b>AlphaBot V7 — Tableau de bord</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 {date.today().strftime('%d/%m/%Y')}",
        f"💰 PnL jour    : <b>${_daily_pnl:+.2f}</b> / ${DAILY_TARGET}",
        f"📊 Progression : {bar} {pct:.0f}%",
        f"🔢 Trades      : <b>{_daily_trades}</b>",
        f"⚡ Statut      : <b>{'🟢 ACTIF' if BASE_URL else '🔴 HORS LIGNE'}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "Choisissez une option :"
    ]
    msg = "\n".join(lines)
    markup = {"inline_keyboard": [
        [btn("💰 PnL & Profits", "pnl"),    btn("📋 Historique trades", "trades")],
        [btn("💼 Solde compte", "solde"),    btn("📍 Positions ouvertes", "positions")],
        [btn("📊 Rapport du jour", "rapport"), btn("⚙️ Paramètres", "parametres")],
    ]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_pnl_report(cid):
    wins   = [t for t in _trade_history if t["pnl"] > 0]
    losses = [t for t in _trade_history if t["pnl"] <= 0]
    total_win  = sum(t["pnl"] for t in wins)
    total_loss = sum(t["pnl"] for t in losses)
    winrate    = (len(wins) / len(_trade_history) * 100) if _trade_history else 0
    lines = [
        "💰 <b>Rapport PnL — AlphaBot V7</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📅 Aujourd'hui",
        f"   PnL net     : <b>${_daily_pnl:+.2f}</b>",
        f"   Objectif    : <b>${DAILY_TARGET}</b>",
        f"   Progression : <b>{(_daily_pnl/DAILY_TARGET*100) if DAILY_TARGET else 0:.0f}%</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 Session",
        f"   Trades total : <b>{len(_trade_history)}</b>",
        f"   ✅ Gagnants  : <b>{len(wins)}</b>  (+${total_win:.2f})",
        f"   ❌ Perdants  : <b>{len(losses)}</b>  (-${abs(total_loss):.2f})",
        f"   🎯 Win rate  : <b>{winrate:.0f}%</b>",
        f"   💵 Meilleur  : <b>${max((t['pnl'] for t in _trade_history), default=0):.2f}</b>",
        f"   📉 Pire      : <b>${min((t['pnl'] for t in _trade_history), default=0):.2f}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⚙️  Capital    : <b>${CAPITAL}</b>  |  Levier: <b>{LEVERAGE}x</b>",
        f"<i>{datetime.now().strftime('%d/%m %H:%M')}</i>"
    ]
    msg = "\n".join(lines)
    markup = {"inline_keyboard": [[btn("🔙 Menu", "menu")]]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_trade_history(cid):
    if not _trade_history:
        msg = "📋 <b>Historique trades</b>\n\nAucun trade cette session."
    else:
        lines = ["📋 <b>Historique trades — Session</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━"]
        for t in _trade_history[-10:]:
            emoji = "✅" if t["pnl"] > 0 else "❌"
            d     = "🟢" if t["direction"] == "LONG" else "🔴"
            lines.append(f"{emoji} {d} <b>{t['symbol']}</b>  <code>${t['pnl']:+.2f}</code>")
            lines.append(f"   <i>{t['reason']}</i>  •  {t['time']}")
        msg = "\n".join(lines)
    markup = {"inline_keyboard": [[btn("🔙 Menu", "menu")]]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_balance(cid):
    data = bget("/fapi/v2/balance", {}, signed=True) if BASE_URL else None
    if not data:
        msg = "💼 <b>Solde compte</b>\n\n⚠️ Binance non connecté"
    else:
        usdt = next((a for a in data if a.get("asset") == "USDT"), None)
        if usdt:
            balance    = float(usdt.get("balance", 0))
            available  = float(usdt.get("availableBalance", 0))
            unrealized = float(usdt.get("crossUnPnl", 0))
            lines = [
                "💼 <b>Solde compte Binance</b>",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"💵 Balance total  : <b>${balance:.2f}</b>",
                f"✅ Disponible     : <b>${available:.2f}</b>",
                f"📊 PnL non réalisé: <b>${unrealized:+.2f}</b>",
                f"⚙️  Levier        : <b>{LEVERAGE}x</b>",
                f"🎯 PnL jour       : <b>${_daily_pnl:+.2f}</b>",
                f"<i>Binance Demo • {datetime.now().strftime('%H:%M:%S')}</i>"
            ]
            msg = "\n".join(lines)
        else:
            msg = "💼 Solde USDT non trouvé."
    markup = {"inline_keyboard": [[btn("🔙 Menu", "menu")]]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_positions(cid):
    positions = get_positions() if BASE_URL else []
    if not positions:
        msg = "📍 <b>Positions ouvertes</b>\n\nAucune position ouverte actuellement."
    else:
        lines = [f"📍 <b>Positions ouvertes ({len(positions)})</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━"]
        for p in positions:
            sym  = p["symbol"]
            amt  = float(p.get("positionAmt", 0))
            entry= float(p.get("entryPrice", 0))
            pnl  = float(p.get("unRealizedProfit", 0))
            side = "🟢 LONG" if amt > 0 else "🔴 SHORT"
            ep   = "✅" if pnl > 0 else "❌"
            lines.append(f"{side} <b>{sym}</b>")
            lines.append(f"   Entrée: <code>{entry:.4f}</code>  PnL: {ep} <b>${pnl:+.2f}</b>")
        msg = "\n".join(lines)
    markup = {"inline_keyboard": [[btn("🔄 Rafraîchir", "positions"), btn("🔙 Menu", "menu")]]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_daily_report(cid):
    wins     = [t for t in _trade_history if t["pnl"] > 0]
    losses   = [t for t in _trade_history if t["pnl"] <= 0]
    winrate  = (len(wins) / len(_trade_history) * 100) if _trade_history else 0
    status   = "🏆 OBJECTIF ATTEINT" if _daily_pnl >= DAILY_TARGET else ("🔴 PERTE" if _daily_pnl < 0 else "🟡 En cours")
    lines = [
        f"📊 <b>RAPPORT — {date.today().strftime('%d/%m/%Y')}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 PnL net     : <b>${_daily_pnl:+.2f}</b>",
        f"🎯 Objectif    : <b>${DAILY_TARGET}</b>",
        f"📈 Statut      : <b>{status}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📋 Trades",
        f"   Total       : <b>{len(_trade_history)}</b>",
        f"   ✅ TP        : <b>{len(wins)}</b>",
        f"   ❌ SL        : <b>{len(losses)}</b>",
        f"   🎯 Win rate  : <b>{winrate:.0f}%</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚙️  Config",
        f"   Capital     : <b>${CAPITAL}</b>",
        f"   Risque/trade: <b>${RISK_USD}</b>",
        f"   Levier      : <b>{LEVERAGE}x</b>",
        f"   Claude AI   : <b>{'✅ Activé' if USE_CLAUDE_AI else '❌ Off'}</b>",
        f"   Trailing SL : <b>{'✅ Activé' if TRAILING_ENABLED else '❌ Off'}</b>",
        f"<i>AlphaBot V7 • {datetime.now().strftime('%d/%m %H:%M')}</i>"
    ]
    msg = "\n".join(lines)
    markup = {"inline_keyboard": [[btn("🔙 Menu", "menu")]]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_parametres(cid):
    lines = [
        "⚙️ <b>Paramètres AlphaBot V7</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Capital      : <b>${CAPITAL}</b>",
        f"⚠️  Risque/trade : <b>${RISK_USD}</b>",
        f"⚙️  Levier       : <b>{LEVERAGE}x</b>",
        f"🎯 Objectif/jour : <b>${DAILY_TARGET}</b>",
        f"🛑 Max perte/jour: <b>${DAILY_MAX_LOSS}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔍 Scanner",
        f"   Top N        : <b>{TOP_N}</b> cryptos",
        f"   Volume min   : <b>${MIN_VOLUME:,}</b>",
        f"   Score min SMC: <b>{MIN_SCORE}/12</b>",
        "   Timeframe    : <b>M1</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔄 Trailing SL",
        f"   Activation   : <b>{TRAILING_ACTIVATION}x ATR</b>",
        f"   Distance     : <b>{TRAILING_DISTANCE_ATR}x ATR</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🤖 Claude AI     : <b>{'✅ Web Search' if USE_CLAUDE_AI else '❌ Off'}</b>",
        f"🌐 Binance       : <code>{BASE_URL or 'Non connecté'}</code>",
        "<i>AlphaBot V7 Pro</i>"
    ]
    msg = "\n".join(lines)
    markup = {"inline_keyboard": [[btn("🔙 Menu", "menu")]]}
    tg_send(msg, chat_id=cid, reply_markup=markup)


def send_help(cid):
    lines = [
        "❓ <b>Commandes AlphaBot V7</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "/menu — 🏠 Tableau de bord",
        "/pnl — 💰 Rapport PnL",
        "/trades — 📋 Historique",
        "/solde — 💼 Solde Binance",
        "/positions — 📍 Positions",
        "/rapport — 📊 Rapport jour",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<i>Partagez ce bot avec votre groupe pour suivre en live !</i>"
    ]
    tg_send("\n".join(lines), chat_id=cid)


def tg_signal(sig, ai):
    """Message Telegram COMPLET — envoyé uniquement lors d'un trade réel."""
    emoji  = "🟢" if sig["direction"] == "LONG" else "🔴"
    arrow  = "📈" if sig["direction"] == "LONG" else "📉"
    setups = " + ".join(sig["setups"])

    verdict_emoji = {"FAVORABLE": "✅", "NEUTRE": "⚖️", "DÉFAVORABLE": "⛔"}.get(
        ai.get("verdict", "NEUTRE"), "⚖️")
    trend_emoji   = {"BULL": "🐂", "BEAR": "🐻", "NEUTRE": "➡️"}.get(
        ai.get("trend_global", "NEUTRE"), "➡️")
    risk_emoji    = {"FAIBLE": "🟢", "MOYEN": "🟡", "ÉLEVÉ": "🔴"}.get(
        ai.get("risk_level", "MOYEN"), "🟡")
    close_emoji   = {"ATTENDRE_TP": "⏳", "SL_SUIVEUR": "🔄", "CLOTURER_MAINTENANT": "⚡"}.get(
        ai.get("close_recommendation", "ATTENDRE_TP"), "⏳")

    total_score = sig["score"] + ai.get("score_ai", 0)
    pnl_info    = f"${_daily_pnl:.2f}/{DAILY_TARGET:.0f}$"

    msg = (
        f"{emoji} <b>TRADE {sig['direction']} — AlphaBot V7</b> {arrow}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔷 Paire        : <b>{sig['symbol']}</b>\n"
        f"🎯 Entrée       : <code>{sig['entry']:.4f}</code>\n"
        f"🛑 Stop Loss    : <code>{sig['sl']:.4f}</code>\n"
        f"💰 Take Profit  : <code>{sig['tp']:.4f}</code>\n"
        f"🔄 Trailing SL  : <b>{'Activé' if TRAILING_ENABLED else 'Désactivé'}</b> ({TRAILING_ACTIVATION}x ATR)\n"
        f"📊 Quantité     : <code>{sig['qty']}</code>\n"
        f"⚙️  Levier      : <b>{LEVERAGE}x</b>\n"
        f"💵 Risque       : <b>${RISK_USD}</b>  |  RR: <b>1:{int(TP_RATIO)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <b>Analyse Technique SMC</b>\n"
        f"   Score       : <b>{sig['score']}/12</b>\n"
        f"   Setups      : <i>{setups}</i>\n"
        f"   ATR         : <code>{sig['atr']:.6f}</code>\n"
        f"   Volatilité  : <b>{sig.get('volatility_24h', 0):.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>Claude AI — Fondamentaux + News Web</b>\n"
        f"   Verdict     : {verdict_emoji} <b>{ai.get('verdict','N/A')}</b>\n"
        f"   Tendance    : {trend_emoji} {ai.get('trend_global','N/A')}\n"
        f"   Risque      : {risk_emoji} {ai.get('risk_level','N/A')}\n"
        f"   News        : <i>{ai.get('news_summary','N/A')}</i>\n"
        f"   Raison      : <i>{ai.get('reason','')}</i>\n"
        f"   Score AI    : <b>+{ai.get('score_ai',0)}/3</b>\n"
        f"   Gestion     : {close_emoji} <b>{ai.get('close_recommendation','ATTENDRE_TP')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Score Total  : <b>{total_score}/15</b>\n"
        f"📅 PnL Jour     : <b>{pnl_info}</b>  |  Trades: <b>{_daily_trades}</b>\n"
        f"⏱️  Timeframe   : M1  |  Demo Futures\n"
        f"<i>AlphaBot V7 Pro • {datetime.now().strftime('%d/%m %H:%M:%S')}</i>"
    )
    tg_send(msg)


def tg_trade_closed(symbol, direction, pnl, reason, ai_rec):
    """Notification de clôture de trade."""
    emoji  = "✅" if pnl > 0 else "❌"
    action = "🏆 PROFIT" if pnl > 0 else "💸 STOP"
    pnl_info = f"${_daily_pnl:.2f}/{DAILY_TARGET:.0f}$"

    msg = (
        f"{emoji} <b>{action} — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Direction  : <b>{direction}</b>\n"
        f"💵 PnL Trade  : <b>${pnl:+.2f}</b>\n"
        f"📋 Raison     : <i>{reason}</i>\n"
        f"🤖 AI conseil : <i>{ai_rec}</i>\n"
        f"📅 PnL Jour   : <b>{pnl_info}</b>\n"
        f"<i>{datetime.now().strftime('%d/%m %H:%M:%S')}</i>"
    )
    tg_send(msg)


def tg_daily_summary():
    """Bilan quotidien."""
    status = "🎯 OBJECTIF ATTEINT" if _daily_pnl >= DAILY_TARGET else "📊 En cours"
    msg = (
        f"📅 <b>BILAN JOURNALIER — AlphaBot V7</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 PnL Total   : <b>${_daily_pnl:+.2f}</b>\n"
        f"🎯 Objectif    : <b>${DAILY_TARGET}</b>\n"
        f"📊 Trades      : <b>{_daily_trades}</b>\n"
        f"🏆 Statut      : <b>{status}</b>\n"
        f"<i>{date.today().strftime('%d/%m/%Y')}</i>"
    )
    tg_send(msg)


def tg_welcome():
    lines = [
        "🚀 <b>AlphaBot V7 — En ligne !</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Capital       : <b>${CAPITAL}</b>",
        f"⚠️  Risque/trade : <b>${RISK_USD}</b>",
        f"⚙️  Levier       : <b>{LEVERAGE}x</b>",
        f"🎯 Objectif/jour : <b>${DAILY_TARGET}</b>",
        f"🔄 Trailing SL   : <b>{'✅ Activé' if TRAILING_ENABLED else '❌ Off'}</b>",
        f"🤖 Claude AI     : <b>{'✅ Web Search' if USE_CLAUDE_AI else '❌ Off'}</b>",
        f"🌐 Binance       : <code>{BASE_URL}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<i>Tapez /menu pour le tableau de bord</i>"
    ]
    msg = "\n".join(lines)
    markup = {"inline_keyboard": [
        [btn("🏠 Tableau de bord", "menu")],
        [btn("💰 PnL", "pnl"), btn("💼 Solde", "solde")],
    ]}
    tg_send(msg, reply_markup=markup)


def auto_detect_chat_id(timeout=90):
    global TG_CHAT_ID
    log("📱 Envoie un message à ton bot Telegram pour continuer...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tg_get_chat_id():
            return True
        time.sleep(3)
    return False


# ═══════════════════════════════════════════════════════════════════
#  ██ DONNÉES OHLCV
# ═══════════════════════════════════════════════════════════════════
def get_klines(symbol, interval="1m", limit=KLINES_LIMIT):
    data = bget("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    if not data or len(data) < 30:
        return None
    return [{"o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
             "c": float(k[4]), "v": float(k[5])} for k in data]


# ═══════════════════════════════════════════════════════════════════
#  ██ SCANNER VOLATILITÉ 24H
# ═══════════════════════════════════════════════════════════════════
def get_top_volatile(n=TOP_N):
    """Retourne les N cryptos les plus volatiles des 24 dernières heures."""
    tickers = bget("/fapi/v1/ticker/24hr")
    if not tickers:
        return []
    excluded = {"USDCUSDT", "BUSDUSDT", "TUSDUSDT", "USDTUSDT", "FDUSDUSDT", "BTCDOMUSDT"}
    filtered = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and t["symbol"] not in excluded
        and float(t.get("quoteVolume", 0)) >= MIN_VOLUME
        and float(t.get("lastPrice", 0)) > 0.0001
    ]
    # Trier par volatilité absolue 24h
    filtered.sort(key=lambda x: abs(float(x.get("priceChangePercent", 0))), reverse=True)
    result = [(t["symbol"], abs(float(t.get("priceChangePercent", 0)))) for t in filtered[:n]]
    return result


# ═══════════════════════════════════════════════════════════════════
#  ██ MOTEUR SMC
# ═══════════════════════════════════════════════════════════════════
def compute_atr(candles, period=ATR_PERIOD):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0001
    return sum(trs[-period:]) / period


def detect_swings(candles, n=SWING_LEN):
    sh_idx, sl_idx = [], []
    for i in range(n, len(candles) - n):
        h, l = candles[i]["h"], candles[i]["l"]
        if (all(h >= candles[i-j]["h"] for j in range(1, n+1)) and
                all(h >= candles[i+j]["h"] for j in range(1, n+1))):
            sh_idx.append(i)
        if (all(l <= candles[i-j]["l"] for j in range(1, n+1)) and
                all(l <= candles[i+j]["l"] for j in range(1, n+1))):
            sl_idx.append(i)
    return sh_idx, sl_idx


def detect_bos_choch(candles):
    sh_idx, sl_idx = detect_swings(candles)
    if len(sh_idx) < 2 or len(sl_idx) < 2:
        return None
    last_c = candles[-1]["c"]
    h_psn  = candles[sh_idx[-2]]["h"]
    l_psl  = candles[sl_idx[-2]]["l"]
    h_lsn  = candles[sh_idx[-1]]["h"]
    l_lsl  = candles[sl_idx[-1]]["l"]
    if l_lsl < l_psl and last_c > h_psn:
        return {"type": "LONG",  "setup": "CHoCH_BULL", "ref": l_lsl, "score": 4}
    if h_lsn > h_psn and last_c < l_psl:
        return {"type": "SHORT", "setup": "CHoCH_BEAR", "ref": h_lsn, "score": 4}
    if last_c > h_lsn and h_lsn > h_psn:
        return {"type": "LONG",  "setup": "BOS_BULL",   "ref": l_lsl, "score": 3}
    if last_c < l_lsl and l_lsl < l_psl:
        return {"type": "SHORT", "setup": "BOS_BEAR",   "ref": h_lsn, "score": 3}
    return None


def detect_liq_sweep(candles):
    sh_idx, sl_idx = detect_swings(candles)
    if not sh_idx or not sl_idx:
        return None
    sh_lvls = [candles[i]["h"] for i in sh_idx]
    sl_lvls = [candles[i]["l"] for i in sl_idx]
    p_low, p_high, l_close = candles[-2]["l"], candles[-2]["h"], candles[-1]["c"]
    n_sl = min(sl_lvls, key=lambda x: abs(x - p_low))
    n_sh = min(sh_lvls, key=lambda x: abs(x - p_high))
    if p_low < n_sl * 0.9995 and l_close > n_sl:
        return {"type": "BULL_SWEEP", "level": n_sl, "score": 3}
    if p_high > n_sh * 1.0005 and l_close < n_sh:
        return {"type": "BEAR_SWEEP", "level": n_sh, "score": 3}
    return None


def detect_order_blocks(candles):
    obs   = []
    start = max(0, len(candles) - 30)
    for i in range(start, len(candles) - 3):
        ci, cn = candles[i], candles[i+1]
        imp = abs(cn["c"] - cn["o"]) / (cn["o"] + 1e-9)
        if ci["c"] < ci["o"] and cn["c"] > cn["o"] and imp > 0.0015:
            obs.append({"type": "BULL", "top": max(ci["o"], ci["c"]),
                        "bot": min(ci["o"], ci["c"]), "score": 2})
        if ci["c"] > ci["o"] and cn["c"] < cn["o"] and imp > 0.0015:
            obs.append({"type": "BEAR", "top": max(ci["o"], ci["c"]),
                        "bot": min(ci["o"], ci["c"]), "score": 2})
    return obs[-5:]


def detect_fvg(candles):
    fvgs = []
    for i in range(2, len(candles)):
        c1, c3 = candles[i-2], candles[i]
        if c3["l"] > c1["h"] and (c3["l"]-c1["h"])/(c1["h"]+1e-9) >= FVG_MIN_PCT:
            fvgs.append({"type": "BULL", "top": c3["l"], "bot": c1["h"], "score": 2})
        if c1["l"] > c3["h"] and (c1["l"]-c3["h"])/(c3["h"]+1e-9) >= FVG_MIN_PCT:
            fvgs.append({"type": "BEAR", "top": c1["l"], "bot": c3["h"], "score": 2})
    return fvgs[-8:]


def detect_breaker_block(candles):
    obs = detect_order_blocks(candles)
    lc, lh, ll = candles[-1]["c"], candles[-1]["h"], candles[-1]["l"]
    for ob in reversed(obs):
        if ob["type"] == "BULL" and lc < ob["bot"] and lh >= ob["bot"]*0.998:
            return {"type": "BEAR_BB", "top": ob["top"], "bot": ob["bot"], "score": 3}
        if ob["type"] == "BEAR" and lc > ob["top"] and ll <= ob["top"]*1.002:
            return {"type": "BULL_BB", "top": ob["top"], "bot": ob["bot"], "score": 3}
    return None


def detect_double_pattern(candles):
    sh_idx, sl_idx = detect_swings(candles)
    tol = 0.002
    if len(sh_idx) >= 2:
        h1, h2 = candles[sh_idx[-2]]["h"], candles[sh_idx[-1]]["h"]
        if abs(h1-h2)/h1 <= tol and candles[-1]["c"] < min(h1, h2):
            return {"type": "SHORT", "setup": "DOUBLE_TOP", "score": 2}
    if len(sl_idx) >= 2:
        l1, l2 = candles[sl_idx[-2]]["l"], candles[sl_idx[-1]]["l"]
        if abs(l1-l2)/l1 <= tol and candles[-1]["c"] > max(l1, l2):
            return {"type": "LONG", "setup": "DOUBLE_BOTTOM", "score": 2}
    return None


# ═══════════════════════════════════════════════════════════════════
#  ██ ANALYSE COMPLÈTE (SMC + Claude + Fondamentaux)
# ═══════════════════════════════════════════════════════════════════
def analyze(symbol, volatility_24h=0.0):
    candles = get_klines(symbol)
    if not candles or len(candles) < 50:
        return None, None

    entry     = candles[-1]["c"]
    atr       = compute_atr(candles)
    score     = 0
    direction = None
    setups    = []

    bos = detect_bos_choch(candles)
    if bos:
        direction = bos["type"]
        score    += bos["score"]
        setups.append(bos["setup"])

    if not direction:
        return None, None

    sw = detect_liq_sweep(candles)
    if sw:
        d = "LONG" if sw["type"] == "BULL_SWEEP" else "SHORT"
        if d == direction:
            score += sw["score"]
            setups.append(sw["type"])

    for ob in reversed(detect_order_blocks(candles)):
        d = "LONG" if ob["type"] == "BULL" else "SHORT"
        if d == direction and ob["bot"]*0.998 <= entry <= ob["top"]*1.002:
            score += ob["score"]
            setups.append(f"OB_{ob['type']}")
            break

    for fvg in reversed(detect_fvg(candles)):
        d = "LONG" if fvg["type"] == "BULL" else "SHORT"
        if d == direction and fvg["bot"]*0.999 <= entry <= fvg["top"]*1.001:
            score += fvg["score"]
            setups.append(f"FVG_{fvg['type']}")
            break

    bb = detect_breaker_block(candles)
    if bb:
        d = "LONG" if bb["type"] == "BULL_BB" else "SHORT"
        if d == direction:
            score += bb["score"]
            setups.append(bb["type"])

    dt = detect_double_pattern(candles)
    if dt and dt["type"] == direction:
        score += dt["score"]
        setups.append(dt["setup"])

    if score < MIN_SCORE:
        return None, None

    # ── Claude AI — Analyse Fondamentale + Web Search
    ai = claude_analyze(symbol, direction, setups, score, volatility_24h)

    if ai.get("score_ai", 1) == 0:
        log(f"  🤖 Claude BLOQUE {symbol}: {ai.get('reason','')}")
        return None, None

    # ── Risk Management
    sl_dist = atr * SL_ATR_MULT
    if sl_dist <= 0 or entry <= 0:
        return None, None

    sl = entry - sl_dist if direction == "LONG" else entry + sl_dist
    tp = entry + sl_dist * TP_RATIO if direction == "LONG" else entry - sl_dist * TP_RATIO

    raw_qty = (RISK_USD / sl_dist) * LEVERAGE
    si      = get_sym_info(symbol)
    qty     = max(round_step(raw_qty, si["step"]), si["min_qty"])

    margin_needed = (qty * entry) / LEVERAGE
    if margin_needed > CAPITAL * 0.9:
        return None, None

    sig = {
        "symbol": symbol, "direction": direction,
        "entry": entry, "sl": sl, "tp": tp,
        "qty": qty, "score": score, "setups": setups,
        "atr": atr, "volatility_24h": volatility_24h
    }
    return sig, ai


# ═══════════════════════════════════════════════════════════════════
#  ██ GESTION DES POSITIONS
# ═══════════════════════════════════════════════════════════════════
def get_positions():
    data = bget("/fapi/v2/positionRisk", {}, signed=True)
    if not data:
        return []
    return [p for p in data if abs(float(p.get("positionAmt", 0))) > 0]


def get_current_price(symbol):
    data = bget("/fapi/v1/ticker/price", {"symbol": symbol})
    if data:
        return float(data.get("price", 0))
    return 0


def set_leverage_margin(symbol, lev):
    try:
        bpost("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
    except Exception:
        pass
    bpost("/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})


def cancel_open_orders(symbol):
    bpost("/fapi/v1/allOpenOrders", {"symbol": symbol})


def close_position(symbol, qty, direction):
    """Clôture une position au marché."""
    side = "SELL" if direction == "LONG" else "BUY"
    r = bpost("/fapi/v1/order", {
        "symbol": symbol, "side": side,
        "type": "MARKET", "quantity": qty,
        "positionSide": "BOTH",
        "reduceOnly": "true"
    })
    return r is not None


def place_order(sig, ai):
    sym  = sig["symbol"]
    side = "BUY" if sig["direction"] == "LONG" else "SELL"
    cside = "SELL" if side == "BUY" else "BUY"
    qty  = sig["qty"]
    si   = get_sym_info(sym)

    set_leverage_margin(sym, LEVERAGE)
    cancel_open_orders(sym)

    # Ordre d'entrée
    r = bpost("/fapi/v1/order", {
        "symbol": sym, "side": side,
        "type": "MARKET", "quantity": qty,
        "positionSide": "BOTH"
    })
    if not r:
        return False

    sl_p = price_str(sig["sl"], si["tick"])
    tp_p = price_str(sig["tp"], si["tick"])

    # Stop Loss
    bpost("/fapi/v1/order", {
        "symbol": sym, "side": cside,
        "type": "STOP_MARKET", "stopPrice": sl_p,
        "closePosition": "true", "positionSide": "BOTH"
    })

    # Take Profit
    bpost("/fapi/v1/order", {
        "symbol": sym, "side": cside,
        "type": "TAKE_PROFIT_MARKET", "stopPrice": tp_p,
        "closePosition": "true", "positionSide": "BOTH"
    })

    # Initialiser trailing data
    _trailing_data[sym] = {
        "highest": sig["entry"],
        "lowest":  sig["entry"],
        "atr":     sig["atr"],
        "direction": sig["direction"],
        "entry":   sig["entry"],
        "qty":     qty,
        "ai_rec":  ai.get("close_recommendation", "ATTENDRE_TP"),
        "sig":     sig,
        "ai":      ai
    }

    log(f"  ✅ {side} {qty} {sym} | SL:{sl_p} TP:{tp_p}")
    tg_signal(sig, ai)
    return True


# ═══════════════════════════════════════════════════════════════════
#  ██ TRAILING STOP LOGIC
# ═══════════════════════════════════════════════════════════════════
def update_trailing_stops(open_symbols):
    """
    Met à jour les trailing stops pour toutes les positions ouvertes.
    Décision de clôture basée sur:
    - Trailing Stop (SL suiveur)
    - Recommandation Claude AI
    - Objectif journalier atteint
    """
    global _daily_pnl, _daily_trades

    symbols_to_remove = []

    for symbol, td in list(_trailing_data.items()):
        if symbol not in open_symbols:
            symbols_to_remove.append(symbol)
            continue

        current_price = get_current_price(symbol)
        if current_price <= 0:
            continue

        direction = td["direction"]
        entry     = td["entry"]
        atr       = td["atr"]
        qty       = td["qty"]
        ai_rec    = td["ai_rec"]
        si        = get_sym_info(symbol)

        # Calcul PnL actuel
        if direction == "LONG":
            pnl_per_unit = current_price - entry
        else:
            pnl_per_unit = entry - current_price
        pnl_usd = pnl_per_unit * qty * LEVERAGE

        activation_dist = atr * TRAILING_ACTIVATION
        trailing_dist   = atr * TRAILING_DISTANCE_ATR

        should_close  = False
        close_reason  = ""

        # 1. Clôture si Claude recommande immédiatement
        if ai_rec == "CLOTURER_MAINTENANT" and pnl_usd > 0:
            should_close = True
            close_reason = "Claude AI: clôture recommandée"

        # 2. Trailing Stop — mettre à jour le highest/lowest
        if TRAILING_ENABLED:
            if direction == "LONG":
                if current_price > td["highest"]:
                    td["highest"] = current_price
                # Activer trailing si profit > activation_dist
                profit_dist = td["highest"] - entry
                if profit_dist >= activation_dist:
                    trail_level = td["highest"] - trailing_dist
                    if current_price <= trail_level and not should_close:
                        should_close = True
                        close_reason = f"Trailing SL déclenché @ {current_price:.4f}"
            else:
                if current_price < td["lowest"]:
                    td["lowest"] = current_price
                profit_dist = entry - td["lowest"]
                if profit_dist >= activation_dist:
                    trail_level = td["lowest"] + trailing_dist
                    if current_price >= trail_level and not should_close:
                        should_close = True
                        close_reason = f"Trailing SL déclenché @ {current_price:.4f}"

        # 3. Objectif journalier atteint → sécuriser les profits
        if _daily_pnl + pnl_usd >= DAILY_TARGET and pnl_usd > 0:
            should_close = True
            close_reason = f"🎯 Objectif journalier atteint (${_daily_pnl + pnl_usd:.2f})"

        if should_close:
            log(f"  🔄 Clôture {symbol} {direction} | PnL: ${pnl_usd:.2f} | {close_reason}")
            if close_position(symbol, qty, direction):
                cancel_open_orders(symbol)
                _daily_pnl   += pnl_usd
                _daily_trades += 1
                tg_trade_closed(symbol, direction, pnl_usd, close_reason, ai_rec)
                symbols_to_remove.append(symbol)

                if _daily_pnl >= DAILY_TARGET:
                    log(f"🎯 OBJECTIF JOURNALIER ATTEINT: ${_daily_pnl:.2f}")
                    tg_daily_summary()

    for s in symbols_to_remove:
        _trailing_data.pop(s, None)


# ═══════════════════════════════════════════════════════════════════
#  ██ RESET JOURNALIER
# ═══════════════════════════════════════════════════════════════════
def check_daily_reset():
    global _daily_pnl, _daily_trades, _daily_date
    today = date.today()
    if today != _daily_date:
        tg_daily_summary()
        _daily_pnl    = 0.0
        _daily_trades = 0
        _daily_date   = today
        log(f"📅 Nouveau jour: reset compteurs journaliers")



# ═══════════════════════════════════════════════════════════════════
#  ██ FLASK KEEP-ALIVE — Render Free Tier anti-sleep
# ═══════════════════════════════════════════════════════════════════
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return jsonify({
        "status": "running",
        "bot": "AlphaBot V7",
        "pnl_jour": round(_daily_pnl, 2),
        "objectif": DAILY_TARGET,
        "trades": _daily_trades,
        "heure": datetime.now().strftime("%H:%M:%S")
    })

@flask_app.route("/ping")
def ping():
    return "pong", 200

@flask_app.route("/status")
def status():
    pct = (_daily_pnl / DAILY_TARGET * 100) if DAILY_TARGET > 0 else 0
    return jsonify({
        "status":        "actif",
        "pnl_jour":      round(_daily_pnl, 2),
        "objectif":      DAILY_TARGET,
        "progression":   f"{pct:.1f}%",
        "trades_jour":   _daily_trades,
        "capital":       CAPITAL,
        "levier":        LEVERAGE,
        "trailing_sl":   TRAILING_ENABLED,
        "claude_ai":     USE_CLAUDE_AI,
        "timestamp":     datetime.now().isoformat()
    })

def start_keepalive():
    port = int(os.environ.get("PORT", 10000))
    t = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True
    )
    t.start()
    log(f"✅ Flask keep-alive démarré sur port {port}")
    log(f"   → Routes: / | /ping | /status")

# ═══════════════════════════════════════════════════════════════════
#  ██ MAIN LOOP
# ═══════════════════════════════════════════════════════════════════
def banner():
    ai_status = "✅ Activé + Web Search" if (USE_CLAUDE_AI and len(ANTHROPIC_API_KEY) > 20) else "⚠️  Configurez ANTHROPIC_API_KEY"
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║   AlphaBot V7 — SMC + Claude AI + Trailing SL + Objectif $7/jour    ║")
    print(f"║  Capital: ${CAPITAL}  |  Risque: ${RISK_USD}/trade  |  Levier: {LEVERAGE}x             ║")
    print(f"║  Scanner: Top {TOP_N} volatiles 24h  |  M1  |  Score min: {MIN_SCORE}         ║")
    print(f"║  Objectif: ${DAILY_TARGET}/jour  |  Max perte: ${DAILY_MAX_LOSS}/jour              ║")
    print(f"║  Trailing SL: {TRAILING_ACTIVATION}x ATR activation, {TRAILING_DISTANCE_ATR}x ATR distance          ║")
    print(f"║  Claude AI : {ai_status:<44}║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()


def main():
    banner()
    start_keepalive()  # Render keep-alive — DOIT rester vivant même si Binance KO

    # Retry Binance jusqu'à connexion (ne jamais quitter = Render ne redémarre pas)
    while not detect_binance_url():
        log("⏳ Binance inaccessible — retry dans 30s...")
        time.sleep(30)

    if not TG_CHAT_ID:
        auto_detect_chat_id(90)

    tg_welcome()

    scan_n  = 0
    sig_tot = 0

    while True:
        try:
            check_daily_reset()

            # Stop si perte journalière max atteinte — on dort 1h, on ne quitte pas
            if _daily_pnl <= -DAILY_MAX_LOSS:
                log(f"🛑 Perte max journalière atteinte: ${_daily_pnl:.2f}")
                tg_send(f"🛑 <b>Stop trading — Perte max atteinte: ${_daily_pnl:.2f}</b>")
                time.sleep(3600)
                continue

            # Vérifier que Binance est toujours accessible
            if not BASE_URL:
                log("⚠️ Binance perdu — reconnexion...")
                detect_binance_url()
                time.sleep(30)
                continue

            # Stop si objectif déjà atteint aujourd'hui
            if _daily_pnl >= DAILY_TARGET:
                log(f"🎯 Objectif atteint (${_daily_pnl:.2f}), surveillance uniquement")
                positions     = get_positions()
                open_symbols  = {p["symbol"] for p in positions}
                update_trailing_stops(open_symbols)
                time.sleep(SCAN_INTERVAL)
                continue

            scan_n += 1
            log(f"══════ SCAN #{scan_n} | PnL: ${_daily_pnl:.2f}/${DAILY_TARGET} {'═'*20}")

            positions    = get_positions()
            open_symbols = {p["symbol"] for p in positions}
            open_count   = len(positions)

            # Écouter les commandes Telegram (boutons, /menu, etc.)
            tg_get_chat_id()

            # Mettre à jour les trailing stops SILENCIEUSEMENT (pas de message Telegram)
            update_trailing_stops(open_symbols)

            log(f"📊 Positions: {open_count}/{MAX_TRADES}")

            if open_count >= MAX_TRADES:
                log("⚠️  Limite atteinte. Surveillance trailing stops...")
                time.sleep(SCAN_INTERVAL)
                continue

            slots = MAX_TRADES - open_count

            # Scanner les cryptos les plus volatiles
            volatile_pairs = get_top_volatile(TOP_N)
            volatile_dict  = {sym: vol for sym, vol in volatile_pairs}
            symbols        = [sym for sym, _ in volatile_pairs if sym not in open_symbols]

            log(f"🔍 Scanner: {[s for s, v in volatile_pairs[:5]]} (top 5 volatils)")

            signals = []
            for sym in symbols:
                vol = volatile_dict.get(sym, 0)
                sig, ai = analyze(sym, vol)
                if sig:
                    signals.append((sig, ai))
                    ai_score = ai.get("score_ai", 0) if ai else 0
                    log(f"   📡 {sig['direction']} {sym} | SMC:{sig['score']} + AI:{ai_score} | {sig['setups']}")
                time.sleep(0.3)

            # Trier par score total
            signals.sort(
                key=lambda x: x[0]["score"] + x[1].get("score_ai", 0),
                reverse=True
            )

            placed = 0
            for sig, ai in signals[:slots]:
                total = sig["score"] + ai.get("score_ai", 0)
                log(f"🚀 {sig['direction']} {sig['symbol']} (score total {total})")
                ok = place_order(sig, ai)
                if ok:
                    placed  += 1
                    sig_tot += 1
                time.sleep(0.5)

            if placed == 0 and not signals:
                log("💤 Aucun signal valide ce scan.")

            log(f"📈 Signaux session: {sig_tot}")

        except KeyboardInterrupt:
            log("🛑 Arrêt.")
            tg_daily_summary()
            tg_send("🛑 <b>AlphaBot V7 arrêté manuellement.</b>")
            break
        except Exception as e:
            import traceback
            log(f"[ERREUR] {e}")
            log(traceback.format_exc())
            time.sleep(10)  # Pause courte puis continue — ne jamais quitter

        log(f"⏳ Prochain scan dans {SCAN_INTERVAL}s...\n")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
