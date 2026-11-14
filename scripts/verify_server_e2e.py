#!/usr/bin/env python3
"""
End-to-end verification script for MySQL MCP Server.
Tests connection health, table listing, table inspection, query execution with JOINs,
and CSV export functionality.
"""

from pathlib import Path
import sys

# Ensure src/ is on python search path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mysql_mcp.server import (
    describe_table,
    execute_query,
    export_query_results,
    list_tables,
    test_connection,
)


def run_e2e_verification():
    print("=" * 70)
    print("MySQL MCP Server - End-to-End Verification")
    print("=" * 70)

    # 1. Connection Health Check
    print("\n[Step 1/5] Testing MySQL Connection Health...")
    ping_result = test_connection()
    if ping_result.get("status") != "healthy":
        print(f"FAILED: MySQL connection unhealthy: {ping_result}")
        sys.exit(1)
    print(f"  ✓ Connected to MySQL {ping_result.get('version')}")
    print(f"  ✓ Active Database: {ping_result.get('database')}")
    print(f"  ✓ Roundtrip Latency: {ping_result.get('latency_ms')} ms")
    print(f"  ✓ Pool Capacity: {ping_result.get('pool', {}).get('max_capacity')} connections")

    # 2. Table Listing
    print("\n[Step 2/5] Fetching Database Tables...")
    tables = list_tables()
    table_names = [t["table_name"] for t in tables]
    print(f"  ✓ Discovered {len(tables)} tables: {', '.join(table_names)}")
    expected_tables = {"users", "products", "orders", "order_items", "reviews"}
    if not expected_tables.issubset(set(table_names)):
        print(f"FAILED: Expected tables {expected_tables} missing from {table_names}")
        sys.exit(1)

    # 3. Table Inspection (users)
    print("\n[Step 3/5] Describing 'users' Table Schema...")
    users_info = describe_table("users")
    columns = users_info.get("columns", [])
    primary_keys = users_info.get("primary_key", [])
    indexes = users_info.get("indexes", [])
    print(f"  ✓ Primary Key: {primary_keys}")
    print(f"  ✓ Columns ({len(columns)}):")
    for col in columns:
        col_type = col.get("column_type")
        nullable = "NULL" if col.get("nullable") else "NOT NULL"
        extra = f" [{col.get('extra')}]" if col.get("extra") else ""
        print(f"      - {col.get('name')}: {col_type} {nullable}{extra}")
    print(f"  ✓ Indexes ({len(indexes)}): {', '.join(idx.get('name') for idx in indexes)}")

    # 4. SQL Query Execution with JOIN
    print("\n[Step 4/5] Executing Sample Read-Only JOIN Query...")
    sample_sql = """
    SELECT
        o.order_number,
        u.name AS customer_name,
        u.email AS customer_email,
        o.status AS order_status,
        o.total_amount,
        o.order_date
    FROM orders o
    INNER JOIN users u ON o.user_id = u.id
    ORDER BY o.order_date DESC
    LIMIT 10;
    """
    query_result = execute_query(sample_sql, limit=10)
    rows = query_result.get("rows", [])
    elapsed = query_result.get("execution_time_ms")
    print(f"  ✓ Query executed successfully in {elapsed} ms")
    print(f"  ✓ Rows returned: {len(rows)}")
    print("  ✓ Sample records:")
    for r in rows[:3]:
        print(
            f"      - Order: {r.get('order_number')} | Customer: {r.get('customer_name')} "
            f"| Status: {r.get('order_status')} | Total: ${r.get('total_amount')}"
        )

    # 5. CSV Export Verification
    print("\n[Step 5/5] Exporting Query Results to CSV...")
    export_filename = "demo_orders.csv"
    export_result = export_query_results(
        sample_sql,
        format="csv",
        filename=export_filename,
    )
    exported_path = Path(export_result["file_path"])
    print(f"  ✓ Export reported target: {exported_path}")
    print(f"  ✓ Export row count: {export_result.get('row_count')}")

    if not exported_path.exists():
        print(f"FAILED: Export file does not exist on disk: {exported_path}")
        sys.exit(1)

    file_size = exported_path.stat().st_size
    if file_size == 0:
        print(f"FAILED: Export file is empty: {exported_path}")
        sys.exit(1)

    print(f"  ✓ File successfully verified on disk ({file_size} bytes)")
    with open(exported_path, "r", encoding="utf-8") as f:
        first_lines = [f.readline().strip() for _ in range(3)]
    print(f"  ✓ Header preview: {first_lines[0]}")
    if len(first_lines) > 1 and first_lines[1]:
        print(f"  ✓ First row preview: {first_lines[1]}")

    print("\n" + "=" * 70)
    print("🎉 ALL END-TO-END VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_e2e_verification()

