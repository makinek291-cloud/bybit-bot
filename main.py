from pybit.unified_trading import HTTP
import time
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ====================== CONFIG ======================
SYMBOL = "BTCUSDT"
FULL_SIZE = "0.06"
TP_USDT = 20.0
SL_USDT = 5.0
POLL_INTERVAL = 0.3

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
# ====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger()

session = HTTP(
    demo=True,
    api_key=API_KEY,
    api_secret=API_SECRET,
)

def send_email(subject: str, body: str):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log.info("Email sent successfully")
    except Exception as e:
        log.error(f"Failed to send email: {e}")

def get_mark_price():
    try:
        resp = session.get_tickers(category="linear", symbol=SYMBOL)
        return float(resp["result"]["list"][0]["markPrice"])
    except:
        return None

def get_positions():
    try:
        resp = session.get_positions(category="linear", symbol=SYMBOL)
        positions = {"long": None, "short": None}
        for p in resp["result"]["list"]:
            size = float(p["size"])
            if size == 0:
                continue
            if p["positionIdx"] == 1:
                positions["long"] = {"size": size, "entry": float(p["avgPrice"])}
            elif p["positionIdx"] == 2:
                positions["short"] = {"size": size, "entry": float(p["avgPrice"])}
        return positions
    except:
        return {"long": None, "short": None}

def place_market(side, qty, position_idx, reduce_only=False):
    qty = str(round(float(qty), 3))
    try:
        session.place_order(
            category="linear",
            symbol=SYMBOL,
            side=side,
            orderType="Market",
            qty=qty,
            positionIdx=position_idx,
            reduceOnly=reduce_only,
            timeInForce="IOC"
        )
        log.info(f"  → {side} {qty} BTC (reduceOnly={reduce_only})")
    except Exception as e:
        log.error(f"Order error: {e}")

def open_initial_hedge():
    log.info(f"Opening initial {FULL_SIZE} Long + {FULL_SIZE} Short")
    place_market("Buy", FULL_SIZE, 1)
    time.sleep(0.4)
    place_market("Sell", FULL_SIZE, 2)
    time.sleep(1)

def calculate_close_size_for_sl(entry, current_price):
    price_diff = abs(current_price - entry)
    if price_diff == 0:
        return float(FULL_SIZE) / 2
    size_needed = SL_USDT / price_diff
    size_needed = min(size_needed, float(FULL_SIZE))
    return round(size_needed, 3)

def rebalance(is_long_win, current_price):
    log.info("=== REBALANCE ===")
    pos = get_positions()
    if not pos["long"] or not pos["short"]:
        return

    if is_long_win:
        side_won = "LONG"
        place_market("Sell", FULL_SIZE, 1, True)
        time.sleep(0.3)
        close_size = calculate_close_size_for_sl(pos["short"]["entry"], current_price)
        log.info(f"Closing {close_size} Short to target -{SL_USDT}")
        place_market("Buy", close_size, 2, True)
        time.sleep(0.3)
        place_market("Buy", FULL_SIZE, 1)
        time.sleep(0.3)
        place_market("Sell", close_size, 2)
    else:
        side_won = "SHORT"
        place_market("Buy", FULL_SIZE, 2, True)
        time.sleep(0.3)
        close_size = calculate_close_size_for_sl(pos["long"]["entry"], current_price)
        log.info(f"Closing {close_size} Long to target -{SL_USDT}")
        place_market("Sell", close_size, 1, True)
        time.sleep(0.3)
        place_market("Sell", FULL_SIZE, 2)
        time.sleep(0.3)
        place_market("Buy", close_size, 1)

    time.sleep(1.5)
    log.info("=== REBALANCE DONE ===")

    subject = f"Bybit Bot - {side_won} won | Rebalance Done"
    body = f"""
Rebalance completed.

Side that won: {side_won}
Current Price: {current_price}
Time: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_email(subject, body)

def main():
    log.info("Bot started")

    # Only open if no positions exist
    pos = get_positions()
    if not pos["long"] or not pos["short"]:
        log.info("No positions found — opening initial hedge")
        open_initial_hedge()
    else:
        log.info("Positions already exist — skipping initial open")

    time.sleep(2)

    while True:
        try:
            price = get_mark_price()
            if not price:
                time.sleep(2)
                continue

            pos = get_positions()

            if not pos["long"] or not pos["short"]:
                log.warning("Positions missing — skipping this cycle (no auto-reopen)")
                time.sleep(2)
                continue

            delta = TP_USDT / float(FULL_SIZE)
            long_tp = pos["long"]["entry"] + delta
            short_tp = pos["short"]["entry"] - delta

            log.info(f"Price: {price:.1f}")
            log.info(f"  Long  TP: {long_tp:.1f} (+{TP_USDT})   |   Short SL: {long_tp:.1f} (-{SL_USDT})")
            log.info(f"  Short TP: {short_tp:.1f} (+{TP_USDT})   |   Long  SL: {short_tp:.1f} (-{SL_USDT})")

            if price >= long_tp:
                rebalance(True, price)
                time.sleep(1)
            elif price <= short_tp:
                rebalance(False, price)
                time.sleep(1)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Stopped")
            break
        except Exception as e:
            log.error(f"Error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
