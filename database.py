import os
import secrets
import libsql_client
from werkzeug.security import generate_password_hash

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

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

REQUIRED_CLIENT_COLUMNS = {
    "username":      "TEXT",
    "password_hash": "TEXT",
    "is_admin":      "INTEGER DEFAULT 0",
    "is_active":      "INTEGER DEFAULT 1",
}


def get_client():
    http_url = TURSO_URL.replace("libsql://", "https://")
    return libsql_client.create_client_sync(
        url=http_url,
        auth_token=TURSO_AUTH_TOKEN,
    )


def rows_to_dicts(result_set):
    columns = result_set.columns
    return [dict(zip(columns, row)) for row in result_set.rows]


def ensure_table_schema(client, table, required_columns):
    result = client.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in result.rows}
    for col, col_type in required_columns.items():
        if col not in existing:
            client.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


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

        ensure_table_schema(client, "orders", REQUIRED_ORDER_COLUMNS)
        ensure_table_schema(client, "clients", REQUIRED_CLIENT_COLUMNS)

        client.execute("""
            INSERT OR IGNORE INTO clients (client_id, api_key, client_name)
            VALUES ('alzahraa', 'test-api-key-123', 'El-Zahraa')
        """)

        result = client.execute("SELECT client_id FROM clients WHERE is_admin = 1")
        if not result.rows:
            admin_password = ADMIN_PASSWORD or secrets.token_urlsafe(9)
            password_hash = generate_password_hash(admin_password)
            admin_api_key = secrets.token_hex(16)

            client.execute(
                """INSERT OR IGNORE INTO clients
                   (client_id, api_key, client_name, username, password_hash, is_admin, is_active)
                   VALUES (?, ?, ?, ?, ?, 1, 1)""",
                ["admin", admin_api_key, "Administrator", ADMIN_USERNAME, password_hash],
            )

            if not ADMIN_PASSWORD:
                print(f"=== تم إنشاء حساب Admin تلقائيًا ===")
                print(f"Username: {ADMIN_USERNAME}")
                print(f"Password: {admin_password}")
    finally:
        client.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
