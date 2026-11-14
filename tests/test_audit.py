"""
Tests for query history audit logging, filtering, and retrieval.
"""

from pathlib import Path
import pytest
from mysql_mcp.audit import (
    clear_query_history,
    get_history_file_path,
    get_query_history,
    log_query,
)
from mysql_mcp.errors import QuerySafetyError
from mysql_mcp.server import (
    execute_mutation,
    execute_query,
    get_query_history as tool_get_query_history,
)


@pytest.fixture(autouse=True)
def setup_and_teardown_history():
    """Ensure a clean audit log before and after each test."""
    clear_query_history()
    yield
    clear_query_history()


class TestAuditLogger:
    """Unit tests for the audit logger functions."""

    def test_log_query_success(self):
        entry = log_query(
            tool="execute_query",
            sql="SELECT id, name FROM users",
            sql_executed="SELECT id, name FROM users LIMIT 50",
            database="ecommerce_demo",
            query_type="READ",
            status="SUCCESS",
            row_count=10,
            execution_time_ms=12.5,
        )

        assert entry["status"] == "SUCCESS"
        assert entry["query_type"] == "READ"
        assert entry["tool"] == "execute_query"
        assert entry["row_count"] == 10
        assert entry["sql_raw"] == "SELECT id, name FROM users"
        assert entry["sql_executed"] == "SELECT id, name FROM users LIMIT 50"

        history = get_query_history(limit=5)
        assert len(history) == 1
        assert history[0]["id"] == entry["id"]

    def test_log_query_blocked_by_safety(self):
        log_query(
            tool="execute_mutation",
            sql="DELETE FROM orders;",
            database="ecommerce_demo",
            query_type="MUTATION",
            status="BLOCKED_BY_SAFETY",
            error="Query rejected: DELETE without WHERE clause is not allowed.",
        )

        history = get_query_history(limit=10)
        assert len(history) == 1
        assert history[0]["status"] == "BLOCKED_BY_SAFETY"
        assert "DELETE without WHERE" in history[0]["error"]

    def test_log_query_failed(self):
        log_query(
            tool="execute_query",
            sql="SELECT * FROM non_existent_table",
            database="ecommerce_demo",
            query_type="READ",
            status="FAILED",
            error="Table 'non_existent_table' doesn't exist",
            execution_time_ms=5.0,
        )

        history = get_query_history(limit=10)
        assert len(history) == 1
        assert history[0]["status"] == "FAILED"
        assert "non_existent_table" in history[0]["error"]

    def test_get_query_history_ordering_and_limit(self):
        # Insert 5 entries
        for i in range(5):
            log_query(
                tool="execute_query",
                sql=f"SELECT {i}",
                database="test_db",
                query_type="READ",
                status="SUCCESS",
            )

        # Reverse chronological check (newest first)
        history = get_query_history(limit=3)
        assert len(history) == 3
        assert history[0]["sql_raw"] == "SELECT 4"
        assert history[1]["sql_raw"] == "SELECT 3"
        assert history[2]["sql_raw"] == "SELECT 2"

    def test_get_query_history_filters(self):
        log_query(tool="execute_query", sql="SELECT 1", query_type="READ", status="SUCCESS")
        log_query(tool="execute_mutation", sql="DELETE FROM users", query_type="MUTATION", status="BLOCKED_BY_SAFETY")
        log_query(tool="execute_mutation", sql="UPDATE users SET active=1 WHERE id=1", query_type="MUTATION", status="SUCCESS")

        # Filter by status
        blocked = get_query_history(status="BLOCKED_BY_SAFETY")
        assert len(blocked) == 1
        assert blocked[0]["status"] == "BLOCKED_BY_SAFETY"

        # Filter by query_type
        mutations = get_query_history(query_type="MUTATION")
        assert len(mutations) == 2

        # Filter by tool
        reads = get_query_history(tool="execute_query")
        assert len(reads) == 1
        assert reads[0]["sql_raw"] == "SELECT 1"


class TestAuditServerIntegration:
    """Integration tests verifying server tools write to query history."""

    def test_execute_query_logs_success(self):
        res = execute_query("SELECT id, name FROM users", limit=5)
        assert res["row_count"] > 0

        history = tool_get_query_history(limit=5)
        assert len(history) >= 1
        latest = history[0]
        assert latest["tool"] == "execute_query"
        assert latest["status"] == "SUCCESS"
        assert latest["query_type"] == "READ"
        assert "LIMIT 5" in latest["sql_executed"]

    def test_execute_query_blocks_mutation_and_logs(self):
        with pytest.raises(QuerySafetyError):
            execute_query("DELETE FROM users WHERE id = 1;")

        history = tool_get_query_history(limit=5)
        assert len(history) >= 1
        latest = history[0]
        assert latest["tool"] == "execute_query"
        assert latest["status"] == "BLOCKED_BY_SAFETY"
        assert "Security violation" in latest["error"]

    def test_execute_mutation_blocks_unfiltered_and_logs(self):
        with pytest.raises(QuerySafetyError):
            execute_mutation("DELETE FROM orders;")

        history = tool_get_query_history(limit=5)
        assert len(history) >= 1
        latest = history[0]
        assert latest["tool"] == "execute_mutation"
        assert latest["status"] == "BLOCKED_BY_SAFETY"
        assert "WHERE clause" in latest["error"]
