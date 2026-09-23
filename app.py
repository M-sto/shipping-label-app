import os
from functools import wraps
from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, session
)
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_client, init_db, rows_to_dicts

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-production")

try:
    init_db()
except Exception as e:
    print(f"DB init warning: {e}")

ORDER_FIELDS = [
    "customer_name", "phone1", "phone2", "address",
    "governorate", "collect_amount", "shipping_fee", "total_amount",
]


# ------------------------------------------------------------------
# مصادقة الـ API (للطلبات القادمة من جوجل شيتس - api_key)
# ------------------------------------------------------------------
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


# ------------------------------------------------------------------
# مصادقة تسجيل الدخول للوحة التحكم (session-based)
# ------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "client_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "client_id" not in session:
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return "غير مصرح لك بالوصول لهذه الصفحة", 403
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    db = get_client()
    try:
        result = db.execute(
            "SELECT * FROM clients WHERE username = ?", [username]
        )
        rows = rows_to_dicts(result)
    finally:
        db.close()

    if not rows or not rows[0].get("password_hash"):
        return render_template("login.html", error="بيانات الدخول غير صحيحة")

    user = rows[0]
    if not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="بيانات الدخول غير صحيحة")

    session["client_id"] = user["client_id"]
    session["client_name"] = user["client_name"]
    session["is_admin"] = bool(user.get("is_admin"))
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------
# استقبال الطلبات من جوجل شيتس
# ------------------------------------------------------------------
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


# ------------------------------------------------------------------
# لوحة التحكم - كل عميل يشوف طلباته بس، الأدمن يشوف الكل
# ------------------------------------------------------------------
@app.route("/", methods=["GET"])
@login_required
def dashboard():
    db = get_client()
    try:
        if session.get("is_admin"):
            result = db.execute("SELECT * FROM orders ORDER BY created_at DESC")
        else:
            result = db.execute(
                "SELECT * FROM orders WHERE client_id = ? ORDER BY created_at DESC",
                [session["client_id"]],
            )
        orders = rows_to_dicts(result)
    finally:
        db.close()

    return render_template(
        "index.html",
        orders=orders,
        is_admin=session.get("is_admin"),
        client_name=session.get("client_name"),
    )


@app.route("/print/order/<order_id>", methods=["GET"])
@login_required
def print_single_order(order_id):
    db = get_client()
    try:
        if session.get("is_admin"):
            client_id = request.args.get("client_id")
            if client_id:
                result = db.execute(
                    "SELECT * FROM orders WHERE order_id = ? AND client_id = ?",
                    [order_id, client_id],
                )
            else:
                result = db.execute(
                    "SELECT * FROM orders WHERE order_id = ?", [order_id]
                )
        else:
            result = db.execute(
                "SELECT * FROM orders WHERE order_id = ? AND client_id = ?",
                [order_id, session["client_id"]],
            )
        orders = rows_to_dicts(result)
    finally:
        db.close()

    if not orders:
        return f"Order {order_id} not found", 404

    return render_template("label.html", orders=[orders[0]])


@app.route("/print/batch", methods=["POST"])
@login_required
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
            # عميل عادي: مينفعش يطبع طلب عميل تاني حتى لو عدّل الطلب يدويًا
            if not session.get("is_admin") and client_id != session["client_id"]:
                continue
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
@login_required
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
            if not session.get("is_admin") and client_id != session["client_id"]:
                continue
            db.execute(
                "DELETE FROM orders WHERE order_id = ? AND client_id = ?",
                [order_id, client_id],
            )
    finally:
        db.close()

    return redirect(url_for("dashboard"))


# ------------------------------------------------------------------
# صفحات الأدمن - إدارة العملاء
# ------------------------------------------------------------------
@app.route("/admin/clients", methods=["GET"])
@admin_required
def admin_clients():
    db = get_client()
    try:
        result = db.execute("SELECT * FROM clients ORDER BY client_id")
        clients = rows_to_dicts(result)
    finally:
        db.close()
    return render_template("admin_clients.html", clients=clients, message=None)


@app.route("/admin/clients/add", methods=["POST"])
@admin_required
def admin_add_client():
    import secrets as _secrets

    client_id = request.form.get("client_id", "").strip()
    client_name = request.form.get("client_name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not all([client_id, client_name, username, password]):
        return "جميع الحقول مطلوبة", 400

    api_key = _secrets.token_hex(16)
    password_hash = generate_password_hash(password)

    db = get_client()
    try:
        db.execute(
            """INSERT INTO clients (client_id, api_key, client_name, username, password_hash, is_admin)
               VALUES (?, ?, ?, ?, ?, 0)""",
            [client_id, api_key, client_name, username, password_hash],
        )
    finally:
        db.close()

    return redirect(url_for("admin_clients"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
