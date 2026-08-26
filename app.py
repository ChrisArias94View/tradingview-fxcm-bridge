from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "Bridge online", 200

@app.route("/tradingview", methods=["POST"])
def tradingview():
    data = request.get_json(silent=True)
    print("TradingView:", data)
    return jsonify({"status": "ok"}), 200
