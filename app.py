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


# =============================================================================
# ESTADO GLOBAL
# =============================================================================

fx = None

fx_lock = threading.RLock()

fx_connected = False

eurusd_subscription_status = None


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
# SESION FXCM
# =============================================================================

def connect_fxcm():

    global fx
    global fx_connected

    with fx_lock:

        if fx is not None and fx_connected:

            return fx


        if not FXCM_USERNAME:

            raise RuntimeError(
                "FXCM_USERNAME missing"
            )


        if not FXCM_PASSWORD:

            raise RuntimeError(
                "FXCM_PASSWORD missing"
            )


        print(
            "Connecting to FXCM..."
        )


        fx = ForexConnect()


        fx.login(
            FXCM_USERNAME,
            FXCM_PASSWORD,
            FXCM_URL,
            FXCM_CONNECTION,
            session_id=None,
            pin=None
        )


        fx_connected = True


        print(
            "FXCM connected."
        )


        return fx


# =============================================================================
# RECONEXION
# =============================================================================

def reconnect_fxcm():

    global fx
    global fx_connected

    with fx_lock:

        try:

            if fx is not None:

                fx.logout()

        except Exception as e:

            print(
                "Logout warning:",
                str(e)
            )


        fx = None

        fx_connected = False


        return connect_fxcm()


# =============================================================================
# OBTENER CUENTA
# =============================================================================

def get_account():

    session = connect_fxcm()

    accounts = session.get_table(
        ForexConnect.ACCOUNTS
    )


    # Preferimos cuenta self-traded
    for account in accounts:

        if str(
            account.account_kind
        ) == "32":

            return account


    # Si no aparece, usamos la primera
    for account in accounts:

        return account


    raise RuntimeError(
        "No FXCM account found"
    )


# =============================================================================
# OBTENER OFFER
# =============================================================================

def get_offer(
    instrument="EUR/USD"
):

    session = connect_fxcm()

    offers = session.get_table(
        ForexConnect.OFFERS
    )

    requested = normalize_symbol(
        instrument
    )


    for offer in offers:

        if normalize_symbol(
            offer.instrument
        ) == requested:

            return offer


    raise RuntimeError(
        "Instrument not found: "
        + instrument
    )


# =============================================================================
# ESTABLECER SUBSCRIPTION STATUS
# =============================================================================

def set_subscription_status(
    instrument="EUR/USD",
    status="T"
):

    global eurusd_subscription_status

    session = connect_fxcm()

    offer = get_offer(
        instrument
    )


    print(
        "Current subscription:",
        offer.instrument,
        offer.subscription_status
    )


    if str(
        offer.subscription_status
    ) == status:

        eurusd_subscription_status = status

        return {
            "instrument":
                str(
                    offer.instrument
                ),

            "offer_id":
                str(
                    offer.offer_id
                ),

            "previous_status":
                status,

            "status":
                status,

            "changed":
                False
        }


    request_sub = session.create_request({
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


    request_id = (
        request_sub.request_id
    )


    session.send_request(
        request_sub
    )


    print(
        "SET_SUBSCRIPTION_STATUS sent:",
        request_id
    )


    # Esperamos que la tabla Offers se actualice
    for _ in range(20):

        time.sleep(
            0.5
        )


        refreshed = get_offer(
            instrument
        )


        refreshed_status = str(
            refreshed.subscription_status
        )


        print(
            "Subscription check:",
            refreshed_status
        )


        if refreshed_status == status:

            eurusd_subscription_status = status


            return {
                "instrument":
                    str(
                        refreshed.instrument
                    ),

                "offer_id":
                    str(
                        refreshed.offer_id
                    ),

                "previous_status":
                    str(
                        offer.subscription_status
                    ),

                "status":
                    refreshed_status,

                "changed":
                    True,

                "request_id":
                    request_id
            }


    final_offer = get_offer(
        instrument
    )


    eurusd_subscription_status = str(
        final_offer.subscription_status
    )


    raise RuntimeError(
        "Subscription did not change to "
        + status
        + ". Current status="
        + str(
            final_offer.subscription_status
        )
    )


# =============================================================================
# ASEGURAR SUBSCRIPCION TRADING
# =============================================================================

def ensure_eurusd_tradable():

    offer = get_offer(
        "EUR/USD"
    )


    current_status = str(
        offer.subscription_status
    )


    if current_status == "T":

        return offer


    print(
        "EUR/USD is not T. "
        "Attempting subscription..."
    )


    set_subscription_status(
        "EUR/USD",
        "T"
    )


    offer = get_offer(
        "EUR/USD"
    )


    if str(
        offer.subscription_status
    ) != "T":

        raise RuntimeError(
            "EUR/USD subscription_status is "
            + str(
                offer.subscription_status
            )
            + " instead of T"
        )


    return offer


# =============================================================================
# ABRIR ORDEN MARKET
# =============================================================================

def open_market_order(
    is_buy,
    amount
):

    session = connect_fxcm()

    account = get_account()

    offer = ensure_eurusd_tradable()


    side = (
        fxcorepy.Constants.BUY
        if is_buy
        else fxcorepy.Constants.SELL
    )


    request_order = session.create_order_request(
        order_type=
            fxcorepy.Constants.Orders.TRUE_MARKET_OPEN,

        ACCOUNT_ID=
            account.account_id,

        BUY_SELL=
            side,

        AMOUNT=
            int(amount),

        SYMBOL=
            str(
                offer.instrument
            )
    )


    if request_order is None:

        raise RuntimeError(
            "Could not create TRUE_MARKET_OPEN request"
        )


    request_id = (
        request_order.request_id
    )


    session.send_request(
        request_order
    )


    print(
        "Market order sent:",
        request_id
    )


    return {
        "request_id":
            request_id,

        "instrument":
            str(
                offer.instrument
            ),

        "subscription_status":
            str(
                offer.subscription_status
            )
    }


# =============================================================================
# CERRAR POSICIONES
# =============================================================================

def close_positions(
    close_long=False,
    close_short=False
):

    session = connect_fxcm()

    trades = session.get_table(
        ForexConnect.TRADES
    )

    account = get_account()

    closed = []


    for trade in trades:

        if normalize_symbol(
            trade.instrument
        ) != "EURUSD":

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


        request_order = session.create_order_request(
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
                + str(
                    trade.trade_id
                )
            )


        request_id = (
            request_order.request_id
        )


        session.send_request(
            request_order
        )


        closed.append({
            "request_id":
                request_id,

            "trade_id":
                str(
                    trade.trade_id
                ),

            "instrument":
                str(
                    trade.instrument
                )
        })


    return closed


# =============================================================================
# INICIALIZACION
# =============================================================================

def initialize_bridge():

    try:

        connect_fxcm()


        print(
            "FXCM persistent session initialized."
        )


        try:

            result = set_subscription_status(
                "EUR/USD",
                "T"
            )


            print(
                "EUR/USD subscription result:",
                result
            )


        except Exception as e:

            print(
                "EUR/USD subscription initialization error:",
                str(e)
            )


    except Exception as e:

        print(
            "FXCM initialization error:",
            str(e)
        )


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
# STATUS
# =============================================================================

@app.route(
    "/status",
    methods=["GET"]
)
def status():

    try:

        with fx_lock:

            session = connect_fxcm()

            account = get_account()

            offer = get_offer(
                "EUR/USD"
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
                    account.usable_margin,

                "eurusd_subscription_status":
                    str(
                        offer.subscription_status
                    )
            }), 200


    except Exception as e:

        return jsonify({
            "bridge":
                "online",

            "fxcm":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# INSTRUMENT STATUS
# =============================================================================

@app.route(
    "/instrument-status",
    methods=["GET"]
)
def instrument_status():

    try:

        with fx_lock:

            offer = get_offer(
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
# SUSCRIBIR EUR/USD
# =============================================================================

@app.route(
    "/subscribe-eurusd",
    methods=["GET"]
)
def subscribe_eurusd():

    try:

        with fx_lock:

            result = set_subscription_status(
                "EUR/USD",
                "T"
            )


            return jsonify({
                "status":
                    "ok",

                "result":
                    result
            }), 200


    except Exception as e:

        print(
            "FXCM subscription error:",
            str(e)
        )


        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# RECONNECT
# =============================================================================

@app.route(
    "/reconnect",
    methods=["GET"]
)
def reconnect():

    try:

        with fx_lock:

            reconnect_fxcm()

            result = set_subscription_status(
                "EUR/USD",
                "T"
            )


            return jsonify({
                "status":
                    "ok",

                "fxcm":
                    "reconnected",

                "subscription":
                    result
            }), 200


    except Exception as e:

        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# TRADINGVIEW
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
    # SECRET
    # =========================================================================

    received_secret = data.get(
        "secret"
    )


    if WEBHOOK_SECRET:

        if received_secret != WEBHOOK_SECRET:

            return jsonify({
                "status":
                    "rejected",

                "message":
                    "Invalid secret"
            }), 403


    # =========================================================================
    # BROKER
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
    # SYMBOL
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
    # TAMANO FIJO
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

        with fx_lock:

            # =================================================================
            # BUY
            # =================================================================

            if action == "BUY":

                result = open_market_order(
                    True,
                    quantity
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


            # =================================================================
            # SELL
            # =================================================================

            elif action == "SELL":

                result = open_market_order(
                    False,
                    quantity
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


            # =================================================================
            # CLOSE LONG
            # =================================================================

            elif action == "CLOSE_LONG":

                closed = close_positions(
                    close_long=True
                )


                return jsonify({
                    "status":
                        "executed",

                    "action":
                        "CLOSE_LONG",

                    "closed":
                        closed
                }), 200


            # =================================================================
            # CLOSE SHORT
            # =================================================================

            elif action == "CLOSE_SHORT":

                closed = close_positions(
                    close_short=True
                )


                return jsonify({
                    "status":
                        "executed",

                    "action":
                        "CLOSE_SHORT",

                    "closed":
                        closed
                }), 200


            # =================================================================
            # CLOSE ALL
            # =================================================================

            elif action == "CLOSE_ALL":

                longs = close_positions(
                    close_long=True
                )

                shorts = close_positions(
                    close_short=True
                )


                return jsonify({
                    "status":
                        "executed",

                    "action":
                        "CLOSE_ALL",

                    "closed":
                        longs + shorts
                }), 200


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


        # Forzamos reconexion en el siguiente intento
        global fx_connected

        fx_connected = False


        return jsonify({
            "status":
                "error",

            "error":
                str(e)
        }), 500


# =============================================================================
# INICIAR SESION AL ARRANCAR EL SERVIDOR
# =============================================================================

initialize_bridge()
