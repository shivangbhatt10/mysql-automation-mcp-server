"""FastMCP server implementation for MySQL automation, schema exploration, safety, and analytics."""

import csv
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union
from fastmcp import FastMCP

from mysql_mcp.audit import (
    get_query_history as get_audit_query_history,
    log_query,
)
from mysql_mcp.config import get_settings, persist_config
from mysql_mcp.db import (
    close_pool,
    execute_query as db_execute_query,
    get_pool,
    transaction,
)
from mysql_mcp.errors import (
    MySQLServerException,
    QuerySafetyError,
    diagnose_mysql_error,
)
from mysql_mcp.safety import (
    get_statement_type,
    inject_limit,
    is_mutation,
    is_read_only,
    validate_mutation_safety,
)
from mysql_mcp.schema import (
    clear_schema_cache,
    format_schema_as_markdown,
    get_schema as get_cached_schema,
    get_schema_markdown,
    refresh_schema as refresh_cached_schema,
)

# Instantiate FastMCP server
mcp = FastMCP("mysql-automation-server")


class CustomDataEncoder(json.JSONEncoder):
    """JSON encoder handling Decimals, datetimes, dates, and bytes."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


# ==============================================================================
# MCP Tools (11 Tools)
# ==============================================================================


@mcp.tool()
def test_connection() -> Dict[str, Any]:
    """
    Test connection to active MySQL instance and return ping status, latency,
    server version, database name, and connection pool statistics.
    """
    pool = get_pool()
    return pool.ping()


@mcp.tool()
def configure_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    save_config: bool = True,
) -> Dict[str, Any]:
    """
    Update connection credentials dynamically at runtime, reinitialize pool,
    and optionally persist credentials to ~/.mysql-mcp/config.json.
    """
    settings = get_settings()

    updates: Dict[str, Any] = {}
    if host is not None:
        settings.mysql_host = host
        updates["mysql_host"] = host
    if port is not None:
        settings.mysql_port = port
        updates["mysql_port"] = port
    if user is not None:
        settings.mysql_user = user
        updates["mysql_user"] = user
    if password is not None:
        settings.mysql_password = password
        updates["mysql_password"] = password
    if database is not None:
        settings.mysql_database = database if database != "" else None
        updates["mysql_database"] = settings.mysql_database

    if save_config and updates:
        persist_config(updates)

    # Close existing pool and wipe caches
    close_pool()
    clear_schema_cache()

    # Verify connectivity with updated credentials
    ping_result = get_pool().ping()
    connected = ping_result.get("status") == "healthy"

    return {
        "status": "configured",
        "connected": connected,
        "active_configuration": {
            "host": settings.mysql_host,
            "port": settings.mysql_port,
            "user": settings.mysql_user,
            "database": settings.mysql_database,
        },
        "saved_persistently": save_config,
        "ping": ping_result,
    }


@mcp.tool()
def list_databases() -> List[Dict[str, Any]]:
    """
    List all accessible databases on the connected MySQL instance,
    indicating the active database and identifying system catalogs.
    """
    pool = get_pool()
    with pool.acquire() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES;")
            rows = cursor.fetchall()
            db_names = [list(r.values())[0] for r in rows]

    current_db = get_settings().mysql_database
    system_dbs = {"information_schema", "mysql", "performance_schema", "sys"}

    result: List[Dict[str, Any]] = []
    for db in sorted(db_names):
        result.append({
            "database_name": db,
            "is_active": db.lower() == (current_db or "").lower(),
            "is_system": db.lower() in system_dbs,
        })

    return result


@mcp.tool()
def use_database(database_name: str) -> Dict[str, Any]:
    """
    Switch the active MySQL database at runtime.
    Validates that the database exists, switches connection pool context,
    and updates persistent configuration.
    """
    target_db = database_name.strip()
    if not target_db:
        raise ValueError("Database name cannot be empty.")

    # Verify database exists on server
    pool = get_pool()
    with pool.acquire() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW DATABASES;")
            existing = {list(r.values())[0].lower() for r in cursor.fetchall()}

    if target_db.lower() not in existing:
        raise ValueError(
            f"Database '{target_db}' does not exist on this MySQL server. "
            f"Available databases: {sorted(list(existing))}"
        )

    settings = get_settings()
    previous_db = settings.mysql_database
    settings.mysql_database = target_db

    # Re-establish pool with the new database context
    close_pool()

    # Persist database preference
    persist_config({"mysql_database": target_db})

    # Test connection with new database
    ping_res = get_pool().ping()

    return {
        "status": "switched",
        "previous_database": previous_db,
        "active_database": target_db,
        "connected": ping_res.get("status") == "healthy",
    }


@mcp.tool()
def list_tables() -> List[Dict[str, Any]]:
    """
    Return list of all tables and views in active database with approximate row counts.
    """
    schema = get_cached_schema(refresh=False, as_markdown=False)
    summary: List[Dict[str, Any]] = []

    for tname, tinfo in sorted(schema.get("tables", {}).items()):
        summary.append({
            "table_name": tname,
            "table_type": tinfo.get("type", "BASE TABLE"),
            "estimated_rows": tinfo.get("estimated_rows", 0),
            "columns_count": len(tinfo.get("columns", [])),
            "primary_key": tinfo.get("primary_key", []),
            "comment": tinfo.get("comment", ""),
        })

    for vname, vinfo in sorted(schema.get("views", {}).items()):
        summary.append({
            "table_name": vname,
            "table_type": "VIEW",
            "estimated_rows": 0,
            "columns_count": 0,
            "primary_key": [],
            "comment": "View",
        })

    return summary


@mcp.tool()
def describe_table(table_name: str) -> Dict[str, Any]:
    """
    Return structured column definitions, data types, indexes, and foreign keys for a table.
    """
    schema = get_cached_schema(refresh=False, as_markdown=False)
    table_info = schema.get("tables", {}).get(table_name)

    if not table_info:
        view_info = schema.get("views", {}).get(table_name)
        if view_info:
            return {
                "table_name": table_name,
                "type": "VIEW",
                "definition": view_info.get("definition"),
                "is_updatable": view_info.get("is_updatable"),
            }
        raise ValueError(
            f"Table '{table_name}' does not exist in database '{schema.get('database')}'. "
            f"Available tables: {list(schema.get('tables', {}).keys())}"
        )

    return {
        "table_name": table_name,
        "type": table_info.get("type", "BASE TABLE"),
        "comment": table_info.get("comment", ""),
        "estimated_rows": table_info.get("estimated_rows", 0),
        "primary_key": table_info.get("primary_key", []),
        "columns": table_info.get("columns", []),
        "indexes": table_info.get("indexes", []),
        "foreign_keys": table_info.get("foreign_keys", []),
    }


@mcp.tool()
def get_schema(refresh: bool = False, format: str = "markdown") -> Union[str, Dict[str, Any]]:
    """
    Return cached or refreshed database schema in Markdown or structured JSON.

    Args:
        refresh: If True, forces fresh introspection of information_schema.
        format: Format style, either 'markdown' (default) or 'json'.
    """
    is_markdown = format.lower() == "markdown"
    return get_cached_schema(refresh=refresh, as_markdown=is_markdown)


@mcp.tool()
def execute_query(sql: str, limit: int = 50) -> Dict[str, Any]:
    """
    Validate query is read-only, safely inject LIMIT clause, execute,
    and return columns, result rows, and execution time.
    """
    settings = get_settings()
    current_db = settings.mysql_database

    if not is_read_only(sql):
        err_msg = (
            "Security violation: execute_query only permits read-only operations "
            "(SELECT, SHOW, DESCRIBE, EXPLAIN). For INSERT, UPDATE, DELETE, or DDL, use execute_mutation."
        )
        log_query(
            tool="execute_query",
            sql=sql,
            database=current_db,
            query_type="READ",
            status="BLOCKED_BY_SAFETY",
            error=err_msg,
        )
        raise QuerySafetyError(err_msg, query=sql)

    clamped_limit = min(limit, settings.mysql_max_limit)
    sql_with_limit = inject_limit(sql, limit=clamped_limit, max_limit=settings.mysql_max_limit)

    start_time = time.perf_counter()
    try:
        result = db_execute_query(sql_with_limit, auto_limit=False)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="execute_query",
            sql=sql,
            sql_executed=sql_with_limit,
            database=current_db,
            query_type="READ",
            status="SUCCESS",
            row_count=len(result["rows"]),
            execution_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="execute_query",
            sql=sql,
            sql_executed=sql_with_limit,
            database=current_db,
            query_type="READ",
            status="FAILED",
            error=str(e),
            execution_time_ms=elapsed_ms,
        )
        raise

    return {
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": len(result["rows"]),
        "execution_time_ms": elapsed_ms,
        "query": sql_with_limit,
    }


@mcp.tool()
def execute_mutation(
    sql: str,
    confirmed: bool = False,
    allow_unfiltered: bool = False,
) -> Dict[str, Any]:
    """
    Validate mutation safety, execute inside a transactional context,
    and return affected row counts.

    - Blocks unconstrained UPDATE / DELETE unless allow_unfiltered=True.
    - Requires confirmed=True for destructive DDL (DROP, TRUNCATE, ALTER).
    """
    settings = get_settings()
    current_db = settings.mysql_database
    stmt_type = get_statement_type(sql)

    # DDL guardrail: require confirmed=True
    if stmt_type in ("DROP", "TRUNCATE", "ALTER"):
        if not confirmed:
            err_msg = (
                f"Safety warning: {stmt_type} is a destructive operation that permanently modifies schema or data. "
                "Pass confirmed=True to confirm execution."
            )
            log_query(
                tool="execute_mutation",
                sql=sql,
                database=current_db,
                query_type="MUTATION",
                status="BLOCKED_BY_SAFETY",
                error=err_msg,
            )
            raise QuerySafetyError(err_msg, query=sql)

    # Unfiltered mutation guardrail
    if stmt_type in ("UPDATE", "DELETE"):
        try:
            validate_mutation_safety(sql, allow_unfiltered=allow_unfiltered)
        except QuerySafetyError as e:
            log_query(
                tool="execute_mutation",
                sql=sql,
                database=current_db,
                query_type="MUTATION",
                status="BLOCKED_BY_SAFETY",
                error=str(e),
            )
            raise

    start_time = time.perf_counter()
    try:
        with transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                affected_rows = cursor.rowcount
                last_insert_id = cursor.lastrowid
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="execute_mutation",
            sql=sql,
            database=current_db,
            query_type="MUTATION",
            status="SUCCESS",
            rows_affected=affected_rows,
            execution_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="execute_mutation",
            sql=sql,
            database=current_db,
            query_type="MUTATION",
            status="FAILED",
            error=str(e),
            execution_time_ms=elapsed_ms,
        )
        raise

    # If DDL altered structure, clear schema cache
    if stmt_type in ("CREATE", "DROP", "ALTER", "TRUNCATE", "RENAME"):
        clear_schema_cache()

    return {
        "statement_type": stmt_type,
        "affected_rows": affected_rows,
        "last_insert_id": last_insert_id,
        "execution_time_ms": elapsed_ms,
        "status": "committed",
    }


@mcp.tool()
def explain_query(sql: str, format: str = "TRADITIONAL") -> Dict[str, Any]:
    """
    Run EXPLAIN on a SQL query and return execution plan (TRADITIONAL, JSON, or TREE).
    """
    settings = get_settings()
    current_db = settings.mysql_database

    fmt = format.upper().strip()
    if fmt not in ("TRADITIONAL", "JSON", "TREE"):
        raise ValueError("Invalid format. Must be one of: 'TRADITIONAL', 'JSON', 'TREE'.")

    # Safety check: ensure underlying statement is a query, not a destructive command
    if not is_read_only(sql):
        stmt_type = get_statement_type(sql)
        if stmt_type in ("DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE"):
            err_msg = f"Cannot run EXPLAIN on destructive command: {stmt_type}"
            log_query(
                tool="explain_query",
                sql=sql,
                database=current_db,
                query_type="EXPLAIN",
                status="BLOCKED_BY_SAFETY",
                error=err_msg,
            )
            raise QuerySafetyError(err_msg, query=sql)

    clean_sql = sql.strip().rstrip(";")
    if fmt == "TRADITIONAL":
        explain_sql = f"EXPLAIN {clean_sql};"
    else:
        explain_sql = f"EXPLAIN FORMAT={fmt} {clean_sql};"

    start_time = time.perf_counter()
    try:
        result = db_execute_query(explain_sql, auto_limit=False)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="explain_query",
            sql=sql,
            sql_executed=explain_sql,
            database=current_db,
            query_type="EXPLAIN",
            status="SUCCESS",
            row_count=len(result["rows"]),
            execution_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="explain_query",
            sql=sql,
            sql_executed=explain_sql,
            database=current_db,
            query_type="EXPLAIN",
            status="FAILED",
            error=str(e),
            execution_time_ms=elapsed_ms,
        )
        raise

    plan_output: Any = result["rows"]
    if fmt == "JSON" and result["rows"] and "EXPLAIN" in result["rows"][0]:
        try:
            plan_output = json.loads(result["rows"][0]["EXPLAIN"])
        except Exception:
            plan_output = result["rows"][0]["EXPLAIN"]
    elif fmt == "TREE" and result["rows"] and "EXPLAIN" in result["rows"][0]:
        plan_output = result["rows"][0]["EXPLAIN"]

    return {
        "format": fmt,
        "query": clean_sql,
        "plan": plan_output,
        "raw_rows": result["rows"],
        "execution_time_ms": elapsed_ms,
    }


@mcp.tool()
def export_query_results(
    sql: str,
    format: str = "csv",
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a read-only query and export the results to ./exports/<filename> (CSV or JSON).
    """
    settings = get_settings()
    settings.ensure_directories()
    current_db = settings.mysql_database

    if not is_read_only(sql):
        err_msg = "Only read-only queries can be exported."
        log_query(
            tool="export_query_results",
            sql=sql,
            database=current_db,
            query_type="EXPORT",
            status="BLOCKED_BY_SAFETY",
            error=err_msg,
        )
        raise QuerySafetyError(err_msg, query=sql)

    fmt = format.lower().strip()
    if fmt not in ("csv", "json"):
        raise ValueError("Export format must be either 'csv' or 'json'.")

    start_time = time.perf_counter()
    try:
        result = db_execute_query(sql, auto_limit=False)
        columns = result["columns"]
        rows = result["rows"]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if filename:
            target_name = filename if filename.endswith(f".{fmt}") else f"{filename}.{fmt}"
        else:
            target_name = f"export_{timestamp}.{fmt}"

        target_path = (settings.mysql_exports_dir / target_name).resolve()

        if fmt == "csv":
            with open(target_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for row in rows:
                    formatted_row = []
                    for col in columns:
                        val = row.get(col)
                        if isinstance(val, (dict, list)):
                            formatted_row.append(json.dumps(val, cls=CustomDataEncoder))
                        elif isinstance(val, (datetime, date)):
                            formatted_row.append(val.isoformat())
                        elif val is None:
                            formatted_row.append("")
                        else:
                            formatted_row.append(str(val))
                    writer.writerow(formatted_row)
        else:  # json
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, cls=CustomDataEncoder)

        file_size = target_path.stat().st_size
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        log_query(
            tool="export_query_results",
            sql=sql,
            database=current_db,
            query_type="EXPORT",
            status="SUCCESS",
            row_count=len(rows),
            execution_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_query(
            tool="export_query_results",
            sql=sql,
            database=current_db,
            query_type="EXPORT",
            status="FAILED",
            error=str(e),
            execution_time_ms=elapsed_ms,
        )
        raise

    return {
        "file_path": str(target_path),
        "filename": target_name,
        "format": fmt,
        "row_count": len(rows),
        "file_size_bytes": file_size,
    }


@mcp.tool()
def get_query_history(
    limit: int = 20,
    status: Optional[str] = None,
    query_type: Optional[str] = None,
    tool: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve recent SQL queries executed by the assistant from the local audit log.
    Useful for reviewing model actions, verifying hallucinations, and post-mortem inspection.

    Args:
        limit: Number of recent queries to return (default: 20, max: 200).
        status: Optional status filter ('SUCCESS', 'FAILED', 'BLOCKED_BY_SAFETY').
        query_type: Optional type filter ('READ', 'MUTATION', 'EXPLAIN', 'EXPORT').
        tool: Optional tool filter ('execute_query', 'execute_mutation', 'explain_query', 'export_query_results').
    """
    return get_audit_query_history(
        limit=limit,
        status=status,
        query_type=query_type,
        tool=tool,
    )


# ==============================================================================
# MCP Resources (2 Resources)
# ==============================================================================


@mcp.resource("mysql://schema")
def get_schema_resource() -> str:
    """Active MySQL database schema documentation in Markdown format."""
    return get_schema_markdown(refresh=False)


@mcp.resource("mysql://query-patterns")
def get_query_patterns_resource() -> str:
    """Reference guide for advanced MySQL query patterns (window functions, CTEs, JSON, EXPLAIN)."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    patterns_file = root_dir / "query-patterns.md"
    if patterns_file.exists():
        with open(patterns_file, "r", encoding="utf-8") as f:
            return f.read()
    return "# MySQL Query Patterns Reference\n\nNo query-patterns.md file found."


# ==============================================================================
# MCP Prompts (2 Prompts)
# ==============================================================================


@mcp.prompt()
def generate_sql(user_request: str, table_context: str = "") -> str:
    """
    Guidance prompt for generating accurate, performant, and safe SQL queries.
    """
    context_section = f"\nRelevant Schema Context:\n{table_context}\n" if table_context else ""
    return f"""You are an expert MySQL database administrator and query engineer.
Generate a safe, accurate, and optimal SQL query for the following business request:

User Request: {user_request}
{context_section}
STRICT GUIDELINES:
1. Syntax & Safety:
   - Always use explicit JOIN syntax: 'FROM table_a INNER JOIN table_b ON table_a.id = table_b.a_id'.
   - NEVER use implicit comma joins ('FROM table_a, table_b WHERE table_a.id = table_b.a_id').
   - For multi-step aggregations or filtering, use Common Table Expressions ('WITH cte AS (...) SELECT ...').
   - NEVER use SELECT * in production queries; always list required column names explicitly.
   - For destructive operations (UPDATE/DELETE), you MUST include a specific WHERE clause.
2. MySQL 8.0 Features:
   - Utilize JSON functions (e.g. JSON_EXTRACT, ->>, JSON_CONTAINS) when querying JSON columns.
   - Utilize window functions (e.g. ROW_NUMBER(), RANK(), DENSE_RANK()) for running totals or rankings.
3. Index Optimization:
   - Filter on indexed columns where possible to prevent full table scans.
   - Limit result set sizes appropriately.
"""


@mcp.prompt()
def optimize_query(sql_query: str, explain_plan: str = "") -> str:
    """
    Guidance prompt for analyzing and optimizing MySQL query execution plans.
    """
    explain_section = f"\nEXPLAIN Output:\n{explain_plan}\n" if explain_plan else ""
    return f"""You are a database performance tuning specialist.
Analyze the following MySQL query and recommend concrete indexing or query refactoring improvements:

Query:
```sql
{sql_query}
```
{explain_section}
ANALYSIS CHECKLIST:
1. Access Types: Check for 'type: ALL' (Full Table Scan) vs 'ref', 'range', 'eq_ref', or 'const'.
2. Rows Examined: Compare 'rows_examined_per_scan' vs actual output rows.
3. Indexes: Are 'possible_keys' being utilized in 'key'? Check for index column order mismatches.
4. Sorting & Buffers: Look for 'Using filesort' or 'Using temporary' in the Extra column.
5. Recommendation: Provide exact 'CREATE INDEX ...' DDL or refactored SQL syntax to achieve optimal performance.
"""


# ==============================================================================
# CLI Entrypoint
# ==============================================================================


def main() -> None:
    """Main CLI entrypoint for FastMCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
