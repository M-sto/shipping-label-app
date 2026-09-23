import os
import libsql_client

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

REQUIRED_ORDER_COLUMNS = {
    "customer_name":   "TEXT",
    "phone1":          "TEXT",
    "phone2":          "TEXT",
    "address":         "TEXT",
    "governorate":     "TEXT",
    "collect_amount":  "REAL",
    "shipping_fee":    "REAL",
    "total_amount":    "REAL",
    "status":          "TEXT DEFAULT 'pending'",
}


def get_client():
    return libsql_client.create_client_sync(
        url=TURSO_URL,
        auth_token=TURSO_AUTH_TOKEN,
    )


def rows_to_dicts(result_set):
    """يحول نتيجة libsql-client إلى list of dicts، عشان يشتغل زي sqlite3.Row في القوالب."""
    columns = result_set.columns
    return [dict(zip(columns, row)) for row in result_set.rows]


def ensure_orders_schema(client):
    result = client.execute("PRAGMA table_info(orders)")
    existing = {row[1] for row in result.rows}
    for col, col_type in REQUIRED_ORDER_COLUMNS.items():
        if col not in existing:
            client.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")


def init_db():
    client = get_client()
    try:
        client.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                api_key TEXT UNIQUE NOT NULL,
                client_name TEXT
            )
        """)

        client.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (order_id, client_id),
                FOREIGN KEY (client_id) REFERENCES clients (client_id)
            )
        """)

        ensure_orders_schema(client)

        client.execute("""
            INSERT OR IGNORE INTO clients (client_id, api_key, client_name)
            VALUES ('alzahraa', 'test-api-key-123', 'El-Zahraa')
        """)
    finally:
        client.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")