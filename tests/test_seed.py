"""Basic verification test for database connection and seeded schema."""

import os
import pymysql
from dotenv import load_dotenv

load_dotenv()


def test_database_connection_and_seeded_tables():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "ecommerce_demo")

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
    )

    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES;")
            tables = {list(row.values())[0] for row in cursor.fetchall()}
            expected_tables = {"users", "products", "orders", "order_items", "reviews"}
            assert expected_tables.issubset(tables)

            for table in expected_tables:
                cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table};")
                count = cursor.fetchone()["cnt"]
                assert count > 0, f"Table {table} has no rows"
    finally:
        conn.close()

