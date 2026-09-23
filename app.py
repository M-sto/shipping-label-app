from flask import Flask, request, jsonify, render_template, redirect
from database import get_client, init_db, rows_to_dicts

app = Flask(__name__)

try:
    init_db()
except Exception as e:
    print(f"DB init warning: {e}")

ORDER_FIELDS = [
    "customer_name", "phone1", "phone2", "address",
    "governorate", "collect_amount", "shipping_fee", "total_amount",
]


def authenticate_client(req):
    api_key = (
        req.headers.get("X-API-KEY") or
        req.headers.get("x-api-key") or
        req.headers.get("api_key") or
        req.headers.get("Api-Key") or
        req.args.get("api_key")
    )
    if not api_key and req.is_json:
        api_key = req.json.get("api_key")
    if not api_key:
        return None

    client = get_client()
    try:
        result = client.execute(
            "SELECT * FROM clients WHERE api_key = ?", [api_key]
        )
        rows = rows_to_dicts(result)
        return rows[0] if rows else None
    finally:
        client.close()


@app.route("/api/orders", methods=["POST"])
def receive_order():
    auth_client = authenticate_client(request)
    if not auth_client:
        return jsonify({"error": "Invalid or missing API key"}), 401

    data = request.get_json() or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": "order_id is required"}), 400

    client_id = auth_client["client_id"]
    values = [data.get(f) for f in ORDER_FIELDS]

    db = get_client()
    try:
        existing = db.execute(
            "SELECT order_id FROM orders WHERE order_id = ? AND client_id = ?",
            [order_id, client_id],
        )

        if existing.rows:
            db.execute(
                f"""UPDATE orders SET
                    {", ".join(f"{f} = ?" for f in ORDER_FIELDS)},
                    updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = ? AND client_id = ?""",
                values + [order_id, client_id],
            )
            action = "updated"
        else:
            db.execute(
                f"""INSERT INTO orders (order_id, client_id, {", ".join(ORDER_FIELDS)})
                    VALUES (?, ?, {", ".join("?" for _ in ORDER_FIELDS)})""",
                [order_id, client_id] + values,
            )
            action = "created"
    finally:
        db.close()

    return jsonify({
        "status": "success", "action": action,
        "order_id": order_id, "client_id": client_id
    }), 200


@app.route("/", methods=["GET"])
def dashboard():
    db = get_client()
    try:
        result = db.execute("SELECT * FROM orders ORDER BY created_at DESC")
        orders = rows_to_dicts(result)
    finally:
        db.close()
    return render_template("index.html", orders=orders)


@app.route("/print/order/<order_id>", methods=["GET"])
def print_single_order(order_id):
    client_id = request.args.get("client_id")

    db = get_client()
    try:
        if client_id:
            result = db.execute(
                "SELECT * FROM orders WHERE order_id = ? AND client_id = ?",
                [order_id, client_id],
            )
        else:
            result = db.execute(
                "SELECT * FROM orders WHERE order_id = ?", [order_id]
            )
        orders = rows_to_dicts(result)
    finally:
        db.close()

    if not orders:
        return f"Order {order_id} not found", 404

    return render_template("label.html", orders=[orders[0]])


@app.route("/print/batch", methods=["POST"])
def print_batch_orders():
    selected = request.form.getlist("order_ids")
    if not selected:
        return "No orders selected", 400

    pairs = []
    for item in selected:
        if "::" in item:
            oid, cid = item.split("::", 1)
            pairs.append((oid, cid))

    if not pairs:
        return "Invalid selection", 400

    db = get_client()
    try:
        orders = []
        for order_id, client_id in pairs:
            result = db.execute(
                "SELECT * FROM orders WHERE order_id = ? AND client_id = ?",
                [order_id, client_id],
            )
            orders.extend(rows_to_dicts(result))
    finally:
        db.close()

    if not orders:
        return "No matching orders found", 404

    return render_template("label.html", orders=orders)


@app.route("/orders/delete", methods=["POST"])
def delete_orders():
    selected = request.form.getlist("order_ids")
    if not selected:
        return "No orders selected", 400

    pairs = []
    for item in selected:
        if "::" in item:
            oid, cid = item.split("::", 1)
            pairs.append((oid, cid))

    if not pairs:
        return "Invalid selection", 400

    db = get_client()
    try:
        for order_id, client_id in pairs:
            db.execute(
                "DELETE FROM orders WHERE order_id = ? AND client_id = ?",
                [order_id, client_id],
            )
    finally:
        db.close()

    return redirect("/")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
