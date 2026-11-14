"""Tests for SQL safety rules, classification, and LIMIT injection."""

import pytest
from mysql_mcp.errors import QuerySafetyError
from mysql_mcp.safety import (
    get_statement_type,
    has_where_clause,
    inject_limit,
    is_mutation,
    is_read_only,
    validate_mutation_safety,
)


class TestStatementClassification:
    """Test read-only vs mutation query identification."""

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM users",
            "SELECT id, name FROM users WHERE id = 1;",
            "/* leading comment */ SELECT * FROM products",
            "-- comment\nSELECT * FROM orders",
            "SHOW TABLES;",
            "SHOW DATABASES;",
            "SHOW CREATE TABLE users;",
            "DESCRIBE users;",
            "DESC products;",
            "EXPLAIN SELECT * FROM orders;",
            "WITH cte AS (SELECT 1) SELECT * FROM cte;",
        ],
    )
    def test_is_read_only_true_for_read_queries(self, query: str):
        assert is_read_only(query) is True
        assert is_mutation(query) is False

    @pytest.mark.parametrize(
        "query",
        [
            "UPDATE users SET name = 'Alice' WHERE id = 1;",
            "UPDATE users SET status = 'active';",
            "DELETE FROM users WHERE id = 1;",
            "DELETE FROM users;",
            "INSERT INTO users (name, email) VALUES ('Bob', 'bob@example.com');",
            "REPLACE INTO users (id, name) VALUES (1, 'Charlie');",
            "DROP TABLE users;",
            "TRUNCATE TABLE logs;",
            "ALTER TABLE users ADD COLUMN phone VARCHAR(20);",
            "CREATE TABLE temp_test (id INT);",
        ],
    )
    def test_is_read_only_false_for_mutation_queries(self, query: str):
        assert is_read_only(query) is False
        assert is_mutation(query) is True

    def test_multi_statement_with_mutation(self):
        query = "SELECT * FROM users; DROP TABLE users;"
        assert is_read_only(query) is False
        assert is_mutation(query) is True


class TestMutationSafety:
    """Test rejection of unfiltered UPDATE and DELETE statements."""

    def test_delete_without_where_raises_error(self):
        with pytest.raises(QuerySafetyError) as exc_info:
            validate_mutation_safety("DELETE FROM users;")
        assert "without a WHERE clause" in str(exc_info.value)
        assert "DELETE" in str(exc_info.value)

    def test_update_without_where_raises_error(self):
        with pytest.raises(QuerySafetyError) as exc_info:
            validate_mutation_safety("UPDATE users SET status = 'inactive';")
        assert "without a WHERE clause" in str(exc_info.value)
        assert "UPDATE" in str(exc_info.value)

    def test_delete_with_where_passes(self):
        validate_mutation_safety("DELETE FROM users WHERE id = 42;")

    def test_update_with_where_passes(self):
        validate_mutation_safety("UPDATE users SET status = 'active' WHERE id = 1;")

    def test_delete_without_where_allowed_when_explicit(self):
        validate_mutation_safety("DELETE FROM users;", allow_unfiltered=True)

    def test_update_without_where_allowed_when_explicit(self):
        validate_mutation_safety("UPDATE users SET status = 'active';", allow_unfiltered=True)

    def test_empty_where_clause_raises_error(self):
        with pytest.raises(QuerySafetyError):
            validate_mutation_safety("DELETE FROM users WHERE ;")

    def test_comment_only_where_clause_raises_error(self):
        with pytest.raises(QuerySafetyError):
            validate_mutation_safety("DELETE FROM users WHERE /* just a comment */ ;")

    def test_subquery_where_with_unfiltered_outer_update_raises_error(self):
        query = "UPDATE users SET status = (SELECT code FROM statuses WHERE id = 1);"
        with pytest.raises(QuerySafetyError):
            validate_mutation_safety(query)


class TestLimitInjection:
    """Test LIMIT clause injection and clamping on SELECT queries."""

    def test_inject_default_limit_without_semicolon(self):
        sql = "SELECT * FROM users"
        result = inject_limit(sql, limit=50)
        assert result == "SELECT * FROM users LIMIT 50"

    def test_inject_default_limit_with_semicolon(self):
        sql = "SELECT id, name FROM users;"
        result = inject_limit(sql, limit=50)
        assert result == "SELECT id, name FROM users LIMIT 50;"

    def test_preserve_existing_limit_under_max(self):
        sql = "SELECT * FROM products LIMIT 10;"
        result = inject_limit(sql, limit=50, max_limit=1000)
        assert result == "SELECT * FROM products LIMIT 10;"

    def test_clamp_existing_limit_exceeding_max(self):
        sql = "SELECT * FROM orders LIMIT 5000;"
        result = inject_limit(sql, limit=50, max_limit=1000)
        assert result == "SELECT * FROM orders LIMIT 1000;"

    def test_clamp_offset_limit_exceeding_max(self):
        sql = "SELECT * FROM orders LIMIT 20, 3000;"
        result = inject_limit(sql, limit=50, max_limit=1000)
        assert result == "SELECT * FROM orders LIMIT 20, 1000;"

    def test_clamp_explicit_offset_exceeding_max(self):
        sql = "SELECT * FROM orders LIMIT 5000 OFFSET 20;"
        result = inject_limit(sql, limit=50, max_limit=1000)
        assert result == "SELECT * FROM orders LIMIT 1000 OFFSET 20;"

    def test_inject_limit_before_for_update_clause(self):
        sql = "SELECT * FROM users FOR UPDATE;"
        result = inject_limit(sql, limit=50)
        assert result == "SELECT * FROM users LIMIT 50 FOR UPDATE;"

    def test_subquery_with_limit_gets_outer_limit(self):
        sql = "SELECT * FROM (SELECT id, name FROM users LIMIT 5) AS sub;"
        result = inject_limit(sql, limit=50)
        assert result == "SELECT * FROM (SELECT id, name FROM users LIMIT 5) AS sub LIMIT 50;"

    def test_cte_query_gets_limit(self):
        sql = "WITH active_users AS (SELECT * FROM users WHERE status = 'active') SELECT * FROM active_users;"
        result = inject_limit(sql, limit=50)
        assert result == "WITH active_users AS (SELECT * FROM users WHERE status = 'active') SELECT * FROM active_users LIMIT 50;"

    def test_non_select_queries_untouched(self):
        queries = [
            "SHOW TABLES;",
            "DESCRIBE users;",
            "UPDATE users SET name = 'Bob' WHERE id = 1;",
            "INSERT INTO users (name) VALUES ('Charlie');",
        ]
        for q in queries:
            assert inject_limit(q) == q

