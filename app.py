import os
import time
import threading

from flask import Flask, request, jsonify
from forexconnect import ForexConnect, fxcorepy


app = Flask(__name__)


# =============================================================================
# VARIABLES DE ENTORNO
# =============================================================================

FXCM_USERNAME = os.environ.get("FXCM_USERNAME")
FXCM_PASSWORD = os.environ.get("FXCM_PASSWORD")

FXCM_CONNECTION = os.environ.get(
    "FXCM_CONNECTION",
    "Demo"
)

FXCM_URL = os.environ.get(
    "FXCM_URL",
    "www.fxcorporate.com/Hosts.jsp"
)

WEBHOOK_SECRET = os.environ.get(
    "WEBHOOK_SECRET"
)


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
# NORMALIZAR SIMBOLO
# =============================================================================

def normalize_symbol(symbol):

    return (
        str(symbol)
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .upper()
    )


# =============================================================================
# OBTENER CUENTA
# =============================================================================

def get_account(fx):

    accounts = fx.get_table(
        ForexConnect.ACCOUNTS
    )

    # Cuenta self-traded normal.
    for account in accounts:

        if str(account.account_kind) == "32":

            return account

    # Si no encontramos kind 32,
    # usamos la primera disponible.
    for account in accounts:

        return account

    raise RuntimeError(
        "No FXCM account found"
    )


# =============================================================================
# OBTENER OFFER
# =============================================================================

def get_offer(fx, instrument):

    offers = fx.get_table(
        ForexConnect.OFFERS
    )

    requested = normalize_symbol(
        instrument
    )

    available = []

    for offer in offers:

        offer_name = str(
            offer.instrument
        )

        available.append(
            offer_name
        )

        if normalize_symbol(
            offer_name
        ) == requested:

            return offer

    raise RuntimeError(
        "Instrument not found. Requested: "
        + instrument
        + " | Available: "
        + ", ".join(
            available[:50]
        )
    )


# =============================================================================
# CAMBIAR SUBSCRIPTION STATUS
# =============================================================================

def set_subscription_status(
    fx,
    offer,
    status="T"
):

    request_sub = fx.create_request({
        fxcorepy.O2GRequestParamsEnum.COMMAND:
            fxcorepy.Constants.Commands.SET_SUBSCRIPTION_STATUS,

        fxcorepy.O2GRequestParamsEnum.OFFER_ID:
            offer.offer_id,

        fxcorepy.O2GRequestParamsEnum.SUBSCRIPTION_STATUS:
            status
    })

    if request_sub is None:

        raise RuntimeError(
            "Could not create SET_SUBSCRIPTION_STATUS request"
        )

    fx.send_request(
        request_sub
    )

    return request_sub.request_id


# =============================================================================
# ASEGURAR EUR/USD EN ESTADO T
# =============================================================================

def ensure_trading_subscription(
    fx,
    instrument
):

    offer = get_offer(
        fx,
        instrument
    )

    current_status = str(
        offer.subscription_status
    )

    if current_status == "T":

        return offer


    set_subscription_status(
        fx,
        offer,
        "T"
    )


    # Damos tiempo a ForexConnect para actualizar la tabla.
    for _ in range(10):

        time.sleep(0.5)

        refreshed_offer = get_offer(
            fx,
            instrument
        )

        refreshed_status = str(
            refreshed_offer.subscription_status
        )

        if refreshed_status == "T":

            return refreshed_offer


    refreshed_offer = get_offer(
        fx,
        instrument
    )

    raise RuntimeError(
        "Could not enable trading subscription. "
        + "Instrument="
        + str(refreshed_offer.instrument)
        + " status="
        + str(refreshed_offer.subscription_status)
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

    account = get_account(
        fx
    )

    offer = ensure_trading_subscription(
        fx,
        instrument
    )

    subscription_status = str(
        offer.subscription_status
    )

    if subscription_status != "T":

        raise RuntimeError(
            "Instrument is not available for trading. "
            + "Instrument="
            + str(offer.instrument)
            + " status="
            + subscription_status
        )


    side = (
        fxcorepy.Constants.BUY
        if is_buy
        else fxcorepy.Constants.SELL
    )


    request_order = fx.create_order_request(
        order_type=
            fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,

        ACCOUNT_ID=
            account.account_id,

        BUY_SELL=
            side,

        AMOUNT=
            int(amount),

        SYMBOL=
            str(offer.instrument)
    )


    if request_order is None:

        raise RuntimeError(
            "Could not create market order request"
        )


    request_id = (
        request_order.request_id
    )


    fx.send_request(
        request_order
    )


    return {
        "request_id":
            request_id,

        "instrument":
            str(offer.instrument),

        "subscription_status":
            str(offer.subscription_status)
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

    account = get_account(
        fx
    )

    requested = normalize_symbol(
        instrument
    )

    closed = []


    for trade in trades:

        trade_instrument = str(
            trade.instrument
        )

        if normalize_symbol(
            trade_instrument
        ) != requested:

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
            order_type=
                fxcorepy.Constants.Orders.TRUE_MARKET_CLOSE,

            ACCOUNT_ID=
                account.account_id,

            OFFER_ID=
                trade.offer_id,

            TRADE_ID=
                trade.trade_id,

            BUY_SELL=
                opposite_side,

            AMOUNT=
                trade.amount
        )


        if request_order is None:

            raise RuntimeError(
                "Could not create close request for trade "
                + str(trade.trade_id)
            )


        request_id = (
            request_order.request_id
        )


        fx.send_request(
            request_order
        )


        closed.append({
            "request_id":
                request_id,

            "trade_id":
                str(trade.trade_id),

            "instrument":
                trade_instrument
        })


    return closed


# =============================================================================
# HOME
# =============================================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return (
        "Bridge online",
        200
    )


# =============================================================================
# STATUS GENERAL
# =============================================================================

@app.route(
    "/status",
    methods=["GET"]
)
def status():

    if not FXCM_USERNAME:

        return jsonify({
            "bridge":
                "online",

            "fxcm":
                "credentials_missing",

            "missing":
                "FXCM_USERNAME"
        }), 500


    if not FXCM_PASSWORD:

        return jsonify({
            "bridge":
                "online",

            "fxcm":
                "credentials_missing",

            "missing":
                "FXCM_PASSWORD"
        }), 500


    try:

        with lock:

            with get_fxcm() as fx:

                account = get_account(
                    fx
                )


                return jsonify({
                    "bridge":
                        "online",

                    "fxcm":
                        "connected",

                    "connection":
                        FXCM_CONNECTION,

                    "balance":
                        account.balance,

                    "equity":
                        account.equity,

                    "used_margin":
                        account.used_margin,

                    "usable_margin":
                        account.usable_margin
                }), 200


    except Exception as e:

        print(
            "FXCM STATUS ERROR:",
            str(e)
        )


        return jsonify({
            "bridge":
                "online",

            "fxcm":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# LISTAR INSTRUMENTOS
# =============================================================================

@app.route(
    "/instruments",
    methods=["GET"]
)
def instruments():

    try:

        with lock:

            with get_fxcm() as fx:

                offers = fx.get_table(
                    ForexConnect.OFFERS
                )

                instrument_list = []


                for offer in offers:

                    instrument_list.append({
                        "instrument":
                            str(
                                offer.instrument
                            ),

                        "offer_id":
                            str(
                                offer.offer_id
                            ),

                        "status":
                            str(
                                offer.subscription_status
                            )
                    })


                return jsonify({
                    "status":
                        "ok",

                    "count":
                        len(
                            instrument_list
                        ),

                    "instruments":
                        instrument_list
                }), 200


    except Exception as e:

        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# ESTADO EUR/USD
# =============================================================================

@app.route(
    "/instrument-status",
    methods=["GET"]
)
def instrument_status():

    try:

        with lock:

            with get_fxcm() as fx:

                offer = get_offer(
                    fx,
                    "EUR/USD"
                )


                return jsonify({
                    "instrument":
                        str(
                            offer.instrument
                        ),

                    "offer_id":
                        str(
                            offer.offer_id
                        ),

                    "subscription_status":
                        str(
                            offer.subscription_status
                        ),

                    "bid":
                        float(
                            offer.bid
                        ),

                    "ask":
                        float(
                            offer.ask
                        )
                }), 200


    except Exception as e:

        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# SUSCRIBIR EUR/USD PARA TRADING
# =============================================================================

@app.route(
    "/subscribe-eurusd",
    methods=["GET"]
)
def subscribe_eurusd():

    try:

        with lock:

            with get_fxcm() as fx:

                original_offer = get_offer(
                    fx,
                    "EUR/USD"
                )


                original_status = str(
                    original_offer.subscription_status
                )


                enabled_offer = (
                    ensure_trading_subscription(
                        fx,
                        "EUR/USD"
                    )
                )


                return jsonify({
                    "status":
                        "ok",

                    "instrument":
                        str(
                            enabled_offer.instrument
                        ),

                    "offer_id":
                        str(
                            enabled_offer.offer_id
                        ),

                    "previous_subscription_status":
                        original_status,

                    "subscription_status":
                        str(
                            enabled_offer.subscription_status
                        ),

                    "message":
                        "EUR/USD subscription enabled for trading"
                }), 200


    except Exception as e:

        print(
            "FXCM SUBSCRIPTION ERROR:",
            str(e)
        )


        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# TRADINGVIEW WEBHOOK
# =============================================================================

@app.route(
    "/tradingview",
    methods=["POST"]
)
def tradingview():

    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({
            "status":
                "error",

            "message":
                "Invalid JSON"
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
                "status":
                    "rejected",

                "message":
                    "Invalid secret"
            }), 403


    # =========================================================================
    # VALIDAR BROKER
    # =========================================================================

    if data.get(
        "broker"
    ) != "FXCM":

        return jsonify({
            "status":
                "rejected",

            "message":
                "Wrong broker"
        }), 400


    # =========================================================================
    # VALIDAR SIMBOLO
    # =========================================================================

    if data.get(
        "symbol"
    ) != "EURUSD":

        return jsonify({
            "status":
                "rejected",

            "message":
                "Only EURUSD allowed"
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

    if quantity != 1000:

        return jsonify({
            "status":
                "rejected",

            "message":
                "Quantity must be exactly 1000 units"
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
                        "status":
                            "executed",

                        "action":
                            "BUY",

                        "symbol":
                            result[
                                "instrument"
                            ],

                        "quantity":
                            quantity,

                        "request_id":
                            result[
                                "request_id"
                            ],

                        "subscription_status":
                            result[
                                "subscription_status"
                            ]
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
                        "status":
                            "executed",

                        "action":
                            "SELL",

                        "symbol":
                            result[
                                "instrument"
                            ],

                        "quantity":
                            quantity,

                        "request_id":
                            result[
                                "request_id"
                            ],

                        "subscription_status":
                            result[
                                "subscription_status"
                            ]
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
                        "status":
                            "executed",

                        "action":
                            "CLOSE_LONG",

                        "closed":
                            closed
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
                        "status":
                            "executed",

                        "action":
                            "CLOSE_SHORT",

                        "closed":
                            closed
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
                        "status":
                            "executed",

                        "action":
                            "CLOSE_ALL",

                        "closed":
                            all_closed
                    }), 200


                # =============================================================
                # ACCION DESCONOCIDA
                # =============================================================

                else:

                    return jsonify({
                        "status":
                            "rejected",

                        "message":
                            "Unknown action"
                    }), 400


    except Exception as e:

        print(
            "FXCM execution error:",
            str(e)
        )


        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500
