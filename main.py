

"""
main.py — AlphaBot SMC PRO (LIVE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sources réelles :
  • BTCUSD  → Binance REST API  (gratuit, sans compte)
  • XAUUSD  → yfinance GC=F    (gratuit, sans compte)
               + metals.live   (prix live spot)

requirements.txt :
  pandas
  numpy
  requests
  anthropic
  plotly
  dash
  yfinance

Variables d'environnement Render :
  ANTHROPIC_API_KEY
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import logging
import threading
import time
from datetime import datetime, timezone

import anthropic
import pandas as pd
import requests
import yfinance as yf
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("alphabot")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "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")
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN",    "8665812395:AAFO4BMTIrBCQJYVL8UytO028TcB1sDfgbI")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID",  "8666812395")

MARKETS = {
    "BTCUSD": {"source": "binance",  "binance_sym": "BTCUSDT", "digits": 1, "pip": 1,   "spread_max": 5},
    "XAUUSD": {"source": "yfinance", "yf_sym":      "GC=F",    "digits": 2, "pip": 0.1, "spread_max": 0.5},
}

TF_BINANCE  = {"M1":"1m","M5":"5m","M15":"15m","H1":"1h","H4":"4h"}
TF_YFINANCE = {"M1":"1m","M5":"5m","M15":"15m","H1":"1h","H4":"1h"}   # yfinance max intraday
TIMEFRAMES   = ["M1","M5","M15","H1","H4"]
CANDLE_COUNT = 120
REFRESH_INTERVAL_MS = 30_000   # 30s
TICK_INTERVAL_MS    =  5_000   # 5s  (metals.live rate-limit friendly)

DARK = {
    "bg":     "#0a0b0e", "panel":  "#0f1117",
    "border": "#1e2330", "accent": "#00d4aa",
    "bull":   "#00c896", "bear":   "#ff4d6d",
    "text":   "#8b95a8", "textHi": "#c8d0de",
}

MIN_SCORE = 75
MIN_RR    = 3.0


# ─── DONNÉES BINANCE ──────────────────────────────────────────────────────────

def get_binance_candles(symbol: str, tf: str, limit: int = CANDLE_COUNT) -> pd.DataFrame | None:
    interval = TF_BINANCE.get(tf, "15m")
    url = "https://api.binance.com/api/v3/klines"
    try:
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=8)
        r.raise_for_status()
        raw = r.json()
        df = pd.DataFrame(raw, columns=[
            "time","open","high","low","close","volume",
            "close_time","qav","trades","tbbav","tbqav","ignore",
        ])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        return df[["time","open","high","low","close","volume"]]
    except Exception as e:
        log.error(f"Binance candles error: {e}")
        return None


def get_binance_price(symbol: str) -> float | None:
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol}, timeout=5,
        )
        return float(r.json()["price"])
    except Exception as e:
        log.error(f"Binance price error: {e}")
        return None


# ─── DONNÉES GOLD via yfinance + metals.live ──────────────────────────────────

def get_yfinance_candles(symbol: str, tf: str, count: int = CANDLE_COUNT) -> pd.DataFrame | None:
    """Bougies Gold depuis Yahoo Finance (GC=F — Gold Futures). Gratuit, sans clé."""
    interval = TF_YFINANCE.get(tf, "15m")
    # H4 non dispo nativement — on utilise H1 et on resamble
    resample_h4 = (tf == "H4")
    fetch_interval = "1h" if resample_h4 else interval

    # Période : intraday limité à 60 jours max pour yfinance
    period_map = {"1m":"1d","5m":"5d","15m":"60d","1h":"60d"}
    period = period_map.get(fetch_interval, "60d")

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=fetch_interval, auto_adjust=True)
        if df is None or df.empty:
            log.error(f"yfinance: données vides pour {symbol} {tf}")
            return None

        df = df.reset_index()
        df = df.rename(columns={
            "Datetime": "time", "Date": "time",
            "Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"
        })
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df[["time","open","high","low","close","volume"]].dropna()

        # Resamble H1 → H4
        if resample_h4:
            df = df.set_index("time")
            df = df.resample("4h").agg({
                "open":"first","high":"max","low":"min","close":"last","volume":"sum"
            }).dropna().reset_index()

        return df.tail(count).reset_index(drop=True)

    except Exception as e:
        log.error(f"yfinance candles error: {e}")
        return None


def get_gold_price_live() -> float | None:
    """Prix spot Gold live depuis metals.live — gratuit, sans clé."""
    try:
        r = requests.get("https://metals.live/api/spot", timeout=6)
        r.raise_for_status()
        data = r.json()
        for item in data:
            if item.get("metal","").lower() == "gold":
                return float(item["price"])
    except Exception as e:
        log.error(f"metals.live error: {e}")

    # Fallback : dernier close yfinance si metals.live échoue
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        log.error(f"yfinance price fallback error: {e}")

    return None


# ─── DISPATCHER ───────────────────────────────────────────────────────────────

def get_candles(symbol: str, tf: str) -> pd.DataFrame | None:
    cfg = MARKETS[symbol]
    if cfg["source"] == "binance":
        return get_binance_candles(cfg["binance_sym"], tf)
    elif cfg["source"] == "yfinance":
        return get_yfinance_candles(cfg["yf_sym"], tf)
    return None


def get_price(symbol: str) -> float | None:
    cfg = MARKETS[symbol]
    if cfg["source"] == "binance":
        return get_binance_price(cfg["binance_sym"])
    elif cfg["source"] == "yfinance":
        return get_gold_price_live()
    return None


# ─── DÉTECTION SMC ────────────────────────────────────────────────────────────

def detect_trend(df: pd.DataFrame) -> str:
    if len(df) < 20:
        return "NEUTRE"
    first = df["close"].iloc[:10].mean()
    last  = df["close"].iloc[-10:].mean()
    diff  = (last - first) / first
    if diff >  0.003: return "BULLISH"
    if diff < -0.003: return "BEARISH"
    return "NEUTRE"


def detect_bos_choch(df: pd.DataFrame) -> dict:
    highs = df["high"].values
    lows  = df["low"].values
    n = len(df)
    bos, choch = None, None

    for i in range(2, n - 1):
        if highs[i] > max(highs[max(0,i-5):i]):
            bos = f"BOS BULL @ {highs[i]:.5g}"
        if lows[i] < min(lows[max(0,i-5):i]):
            bos = f"BOS BEAR @ {lows[i]:.5g}"
        if i > 5:
            was_bull = highs[i-3] > highs[i-6]
            now_bear = lows[i] < lows[i-3]
            if was_bull and now_bear:
                choch = f"CHoCH BEAR @ {lows[i]:.5g}"
            was_bear = lows[i-3] < lows[i-6]
            now_bull = highs[i] > highs[i-3]
            if was_bear and now_bull:
                choch = f"CHoCH BULL @ {highs[i]:.5g}"

    return {"bos": bos, "choch": choch}


def detect_smc(df: pd.DataFrame) -> dict:
    ob, fvg, bb, sd = [], [], [], []
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    t = df["time"].values
    n = len(df)

    for i in range(3, n - 2):
        body   = abs(c[i] - o[i])
        n_bull = c[i+1] - o[i+1]
        n_bear = o[i+1] - c[i+1]

        # Order Blocks
        if c[i] < o[i] and n_bull > body * 1.4:
            ob.append({"low": l[i], "high": h[i], "dir":"bull", "t0": t[i], "t1": t[-1]})
        if c[i] > o[i] and n_bear > body * 1.4:
            ob.append({"low": l[i], "high": h[i], "dir":"bear", "t0": t[i], "t1": t[-1]})

        # Fair Value Gaps
        gap_bull = l[i+1] - h[i-1]
        gap_bear = l[i-1] - h[i+1]
        if gap_bull > 0:
            fvg.append({"low": h[i-1], "high": l[i+1], "dir":"bull", "t0": t[i-1], "t1": t[-1]})
        if gap_bear > 0:
            fvg.append({"low": h[i+1], "high": l[i-1], "dir":"bear", "t0": t[i-1], "t1": t[-1]})

        # Breaker Blocks
        if i > 5:
            j = i - 4
            if c[j] < o[j] and c[i] > h[j]:
                bb.append({"low": l[j], "high": h[j], "dir":"bull", "t0": t[j], "t1": t[-1]})
            if c[j] > o[j] and c[i] < l[j]:
                bb.append({"low": l[j], "high": h[j], "dir":"bear", "t0": t[j], "t1": t[-1]})

        # Supply & Demand
        if i > 2 and i < n - 3:
            consol = abs(h[i-1] - l[i-2]) < abs(h[i] - l[i]) * 0.5
            if consol and c[i] > o[i]:
                sd.append({"low": min(l[i-2],l[i-1]), "high": max(h[i-2],h[i-1]),
                           "dir":"bull", "t0": t[i-2], "t1": t[-1]})
            if consol and c[i] < o[i]:
                sd.append({"low": min(l[i-2],l[i-1]), "high": max(h[i-2],h[i-1]),
                           "dir":"bear", "t0": t[i-2], "t1": t[-1]})

    return {
        "order_blocks":   ob[-4:],
        "fvg":            fvg[-4:],
        "breaker_blocks": bb[-2:],
        "supply_demand":  sd[-3:],
    }


def score_signal(df: pd.DataFrame, zones: dict, trend: str) -> dict | None:
    if len(df) < 10:
        return None

    last  = df["close"].iloc[-1]
    score = 0
    entry = None
    sl    = None
    tp    = None
    direction = None

    for z in reversed(zones.get("order_blocks", [])):
        in_zone = z["low"] <= last <= z["high"]
        aligned = (z["dir"]=="bull" and trend=="BULLISH") or (z["dir"]=="bear" and trend=="BEARISH")

        if in_zone:
            score += 30
            direction = z["dir"]
            entry = last

        if aligned:
            score += 20

        if in_zone and aligned:
            pip_size = df["high"].std() * 0.1
            if z["dir"] == "bull":
                sl = z["low"]  - pip_size
                tp = last + (last - sl) * MIN_RR
            else:
                sl = z["high"] + pip_size
                tp = last - (sl - last) * MIN_RR
            break

    for z in zones.get("fvg", []):
        if z["low"] <= last <= z["high"]:
            score += 15

    for z in zones.get("breaker_blocks", []):
        if z["low"] <= last <= z["high"]:
            score += 10

    for z in zones.get("supply_demand", []):
        if z["low"] <= last <= z["high"]:
            score += 10

    sess = get_session()
    if sess in ("LONDON","NEW YORK"):
        score += 15

    if score < MIN_SCORE or entry is None or sl is None:
        return None

    rr = abs(tp - entry) / abs(entry - sl) if sl and tp else 0
    if rr < MIN_RR:
        return None

    return {"score": score, "direction": direction, "entry": entry,
            "sl": sl, "tp": tp, "rr": round(rr, 1)}


# ─── SESSION ──────────────────────────────────────────────────────────────────

def get_session() -> str:
    h = datetime.now(timezone.utc).hour
    if  0 <= h <  8: return "ASIA"
    if  8 <= h < 12: return "LONDON"
    if 12 <= h < 17: return "NEW YORK"
    if 17 <= h < 21: return "NY LATE"
    return "HORS SESSION"


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(text: str) -> bool:
    """Envoie un message Telegram. Retourne True si succès."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram: TOKEN ou CHAT_ID manquant — message non envoyé")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            log.info(f"Telegram ✓ message_id={data['result']['message_id']}")
            return True
        else:
            log.error(f"Telegram erreur HTTP {resp.status_code}: {data}")
            return False
    except Exception as e:
        log.error(f"Telegram exception: {e}")
        return False


def format_signal(symbol: str, sig: dict, session: str, digits: int) -> str:
    arrow = "📈" if sig["direction"]=="bull" else "📉"
    d     = "BUY" if sig["direction"]=="bull" else "SELL"
    return (
        f"{arrow} *SIGNAL SMC — {symbol}*\n"
        f"Direction : *{d}*\n"
        f"Entrée    : `{sig['entry']:.{digits}f}`\n"
        f"SL        : `{sig['sl']:.{digits}f}`\n"
        f"TP        : `{sig['tp']:.{digits}f}`\n"
        f"RR        : 1:{sig['rr']}\n"
        f"Score     : {sig['score']}/100\n"
        f"Session   : {session}\n"
        f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}"
    )


# ─── GRAPHIQUE ────────────────────────────────────────────────────────────────

ZONE_STYLES = {
    "order_blocks":   {"bull":("rgba(0,200,150,0.15)",  DARK["bull"]), "bear":("rgba(255,77,109,0.15)",  DARK["bear"]), "label":"OB"},
    "fvg":            {"bull":("rgba(100,180,255,0.12)","#64b4ff"),    "bear":("rgba(255,160,60,0.12)",  "#ffa03c"),    "label":"FVG"},
    "breaker_blocks": {"bull":("rgba(200,100,255,0.15)","#c864ff"),    "bear":("rgba(200,100,255,0.15)", "#c864ff"),    "label":"BB"},
    "supply_demand":  {"bull":("rgba(0,255,200,0.08)",  "#00ffc8"),    "bear":("rgba(255,80,80,0.08)",   "#ff5050"),    "label":"S/D"},
}


def build_figure(df: pd.DataFrame, zones: dict, show: dict,
                 symbol: str, signal: dict | None) -> go.Figure:
    fig = go.Figure()
    digits = MARKETS[symbol]["digits"]

    fig.add_trace(go.Candlestick(
        x=df["time"],
        open=df["open"], high=df["high"],
        low=df["low"],   close=df["close"],
        name=symbol,
        increasing_fillcolor=DARK["bull"], increasing_line_color=DARK["bull"],
        decreasing_fillcolor=DARK["bear"], decreasing_line_color=DARK["bear"],
        whiskerwidth=0.3, showlegend=False,
    ))

    for zone_key, style in ZONE_STYLES.items():
        if not show.get(zone_key, True):
            continue
        for z in zones.get(zone_key, []):
            fill, line = style[z["dir"]]
            fig.add_shape(type="rect",
                x0=df["time"].iloc[0], x1=df["time"].iloc[-1],
                y0=z["low"], y1=z["high"],
                fillcolor=fill, line=dict(color=line, width=1, dash="dot"),
                layer="below",
            )
            fig.add_annotation(
                x=df["time"].iloc[-1], y=(z["high"]+z["low"])/2,
                text=f"{style['label']} {'▲' if z['dir']=='bull' else '▼'}",
                showarrow=False,
                font=dict(size=9, color=line, family="Courier New"),
                xanchor="left",
                bgcolor="rgba(10,11,14,0.75)",
            )

    if signal:
        color = DARK["bull"] if signal["direction"]=="bull" else DARK["bear"]
        for price, label, dash in [
            (signal["entry"], f"ENTRY {signal['entry']:.{digits}f}", "solid"),
            (signal["sl"],    f"SL    {signal['sl']:.{digits}f}",    "dot"),
            (signal["tp"],    f"TP    {signal['tp']:.{digits}f}",    "dash"),
        ]:
            fig.add_hline(y=price, line_color=color, line_dash=dash, line_width=1.5,
                          annotation_text=f" {label}",
                          annotation_position="right",
                          annotation_font=dict(size=9, color=color, family="Courier New"))

    last = df["close"].iloc[-1]
    lc   = DARK["bull"] if df["close"].iloc[-1] >= df["open"].iloc[-1] else DARK["bear"]
    fig.add_hline(y=last, line_dash="dot", line_color=lc, line_width=1,
                  annotation_text=f" {last:.{digits}f}",
                  annotation_position="right",
                  annotation_font=dict(size=10, color=lc, family="Courier New"))

    fig.update_layout(
        paper_bgcolor=DARK["bg"], plot_bgcolor=DARK["bg"],
        font=dict(family="Courier New", color=DARK["text"], size=10),
        margin=dict(l=8, r=95, t=10, b=30),
        xaxis=dict(gridcolor=DARK["border"], showgrid=True,
                   rangeslider=dict(visible=False), type="date",
                   tickfont=dict(size=9), color=DARK["text"]),
        yaxis=dict(gridcolor=DARK["border"], showgrid=True, side="right",
                   tickfont=dict(size=9), color=DARK["text"]),
        dragmode="pan", hovermode="x unified",
        hoverlabel=dict(bgcolor=DARK["panel"],
                        font=dict(family="Courier New", size=10, color=DARK["textHi"])),
    )
    return fig


# ─── CLAUDE AI ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es AlphaBot-AI, analyste SMC expert.
Analyse concise et professionnelle en français.
Pas de conseil financier — analyse technique objective uniquement."""


def analyse_claude(symbol: str, tf: str, trend: str, structure: dict,
                   zones: dict, price: float, session: str,
                   signal: dict | None, digits: int) -> str:
    if not ANTHROPIC_API_KEY:
        return "❌ ANTHROPIC_API_KEY non défini dans les variables d'environnement Render."

    def fmt(items, label):
        return "\n".join(
            f"  {label} [{z['dir'].upper()}] : {z['low']:.{digits}f}–{z['high']:.{digits}f}"
            for z in items[-2:]
        ) if items else ""

    zones_txt = "\n".join(filter(None, [
        fmt(zones.get("order_blocks",   []), "Order Block"),
        fmt(zones.get("fvg",            []), "FVG"),
        fmt(zones.get("breaker_blocks", []), "Breaker Block"),
        fmt(zones.get("supply_demand",  []), "Supply/Demand"),
    ])) or "  Aucune zone SMC détectée"

    sig_txt = (
        f"\nSetup détecté : {signal['direction'].upper()} | "
        f"Entry {signal['entry']:.{digits}f} | "
        f"SL {signal['sl']:.{digits}f} | "
        f"TP {signal['tp']:.{digits}f} | "
        f"RR 1:{signal['rr']} | Score {signal['score']}"
        if signal else "\nAucun setup SMC actif (score < 75 ou RR < 1:3)"
    )

    prompt = f"""
Symbole : {symbol} | TF : {tf} | Session : {session}
Prix actuel (RÉEL) : {price:.{digits}f}
Tendance H4 : {trend}
Structure : BOS={structure.get('bos','—')} | CHoCH={structure.get('choch','—')}

=== ZONES SMC RÉELLES ===
{zones_txt}
{sig_txt}

Fournis une analyse structurée en 5 points :
1. BIAS global (Bullish/Bearish/Neutre) + justification
2. Zone d'attaque prioritaire (fourchette précise)
3. Scénario de réaction du prix attendu
4. Confirmation d'entrée à attendre (bougie, retest…)
5. Risque principal / invalidation du setup
Maximum 200 mots. Précis, professionnel.
"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role":"user","content":prompt}],
        )
        return resp.content[0].text.strip()
    except anthropic.AuthenticationError:
        return "❌ Clé API Anthropic invalide."
    except anthropic.RateLimitError:
        return "⏳ Rate limit Anthropic — réessaie dans quelques secondes."
    except Exception as e:
        return f"❌ Erreur Claude : {e}"


# ─── LAYOUT ───────────────────────────────────────────────────────────────────

app = Dash(__name__, title="AlphaBot SMC LIVE")


def sym_btn(sym, selected):
    active = sym == selected
    cfg    = MARKETS[sym]
    src_label = " YF" if cfg["source"]=="yfinance" else " BNC"
    return html.Button(
        [sym, html.Span(src_label, style={"fontSize":8,"opacity":0.6,"marginLeft":3})],
        id={"type":"sym-btn","index":sym}, n_clicks=0,
        style={
            "padding":"4px 11px","borderRadius":4,"cursor":"pointer",
            "border":f"1px solid {DARK['accent'] if active else DARK['border']}",
            "background":"rgba(0,212,170,0.13)" if active else "transparent",
            "color": DARK["accent"] if active else DARK["text"],
            "fontFamily":"Courier New,monospace","fontSize":11,
        },
    )


def tf_btn(tf, selected):
    active = tf == selected
    return html.Button(tf, id={"type":"tf-btn","index":tf}, n_clicks=0, style={
        "padding":"4px 9px","borderRadius":4,"cursor":"pointer",
        "border":f"1px solid {'#4a8fff' if active else DARK['border']}",
        "background":"rgba(74,143,255,0.18)" if active else "transparent",
        "color":"#4a8fff" if active else DARK["text"],
        "fontFamily":"Courier New,monospace","fontSize":11,
    })


def zone_toggle(key, label, color):
    return dcc.Checklist(
        id=f"tog-{key}",
        options=[{"label":f" {label}","value":key}],
        value=[key],
        labelStyle={
            "color":color,"fontSize":10,"fontFamily":"Courier New,monospace",
            "border":f"1px solid {color}","background":f"{color}18",
            "padding":"3px 9px","borderRadius":3,"cursor":"pointer","marginRight":6,
        },
    )


app.layout = html.Div([
    dcc.Store(id="s-symbol",      data="BTCUSD"),
    dcc.Store(id="s-tf",          data="M15"),
    dcc.Store(id="s-candles",     data=None),
    dcc.Store(id="s-zones",       data=None),
    dcc.Store(id="s-trend",       data="NEUTRE"),
    dcc.Store(id="s-struct",      data={}),
    dcc.Store(id="s-signal",      data=None),
    dcc.Store(id="s-price",       data=None),
    dcc.Store(id="s-alerts",      data=[]),
    dcc.Store(id="s-last-signal", data=None),   # clé anti-doublon Telegram

    dcc.Interval(id="iv-candles", interval=REFRESH_INTERVAL_MS, n_intervals=0),
    dcc.Interval(id="iv-tick",    interval=TICK_INTERVAL_MS,    n_intervals=0),

    # ── HEADER ────────────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Span("α", style={
                "width":26,"height":26,"borderRadius":5,"display":"inline-flex",
                "alignItems":"center","justifyContent":"center","fontWeight":"bold",
                "fontSize":13,"color":"#000",
                "background":"linear-gradient(135deg,#00d4aa,#0077ff)","marginRight":10,
            }),
            html.Span("ALPHABOT ", style={"fontWeight":"bold","letterSpacing":2,
                                          "color":DARK["accent"],"fontSize":13}),
            html.Span("SMC  LIVE", style={"color":DARK["text"],"fontSize":13}),
        ], style={"display":"flex","alignItems":"center"}),

        html.Div(id="sym-buttons",
                 children=[sym_btn(s,"BTCUSD") for s in MARKETS],
                 style={"display":"flex","gap":5}),

        html.Div(id="tf-buttons",
                 children=[tf_btn(t,"M15") for t in TIMEFRAMES],
                 style={"display":"flex","gap":3}),

        html.Div(id="live-price"),
        html.Div(id="session-badge"),
        html.Div(id="source-badge"),
    ], style={
        "display":"flex","alignItems":"center","gap":18,"padding":"10px 18px",
        "borderBottom":f"1px solid {DARK['border']}","background":DARK["panel"],
        "flexShrink":0,
    }),

    # ── BODY ──────────────────────────────────────────────────────────────────
    html.Div([

        # Chart column
        html.Div([
            html.Div([
                html.Span("ZONES:", style={"fontSize":10,"color":DARK["text"],"marginRight":8}),
                zone_toggle("order_blocks","Order Block",DARK["bull"]),
                zone_toggle("fvg","FVG","#64b4ff"),
                zone_toggle("breaker_blocks","Breaker Block","#c864ff"),
                zone_toggle("supply_demand","Supply/Demand","#00ffc8"),
                html.Button("↻ REFRESH", id="btn-refresh", n_clicks=0, style={
                    "marginLeft":"auto","padding":"3px 12px","borderRadius":3,
                    "border":f"1px solid {DARK['border']}","background":"transparent",
                    "color":DARK["text"],"cursor":"pointer","fontSize":10,
                    "fontFamily":"Courier New,monospace",
                }),
            ], style={"display":"flex","alignItems":"center","padding":"7px 14px",
                      "borderBottom":f"1px solid {DARK['border']}","flexShrink":0}),

            html.Div([
                html.Span("TREND H4:", style={"color":DARK["text"],"fontSize":10}),
                html.Span(id="trend-lbl",style={"fontWeight":"bold","fontSize":10}),
                html.Span(id="struct-lbl",style={"color":DARK["text"],"fontSize":10,"marginLeft":14}),
                html.Span(id="signal-lbl",style={"fontSize":10,"marginLeft":14}),
            ], style={"display":"flex","alignItems":"center","gap":10,"padding":"5px 14px",
                      "borderBottom":f"1px solid {DARK['border']}","flexShrink":0}),

            dcc.Graph(id="chart", config={"scrollZoom":True,"displayModeBar":True,
                      "modeBarButtonsToRemove":["autoScale2d","lasso2d","select2d"]},
                      style={"flex":1,"minHeight":0}),

        ], style={"flex":1,"display":"flex","flexDirection":"column","minWidth":0}),

        # Right panel
        html.Div([
            html.Div(id="zones-list", style={
                "padding":"12px 14px","borderBottom":f"1px solid {DARK['border']}",
                "fontSize":10,"lineHeight":"1.9","maxHeight":230,"overflowY":"auto",
            }),

            html.Div([
                html.Button("🧠  ANALYSE CLAUDE AI", id="btn-ia", n_clicks=0, style={
                    "width":"100%","padding":"11px","borderRadius":5,"cursor":"pointer",
                    "border":f"1px solid {DARK['accent']}",
                    "background":"linear-gradient(135deg,rgba(0,212,170,0.18),rgba(0,119,255,0.18))",
                    "color":DARK["accent"],"fontSize":11,
                    "fontFamily":"Courier New,monospace","letterSpacing":2,"fontWeight":"bold",
                }),
            ], style={"padding":"10px 14px","borderBottom":f"1px solid {DARK['border']}"}),

            # ── BOUTON TEST TELEGRAM ──────────────────────────────────────────
            html.Div([
                html.Button("📨  TEST TELEGRAM", id="btn-tg-test", n_clicks=0, style={
                    "width":"100%","padding":"8px","borderRadius":5,"cursor":"pointer",
                    "border":"1px solid #4a8fff",
                    "background":"rgba(74,143,255,0.10)",
                    "color":"#4a8fff","fontSize":10,
                    "fontFamily":"Courier New,monospace","letterSpacing":2,
                }),
                html.Div(id="tg-test-result", style={
                    "marginTop":5,"fontSize":9,"color":DARK["text"],
                    "fontFamily":"Courier New,monospace","minHeight":14,
                }),
            ], style={"padding":"8px 14px","borderBottom":f"1px solid {DARK['border']}"}),

            dcc.Loading(type="circle", color=DARK["accent"], children=
                html.Div(id="ia-output", style={
                    "flex":1,"padding":"12px 14px","overflowY":"auto",
                    "fontSize":10,"lineHeight":"1.9","color":DARK["textHi"],
                    "whiteSpace":"pre-wrap","fontFamily":"Courier New,monospace",
                }),
            ),

            html.Div([
                html.Div("▸ SIGNAUX DÉTECTÉS", style={"color":DARK["accent"],"fontSize":9,
                         "letterSpacing":2,"marginBottom":6}),
                html.Div(id="alerts-log", style={"fontSize":9,"color":DARK["text"],
                         "lineHeight":"1.7","maxHeight":100,"overflowY":"auto"}),
            ], style={"padding":"10px 14px","borderTop":f"1px solid {DARK['border']}"}),

        ], style={"width":330,"borderLeft":f"1px solid {DARK['border']}",
                  "display":"flex","flexDirection":"column","overflow":"hidden","flexShrink":0}),

    ], style={"display":"flex","flex":1,"overflow":"hidden"}),

], style={"background":DARK["bg"],"minHeight":"100vh","fontFamily":"Courier New,monospace",
          "color":DARK["textHi"],"display":"flex","flexDirection":"column","overflow":"hidden"})


# ─── CALLBACKS ────────────────────────────────────────────────────────────────

# FIX : mise à jour visuelle des boutons symbole quand la sélection change
@app.callback(
    Output("sym-buttons","children"),
    Input("s-symbol","data"),
)
def cb_sym_buttons(symbol):
    return [sym_btn(s, symbol) for s in MARKETS]


# FIX : mise à jour visuelle des boutons timeframe quand la sélection change
@app.callback(
    Output("tf-buttons","children"),
    Input("s-tf","data"),
)
def cb_tf_buttons(tf):
    return [tf_btn(t, tf) for t in TIMEFRAMES]


@app.callback(
    Output("s-symbol","data"),
    [Input({"type":"sym-btn","index":s},"n_clicks") for s in MARKETS],
    prevent_initial_call=True,
)
def cb_symbol(*_):
    ctx = callback_context
    if not ctx.triggered: raise PreventUpdate
    return ctx.triggered[0]["prop_id"].split('"index":"')[1].split('"')[0]


@app.callback(
    Output("s-tf","data"),
    [Input({"type":"tf-btn","index":t},"n_clicks") for t in TIMEFRAMES],
    prevent_initial_call=True,
)
def cb_tf(*_):
    ctx = callback_context
    if not ctx.triggered: raise PreventUpdate
    return ctx.triggered[0]["prop_id"].split('"index":"')[1].split('"')[0]


@app.callback(
    Output("s-candles",     "data"),
    Output("s-zones",       "data"),
    Output("s-trend",       "data"),
    Output("s-struct",      "data"),
    Output("s-signal",      "data"),
    Output("s-alerts",      "data"),       # FIX : maintenant mis à jour
    Output("s-last-signal", "data"),       # FIX : anti-doublon Telegram
    Input("s-symbol",       "data"),
    Input("s-tf",           "data"),
    Input("iv-candles",     "n_intervals"),
    Input("btn-refresh",    "n_clicks"),
    State("s-alerts",       "data"),
    State("s-last-signal",  "data"),
)
def cb_load_candles(symbol, tf, _iv, _btn, alerts, last_signal_key):
    df = get_candles(symbol, tf)

    if df is None or df.empty:
        log.warning(f"Pas de données pour {symbol} {tf}")
        raise PreventUpdate

    zones   = detect_smc(df)
    trend   = detect_trend(df)
    struct  = detect_bos_choch(df)
    signal  = score_signal(df, zones, trend)

    alerts = list(alerts or [])

    if signal:
        sess = get_session()
        digits = MARKETS[symbol]["digits"]

        # Clé unique pour éviter d'envoyer Telegram à chaque refresh (30s)
        # On identifie un signal par : symbole + TF + direction + entry arrondi
        sig_key = f"{symbol}_{tf}_{signal['direction']}_{signal['entry']:.{digits}f}"

        if sig_key != last_signal_key:
            msg = format_signal(symbol, signal, sess, digits)
            threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
            last_signal_key = sig_key
            log.info(f"Nouveau signal Telegram envoyé : {sig_key}")

        # Ajout au log d'alertes affiché dans le panel
        ts = datetime.utcnow().strftime("%H:%M")
        direction_label = "BUY" if signal["direction"] == "bull" else "SELL"
        alert_line = f"[{ts}] {symbol} {tf} {direction_label} | Score {signal['score']} | RR 1:{signal['rr']}"
        if not alerts or alerts[-1] != alert_line:
            alerts.append(alert_line)
            alerts = alerts[-20:]  # garder les 20 derniers

    return (
        df.to_json(orient="records", date_format="iso"),
        zones,
        trend,
        struct,
        signal,
        alerts,
        last_signal_key,
    )


@app.callback(
    Output("s-price",    "data"),
    Output("live-price", "children"),
    Input("iv-tick",     "n_intervals"),
    State("s-symbol",    "data"),
    State("s-price",     "data"),
)
def cb_tick(_, symbol, prev_price):
    price = get_price(symbol)
    if price is None:
        raise PreventUpdate

    m      = MARKETS[symbol]
    is_up  = (price >= prev_price) if prev_price else True
    color  = DARK["bull"] if is_up else DARK["bear"]
    arrow  = "▲" if is_up else "▼"

    widget = html.Div([
        html.Span(f"{arrow} {price:.{m['digits']}f}",
                  style={"fontSize":13,"fontWeight":"bold","color":color}),
    ], style={
        "padding":"4px 14px","borderRadius":4,
        "border":f"1px solid {color}",
        "background":"rgba(0,200,150,0.08)" if is_up else "rgba(255,77,109,0.08)",
    })
    return price, widget


@app.callback(
    Output("session-badge","children"),
    Output("source-badge", "children"),
    Input("iv-tick","n_intervals"),
    State("s-symbol","data"),
)
def cb_badges(_, symbol):
    sess  = get_session()
    sc    = DARK["accent"] if sess != "HORS SESSION" else "#ff8c42"
    src   = MARKETS[symbol]["source"].upper()
    src_c = "#4a8fff" if src=="BINANCE" else "#ffa03c"

    sess_badge = html.Span(sess, style={
        "fontSize":10,"color":sc,"border":f"1px solid {sc}",
        "padding":"3px 9px","borderRadius":3,"letterSpacing":1,
    })
    src_badge = html.Span(f"● {src}", style={
        "fontSize":9,"color":src_c,
        "border":f"1px solid {src_c}",
        "padding":"2px 7px","borderRadius":3,"letterSpacing":1,
    })
    return sess_badge, src_badge


@app.callback(
    Output("chart",      "figure"),
    Output("trend-lbl",  "children"),
    Output("trend-lbl",  "style"),
    Output("struct-lbl", "children"),
    Output("signal-lbl", "children"),
    Output("signal-lbl", "style"),
    Output("zones-list", "children"),
    Output("alerts-log", "children"),
    Input("s-candles",   "data"),
    Input("s-zones",     "data"),
    Input("s-trend",     "data"),
    Input("s-struct",    "data"),
    Input("s-signal",    "data"),
    Input("s-alerts",    "data"),
    Input("tog-order_blocks",   "value"),
    Input("tog-fvg",            "value"),
    Input("tog-breaker_blocks", "value"),
    Input("tog-supply_demand",  "value"),
    State("s-symbol","data"),
    State("s-tf",    "data"),
)
def cb_chart(candles_json, zones, trend, struct, signal, alerts,
             tog_ob, tog_fvg, tog_bb, tog_sd, symbol, tf):
    if not candles_json or not zones:
        raise PreventUpdate

    df  = pd.read_json(candles_json, orient="records")
    show= {"order_blocks":bool(tog_ob),"fvg":bool(tog_fvg),
           "breaker_blocks":bool(tog_bb),"supply_demand":bool(tog_sd)}
    fig = build_figure(df, zones, show, symbol, signal)
    digits = MARKETS[symbol]["digits"]

    tc = DARK["bull"] if trend=="BULLISH" else DARK["bear"] if trend=="BEARISH" else "#ffa03c"
    ta = "▲" if trend=="BULLISH" else "▼" if trend=="BEARISH" else "→"
    trend_style = {"fontWeight":"bold","letterSpacing":1,"color":tc,"fontSize":10}

    s_parts = []
    if struct.get("bos"):   s_parts.append(struct["bos"])
    if struct.get("choch"): s_parts.append(struct["choch"])
    struct_txt = "  |  ".join(s_parts) if s_parts else "Structure : —"

    if signal:
        sc = DARK["bull"] if signal["direction"]=="bull" else DARK["bear"]
        sig_txt  = f"✅ SETUP {signal['direction'].upper()} | Score {signal['score']} | RR 1:{signal['rr']}"
        sig_style = {"color":sc,"fontWeight":"bold","fontSize":10}
    else:
        sig_txt  = "Pas de setup actif"
        sig_style = {"color":DARK["text"],"fontSize":10}

    rows = [html.Div("▸ ZONES ACTIVES",style={
        "color":DARK["accent"],"letterSpacing":2,"marginBottom":7,
        "fontSize":9,"borderBottom":f"1px solid {DARK['border']}","paddingBottom":5,
    })]

    def add_rows(items, label, color_bull, color_bear):
        for z in items:
            c = color_bull if z["dir"]=="bull" else color_bear
            rows.append(html.Div([
                html.Span(f"{label} {'▲' if z['dir']=='bull' else '▼'}",
                          style={"color":c,"minWidth":135}),
                html.Span(f"{z['low']:.{digits}f} – {z['high']:.{digits}f}",
                          style={"color":DARK["text"]}),
            ],style={"display":"flex","justifyContent":"space-between","padding":"1px 0"}))

    add_rows(zones.get("order_blocks",  []), "Order Block",    DARK["bull"], DARK["bear"])
    add_rows(zones.get("fvg",          []), "FVG",             "#64b4ff",    "#ffa03c")
    add_rows(zones.get("breaker_blocks",[]), "Breaker Block",  "#c864ff",    "#c864ff")
    add_rows(zones.get("supply_demand", []), "Supply/Demand",  "#00ffc8",    "#ff5050")

    if len(rows) == 1:
        rows.append(html.Div("Aucune zone détectée",style={"color":DARK["text"]}))

    alert_rows = [html.Div(a, style={"padding":"1px 0"}) for a in (alerts or [])[-8:]] or \
                 [html.Div("Aucun signal depuis le lancement",style={"color":DARK["border"]})]

    return fig, f"{ta} {trend}", trend_style, struct_txt, sig_txt, sig_style, rows, alert_rows


@app.callback(
    Output("ia-output","children"),
    Input("btn-ia","n_clicks"),
    State("s-candles","data"),
    State("s-zones",  "data"),
    State("s-trend",  "data"),
    State("s-struct", "data"),
    State("s-signal", "data"),
    State("s-price",  "data"),
    State("s-symbol", "data"),
    State("s-tf",     "data"),
    prevent_initial_call=True,
)
def cb_ia(n, candles_json, zones, trend, struct, signal, price, symbol, tf):
    if not n or not candles_json:
        raise PreventUpdate
    df = pd.read_json(candles_json, orient="records")
    p  = price or df["close"].iloc[-1]
    m  = MARKETS[symbol]
    r  = analyse_claude(symbol, tf, trend, struct or {}, zones or {},
                        p, get_session(), signal, m["digits"])
    return html.Div([
        html.Div(f"▸ {symbol} {tf} — {get_session()} — {datetime.utcnow().strftime('%H:%M UTC')}",
                 style={"color":DARK["accent"],"letterSpacing":2,"marginBottom":10,
                        "fontSize":9,"borderBottom":f"1px solid {DARK['border']}","paddingBottom":5}),
        html.Div(r, style={"whiteSpace":"pre-wrap","lineHeight":"1.9"}),
    ])


# ─── CALLBACK TEST TELEGRAM ───────────────────────────────────────────────────

@app.callback(
    Output("tg-test-result","children"),
    Output("tg-test-result","style"),
    Input("btn-tg-test","n_clicks"),
    prevent_initial_call=True,
)
def cb_tg_test(n):
    if not n:
        raise PreventUpdate

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return ("❌ TOKEN ou CHAT_ID manquant dans les variables Render",
                {"color":DARK["bear"],"fontSize":9,"fontFamily":"Courier New,monospace","marginTop":5})

    msg = (
        "🧪 *AlphaBot SMC — TEST*\n"
        f"Connexion Telegram OK ✅\n"
        f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}"
    )
    ok = send_telegram(msg)
    if ok:
        return ("✅ Message envoyé !",
                {"color":DARK["bull"],"fontSize":9,"fontFamily":"Courier New,monospace","marginTop":5})
    else:
        return ("❌ Échec — vérifie TOKEN et CHAT_ID dans les logs Render",
                {"color":DARK["bear"],"fontSize":9,"fontFamily":"Courier New,monospace","marginTop":5})


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY manquant — bouton Claude AI désactivé")
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN manquant — alertes Telegram désactivées")

    print("=" * 55)
    print("  AlphaBot SMC PRO — LIVE RÉEL")
    print("  BTC  : Binance API  (gratuit, sans compte)")
    print("  GOLD : yfinance GC=F + metals.live (gratuit)")
    print("=" * 55)

    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host="0.0.0.0", port=port)

