"""
main.py — AlphaBot SMC PRO (Leader ODG)
Telegram bot + auto-scanner 30 secondes
+ Mission Stratégique Claude AI (Anthropic)
"""

import asyncio
import logging
import os

# ─── TOKENS (fallback si variables d'environnement absentes) ──────────────────
os.environ.setdefault("TELEGRAM_TOKEN",    "8665812395:AAFO4BMTIrBCQJYVL8UytO028TcB1sDfgbI")
os.environ.setdefault("ANTHROPIC_API_KEY", "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")

# ─── Imports standard ─────────────────────────────────────────────────────────
try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    logging.warning("⚠️  Package 'anthropic' non installé — /ia désactivé. Lancez : pip install anthropic")

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import signal_manager as sm
import session_manager as sess
from market_data import get_candles, get_price
from smc_engine import Direction, SMCEngine

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

engine = SMCEngine()


# ─────────────────────────────────────────────────────────────────────────────
# CLAUDE AI — ANALYSTE STRATÉGIQUE
# ─────────────────────────────────────────────────────────────────────────────

_CLAUDE_SYSTEM = """
Tu es AlphaBot-AI, un analyste de trading de haut niveau spécialisé en Smart Money Concepts (SMC).
Ta mission stratégique :
1. Analyser la structure de marché (BOS, CHoCH, HH/LL) sur H4 pour la tendance macro.
2. Identifier les zones clés M15 : Order Blocks, Breaker Blocks, FVG, Supply & Demand.
3. Évaluer la session de trading en cours et son impact sur la liquidité.
4. Proposer un bias directionnel clair (BULLISH / BEARISH / NEUTRE) avec raisonnement.
5. Alerter si le contexte est défavorable (news, spread large, hors session).
Réponds toujours en français, de façon concise, structurée et professionnelle.
Ne donne jamais de conseil financier direct — tu fournis une analyse technique objective.
"""

async def analyse_with_claude(symbol: str, trend_info: dict, zones_info: dict, session: str) -> str:
    """Envoie le contexte marché à Claude et retourne son analyse stratégique."""
    if not _ANTHROPIC_AVAILABLE:
        return "❌ Module `anthropic` non installé sur ce serveur."

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "❌ ANTHROPIC_API_KEY manquant."

    prompt = (
        f"Symbole : {symbol}\n"
        f"Session active : {session}\n\n"
        f"=== TENDANCE H4 ===\n{trend_info}\n\n"
        f"=== ZONES M15 ===\n{zones_info}\n\n"
        "Fournis ton analyse stratégique complète selon ta mission."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-opus-4-5",
            max_tokens=700,
            system=_CLAUDE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    except anthropic.AuthenticationError:
        return "❌ Clé API Anthropic invalide ou expirée."
    except anthropic.RateLimitError:
        return "⏳ Limite de requêtes Anthropic atteinte — réessaie dans quelques secondes."
    except anthropic.APIConnectionError:
        return "❌ Impossible de joindre l'API Anthropic (vérifier la connexion réseau)."
    except Exception as exc:
        logger.error(f"Claude API error: {exc}", exc_info=True)
        return f"❌ Erreur inattendue Claude AI : {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *AlphaBot SMC PRO — Leader ODG*\n\n"
        "Commandes :\n"
        "`/price BTCUSD`  — Prix actuel + spread\n"
        "`/trend BTCUSD`  — Tendance H4\n"
        "`/zones BTCUSD`  — Zones M15 (OB, BB, FVG, S&D)\n"
        "`/entry BTCUSD`  — Setup actif + signal complet\n"
        "`/ia BTCUSD`     — 🧠 Analyse stratégique Claude AI\n"
        "`/session`       — Session active\n"
        "`/stats`         — Stats signaux du jour\n\n"
        "Marchés : BTCUSD · XAUUSD · XAGUSD · EURUSD · NAS100",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    symbol = (ctx.args[0].upper() if ctx.args else "BTCUSD")
    if symbol not in config.MARKETS:
        await update.message.reply_text(f"❌ Symbole inconnu : {symbol}")
        return

    data = get_price(symbol)
    if not data:
        await update.message.reply_text(f"❌ Données indisponibles pour {symbol}")
        return

    digits = config.MARKETS[symbol]["digits"]
    spread = data["spread"]

    await update.message.reply_text(
        f"💰 *{symbol}*\n"
        f"Bid : `{data['bid']:.{digits}f}`\n"
        f"Ask : `{data['ask']:.{digits}f}`\n"
        f"Spread : `{spread:.{digits}f}`\n"
        f"Type : {config.MARKETS[symbol]['type']}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_trend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    symbol = (ctx.args[0].upper() if ctx.args else "BTCUSD")
    df = get_candles(symbol, config.TF_TREND, config.CANDLE_COUNT)

    if df is None:
        await update.message.reply_text(f"❌ Données H4 indisponibles pour {symbol}")
        return

    t = engine.trend(df)
    s = engine.structure(df)
    emoji = "📈" if t == Direction.BULLISH else "📉" if t == Direction.BEARISH else "➡️"

    bos_txt   = f"BOS : {s['bos']}"     if s["bos"]   else "BOS : —"
    choch_txt = f"CHoCH : {s['choch']}" if s["choch"] else "CHoCH : —"

    await update.message.reply_text(
        f"{emoji} *{symbol}* — H4 Trend : *{t.value}*\n"
        f"{bos_txt}\n{choch_txt}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_zones(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    symbol = (ctx.args[0].upper() if ctx.args else "BTCUSD")
    df = get_candles(symbol, config.TF_ZONE, config.CANDLE_COUNT)

    if df is None:
        await update.message.reply_text(f"❌ Données M15 indisponibles pour {symbol}")
        return

    z   = engine.all_zones(df)
    dig = config.MARKETS.get(symbol, {}).get("digits", 5)

    def _fmt(zones, label):
        if not zones:
            return ""
        lines = [f"\n{label}"]
        for zn in zones[-3:]:
            d = "Bull" if zn.direction == Direction.BULLISH else "Bear"
            lines.append(f"  {d}: `{zn.low:.{dig}f}` — `{zn.high:.{dig}f}`")
        return "\n".join(lines)

    msg = f"📍 *Zones M15 — {symbol}*"
    msg += _fmt(z["breaker_blocks"], "🔴 Breaker Blocks")
    msg += _fmt(z["order_blocks"],   "🔵 Order Blocks")
    msg += _fmt(z["fvg"],            "🟣 FVG")
    msg += _fmt(z["supply_demand"],  "🟢 Supply / Demand")

    if not any(z.values()):
        msg += "\n\nAucune zone SMC détectée pour le moment."

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    symbol  = (ctx.args[0].upper() if ctx.args else "BTCUSD")
    session = sess.current_session() or "Hors session"

    await update.message.reply_text(f"🔍 Analyse {symbol} en cours…")

    h4  = get_candles(symbol, config.TF_TREND, config.CANDLE_COUNT)
    m15 = get_candles(symbol, config.TF_ZONE,  config.CANDLE_COUNT)
    m1  = get_candles(symbol, config.TF_ENTRY, 100)

    signal = engine.analyze(symbol, h4, m15, m1, session)

    if signal is None:
        await update.message.reply_text(
            f"🔍 *{symbol}* — Pas de setup SMC valide (≥75 score, RR ≥ 1:3).\n"
            f"Session : {session}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = sm.format_signal(signal, count=sm.count_today())
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_ia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🧠 Analyse stratégique Claude AI sur un symbole."""
    symbol  = (ctx.args[0].upper() if ctx.args else "BTCUSD")
    session = sess.current_session() or "Hors session"

    if symbol not in config.MARKETS:
        await update.message.reply_text(f"❌ Symbole inconnu : {symbol}")
        return

    await update.message.reply_text(f"🧠 Claude AI analyse *{symbol}*…", parse_mode=ParseMode.MARKDOWN)

    # ── Récupération des données ───────────────────────────────────────────────
    h4_df  = get_candles(symbol, config.TF_TREND, config.CANDLE_COUNT)
    m15_df = get_candles(symbol, config.TF_ZONE,  config.CANDLE_COUNT)

    # ── Construction du contexte tendance ─────────────────────────────────────
    if h4_df is not None:
        t  = engine.trend(h4_df)
        s  = engine.structure(h4_df)
        trend_info = (
            f"Trend H4 : {t.value}\n"
            f"BOS : {s.get('bos', '—')}\n"
            f"CHoCH : {s.get('choch', '—')}"
        )
    else:
        trend_info = "Données H4 indisponibles"

    # ── Construction du contexte zones ────────────────────────────────────────
    if m15_df is not None:
        z   = engine.all_zones(m15_df)
        dig = config.MARKETS.get(symbol, {}).get("digits", 5)
        zones_lines = []
        for cat, label in [
            ("order_blocks",   "Order Blocks"),
            ("breaker_blocks", "Breaker Blocks"),
            ("fvg",            "FVG"),
            ("supply_demand",  "Supply/Demand"),
        ]:
            items = z.get(cat, [])
            if items:
                last = items[-1]
                d = "Bull" if last.direction == Direction.BULLISH else "Bear"
                zones_lines.append(
                    f"{label} [{d}] : {last.low:.{dig}f} — {last.high:.{dig}f}"
                )
        zones_info = "\n".join(zones_lines) if zones_lines else "Aucune zone SMC détectée"
    else:
        zones_info = "Données M15 indisponibles"

    # ── Appel Claude AI ───────────────────────────────────────────────────────
    analysis = await analyse_with_claude(symbol, trend_info, zones_info, session)

    header = f"🧠 *AlphaBot-AI — {symbol}* | Session : {session}\n{'─'*30}\n"
    await update.message.reply_text(
        header + analysis,
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_session(update: Update, _: ContextTypes.DEFAULT_TYPE):
    s = sess.current_session()
    news_block = sess.is_news_window()
    if s:
        msg = f"🕒 Session active : *{s}*"
        if news_block:
            msg += "\n⚠️ _Fenêtre news haute impact — trading suspendu_"
    else:
        msg = "💤 Hors session (Asia / marché fermé)"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_stats(update: Update, _: ContextTypes.DEFAULT_TYPE):
    count   = sm.count_today()
    summary = sm.get_today_summary()
    session = sess.current_session() or "Hors session"

    lines = [f"📊 *Stats du jour*",
             f"Signaux : {count}/{config.MAX_SIGNALS_PER_DAY}",
             f"Session : {session}"]

    if summary:
        lines.append("\n*Derniers signaux :*")
        for s in summary[-5:]:
            emoji = "📈" if s["direction"] == "BUY" else "📉"
            lines.append(f"  {emoji} {s['symbol']} {s['direction']} — RR 1:{s['rr']:.1f} | Score {s['score']}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-SCANNER (30 secondes)
# ─────────────────────────────────────────────────────────────────────────────

async def _scanner(app: Application):
    logger.info("🔁 Auto-scanner démarré (30s)")
    presignal_sent: set = set()

    while True:
        try:
            if not sess.is_trading_allowed():
                logger.info("Hors session — pause scanner")
                await asyncio.sleep(60)
                continue

            if sess.is_news_window():
                logger.info("News window — scanner suspendu")
                await asyncio.sleep(60)
                continue

            if not sm.can_send():
                logger.info("Limite 10 signaux atteinte")
                await asyncio.sleep(300)
                continue

            session = sess.current_session()

            for symbol, minfo in config.MARKETS.items():
                if not sm.can_send():
                    break

                price_data = get_price(symbol)
                if price_data and price_data["spread"] > minfo["spread_max"]:
                    logger.debug(f"Spread trop large {symbol}: {price_data['spread']:.5f}")
                    continue

                h4  = get_candles(symbol, config.TF_TREND, config.CANDLE_COUNT)
                m15 = get_candles(symbol, config.TF_ZONE,  config.CANDLE_COUNT)
                m1  = get_candles(symbol, config.TF_ENTRY, 100)

                signal = engine.analyze(symbol, h4, m15, m1, session)

                if not signal:
                    presignal_sent.discard(symbol)
                    await asyncio.sleep(1)
                    continue

                if signal.score >= 70 and symbol not in presignal_sent:
                    pre_msg = sm.format_presignal(symbol, signal.direction,
                                                   signal.setup.value, session)
                    if config.LEADER_CHAT_ID:
                        await app.bot.send_message(
                            chat_id=config.LEADER_CHAT_ID,
                            text=pre_msg,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    presignal_sent.add(symbol)

                if signal.score >= config.MIN_SCORE and signal.rr >= config.MIN_RR:
                    msg = sm.format_signal(signal, count=sm.count_today() + 1)

                    if config.CHANNEL_ID:
                        await app.bot.send_message(
                            chat_id=config.CHANNEL_ID,
                            text=msg,
                            parse_mode=ParseMode.MARKDOWN,
                        )

                    if config.LEADER_CHAT_ID:
                        await app.bot.send_message(
                            chat_id=config.LEADER_CHAT_ID,
                            text=f"✅ Signal auto envoyé : *{symbol}* {signal.direction.value} | Score {signal.score} | RR 1:{signal.rr}",
                            parse_mode=ParseMode.MARKDOWN,
                        )

                    sm.record(signal)
                    presignal_sent.discard(symbol)
                    await asyncio.sleep(3)

                await asyncio.sleep(1)

        except Exception as exc:
            logger.error(f"Scanner exception: {exc}", exc_info=True)

        await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

async def _post_init(app: Application):
    """Start background scanner after bot is ready."""
    asyncio.create_task(_scanner(app))


def main():
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN manquant dans les variables d'environnement")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("⚠️  ANTHROPIC_API_KEY non défini — commande /ia désactivée")

    app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("price",   cmd_price))
    app.add_handler(CommandHandler("trend",   cmd_trend))
    app.add_handler(CommandHandler("zones",   cmd_zones))
    app.add_handler(CommandHandler("entry",   cmd_entry))
    app.add_handler(CommandHandler("ia",      cmd_ia))
    app.add_handler(CommandHandler("session", cmd_session))
    app.add_handler(CommandHandler("stats",   cmd_stats))

    logger.info("AlphaBot SMC PRO + Claude AI démarré")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
