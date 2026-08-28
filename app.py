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


# =============================================================================
# CONEXION FXCM
# =============================================================================

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


# =============================================================================
# OBTENER CUENTA
# =============================================================================

def get_account(fx):
    accounts = fx.get_table(
        ForexConnect.ACCOUNTS
    )

    # Primero intenta usar una cuenta self-traded normal
    for account in accounts:
        if account.account_kind == "32":
            return account

    # Si no encuentra account_kind 32,
    # utiliza la primera cuenta disponible
    for account in accounts:
        return account

    raise RuntimeError(
        "No FXCM account found"
    )


# =============================================================================
# OBTENER INSTRUMENTO DISPONIBLE
# =============================================================================

def get_offer(fx, instrument):
    offers = fx.get_table(
        ForexConnect.OFFERS
    )

    normalized = (
        instrument
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .upper()
    )

    available = []

    for offer in offers:
        offer_name = str(
            offer.instrument
        )

        offer_normalized = (
            offer_name
            .replace("/", "")
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
            .upper()
        )

        available.append(
            offer_name
        )

        if offer_normalized == normalized:
            return offer

    raise RuntimeError(
        "Instrument not found. Requested: "
        + instrument
        + " | Available: "
        + ", ".join(available[:50])
    )


# =============================================================================
# ABRIR ORDEN MARKET
# =============================================================================

def open_market_order(
    fx,
    instrument,
    is_buy,
    amount
):
    account = get_account(fx)

    offer = get_offer(
        fx,
        instrument
    )

    side = (
        fxcorepy.Constants.BUY
        if is_buy
        else fxcorepy.Constants.SELL
    )

    request_order = fx.create_order_request(
        order_type=fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,
        ACCOUNT_ID=account.account_id,
        BUY_SELL=side,
        AMOUNT=int(amount),
        SYMBOL=offer.instrument
    )

    request_id = request_order.request_id

    fx.send_request(
        request_order
    )

    return {
        "request_id": request_id,
        "instrument": offer.instrument
    }


# =============================================================================
# CERRAR POSICIONES
# =============================================================================

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

    normalized_requested = (
        instrument
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .upper()
    )

    for trade in trades:

        trade_instrument = str(
            trade.instrument
        )

        trade_normalized = (
            trade_instrument
            .replace("/", "")
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
            .upper()
        )

        if trade_normalized != normalized_requested:
            continue

        is_long = (
            trade.buy_sell ==
            fxcorepy.Constants.BUY
        )

        if close_long and not is_long:
            continue

        if close_short and is_long:
            continue

        opposite_side = (
            fxcorepy.Constants.SELL
            if is_long
            else fxcorepy.Constants.BUY
        )

        request_order = fx.create_order_request(
            order_type=fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE,
            ACCOUNT_ID=account.account_id,
            OFFER_ID=trade.offer_id,
            TRADE_ID=trade.trade_id,
            BUY_SELL=opposite_side,
            AMOUNT=trade.amount
        )

        request_id = (
            request_order.request_id
        )

        fx.send_request(
            request_order
        )

        closed.append({
            "request_id": request_id,
            "trade_id": trade.trade_id,
            "instrument": trade_instrument
        })

    return closed


# =============================================================================
# HOME
# =============================================================================

@app.route("/", methods=["GET"])
def home():
    return "Bridge online", 200


# =============================================================================
# STATUS
# =============================================================================

@app.route("/status", methods=["GET"])
def status():

    if not FXCM_USERNAME:
        return jsonify({
            "bridge": "online",
            "fxcm": "credentials_missing",
            "missing": "FXCM_USERNAME"
        }), 500

    if not FXCM_PASSWORD:
        return jsonify({
            "bridge": "online",
            "fxcm": "credentials_missing",
            "missing": "FXCM_PASSWORD"
        }), 500

    try:
        with lock:
            with get_fxcm() as fx:

                account = get_account(fx)

                return jsonify({
                    "bridge": "online",
                    "fxcm": "connected",
                    "connection": FXCM_CONNECTION,
                    "balance": account.balance,
                    "equity": account.equity,
                    "used_margin": account.used_margin,
                    "usable_margin": account.usable_margin
                }), 200

    except Exception as e:

        print(
            "FXCM STATUS ERROR:",
            str(e)
        )

        return jsonify({
            "bridge": "online",
            "fxcm": "error",
            "error": str(e)
        }), 500


# =============================================================================
# LISTAR INSTRUMENTOS DISPONIBLES
# =============================================================================

@app.route("/instruments", methods=["GET"])
def instruments():

    try:
        with lock:
            with get_fxcm() as fx:

                offers = fx.get_table(
                    ForexConnect.OFFERS
                )

                instrument_list = []

                for offer in offers:
                    instrument_list.append(
                        str(offer.instrument)
                    )

                return jsonify({
                    "status": "ok",
                    "count": len(instrument_list),
                    "instruments": instrument_list
                }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# =============================================================================
# TRADINGVIEW WEBHOOK
# =============================================================================

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


    print(
        "TradingView message received:",
        data
    )


    # =========================================================================
    # VALIDAR SECRET
    # =========================================================================

    received_secret = data.get(
        "secret"
    )

    if WEBHOOK_SECRET:

        if received_secret != WEBHOOK_SECRET:

            print(
                "Webhook rejected: invalid secret"
            )

            return jsonify({
                "status": "rejected",
                "message": "Invalid secret"
            }), 403


    # =========================================================================
    # VALIDAR BROKER
    # =========================================================================

    if data.get("broker") != "FXCM":

        return jsonify({
            "status": "rejected",
            "message": "Wrong broker"
        }), 400


    # =========================================================================
    # VALIDAR SIMBOLO
    # =========================================================================

    if data.get("symbol") != "EURUSD":

        return jsonify({
            "status": "rejected",
            "message": "Only EURUSD allowed"
        }), 400


    action = data.get(
        "action"
    )


    quantity = int(
        float(
            data.get(
                "quantity",
                1000
            )
        )
    )


    # =========================================================================
    # SEGURIDAD DE TAMANO
    # =========================================================================

    if quantity < 1000:

        return jsonify({
            "status": "rejected",
            "message": "Minimum quantity is 1000 units"
        }), 400


    if quantity > 1000:

        return jsonify({
            "status": "rejected",
            "message": "Maximum quantity is 1000 units"
        }), 400


    # =========================================================================
    # EJECUCION
    # =========================================================================

    try:

        with lock:

            with get_fxcm() as fx:

                # =============================================================
                # BUY
                # =============================================================

                if action == "BUY":

                    result = open_market_order(
                        fx,
                        "EUR/USD",
                        True,
                        quantity
                    )

                    print(
                        "FXCM BUY executed:",
                        result
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "BUY",
                        "symbol": result["instrument"],
                        "quantity": quantity,
                        "request_id": result["request_id"]
                    }), 200


                # =============================================================
                # SELL
                # =============================================================

                elif action == "SELL":

                    result = open_market_order(
                        fx,
                        "EUR/USD",
                        False,
                        quantity
                    )

                    print(
                        "FXCM SELL executed:",
                        result
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "SELL",
                        "symbol": result["instrument"],
                        "quantity": quantity,
                        "request_id": result["request_id"]
                    }), 200


                # =============================================================
                # CLOSE LONG
                # =============================================================

                elif action == "CLOSE_LONG":

                    closed = close_positions(
                        fx,
                        "EUR/USD",
                        close_long=True
                    )

                    print(
                        "FXCM CLOSE_LONG:",
                        closed
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "CLOSE_LONG",
                        "closed": closed
                    }), 200


                # =============================================================
                # CLOSE SHORT
                # =============================================================

                elif action == "CLOSE_SHORT":

                    closed = close_positions(
                        fx,
                        "EUR/USD",
                        close_short=True
                    )

                    print(
                        "FXCM CLOSE_SHORT:",
                        closed
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "CLOSE_SHORT",
                        "closed": closed
                    }), 200


                # =============================================================
                # CLOSE ALL
                # =============================================================

                elif action == "CLOSE_ALL":

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

                    all_closed = (
                        longs +
                        shorts
                    )

                    print(
                        "FXCM CLOSE_ALL:",
                        all_closed
                    )

                    return jsonify({
                        "status": "executed",
                        "action": "CLOSE_ALL",
                        "closed": all_closed
                    }), 200


                # =============================================================
                # ACCION DESCONOCIDA
                # =============================================================

                else:

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
