"""Tests for FastMCP server tools, resources, and prompts registration and execution."""

import asyncio
from pathlib import Path
import pytest
from mysql_mcp.errors import QuerySafetyError
from mysql_mcp.server import (
    configure_connection,
    describe_table,
    execute_mutation,
    execute_query,
    explain_query,
    export_query_results,
    generate_sql,
    get_query_patterns_resource,
    get_schema,
    get_schema_resource,
    list_tables,
    mcp,
    optimize_query,
    test_connection as tool_test_connection,
)

EXPECTED_TOOLS = {
    "test_connection",
    "configure_connection",
    "list_tables",
    "describe_table",
    "get_schema",
    "execute_query",
    "execute_mutation",
    "explain_query",
    "export_query_results",
}

EXPECTED_RESOURCES = {
    "mysql://schema",
    "mysql://query-patterns",
}

EXPECTED_PROMPTS = {
    "generate_sql",
    "optimize_query",
}


class TestServerRegistration:
    """Test that all 9 tools, 2 resources, and 2 prompts are registered with FastMCP."""

    def test_tools_registered(self):
        registered_tools = {t.name for t in asyncio.run(mcp.list_tools())}
        assert EXPECTED_TOOLS.issubset(registered_tools)
        assert len(registered_tools) == 9

    def test_resources_registered(self):
        registered_resources = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
        assert EXPECTED_RESOURCES.issubset(registered_resources)
        assert len(registered_resources) == 2

    def test_prompts_registered(self):
        registered_prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
        assert EXPECTED_PROMPTS.issubset(registered_prompts)
        assert len(registered_prompts) == 2


class TestToolExecution:
    """Test execution and error handling of all 9 MCP tools."""

    def test_tool_test_connection(self):
        res = tool_test_connection()
        assert isinstance(res, dict)
        assert res["status"] == "healthy"
        assert "version" in res
        assert "latency_ms" in res
        assert res["database"] == "ecommerce_demo"

    def test_tool_configure_connection(self):
        res = configure_connection(database="ecommerce_demo")
        assert isinstance(res, dict)
        assert res["status"] == "configured"
        assert res["connected"] is True
        assert res["active_configuration"]["database"] == "ecommerce_demo"

    def test_tool_list_tables(self):
        tables = list_tables()
        assert isinstance(tables, list)
        table_names = {t["table_name"] for t in tables}
        expected = {"users", "products", "orders", "order_items", "reviews"}
        assert expected.issubset(table_names)

        users_meta = next(t for t in tables if t["table_name"] == "users")
        assert users_meta["table_type"] == "BASE TABLE"
        assert users_meta["columns_count"] >= 8

    def test_tool_describe_table_existing(self):
        info = describe_table("users")
        assert info["table_name"] == "users"
        assert info["primary_key"] == ["id"]
        col_names = [c["name"] for c in info["columns"]]
        assert "id" in col_names
        assert "email" in col_names
        assert len(info["indexes"]) > 0

    def test_tool_describe_table_nonexistent(self):
        with pytest.raises(ValueError) as exc:
            describe_table("non_existent_table_xyz")
        assert "does not exist" in str(exc.value)

    def test_tool_get_schema_markdown(self):
        md = get_schema(format="markdown")
        assert isinstance(md, str)
        assert "# Database Schema: `ecommerce_demo`" in md
        assert "## Tables Overview" in md

    def test_tool_get_schema_json(self):
        schema_dict = get_schema(format="json")
        assert isinstance(schema_dict, dict)
        assert schema_dict["database"] == "ecommerce_demo"
        assert "tables" in schema_dict

    def test_tool_execute_query_success(self):
        res = execute_query("SELECT id, name, email FROM users ORDER BY id ASC;", limit=3)
        assert isinstance(res, dict)
        assert res["columns"] == ["id", "name", "email"]
        assert len(res["rows"]) == 3
        assert "execution_time_ms" in res
        assert res["row_count"] == 3

    def test_tool_execute_query_rejects_mutation(self):
        with pytest.raises(QuerySafetyError) as exc:
            execute_query("DELETE FROM users WHERE id = 999;")
        assert "execute_query only permits read-only operations" in str(exc.value)

    def test_tool_execute_mutation_transaction_lifecycle(self):
        # 1. Insert test record
        insert_sql = "INSERT INTO users (name, email) VALUES ('Temp Test User', 'temp.test@example.com');"
        insert_res = execute_mutation(insert_sql)
        assert insert_res["statement_type"] == "INSERT"
        assert insert_res["affected_rows"] == 1
        assert insert_res["last_insert_id"] > 0
        assert insert_res["status"] == "committed"

        # 2. Update test record
        update_sql = "UPDATE users SET status = 'inactive' WHERE email = 'temp.test@example.com';"
        update_res = execute_mutation(update_sql)
        assert update_res["statement_type"] == "UPDATE"
        assert update_res["affected_rows"] == 1

        # 3. Clean up test record
        delete_sql = "DELETE FROM users WHERE email = 'temp.test@example.com';"
        delete_res = execute_mutation(delete_sql)
        assert delete_res["statement_type"] == "DELETE"
        assert delete_res["affected_rows"] == 1

    def test_tool_execute_mutation_blocks_unconstrained_update(self):
        with pytest.raises(QuerySafetyError):
            execute_mutation("UPDATE users SET status = 'active';")

    def test_tool_execute_mutation_blocks_unconfirmed_ddl(self):
        with pytest.raises(QuerySafetyError) as exc:
            execute_mutation("DROP TABLE users;")
        assert "confirmed=True" in str(exc.value)

    def test_tool_explain_query_formats(self):
        query = "SELECT * FROM orders WHERE status = 'delivered';"

        # 1. TRADITIONAL format
        trad = explain_query(query, format="TRADITIONAL")
        assert trad["format"] == "TRADITIONAL"
        assert len(trad["raw_rows"]) > 0
        assert "select_type" in trad["raw_rows"][0]

        # 2. JSON format
        json_plan = explain_query(query, format="JSON")
        assert json_plan["format"] == "JSON"
        assert isinstance(json_plan["plan"], dict)
        assert "query_block" in json_plan["plan"]

        # 3. TREE format
        tree_plan = explain_query(query, format="TREE")
        assert tree_plan["format"] == "TREE"
        assert isinstance(tree_plan["plan"], str)

    def test_tool_explain_query_invalid_format(self):
        with pytest.raises(ValueError):
            explain_query("SELECT 1;", format="INVALID_FORMAT")

    def test_tool_export_query_results_csv(self):
        sql = "SELECT id, name, price, category FROM products;"
        res = export_query_results(sql, format="csv", filename="test_products.csv")
        assert res["format"] == "csv"
        assert res["row_count"] == 12
        assert res["file_size_bytes"] > 0

        target_file = Path(res["file_path"])
        assert target_file.exists()
        content = target_file.read_text(encoding="utf-8")
        assert "id,name,price,category" in content
        assert "MacBook Pro" in content

    def test_tool_export_query_results_json(self):
        sql = "SELECT id, name, email FROM users LIMIT 3;"
        res = export_query_results(sql, format="json", filename="test_users.json")
        assert res["format"] == "json"
        assert res["row_count"] == 3

        target_file = Path(res["file_path"])
        assert target_file.exists()
        content = target_file.read_text(encoding="utf-8")
        assert "Alice Walker" in content

    def test_tool_export_query_results_rejects_mutation(self):
        with pytest.raises(QuerySafetyError):
            export_query_results("DELETE FROM users WHERE id = 1;")


class TestResourcesAndPrompts:
    """Test reading MCP resources and rendering MCP prompts."""

    def test_resource_mysql_schema(self):
        # Direct function call
        content = get_schema_resource()
        assert "# Database Schema: `ecommerce_demo`" in content

        # Async FastMCP read_resource
        res = asyncio.run(mcp.read_resource("mysql://schema"))
        assert len(res.contents) == 1
        assert "# Database Schema: `ecommerce_demo`" in res.contents[0].content

    def test_resource_mysql_query_patterns(self):
        content = get_query_patterns_resource()
        assert "MySQL Advanced Query Patterns" in content or "Query Patterns" in content

        res = asyncio.run(mcp.read_resource("mysql://query-patterns"))
        assert len(res.contents) == 1
        assert len(res.contents[0].content) > 100

    def test_prompt_generate_sql(self):
        prompt_text = generate_sql("Calculate monthly recurring revenue for 2025")
        assert "Calculate monthly recurring revenue for 2025" in prompt_text
        assert "explicit JOIN syntax" in prompt_text

        # FastMCP render_prompt
        rendered = asyncio.run(
            mcp.render_prompt(
                "generate_sql",
                {"user_request": "List active subscribers"},
            )
        )
        assert len(rendered.messages) == 1
        assert "List active subscribers" in rendered.messages[0].content.text

    def test_prompt_optimize_query(self):
        prompt_text = optimize_query("SELECT * FROM orders WHERE total_amount > 500;")
        assert "SELECT * FROM orders WHERE total_amount > 500;" in prompt_text
        assert "Full Table Scan" in prompt_text

        rendered = asyncio.run(
            mcp.render_prompt(
                "optimize_query",
                {"sql_query": "SELECT * FROM users WHERE status = 'active'"},
            )
        )
        assert len(rendered.messages) == 1
        assert "SELECT * FROM users WHERE status = 'active'" in rendered.messages[0].content.text
