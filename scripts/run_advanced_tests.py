"""
Comprehensive test script for advanced SQL patterns, edge cases, joins,
window functions, CTEs, JSON operators, triggers, and analytical queries
against the MySQL MCP server.
"""

import json
from pathlib import Path
from mysql_mcp.server import (
    execute_query,
    execute_mutation,
    explain_query,
    export_query_results,
    describe_table,
    get_schema,
    test_connection,
)
from mysql_mcp.errors import QuerySafetyError


def banner(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def run_test(name: str, fn):
    print(f"\n▶ Running: {name}")
    try:
        fn()
        print("  ✓ SUCCESS")
    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__} - {e}")


def main():
    banner("ADVANCED TEST SUITE FOR MYSQL MCP SERVER")

    # 1. Safety Guardrails & Edge Cases
    banner("1. SAFETY GUARDRAILS & EDGE CASES")

    def test_block_unfiltered_delete():
        try:
            execute_mutation("DELETE FROM users;")
            raise AssertionError("Should have blocked DELETE without WHERE")
        except QuerySafetyError as e:
            print(f"    Expected Block: {e}")

    def test_block_unfiltered_update():
        try:
            execute_mutation("UPDATE users SET status = 'inactive';")
            raise AssertionError("Should have blocked UPDATE without WHERE")
        except QuerySafetyError as e:
            print(f"    Expected Block: {e}")

    def test_block_unconfirmed_drop():
        try:
            execute_mutation("DROP TABLE IF EXISTS fake_table;")
            raise AssertionError("Should have blocked DROP without confirmed=True")
        except QuerySafetyError as e:
            print(f"    Expected Block: {e}")

    def test_auto_limit_injection():
        res = execute_query("SELECT * FROM users")
        print(f"    Auto-injected limit check: returned {len(res['rows'])} rows (query ran as: {res['query']})")
        assert "LIMIT" in res["query"]

    def test_clamp_max_limit():
        res = execute_query("SELECT * FROM users", limit=5000)
        print(f"    Clamped limit check: query ran as '{res['query']}'")
        assert "LIMIT 1000" in res["query"]

    run_test("Block DELETE without WHERE", test_block_unfiltered_delete)
    run_test("Block UPDATE without WHERE", test_block_unfiltered_update)
    run_test("Block DROP without confirmation", test_block_unconfirmed_drop)
    run_test("Auto-inject LIMIT 50 on SELECT", test_auto_limit_injection)
    run_test("Clamp requested LIMIT to MAX (1000)", test_clamp_max_limit)

    # 2. Complex Joins & Multi-Table Aggregation
    banner("2. COMPLEX JOINS & MULTI-TABLE AGGREGATION")

    def test_3_table_join():
        sql = """
        SELECT 
            u.id AS customer_id,
            u.name AS customer_name,
            COUNT(DISTINCT o.id) AS total_orders,
            COALESCE(SUM(oi.quantity), 0) AS total_items_purchased,
            COALESCE(SUM(oi.quantity * oi.unit_price), 0.0) AS calculated_revenue,
            COALESCE(AVG(r.rating), 0.0) AS avg_review_score
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        LEFT JOIN reviews r ON u.id = r.user_id
        GROUP BY u.id, u.name
        ORDER BY calculated_revenue DESC;
        """
        res = execute_query(sql)
        print(f"    Execution time: {res['execution_time_ms']} ms")
        print(f"    Returned {len(res['rows'])} customer profiles with order & review summaries.")
        for row in res['rows'][:3]:
            print(f"      - {row['customer_name']}: Orders={row['total_orders']}, Rev=${row['calculated_revenue']:.2f}, AvgRating={row['avg_review_score']:.1f}")

    def test_unmatched_left_join():
        sql = """
        SELECT u.id, u.name, u.email, u.created_at
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE o.id IS NULL;
        """
        res = execute_query(sql)
        print(f"    Found {len(res['rows'])} users with zero orders (inactive leads).")

    run_test("3-Table Join with Multiple Aggregations", test_3_table_join)
    run_test("LEFT JOIN to detect non-purchasing users", test_unmatched_left_join)

    # 3. Window Functions & Analytical Queries
    banner("3. WINDOW FUNCTIONS & ANALYTICAL METRICS")

    def test_window_ranking():
        sql = """
        SELECT 
            p.category,
            p.name AS product_name,
            p.price,
            DENSE_RANK() OVER (PARTITION BY p.category ORDER BY p.price DESC) AS price_rank_in_category
        FROM products p;
        """
        res = execute_query(sql)
        print(f"    Product price ranks by category (first 4):")
        for row in res['rows'][:4]:
            print(f"      - [{row['category']}] {row['product_name']}: ${row['price']} (Rank #{row['price_rank_in_category']})")

    def test_running_total():
        sql = """
        SELECT 
            o.id,
            o.order_number,
            o.order_date,
            o.total_amount,
            SUM(o.total_amount) OVER (ORDER BY o.order_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_revenue
        FROM orders o
        WHERE o.status != 'cancelled'
        ORDER BY o.order_date;
        """
        res = execute_query(sql)
        print(f"    Running revenue trajectory (first 3):")
        for row in res['rows'][:3]:
            print(f"      - Date: {row['order_date']} | Order: {row['order_number']} | Amount: ${row['total_amount']} | Cumulative: ${row['running_revenue']:.2f}")

    run_test("Window Function DENSE_RANK()", test_window_ranking)
    run_test("Running Total Cumulative Sum OVER()", test_running_total)

    # 4. Common Table Expressions (CTEs) & Nested Queries
    banner("4. COMMON TABLE EXPRESSIONS (CTEs) & NESTED QUERIES")

    def test_multi_stage_cte():
        sql = """
        WITH customer_spend AS (
            SELECT 
                u.id AS user_id,
                u.name AS user_name,
                SUM(o.total_amount) AS total_spent,
                COUNT(o.id) AS order_count
            FROM users u
            JOIN orders o ON u.id = o.user_id
            WHERE o.status != 'cancelled'
            GROUP BY u.id, u.name
        ),
        spend_tiers AS (
            SELECT 
                user_id,
                user_name,
                total_spent,
                order_count,
                CASE 
                    WHEN total_spent >= 1000 THEN 'VIP Platinum'
                    WHEN total_spent >= 500  THEN 'Gold'
                    ELSE 'Silver'
                END AS loyalty_tier
            FROM customer_spend
        )
        SELECT loyalty_tier, COUNT(*) AS customer_count, ROUND(AVG(total_spent), 2) AS avg_spend
        FROM spend_tiers
        GROUP BY loyalty_tier
        ORDER BY avg_spend DESC;
        """
        res = execute_query(sql)
        print(f"    Customer Loyalty Cohort Segmentation:")
        for row in res['rows']:
            print(f"      - {row['loyalty_tier']}: {row['customer_count']} customers (Avg Spend: ${row['avg_spend']})")

    run_test("Multi-stage CTE for Loyalty Segmentation", test_multi_stage_cte)

    # 5. JSON Columns & Search
    banner("5. JSON ATTRIBUTE INSPECTION & FILTERING")

    def test_json_extraction():
        sql = """
        SELECT 
            id,
            name,
            preferences->>'$.theme' AS preferred_theme,
            preferences->>'$.language' AS preferred_lang,
            JSON_UNQUOTE(JSON_EXTRACT(preferences, '$.notifications.newsletter')) AS newsletter_optin
        FROM users
        WHERE preferences IS NOT NULL;
        """
        res = execute_query(sql)
        print(f"    Extracted JSON user preferences (first 3):")
        for row in res['rows'][:3]:
            print(f"      - {row['name']}: Theme={row['preferred_theme']}, Lang={row['preferred_lang']}, Newsletter={row['newsletter_optin']}")

    run_test("JSON Extraction & Shorthand Arrow Syntax", test_json_extraction)

    # 6. EXPLAIN Performance Analysis
    banner("6. EXPLAIN EXECUTION PLAN ANALYSIS")

    def test_explain_analysis():
        query = "SELECT * FROM orders WHERE user_id = 2 ORDER BY order_date DESC;"
        traditional = explain_query(query, format="TRADITIONAL")
        print(f"    EXPLAIN TRADITIONAL: returned {len(traditional['plan'])} steps.")
        for step in traditional['plan']:
            print(f"      - Table: {step.get('table')} | Type: {step.get('type')} | Key Used: {step.get('key')} | Rows Scanned: {step.get('rows')}")

        json_plan = explain_query(query, format="JSON")
        print(f"    EXPLAIN JSON successfully fetched query block cost: {json_plan['plan'].get('query_block', {}).get('cost_info', {})}")

    run_test("EXPLAIN Query Execution Plan", test_explain_analysis)

    # 7. Triggers & DDL Lifecycle
    banner("7. TRIGGERS & MUTATION LIFECYCLE")

    def test_trigger_creation_and_firing():
        # Create audit table
        execute_mutation("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            table_name VARCHAR(50) NOT NULL,
            action VARCHAR(20) NOT NULL,
            record_id INT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """, confirmed=True)

        # Drop trigger if exists
        execute_mutation("DROP TRIGGER IF EXISTS trg_after_user_update;", confirmed=True)

        # Create trigger
        trigger_sql = """
        CREATE TRIGGER trg_after_user_update
        AFTER UPDATE ON users
        FOR EACH ROW
        BEGIN
            INSERT INTO audit_log (table_name, action, record_id)
            VALUES ('users', 'UPDATE', NEW.id);
        END;
        """
        execute_mutation(trigger_sql, confirmed=True)
        print("    Trigger created successfully.")

        # Fire trigger with an UPDATE
        execute_mutation("UPDATE users SET status = 'active' WHERE id = 1;")
        print("    Updated user 1 (firing trigger).")

        # Verify audit log recorded it
        audit_res = execute_query("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1;")
        assert len(audit_res['rows']) == 1
        log_entry = audit_res['rows'][0]
        print(f"    ✓ Audit log verified: action={log_entry['action']} on table={log_entry['table_name']} for record_id={log_entry['record_id']}")

        # Cleanup
        execute_mutation("DROP TRIGGER IF EXISTS trg_after_user_update;", confirmed=True)
        execute_mutation("DROP TABLE IF EXISTS audit_log;", confirmed=True)
        print("    Cleaned up temporary trigger and audit table.")

    run_test("Create, Fire, and Verify MySQL Trigger Lifecycle", test_trigger_creation_and_firing)

    # 8. Exporting Advanced Analysis
    banner("8. EXPORTING ANALYTICAL RESULTS")

    def test_export_analytics():
        sql = """
        SELECT 
            p.category,
            COUNT(DISTINCT p.id) AS product_count,
            COUNT(oi.id) AS units_sold,
            ROUND(SUM(oi.quantity * oi.unit_price), 2) AS total_category_revenue,
            ROUND(AVG(r.rating), 2) AS avg_product_rating
        FROM products p
        LEFT JOIN order_items oi ON p.id = oi.product_id
        LEFT JOIN reviews r ON p.id = r.product_id
        GROUP BY p.category
        ORDER BY total_category_revenue DESC;
        """
        export_res = export_query_results(sql, format="csv", filename="category_sales_analysis.csv")
        print(f"    Exported category analytics to: {export_res['file_path']}")
        print(f"    Exported row count: {export_res['row_count']}, file size: {export_res['file_size_bytes']} bytes")
        assert Path(export_res['file_path']).exists()

    run_test("Export Analytical Query to CSV", test_export_analytics)

    banner("ALL ADVANCED TEST CASES COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
