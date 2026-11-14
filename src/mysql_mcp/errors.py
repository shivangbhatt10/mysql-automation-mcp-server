"""MySQL error diagnostics and friendly error translation."""

from dataclasses import dataclass
from typing import Any, Dict, Optional
import pymysql


@dataclass
class DiagnosticInfo:
    """Structured diagnostic information for a MySQL error."""

    code: int
    name: str
    title: str
    original_message: str
    guidance: str
    suggested_action: str

    def format_message(self) -> str:
        """Format into a human-readable diagnostic message."""
        parts = [
            f"MySQL Error [{self.code}] {self.name}: {self.title}",
            f"Details: {self.original_message}" if self.original_message else "",
            f"Diagnostic: {self.guidance}",
            f"Suggested Action: {self.suggested_action}",
        ]
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> Dict[str, Any]:
        """Convert diagnostic info into a dictionary."""
        return {
            "code": self.code,
            "name": self.name,
            "title": self.title,
            "original_message": self.original_message,
            "guidance": self.guidance,
            "suggested_action": self.suggested_action,
        }


# Mapping of MySQL error codes to friendly diagnostic guidance
ERROR_CATALOG: Dict[int, Dict[str, str]] = {
    1045: {
        "name": "ER_ACCESS_DENIED_ERROR",
        "title": "Access Denied / Authentication Failed",
        "guidance": (
            "MySQL rejected the provided credentials. The username or password specified "
            "is incorrect, or the user does not have permission to connect from this host."
        ),
        "suggested_action": (
            "Verify MYSQL_USER and MYSQL_PASSWORD in your .env file or configuration. "
            "Ensure the MySQL user has host permissions (e.g. 'root'@'localhost' or 'root'@'%')."
        ),
    },
    1049: {
        "name": "ER_BAD_DB_ERROR",
        "title": "Unknown Database",
        "guidance": (
            "The requested database does not exist on this MySQL server instance."
        ),
        "suggested_action": (
            "Verify the database name spelling in MYSQL_DATABASE. Run 'SHOW DATABASES;' "
            "to list existing databases or execute 'scripts/seed_demo_db.py' to initialize the demo database."
        ),
    },
    1054: {
        "name": "ER_BAD_FIELD_ERROR",
        "title": "Unknown Column",
        "guidance": (
            "A column referenced in the SELECT, WHERE, ORDER BY, GROUP BY, or ON clause "
            "does not exist in the queried table(s)."
        ),
        "suggested_action": (
            "Inspect the table schema using 'DESCRIBE <table_name>;'. Check for typos, verify table "
            "aliases in multi-table JOINs, or wrap identifiers in backticks if they conflict with keywords."
        ),
    },
    1064: {
        "name": "ER_PARSE_ERROR",
        "title": "SQL Syntax Error",
        "guidance": (
            "The MySQL parser encountered invalid SQL syntax near the indicated token. "
            "Common causes include missing commas, unmatched quotes or parentheses, or invalid keyword usage."
        ),
        "suggested_action": (
            "Review query syntax around the highlighted token. Enclose table/column names in backticks (`` `col` ``), "
            "verify all string quotes are balanced, and confirm syntax compatibility with MySQL 8.0."
        ),
    },
    1146: {
        "name": "ER_NO_SUCH_TABLE",
        "title": "Table Does Not Exist",
        "guidance": (
            "The referenced table or view was not found in the current active database."
        ),
        "suggested_action": (
            "Run 'SHOW TABLES;' to verify table names in the active database. If querying a table in "
            "another schema, prefix it with the database name (e.g., 'db_name.table_name')."
        ),
    },
    1215: {
        "name": "ER_CANNOT_ADD_FOREIGN",
        "title": "Cannot Add Foreign Key Constraint",
        "guidance": (
            "MySQL was unable to establish the foreign key relationship. Both columns must have identical "
            "data types (including signed/unsigned attributes) and matching collations. The referenced column "
            "must have a PRIMARY KEY or UNIQUE index, and both tables must use the InnoDB engine."
        ),
        "suggested_action": (
            "Execute 'SHOW CREATE TABLE <referenced_table>;' and check that referenced column type, unsigned flag, "
            "and character set match the foreign key column definition exactly."
        ),
    },
    1451: {
        "name": "ER_ROW_IS_REFERENCED_2",
        "title": "Foreign Key Restriction (Row Is Referenced)",
        "guidance": (
            "Cannot delete or update this parent row because child records in another table reference it "
            "with a foreign key constraint configured with RESTRICT or NO ACTION."
        ),
        "suggested_action": (
            "Delete or update dependent records in the referencing child table first, or alter the foreign key "
            "definition to use 'ON DELETE CASCADE' or 'ON DELETE SET NULL' if automatic propagation is intended."
        ),
    },
    # Additional common MySQL errors for completeness
    1062: {
        "name": "ER_DUP_ENTRY",
        "title": "Duplicate Entry for Unique Key",
        "guidance": (
            "The value being inserted or updated violates a PRIMARY KEY or UNIQUE index constraint."
        ),
        "suggested_action": (
            "Ensure the unique identifier or email does not already exist, or use 'INSERT ... ON DUPLICATE KEY UPDATE'."
        ),
    },
    2003: {
        "name": "CR_CONN_HOST_ERROR",
        "title": "Connection Refused / Server Unreachable",
        "guidance": (
            "Cannot connect to MySQL server on the specified host and port. MySQL service may not be running "
            "or firewall rules might be blocking port 3306."
        ),
        "suggested_action": (
            "Ensure the MySQL Windows service is started (e.g. 'net start MySQL80') and verify MYSQL_HOST and MYSQL_PORT."
        ),
    },
}


class MySQLServerException(Exception):
    """Base exception for MySQL execution errors with diagnostic guidance."""

    def __init__(self, diagnostic: DiagnosticInfo):
        self.diagnostic = diagnostic
        super().__init__(diagnostic.format_message())


class QuerySafetyError(Exception):
    """Raised when a query violates safety constraints (e.g. unfiltered mutation)."""

    def __init__(self, message: str, query: str = ""):
        self.query = query
        super().__init__(message)


def diagnose_mysql_error(error: Exception | int, original_message: str = "") -> DiagnosticInfo:
    """
    Translate a MySQL error or code into structured diagnostic information.

    Args:
        error: Either an integer error code, or a pymysql.MySQLError / Exception.
        original_message: Optional raw message if error is provided as an integer code.

    Returns:
        DiagnosticInfo containing code, name, user guidance, and suggested action.
    """
    code = 0
    raw_message = original_message

    if isinstance(error, int):
        code = error
    elif isinstance(error, pymysql.MySQLError):
        if error.args and len(error.args) >= 2:
            code = error.args[0] if isinstance(error.args[0], int) else 0
            raw_message = str(error.args[1])
        elif error.args and len(error.args) == 1:
            raw_message = str(error.args[0])
    elif hasattr(error, "errno"):
        code = getattr(error, "errno") or 0
        raw_message = str(error)
    else:
        raw_message = str(error)

    entry = ERROR_CATALOG.get(code)
    if entry:
        return DiagnosticInfo(
            code=code,
            name=entry["name"],
            title=entry["title"],
            original_message=raw_message,
            guidance=entry["guidance"],
            suggested_action=entry["suggested_action"],
        )

    # Generic fallback for uncataloged error codes
    return DiagnosticInfo(
        code=code,
        name="UNKNOWN_MYSQL_ERROR",
        title="MySQL Execution Error",
        original_message=raw_message,
        guidance=f"MySQL returned error code {code}. Review MySQL documentation for code details.",
        suggested_action="Check the SQL statement, table schema, and server error logs for additional context.",
    )


def format_error_guidance(error: Exception | int, original_message: str = "") -> str:
    """Helper returning the formatted human-readable diagnostic string."""
    diag = diagnose_mysql_error(error, original_message)
    return diag.format_message()

