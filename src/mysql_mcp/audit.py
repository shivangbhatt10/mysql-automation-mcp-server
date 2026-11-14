"""
Query execution audit logger and history tracker for MySQL MCP Server.
Maintains an append-only JSONL log of all executed, failed, and safety-blocked queries
for compliance, debugging, and post-mortem review of LLM actions.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
import uuid
from typing import Any, Dict, List, Optional

from mysql_mcp.config import get_settings

_history_lock = Lock()


def get_history_file_path() -> Path:
    """Return the absolute path to the query history JSONL file."""
    settings = get_settings()
    settings.ensure_directories()
    return settings.mysql_logs_dir / "query_history.jsonl"


def log_query(
    tool: str,
    sql: str,
    database: Optional[str] = None,
    query_type: str = "READ",
    status: str = "SUCCESS",
    sql_executed: Optional[str] = None,
    rows_affected: Optional[int] = None,
    row_count: Optional[int] = None,
    execution_time_ms: Optional[float] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Append an entry to the query history audit log in ~/.mysql-mcp/logs/query_history.jsonl.

    Args:
        tool: MCP tool name that triggered the query (e.g. 'execute_query', 'execute_mutation')
        sql: The raw SQL statement requested by the client / LLM
        database: Active MySQL database at the time of execution
        query_type: 'READ', 'MUTATION', 'EXPLAIN', or 'EXPORT'
        status: 'SUCCESS', 'FAILED', or 'BLOCKED_BY_SAFETY'
        sql_executed: The exact SQL executed against MySQL (e.g. with injected LIMIT)
        rows_affected: Number of affected rows (for UPDATE / INSERT / DELETE)
        row_count: Number of returned rows (for SELECT)
        execution_time_ms: Roundtrip execution duration in milliseconds
        error: Error or diagnostic message if query failed or was blocked

    Returns:
        The logged audit entry dictionary.
    """
    entry: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "database": database,
        "query_type": query_type.upper(),
        "status": status.upper(),
        "sql_raw": sql.strip(),
        "sql_executed": (sql_executed or sql).strip(),
        "row_count": row_count,
        "rows_affected": rows_affected,
        "execution_time_ms": execution_time_ms,
        "error": error,
    }

    try:
        log_file = get_history_file_path()
        with _history_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        # Logging failure must never interrupt the primary database operation
        pass

    return entry


def get_query_history(
    limit: int = 20,
    status: Optional[str] = None,
    query_type: Optional[str] = None,
    tool: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve recent query audit history entries in reverse chronological order (newest first).

    Args:
        limit: Maximum number of records to return (default 20, max 200).
        status: Filter by status ('SUCCESS', 'FAILED', 'BLOCKED_BY_SAFETY').
        query_type: Filter by query type ('READ', 'MUTATION', 'EXPLAIN', 'EXPORT').
        tool: Filter by tool name (e.g. 'execute_mutation').

    Returns:
        List of audit record dictionaries.
    """
    clamped_limit = min(max(1, limit), 200)
    log_file = get_history_file_path()

    if not log_file.exists():
        return []

    entries: List[Dict[str, Any]] = []

    try:
        with _history_lock:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # Parse from most recent backwards
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue

            # Apply filters
            if status and record.get("status", "").upper() != status.strip().upper():
                continue
            if query_type and record.get("query_type", "").upper() != query_type.strip().upper():
                continue
            if tool and record.get("tool", "").lower() != tool.strip().lower():
                continue

            entries.append(record)
            if len(entries) >= clamped_limit:
                break
    except Exception:
        return []

    return entries


def clear_query_history() -> bool:
    """Clear or truncate the query history audit file."""
    log_file = get_history_file_path()
    try:
        with _history_lock:
            if log_file.exists():
                with open(log_file, "w", encoding="utf-8") as f:
                    f.truncate(0)
        return True
    except Exception:
        return False
