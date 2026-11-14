"""Pure-Python PyMySQL connection pooling, health checks, and transaction management."""

from collections import deque
from contextlib import contextmanager
import time
import threading
from typing import Any, Dict, Generator, List, Optional, Set, Tuple
import pymysql
import pymysql.cursors

from mysql_mcp.config import Settings, get_settings
from mysql_mcp.errors import (
    DiagnosticInfo,
    MySQLServerException,
    diagnose_mysql_error,
)
from mysql_mcp.safety import (
    inject_limit,
    is_mutation,
    is_read_only,
    validate_mutation_safety,
)


class DatabaseConnectionError(Exception):
    """Raised when acquiring or managing a database connection fails."""
    pass


class ConnectionPool:
    """
    Pure-Python thread-safe connection pool for PyMySQL.
    Manages active connections, overflow capacity, health pings, and reclamation.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._pool_size: int = self.settings.mysql_pool_size
        self._max_overflow: int = self.settings.mysql_pool_max_overflow
        self._max_connections: int = self._pool_size + self._max_overflow
        self._timeout: float = self.settings.mysql_pool_timeout

        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._available_connections: deque[pymysql.connections.Connection] = deque()
        self._in_use_connections: Set[pymysql.connections.Connection] = set()
        self._is_closed: bool = False

    def _create_raw_connection(self) -> pymysql.connections.Connection:
        """Create a new raw PyMySQL connection with settings parameters."""
        params = self.settings.get_connection_dict()
        try:
            conn = pymysql.connect(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                database=params.get("database"),
                charset=params.get("charset", "utf8mb4"),
                connect_timeout=params.get("connect_timeout", 10),
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
            return conn
        except Exception as exc:
            diag = diagnose_mysql_error(exc)
            raise MySQLServerException(diag) from exc

    def _validate_connection(self, conn: pymysql.connections.Connection) -> bool:
        """Check if connection is open and responsive via ping()."""
        try:
            conn.ping()
            return True
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return False

    def get_connection(self, timeout: Optional[float] = None) -> pymysql.connections.Connection:
        """
        Check out a connection from the pool.
        Validates connection health and replaces stale connections automatically.
        """
        wait_timeout = timeout if timeout is not None else self._timeout
        deadline = time.time() + wait_timeout

        with self._condition:
            while True:
                if self._is_closed:
                    raise DatabaseConnectionError("Cannot checkout connection: connection pool is closed.")

                # 1. Reuse existing idle connection if available
                while self._available_connections:
                    candidate = self._available_connections.popleft()
                    if self._validate_connection(candidate):
                        self._in_use_connections.add(candidate)
                        return candidate

                # 2. Spawn a new connection if under max capacity
                total_connections = len(self._available_connections) + len(self._in_use_connections)
                if total_connections < self._max_connections:
                    new_conn = self._create_raw_connection()
                    self._in_use_connections.add(new_conn)
                    return new_conn

                # 3. Wait for an in-use connection to be returned
                remaining_time = deadline - time.time()
                if remaining_time <= 0:
                    raise DatabaseConnectionError(
                        f"Connection pool exhausted (active={len(self._in_use_connections)}, "
                        f"max={self._max_connections}). Timed out after {wait_timeout}s."
                    )
                self._condition.wait(remaining_time)

    def release(self, conn: pymysql.connections.Connection) -> None:
        """
        Return a borrowed connection back to the pool.
        Rolls back uncommitted transactions to preserve clean state for next caller.
        """
        with self._condition:
            if conn in self._in_use_connections:
                self._in_use_connections.remove(conn)

            if self._is_closed or not conn.open:
                try:
                    conn.close()
                except Exception:
                    pass
            else:
                try:
                    conn.rollback()
                    self._available_connections.append(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass

            self._condition.notify()

    @contextmanager
    def acquire(self, timeout: Optional[float] = None) -> Generator[pymysql.connections.Connection, None, None]:
        """Context manager for acquiring and safely returning a pooled connection."""
        conn = self.get_connection(timeout=timeout)
        try:
            yield conn
        finally:
            self.release(conn)

    def ping(self) -> Dict[str, Any]:
        """
        Execute a health ping against the MySQL server and measure round-trip latency.
        Returns health status, version, database name, and pool statistics.
        """
        start_time = time.perf_counter()
        try:
            with self.acquire(timeout=5.0) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 AS alive, VERSION() AS version, DATABASE() AS current_db, "
                        "CURRENT_TIMESTAMP() AS server_time;"
                    )
                    row = cursor.fetchone()
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                with self._lock:
                    pool_stats = {
                        "pool_size": self._pool_size,
                        "available": len(self._available_connections),
                        "in_use": len(self._in_use_connections),
                        "max_capacity": self._max_connections,
                    }

                return {
                    "status": "healthy",
                    "latency_ms": latency_ms,
                    "version": row.get("version") if row else "unknown",
                    "database": row.get("current_db") if row else self.settings.mysql_database,
                    "server_time": str(row.get("server_time")) if row else None,
                    "pool": pool_stats,
                }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            diag = diagnose_mysql_error(exc)
            return {
                "status": "unhealthy",
                "latency_ms": latency_ms,
                "error": diag.to_dict(),
            }

    def close_all(self) -> None:
        """Close all connections and terminate the pool."""
        with self._condition:
            self._is_closed = True

            while self._available_connections:
                c = self._available_connections.popleft()
                try:
                    c.close()
                except Exception:
                    pass

            for c in list(self._in_use_connections):
                try:
                    c.close()
                except Exception:
                    pass
            self._in_use_connections.clear()
            self._condition.notify_all()


# Global pool singleton
_GLOBAL_POOL: Optional[ConnectionPool] = None
_GLOBAL_POOL_LOCK = threading.Lock()


def get_pool() -> ConnectionPool:
    """Retrieve or initialize the global ConnectionPool instance."""
    global _GLOBAL_POOL
    if _GLOBAL_POOL is None:
        with _GLOBAL_POOL_LOCK:
            if _GLOBAL_POOL is None:
                _GLOBAL_POOL = ConnectionPool()
    return _GLOBAL_POOL


def close_pool() -> None:
    """Close the global ConnectionPool instance if active."""
    global _GLOBAL_POOL
    with _GLOBAL_POOL_LOCK:
        if _GLOBAL_POOL is not None:
            _GLOBAL_POOL.close_all()
            _GLOBAL_POOL = None


@contextmanager
def transaction(
    conn: Optional[pymysql.connections.Connection] = None,
    pool: Optional[ConnectionPool] = None,
) -> Generator[pymysql.connections.Connection, None, None]:
    """
    Transaction context manager: commits upon clean exit, rolls back on exception.

    If conn is None, borrows a connection from the pool and releases it upon exit.
    If conn is provided, manages the transaction on that specific connection without releasing it.
    """
    active_pool = pool or get_pool()
    owns_connection = False
    active_conn = conn

    if active_conn is None:
        active_conn = active_pool.get_connection()
        owns_connection = True

    try:
        active_conn.autocommit(False)
        yield active_conn
        active_conn.commit()
    except Exception as exc:
        try:
            active_conn.rollback()
        except Exception:
            pass
        if isinstance(exc, (MySQLServerException, DatabaseConnectionError)):
            raise
        diag = diagnose_mysql_error(exc)
        raise MySQLServerException(diag) from exc
    finally:
        if owns_connection:
            active_pool.release(active_conn)


def execute_query(
    sql: str,
    params: Optional[Any] = None,
    auto_limit: bool = True,
    allow_unfiltered: bool = False,
    pool: Optional[ConnectionPool] = None,
) -> Dict[str, Any]:
    """
    Execute a single SQL query safely with parameter binding and diagnostic handling.

    - Validates mutation safety (rejects unfiltered UPDATE/DELETE unless allow_unfiltered=True).
    - Injects safety LIMIT on SELECT queries if auto_limit=True.
    - Manages automatic transaction commit for mutations and rollback on failure.
    """
    # 1. Safety validation
    validate_mutation_safety(sql, allow_unfiltered=allow_unfiltered)

    # 2. Inject LIMIT on SELECT if requested
    executed_sql = inject_limit(sql) if auto_limit else sql

    active_pool = pool or get_pool()

    with active_pool.acquire() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(executed_sql, params)
                row_count = cursor.rowcount
                last_insert_id = cursor.lastrowid

                if cursor.description:
                    columns = [d[0] for d in cursor.description]
                    rows = cursor.fetchall()
                else:
                    columns = []
                    rows = []

            # If mutation, commit changes
            if is_mutation(executed_sql):
                conn.commit()

            return {
                "columns": columns,
                "rows": rows,
                "row_count": row_count,
                "last_insert_id": last_insert_id,
                "query": executed_sql,
            }
        except Exception as exc:
            if is_mutation(executed_sql):
                try:
                    conn.rollback()
                except Exception:
                    pass
            diag = diagnose_mysql_error(exc)
            raise MySQLServerException(diag) from exc

