import os
import threading
from flask import Flask, request, jsonify
from forexconnect import ForexConnect, fxcorepy

app = Flask(__name__)

FXCM_USERNAME = os.environ.get("FXCM_USERNAME")
FXCM_PASSWORD = os.environ.get("FXCM_PASSWORD")
FXCM_CONNECTION = os.environ.get("FXCM_CONNECTION", "Demo")
FXCM_URL = os.environ.get(
    "FXCM_URL",
    "www.fxcorporate.com/Hosts.jsp"
)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

lock = threading.Lock()


# ------------------------------------------------------------------
# LOGIN FXCM
# ------------------------------------------------------------------

def get_fxcm():
    fx = ForexConnect()

    fx.login(
        FXCM_USERNAME,
        FXCM_PASSWORD,
        FXCM_URL,
        FXCM_CONNECTION,
        session_id=None,
        pin=None
    )

    return fx


# ------------------------------------------------------------------
# ACCOUNT
# ------------------------------------------------------------------

def get_account(fx):
    login_rules = fx.login_rules
    trading_settings = login_rules.trading_settings_provider

    accounts = fx.get_table(
        ForexConnect.ACCOUNTS
    )

    for account in accounts:
        if account.account_kind == "32":
            continue

        return account

    raise RuntimeError("No valid FXCM account found")


# ------------------------------------------------------------------
# OFFER
# ------------------------------------------------------------------

def get_offer(fx, instrument):
    offers = fx.get_table(
        ForexConnect.OFFERS
    )

    for offer in offers:
        if offer.instrument == instrument:
            return offer

    raise RuntimeError(
        "Instrument not found: " + instrument
    )


# ------------------------------------------------------------------
# OPEN ORDER
# ------------------------------------------------------------------

def open_market_order(
    fx,
    instrument,
    is_buy,
    amount
):

    account = get_account(fx)
    offer = get_offer(fx, instrument)

    side = (
        fxcorepy.Constants.BUY
        if is_buy
        else fxcorepy.Constants.SELL
    )

    request = fx.create_order_request(
        order_type=fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,
        ACCOUNT_ID=account.account_id,
        BUY_SELL=side,
        AMOUNT=int(amount),
        SYMBOL=instrument
    )

    response = fx.send_request(request)

    return response.request_id


# ------------------------------------------------------------------
# CLOSE POSITIONS
# ------------------------------------------------------------------

def close_positions(
    fx,
    instrument,
    close_long=False,
    close_short=False
):

    trades = fx.get_table(
        ForexConnect.TRADES
    )

    account = get_account(fx)

    closed = []

    for trade in trades:

        if trade.instrument != instrument:
            continue

        is_long = trade.buy_sell == fxcorepy.Constants.BUY

        if close_long and not is_long:
            continue

        if close_short and is_long:
            continue

        opposite_side = (
            fxcorepy.Constants.SELL
            if is_long
            else fxcorepy.Constants.BUY
        )

        request = fx.create_order_request(
            order_type=fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE,
            ACCOUNT_ID=account.account_id,
            OFFER_ID=trade.offer_id,
            TRADE_ID=trade.trade_id,
            BUY_SELL=opposite_side,
            AMOUNT=trade.amount
        )

        response = fx.send_request(request)

        closed.append(
            response.request_id
        )

    return closed


# ------------------------------------------------------------------
# HOME
# ------------------------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return "Bridge online", 200


# ------------------------------------------------------------------
# STATUS
# ------------------------------------------------------------------

@app.route("/status", methods=["GET"])
def status():

    if not FXCM_USERNAME or not FXCM_PASSWORD:

        return jsonify({
            "bridge": "online",
            "fxcm": "credentials_missing"
        }), 500

    try:

        with lock:

            with get_fxcm() as fx:

                account = get_account(fx)

                return jsonify({
                    "bridge": "online",
                    "fxcm": "connected",
                    "connection": FXCM_CONNECTION,
                    "balance": account.balance
                }), 200

    except Exception as e:

        return jsonify({
            "bridge": "online",
            "fxcm": "error",
            "error": str(e)
        }), 500


# ------------------------------------------------------------------
# TRADINGVIEW
# ------------------------------------------------------------------

@app.route("/tradingview", methods=["POST"])
def tradingview():

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "status": "error",
            "message": "Invalid JSON"
        }), 400


    # --------------------------------------------------------------
    # SECRET
    # --------------------------------------------------------------

    received_secret = data.get("secret")

    if WEBHOOK_SECRET and received_secret != WEBHOOK_SECRET:

        return jsonify({
            "status": "rejected",
            "message": "Invalid secret"
        }), 403


    # --------------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------------

    if data.get("broker") != "FXCM":

        return jsonify({
            "status": "rejected",
            "message": "Wrong broker"
        }), 400


    if data.get("symbol") != "EURUSD":

        return jsonify({
            "status": "rejected",
            "message": "Only EURUSD allowed"
        }), 400


    action = data.get("action")

    quantity = int(
        float(
            data.get(
                "quantity",
                1000
            )
        )
    )


    # Safety
    if quantity > 1000:

        return jsonify({
            "status": "rejected",
            "message": "Maximum 1000 units"
        }), 400


    try:

        with lock:

            with get_fxcm() as fx:

                # --------------------------------------------------
                # BUY
                # --------------------------------------------------

                if action == "BUY":

                    request_id = open_market_order(
                        fx,
                        "EUR/USD",
                        True,
                        quantity
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "BUY",
                        "request_id": request_id
                    }), 200


                # --------------------------------------------------
                # SELL
                # --------------------------------------------------

                if action == "SELL":

                    request_id = open_market_order(
                        fx,
                        "EUR/USD",
                        False,
                        quantity
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "SELL",
                        "request_id": request_id
                    }), 200


                # --------------------------------------------------
                # CLOSE LONG
                # --------------------------------------------------

                if action == "CLOSE_LONG":

                    closed = close_positions(
                        fx,
                        "EUR/USD",
                        close_long=True
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "CLOSE_LONG",
                        "closed": closed
                    }), 200


                # --------------------------------------------------
                # CLOSE SHORT
                # --------------------------------------------------

                if action == "CLOSE_SHORT":

                    closed = close_positions(
                        fx,
                        "EUR/USD",
                        close_short=True
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "CLOSE_SHORT",
                        "closed": closed
                    }), 200


                # --------------------------------------------------
                # CLOSE ALL
                # --------------------------------------------------

                if action == "CLOSE_ALL":

                    longs = close_positions(
                        fx,
                        "EUR/USD",
                        close_long=True
                    )

                    shorts = close_positions(
                        fx,
                        "EUR/USD",
                        close_short=True
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "CLOSE_ALL",
                        "closed": longs + shorts
                    }), 200


                return jsonify({
                    "status": "rejected",
                    "message": "Unknown action"
                }), 400


    except Exception as e:

        print(
            "FXCM execution error:",
            str(e)
        )

        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500
