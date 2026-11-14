#!/usr/bin/env python3
"""
Seed script for MySQL MCP Server demo database (ecommerce_demo).
Creates realistic e-commerce tables: users, products, orders, order_items, reviews
with foreign keys, JSON columns, and indexes for comprehensive testing.
"""

import json
import os
import sys
from datetime import datetime, timedelta
import pymysql
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ecommerce_demo")


def get_server_connection():
    """Connect to MySQL server instance without selecting a database."""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_db_connection():
    """Connect directly to the target database."""
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def init_database():
    """Create database if it does not already exist."""
    print(f"Connecting to MySQL server at {MYSQL_HOST}:{MYSQL_PORT} as {MYSQL_USER}...")
    conn = get_server_connection()
    try:
        with conn.cursor() as cursor:
            print(f"Ensuring database '{MYSQL_DATABASE}' exists...")
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
        print(f"Database '{MYSQL_DATABASE}' is ready.")
    finally:
        conn.close()


def create_schema(cursor):
    """Create all required tables with foreign keys, JSON columns, and indexes."""
    print("Creating schema tables (users, products, orders, order_items, reviews)...")

    # Disable foreign key checks during schema creation / drop
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")

    cursor.execute("DROP TABLE IF EXISTS reviews;")
    cursor.execute("DROP TABLE IF EXISTS order_items;")
    cursor.execute("DROP TABLE IF EXISTS orders;")
    cursor.execute("DROP TABLE IF EXISTS products;")
    cursor.execute("DROP TABLE IF EXISTS users;")

    # 1. Users Table
    cursor.execute("""
    CREATE TABLE users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(150) NOT NULL UNIQUE,
        role ENUM('customer', 'admin', 'vendor') NOT NULL DEFAULT 'customer',
        status ENUM('active', 'inactive', 'suspended') NOT NULL DEFAULT 'active',
        preferences JSON NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_users_role_status (role, status),
        INDEX idx_users_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 2. Products Table
    cursor.execute("""
    CREATE TABLE products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        sku VARCHAR(50) NOT NULL UNIQUE,
        name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        price DECIMAL(10, 2) NOT NULL,
        cost DECIMAL(10, 2) NOT NULL,
        stock_quantity INT NOT NULL DEFAULT 0,
        attributes JSON NULL,
        tags JSON NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_products_category (category),
        INDEX idx_products_price (price),
        INDEX idx_products_active_stock (is_active, stock_quantity)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 3. Orders Table
    cursor.execute("""
    CREATE TABLE orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_number VARCHAR(50) NOT NULL UNIQUE,
        user_id INT NOT NULL,
        status ENUM('pending', 'processing', 'shipped', 'delivered', 'cancelled', 'refunded') NOT NULL DEFAULT 'pending',
        total_amount DECIMAL(10, 2) NOT NULL,
        tax_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
        shipping_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
        discount_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
        shipping_address JSON NULL,
        payment_info JSON NULL,
        notes TEXT NULL,
        order_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        INDEX idx_orders_user_id (user_id),
        INDEX idx_orders_status_date (status, order_date),
        INDEX idx_orders_total_amount (total_amount)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 4. Order Items Table
    cursor.execute("""
    CREATE TABLE order_items (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL DEFAULT 1,
        unit_price DECIMAL(10, 2) NOT NULL,
        subtotal DECIMAL(10, 2) NOT NULL,
        customizations JSON NULL,
        CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
        CONSTRAINT fk_order_items_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE RESTRICT,
        INDEX idx_order_items_order_id (order_id),
        INDEX idx_order_items_product_id (product_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 5. Reviews Table
    cursor.execute("""
    CREATE TABLE reviews (
        id INT AUTO_INCREMENT PRIMARY KEY,
        product_id INT NOT NULL,
        user_id INT NOT NULL,
        rating TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
        title VARCHAR(255) NULL,
        comment TEXT NULL,
        helpful_votes INT NOT NULL DEFAULT 0,
        metadata JSON NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_reviews_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
        CONSTRAINT fk_reviews_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        INDEX idx_reviews_product_id (product_id),
        INDEX idx_reviews_user_id (user_id),
        INDEX idx_reviews_rating (rating),
        INDEX idx_reviews_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
    print("Schema tables and indexes created successfully.")


def seed_data(cursor):
    """Seed realistic initial test records into the tables."""
    print("Seeding demo records...")

    # --- Seed Users ---
    users_data = [
        ("Alice Walker", "alice.walker@example.com", "customer", "active", {
            "theme": "dark",
            "currency": "USD",
            "notifications": {"email": True, "sms": False, "push": True},
            "membership_tier": "gold"
        }, datetime(2025, 1, 15, 9, 30)),
        ("Bob Smith", "bob.smith@example.com", "customer", "active", {
            "theme": "light",
            "currency": "USD",
            "notifications": {"email": True, "sms": True, "push": False},
            "membership_tier": "platinum"
        }, datetime(2025, 2, 1, 14, 20)),
        ("Charlie Davis", "charlie.davis@example.com", "customer", "active", {
            "theme": "dark",
            "currency": "EUR",
            "notifications": {"email": False, "sms": False, "push": True},
            "membership_tier": "silver"
        }, datetime(2025, 2, 10, 11, 45)),
        ("Diana Prince", "diana.prince@example.com", "admin", "active", {
            "theme": "dark",
            "dashboard_layout": "compact",
            "admin_access": ["users", "orders", "analytics"],
            "notifications": {"email": True, "sms": True, "push": True}
        }, datetime(2024, 11, 5, 8, 0)),
        ("Evan Wright", "evan.wright@example.com", "vendor", "active", {
            "store_name": "Wright Audio Gear",
            "payout_schedule": "weekly",
            "currency": "USD"
        }, datetime(2024, 12, 1, 10, 15)),
        ("Fiona Gallagher", "fiona.g@example.com", "customer", "active", {
            "theme": "light",
            "currency": "USD",
            "notifications": {"email": True, "sms": False, "push": False},
            "membership_tier": "bronze"
        }, datetime(2025, 3, 5, 16, 10)),
        ("George Miller", "george.m@example.com", "customer", "inactive", {
            "theme": "light",
            "currency": "USD",
            "notifications": {"email": False, "sms": False, "push": False},
            "membership_tier": "bronze"
        }, datetime(2025, 1, 2, 12, 0)),
        ("Hannah Abbott", "hannah.a@example.com", "customer", "active", {
            "theme": "dark",
            "currency": "GBP",
            "notifications": {"email": True, "sms": True, "push": True},
            "membership_tier": "gold"
        }, datetime(2025, 3, 12, 13, 25)),
        ("Ian Malcolm", "ian.malcolm@example.com", "customer", "active", {
            "theme": "dark",
            "currency": "USD",
            "notifications": {"email": True, "sms": False, "push": True},
            "membership_tier": "silver"
        }, datetime(2025, 3, 20, 15, 40)),
        ("Julia Roberts", "julia.r@example.com", "customer", "suspended", {
            "theme": "light",
            "suspension_reason": "chargeback_investigation"
        }, datetime(2025, 2, 18, 17, 50)),
    ]

    for name, email, role, status, prefs, created in users_data:
        cursor.execute(
            """
            INSERT INTO users (name, email, role, status, preferences, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (name, email, role, status, json.dumps(prefs), created)
        )
    print(f"Inserted {len(users_data)} users.")

    # --- Seed Products ---
    products_data = [
        ("PROD-LAP-001", "MacBook Pro 16\"", "Electronics", 2499.99, 1800.00, 25, {
            "brand": "Apple",
            "processor": "M3 Max",
            "ram": "36GB",
            "storage": "1TB SSD",
            "color": "Space Black",
            "warranty_months": 12
        }, ["laptop", "apple", "pro", "electronics"], True),
        ("PROD-PHN-002", "iPhone 16 Pro", "Electronics", 1199.99, 850.00, 45, {
            "brand": "Apple",
            "display": "6.3-inch OLED",
            "storage": "256GB",
            "color": "Natural Titanium",
            "5g_support": True
        }, ["smartphone", "apple", "5g", "bestseller"], True),
        ("PROD-AUD-003", "Sony WH-1000XM5 Headphones", "Electronics", 399.99, 240.00, 60, {
            "brand": "Sony",
            "noise_canceling": True,
            "battery_hours": 30,
            "wireless": True,
            "color": "Silver"
        }, ["audio", "headphones", "wireless", "anc"], True),
        ("PROD-LOG-004", "Logitech MX Master 3S Mouse", "Electronics", 99.99, 55.00, 120, {
            "brand": "Logitech",
            "sensor_dpi": 8000,
            "connectivity": ["Bluetooth", "Logi Bolt"],
            "ergonomic": True
        }, ["accessories", "mouse", "ergonomic", "office"], True),
        ("PROD-DSK-005", "Ergonomic Standing Desk", "Furniture", 549.00, 320.00, 18, {
            "brand": "FlexiSpot",
            "height_range_cm": "70-120",
            "motor_count": 2,
            "desktop_finish": "Solid Oak",
            "max_load_kg": 125
        }, ["furniture", "desk", "standing desk", "ergonomic"], True),
        ("PROD-CHR-006", "Mesh Office Ergonomic Chair", "Furniture", 429.00, 260.00, 30, {
            "brand": "ErgoPro",
            "lumbar_support": "adjustable",
            "material": "breathable mesh",
            "recline_degrees": 135
        }, ["furniture", "chair", "ergonomic", "office"], True),
        ("PROD-COF-007", "Barista Touch Espresso Machine", "Kitchen", 899.95, 590.00, 14, {
            "brand": "Breville",
            "interface": "touchscreen",
            "grinder": "integrated conical burr",
            "pressure_bar": 15
        }, ["kitchen", "coffee", "espresso", "premium"], True),
        ("PROD-KTL-008", "Precision Electric Kettle", "Kitchen", 129.50, 75.00, 40, {
            "brand": "Fellow",
            "capacity_liters": 0.9,
            "temp_control": True,
            "gooseneck": True
        }, ["kitchen", "kettle", "pour over", "coffee"], True),
        ("PROD-SHR-009", "Merino Wool Everyday T-Shirt", "Apparel", 68.00, 28.00, 150, {
            "material": "100% Merino Wool",
            "fit": "regular",
            "breathable": True,
            "odor_resistant": True,
            "sizes_available": ["S", "M", "L", "XL"]
        }, ["apparel", "clothing", "wool", "casual"], True),
        ("PROD-JCK-010", "All-Weather Technical Parka", "Apparel", 280.00, 140.00, 35, {
            "waterproof_rating": "20000mm",
            "insulation": "recycled down",
            "hood": "removable",
            "pockets": 6
        }, ["apparel", "outerwear", "winter", "waterproof"], True),
        ("PROD-BOK-011", "Designing Data-Intensive Applications", "Books", 44.99, 22.00, 80, {
            "author": "Martin Kleppmann",
            "pages": 616,
            "format": "Paperback",
            "isbn": "978-1449373320"
        }, ["books", "engineering", "database", "distributed systems"], True),
        ("PROD-DIS-012", "Discontinued Smart Speaker v1", "Electronics", 79.99, 45.00, 0, {
            "brand": "EchoLegacy",
            "status": "legacy",
            "voice_assistant": "Alexa"
        }, ["electronics", "audio", "clearance"], False),
    ]

    for sku, name, cat, price, cost, stock, attrs, tags, active in products_data:
        cursor.execute(
            """
            INSERT INTO products (sku, name, category, price, cost, stock_quantity, attributes, tags, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (sku, name, cat, price, cost, stock, json.dumps(attrs), json.dumps(tags), active)
        )
    print(f"Inserted {len(products_data)} products.")

    # Fetch product IDs mapping by SKU
    cursor.execute("SELECT id, sku, price FROM products;")
    products_map = {row["sku"]: row for row in cursor.fetchall()}

    # Fetch user IDs mapping by email
    cursor.execute("SELECT id, email FROM users;")
    users_map = {row["email"]: row["id"] for row in cursor.fetchall()}

    # --- Seed Orders & Order Items ---
    now = datetime.now()
    orders_data = [
        # Order 1 (Delivered, Alice)
        {
            "order_number": "ORD-2025-1001",
            "user_id": users_map["alice.walker@example.com"],
            "status": "delivered",
            "tax_amount": 215.99,
            "shipping_amount": 0.00,
            "discount_amount": 100.00,
            "shipping_address": {
                "recipient": "Alice Walker",
                "street": "742 Evergreen Terrace",
                "city": "Springfield",
                "state": "IL",
                "postal_code": "62704",
                "country": "US"
            },
            "payment_info": {
                "method": "credit_card",
                "card_brand": "Visa",
                "last4": "4242",
                "transaction_id": "ch_3N8kL92eZvKYlo2C1gH",
                "paid": True
            },
            "notes": "Please leave package by the side door.",
            "order_date": now - timedelta(days=45),
            "items": [
                ("PROD-LAP-001", 1, None),
                ("PROD-LOG-004", 1, {"engraving": "AW-PRO"})
            ]
        },
        # Order 2 (Delivered, Bob)
        {
            "order_number": "ORD-2025-1002",
            "user_id": users_map["bob.smith@example.com"],
            "status": "delivered",
            "tax_amount": 103.99,
            "shipping_amount": 15.00,
            "discount_amount": 0.00,
            "shipping_address": {
                "recipient": "Bob Smith",
                "street": "100 Market St",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "country": "US"
            },
            "payment_info": {
                "method": "apple_pay",
                "device_account_number": "9081",
                "transaction_id": "ch_3N8kX32eZvKYlo2C2fB",
                "paid": True
            },
            "notes": "Deliver during business hours.",
            "order_date": now - timedelta(days=32),
            "items": [
                ("PROD-PHN-002", 1, {"case_included": True})
            ]
        },
        # Order 3 (Shipped, Charlie)
        {
            "order_number": "ORD-2025-1003",
            "user_id": users_map["charlie.davis@example.com"],
            "status": "shipped",
            "tax_amount": 34.20,
            "shipping_amount": 0.00,
            "discount_amount": 25.00,
            "shipping_address": {
                "recipient": "Charlie Davis",
                "street": "12 Friedrichstrasse",
                "city": "Berlin",
                "state": "BE",
                "postal_code": "10117",
                "country": "DE"
            },
            "payment_info": {
                "method": "paypal",
                "paypal_email": "charlie.davis@example.com",
                "transaction_id": "PAYID-M4589921",
                "paid": True
            },
            "notes": "Ring doorbell twice.",
            "order_date": now - timedelta(days=12),
            "items": [
                ("PROD-AUD-003", 1, None)
            ]
        },
        # Order 4 (Processing, Fiona)
        {
            "order_number": "ORD-2025-1004",
            "user_id": users_map["fiona.g@example.com"],
            "status": "processing",
            "tax_amount": 85.50,
            "shipping_amount": 50.00,
            "discount_amount": 50.00,
            "shipping_address": {
                "recipient": "Fiona Gallagher",
                "street": "2114 South Wallace St",
                "city": "Chicago",
                "state": "IL",
                "postal_code": "60616",
                "country": "US"
            },
            "payment_info": {
                "method": "credit_card",
                "card_brand": "Mastercard",
                "last4": "5512",
                "transaction_id": "ch_3N8rU92eZvKYlo2C3xY",
                "paid": True
            },
            "notes": "Large delivery - ground floor access available.",
            "order_date": now - timedelta(days=3),
            "items": [
                ("PROD-DSK-005", 1, {"desk_top_color": "Oak"}),
                ("PROD-CHR-006", 1, {"headrest": "included"})
            ]
        },
        # Order 5 (Delivered, Hannah)
        {
            "order_number": "ORD-2025-1005",
            "user_id": users_map["hannah.a@example.com"],
            "status": "delivered",
            "tax_amount": 82.35,
            "shipping_amount": 0.00,
            "discount_amount": 0.00,
            "shipping_address": {
                "recipient": "Hannah Abbott",
                "street": "221B Baker St",
                "city": "London",
                "state": "Greater London",
                "postal_code": "NW1 6XE",
                "country": "GB"
            },
            "payment_info": {
                "method": "credit_card",
                "card_brand": "Amex",
                "last4": "3004",
                "transaction_id": "ch_3N9aP02eZvKYlo2C4kM",
                "paid": True
            },
            "notes": "Fragile items inside.",
            "order_date": now - timedelta(days=20),
            "items": [
                ("PROD-COF-007", 1, {"complimentary_beans": "Ethiopian Yirgacheffe"}),
                ("PROD-KTL-008", 1, {"color": "Matte Black"})
            ]
        },
        # Order 6 (Delivered, Ian)
        {
            "order_number": "ORD-2025-1006",
            "user_id": users_map["ian.malcolm@example.com"],
            "status": "delivered",
            "tax_amount": 16.28,
            "shipping_amount": 8.50,
            "discount_amount": 10.00,
            "shipping_address": {
                "recipient": "Ian Malcolm",
                "street": "400 Discovery Way",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US"
            },
            "payment_info": {
                "method": "credit_card",
                "card_brand": "Visa",
                "last4": "1199",
                "transaction_id": "ch_3N9bC12eZvKYlo2C5qR",
                "paid": True
            },
            "notes": "Leave at apartment reception desk.",
            "order_date": now - timedelta(days=15),
            "items": [
                ("PROD-SHR-009", 2, {"size": "L", "color": "Navy"}),
                ("PROD-BOK-011", 1, None)
            ]
        },
        # Order 7 (Pending, Bob)
        {
            "order_number": "ORD-2025-1007",
            "user_id": users_map["bob.smith@example.com"],
            "status": "pending",
            "tax_amount": 25.20,
            "shipping_amount": 10.00,
            "discount_amount": 0.00,
            "shipping_address": {
                "recipient": "Bob Smith",
                "street": "100 Market St",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "country": "US"
            },
            "payment_info": {
                "method": "credit_card",
                "card_brand": "Visa",
                "last4": "4242",
                "transaction_id": "ch_pending_auth_99182",
                "paid": False
            },
            "notes": "Awaiting payment verification.",
            "order_date": now - timedelta(hours=6),
            "items": [
                ("PROD-JCK-010", 1, {"size": "XL"})
            ]
        },
        # Order 8 (Cancelled, Charlie)
        {
            "order_number": "ORD-2025-1008",
            "user_id": users_map["charlie.davis@example.com"],
            "status": "cancelled",
            "tax_amount": 8.00,
            "shipping_amount": 5.00,
            "discount_amount": 0.00,
            "shipping_address": {
                "recipient": "Charlie Davis",
                "street": "12 Friedrichstrasse",
                "city": "Berlin",
                "state": "BE",
                "postal_code": "10117",
                "country": "DE"
            },
            "payment_info": {
                "method": "paypal",
                "status": "voided"
            },
            "notes": "Customer requested cancellation before fulfillment.",
            "order_date": now - timedelta(days=5),
            "items": [
                ("PROD-LOG-004", 1, None)
            ]
        },
    ]

    total_order_items = 0
    for order in orders_data:
        # Calculate items subtotal
        items_subtotal = 0.0
        order_items_resolved = []
        for sku, qty, custom in order["items"]:
            prod = products_map[sku]
            unit_price = float(prod["price"])
            subtotal = round(unit_price * qty, 2)
            items_subtotal += subtotal
            order_items_resolved.append({
                "product_id": prod["id"],
                "quantity": qty,
                "unit_price": unit_price,
                "subtotal": subtotal,
                "customizations": custom
            })

        total_amount = round(
            items_subtotal + order["tax_amount"] + order["shipping_amount"] - order["discount_amount"],
            2
        )

        cursor.execute(
            """
            INSERT INTO orders (
                order_number, user_id, status, total_amount, tax_amount,
                shipping_amount, discount_amount, shipping_address, payment_info,
                notes, order_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                order["order_number"],
                order["user_id"],
                order["status"],
                total_amount,
                order["tax_amount"],
                order["shipping_amount"],
                order["discount_amount"],
                json.dumps(order["shipping_address"]),
                json.dumps(order["payment_info"]),
                order["notes"],
                order["order_date"]
            )
        )
        order_id = cursor.lastrowid

        for item in order_items_resolved:
            cursor.execute(
                """
                INSERT INTO order_items (
                    order_id, product_id, quantity, unit_price, subtotal, customizations
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    item["product_id"],
                    item["quantity"],
                    item["unit_price"],
                    item["subtotal"],
                    json.dumps(item["customizations"]) if item["customizations"] else None
                )
            )
            total_order_items += 1

    print(f"Inserted {len(orders_data)} orders with {total_order_items} order items.")

    # --- Seed Reviews ---
    reviews_data = [
        (
            products_map["PROD-LAP-001"]["id"],
            users_map["alice.walker@example.com"],
            5,
            "Incredible performance and screen",
            "Upgraded from an Intel MacBook Pro. The M3 Max speed and battery life are remarkable. The display is gorgeous for photography work.",
            34,
            {"verified_purchase": True, "source": "web", "device": "macOS"}
        ),
        (
            products_map["PROD-PHN-002"]["id"],
            users_map["bob.smith@example.com"],
            4,
            "Solid upgrade, battery lasts all day",
            "Camera zoom is sharp and USB-C is finally here. Wish the dynamic island had more app integration, but overall very happy.",
            19,
            {"verified_purchase": True, "source": "ios_app"}
        ),
        (
            products_map["PROD-AUD-003"]["id"],
            users_map["charlie.davis@example.com"],
            5,
            "Best active noise cancellation on planes",
            "Drowns out airplane cabin rumble effortlessly. Comfortable for 8+ hour flights without pinching my ears.",
            27,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-LOG-004"]["id"],
            users_map["alice.walker@example.com"],
            5,
            "Ergonomic perfection for daily coding",
            "The quiet clicks are delightful and thumb scroll makes wide spreadsheets breeze to navigate.",
            42,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-DSK-005"]["id"],
            users_map["fiona.g@example.com"],
            4,
            "Very sturdy standing desk, quiet dual motors",
            "Assembly took about 45 minutes. The preset heights work seamlessly. Beautiful oak desktop finish.",
            15,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-CHR-006"]["id"],
            users_map["fiona.g@example.com"],
            5,
            "Saved my lower back",
            "I sit 9 hours a day. The adjustable lumbar support eliminated my lower back tension within a week.",
            38,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-COF-007"]["id"],
            users_map["hannah.a@example.com"],
            5,
            "Cafe-quality espresso in 3 minutes",
            "Intuitive touch screen guides through grind size and extraction. Steam wand microfoam texture is barista level.",
            53,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-KTL-008"]["id"],
            users_map["hannah.a@example.com"],
            4,
            "Precise temperature pour over kettle",
            "Pour control is exact with the counterbalanced handle. Reaches boiling temperature fast.",
            11,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-SHR-009"]["id"],
            users_map["ian.malcolm@example.com"],
            5,
            "Exceptional travel shirt",
            "Wore this on a three-day hiking trip. Doesn't hold any odors and regulates temperature amazingly.",
            18,
            {"verified_purchase": True, "source": "android_app"}
        ),
        (
            products_map["PROD-BOK-011"]["id"],
            users_map["ian.malcolm@example.com"],
            5,
            "Must-read bible for backend software engineers",
            "Martin Kleppmann explains replication, partitioning, consensus and transactions with unparalleled clarity.",
            89,
            {"verified_purchase": True, "source": "web"}
        ),
        (
            products_map["PROD-LOG-004"]["id"],
            users_map["bob.smith@example.com"],
            3,
            "Good mouse but software is heavy",
            "Hardware is top notch, but Options+ software can consume more memory than necessary on Mac.",
            8,
            {"verified_purchase": False, "source": "web"}
        ),
    ]

    for prod_id, u_id, rating, title, comment, votes, meta in reviews_data:
        cursor.execute(
            """
            INSERT INTO reviews (
                product_id, user_id, rating, title, comment, helpful_votes, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (prod_id, u_id, rating, title, comment, votes, json.dumps(meta))
        )
    print(f"Inserted {len(reviews_data)} reviews.")


def verify_seeding(cursor):
    """Verify table counts and foreign key integrity."""
    print("\n--- Verifying Database Seeding ---")
    tables = ["users", "products", "orders", "order_items", "reviews"]
    counts = {}
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table};")
        res = cursor.fetchone()
        counts[table] = res["cnt"]
        print(f"Table '{table}': {res['cnt']} rows")

    # Verify foreign key integrity
    cursor.execute("""
        SELECT COUNT(*) AS invalid_count
        FROM orders o
        LEFT JOIN users u ON o.user_id = u.id
        WHERE u.id IS NULL;
    """)
    orphan_orders = cursor.fetchone()["invalid_count"]

    cursor.execute("""
        SELECT COUNT(*) AS invalid_count
        FROM order_items oi
        LEFT JOIN orders o ON oi.order_id = o.id
        WHERE o.id IS NULL;
    """)
    orphan_items = cursor.fetchone()["invalid_count"]

    cursor.execute("""
        SELECT COUNT(*) AS invalid_count
        FROM reviews r
        LEFT JOIN products p ON r.product_id = p.id
        WHERE p.id IS NULL;
    """)
    orphan_reviews = cursor.fetchone()["invalid_count"]

    if orphan_orders == 0 and orphan_items == 0 and orphan_reviews == 0:
        print("Foreign key integrity check: PASSED (0 orphaned records)")
    else:
        print(f"Foreign key integrity check: FAILED (orders:{orphan_orders}, items:{orphan_items}, reviews:{orphan_reviews})")
        sys.exit(1)

    # Verify JSON column extraction works
    cursor.execute("""
        SELECT
            p.name,
            JSON_UNQUOTE(JSON_EXTRACT(p.attributes, '$.brand')) AS brand,
            JSON_LENGTH(p.tags) AS tag_count
        FROM products p
        LIMIT 3;
    """)
    json_samples = cursor.fetchall()
    print("\nJSON Column Verification Sample:")
    for sample in json_samples:
        print(f"  - {sample['name']}: Brand={sample['brand']}, Tags Count={sample['tag_count']}")

    print("\n--- Database Seeding Completed Successfully! ---")


def main():
    try:
        init_database()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                create_schema(cursor)
                seed_data(cursor)
                conn.commit()
                verify_seeding(cursor)
        except Exception as e:
            conn.rollback()
            print(f"Error during seeding: {e}", file=sys.stderr)
            raise
        finally:
            conn.close()
    except Exception as e:
        print(f"Failed to seed demo database: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

