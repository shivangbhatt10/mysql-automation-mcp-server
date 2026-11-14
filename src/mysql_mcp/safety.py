"""Query safety inspection, statement classification, and limit injection using sqlparse."""

import re
from typing import List, Optional
import sqlparse
from sqlparse.sql import Comment, Identifier, IdentifierList, Parenthesis, Statement, Where
from sqlparse.tokens import DML, Keyword, Punctuation

from mysql_mcp.config import get_settings
from mysql_mcp.errors import QuerySafetyError

# Recognized read-only statement initial keywords
READ_ONLY_KEYWORDS = frozenset({"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"})

# Mutation statement initial keywords
MUTATION_KEYWORDS = frozenset({
    "INSERT",
    "UPDATE",
    "DELETE",
    "REPLACE",
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "RENAME",
    "CALL",
    "DO",
    "SET",
    "GRANT",
    "REVOKE",
    "LOCK",
    "UNLOCK",
    "LOAD",
})


def _get_first_meaningful_token(stmt: Statement) -> Optional[str]:
    """Find the first non-whitespace, non-comment token value in uppercase."""
    for token in stmt.tokens:
        if token.is_whitespace:
            continue
        if isinstance(token, Comment) or token.ttype == sqlparse.tokens.Comment:
            continue
        return token.value.upper()
    return None


def get_statement_type(stmt: Statement | str) -> str:
    """
    Determine the type of a SQL statement.
    Handles CTEs (WITH ...), comments, and MySQL-specific statements (SHOW, DESCRIBE).
    """
    if isinstance(stmt, str):
        parsed = sqlparse.parse(stmt)
        if not parsed:
            return "UNKNOWN"
        stmt = parsed[0]

    # Check sqlparse built-in statement type first
    base_type = stmt.get_type()
    if base_type in ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE"):
        return base_type

    # Inspect first token for statements sqlparse tags as UNKNOWN (SHOW, DESCRIBE, EXPLAIN, etc.)
    first_token = _get_first_meaningful_token(stmt)
    if not first_token:
        return "UNKNOWN"

    if first_token in ("DESCRIBE", "DESC"):
        return "DESCRIBE"
    if first_token == "SHOW":
        return "SHOW"
    if first_token == "EXPLAIN":
        return "EXPLAIN"

    # Handle CTE queries: WITH ... SELECT / UPDATE / DELETE
    if first_token == "WITH":
        # Look for the primary operation keyword following the CTE definitions
        for token in stmt.tokens:
            if isinstance(token, Parenthesis) or token.is_whitespace or isinstance(token, Comment):
                continue
            val = token.value.upper()
            if val in ("SELECT", "UPDATE", "DELETE", "INSERT"):
                return val
        return "SELECT"

    return first_token


def is_read_only(query: str) -> bool:
    """
    Check if all statements in a query are strictly read-only.
    Read-only operations include SELECT, SHOW, DESCRIBE, and EXPLAIN.
    """
    statements = sqlparse.parse(query)
    if not statements:
        return True

    for stmt in statements:
        stmt_type = get_statement_type(stmt)
        if stmt_type == "UNKNOWN":
            first_kw = _get_first_meaningful_token(stmt)
            if not first_kw or first_kw not in READ_ONLY_KEYWORDS:
                return False
        elif stmt_type not in READ_ONLY_KEYWORDS:
            return False

    return True


def is_mutation(query: str) -> bool:
    """
    Check if a query performs any data or schema mutation.
    Returns True if at least one statement is not read-only.
    """
    statements = sqlparse.parse(query)
    if not statements:
        return False

    return not is_read_only(query)


def has_where_clause(stmt: Statement | str) -> bool:
    """
    Check if an UPDATE or DELETE statement has a meaningful top-level WHERE clause.
    Verifies that the WHERE clause contains actual filter conditions and is not
    just whitespace, comments, punctuation, or empty.
    """
    if isinstance(stmt, str):
        parsed = sqlparse.parse(stmt)
        if not parsed:
            return False
        stmt = parsed[0]

    where_token = next((t for t in stmt.tokens if isinstance(t, Where)), None)
    if where_token is None:
        return False

    # Check for meaningful tokens inside the WHERE clause
    meaningful_tokens = [
        t for t in where_token.tokens
        if not t.is_whitespace
        and not isinstance(t, Comment)
        and t.ttype != sqlparse.tokens.Comment
        and t.ttype != Punctuation
        and t.value.upper() != "WHERE"
    ]

    return len(meaningful_tokens) > 0


def validate_mutation_safety(query: str, allow_unfiltered: bool = False) -> None:
    """
    Validate that UPDATE and DELETE statements have a WHERE clause unless
    allow_unfiltered is explicitly set to True.

    Raises:
        QuerySafetyError: When an unfiltered UPDATE or DELETE is detected.
    """
    if allow_unfiltered:
        return

    statements = sqlparse.parse(query)
    for stmt in statements:
        stmt_type = get_statement_type(stmt)
        if stmt_type in ("UPDATE", "DELETE"):
            if not has_where_clause(stmt):
                raise QuerySafetyError(
                    f"Blocked dangerous query: {stmt_type} without a WHERE clause will modify or delete "
                    "every row in the table. Specify a WHERE filter or pass allow_unfiltered=True to proceed.",
                    query=str(stmt),
                )


def inject_limit(
    query: str,
    limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> str:
    """
    Safely inject or clamp the LIMIT clause on SELECT queries.

    - If the query is not a SELECT, it is returned unmodified.
    - If no LIMIT clause exists, adds 'LIMIT {limit}' (defaults to settings.mysql_default_limit).
    - If a LIMIT clause already exists:
        - If the existing limit exceeds max_limit, clamps it down to max_limit.
        - Otherwise, leaves the existing limit intact.
    - Preserves trailing lock clauses (FOR UPDATE / FOR SHARE / LOCK IN SHARE MODE)
      and trailing semicolons.
    """
    settings = get_settings()
    default_lim = limit if limit is not None else settings.mysql_default_limit
    max_lim = max_limit if max_limit is not None else settings.mysql_max_limit
    effective_default = min(default_lim, max_lim)

    statements = sqlparse.parse(query)
    if not statements:
        return query

    processed_statements: List[str] = []

    for stmt in statements:
        stmt_type = get_statement_type(stmt)
        if stmt_type != "SELECT":
            processed_statements.append(str(stmt))
            continue

        # Look for existing top-level LIMIT keyword
        limit_token_idx: Optional[int] = None
        for i, token in enumerate(stmt.tokens):
            if token.is_whitespace or isinstance(token, Comment) or isinstance(token, Parenthesis):
                continue
            if token.ttype in (Keyword, Keyword.DML) and token.value.upper() == "LIMIT":
                limit_token_idx = i
                break

        if limit_token_idx is not None:
            # Existing LIMIT detected: extract argument tokens and clamp if > max_lim
            limit_args_indices = []
            for j in range(limit_token_idx + 1, len(stmt.tokens)):
                tok = stmt.tokens[j]
                if tok.ttype == Punctuation and tok.value == ";":
                    break
                if tok.ttype in (Keyword, Keyword.DML) and tok.value.upper() in ("FOR", "LOCK"):
                    break
                limit_args_indices.append(j)

            limit_arg_str = "".join(stmt.tokens[j].value for j in limit_args_indices).strip()

            # Handle format variants:
            # 1. "offset, count"
            # 2. "count OFFSET offset"
            # 3. "count"
            if "," in limit_arg_str:
                parts = limit_arg_str.split(",", 1)
                try:
                    offset = int(parts[0].strip())
                    count = int(parts[1].strip())
                    clamped_count = min(count, max_lim)
                    clamped_arg = f"{offset}, {clamped_count}"
                except ValueError:
                    clamped_arg = limit_arg_str
            elif "OFFSET" in limit_arg_str.upper():
                match = re.search(r"^(\d+)\s+OFFSET\s+(\d+)$", limit_arg_str, re.IGNORECASE)
                if match:
                    count = int(match.group(1))
                    offset = int(match.group(2))
                    clamped_count = min(count, max_lim)
                    clamped_arg = f"{clamped_count} OFFSET {offset}"
                else:
                    clamped_arg = limit_arg_str
            else:
                try:
                    count = int(limit_arg_str)
                    clamped_count = min(count, max_lim)
                    clamped_arg = str(clamped_count)
                except ValueError:
                    clamped_arg = limit_arg_str

            prefix = "".join(stmt.tokens[k].value for k in range(0, limit_token_idx + 1))
            suffix_start = (limit_args_indices[-1] + 1) if limit_args_indices else (limit_token_idx + 1)
            suffix = "".join(stmt.tokens[k].value for k in range(suffix_start, len(stmt.tokens)))
            if suffix and not suffix[0].isspace() and not suffix.startswith(";"):
                suffix = " " + suffix

            processed_statements.append(f"{prefix} {clamped_arg}{suffix}")
        else:
            # No top-level LIMIT found: inject target default limit
            # Check for trailing lock clauses (e.g. FOR UPDATE)
            lock_token_idx: Optional[int] = None
            for i, tok in enumerate(stmt.tokens):
                if isinstance(tok, Parenthesis):
                    continue
                if tok.ttype in (Keyword, Keyword.DML) and tok.value.upper() in ("FOR", "LOCK"):
                    lock_token_idx = i
                    break

            if lock_token_idx is not None:
                before_lock = "".join(stmt.tokens[k].value for k in range(0, lock_token_idx)).rstrip()
                lock_and_after = "".join(stmt.tokens[k].value for k in range(lock_token_idx, len(stmt.tokens)))
                processed_statements.append(f"{before_lock} LIMIT {effective_default} {lock_and_after}")
            else:
                raw = str(stmt).rstrip()
                if raw.endswith(";"):
                    without_semi = raw[:-1].rstrip()
                    processed_statements.append(f"{without_semi} LIMIT {effective_default};")
                else:
                    processed_statements.append(f"{raw} LIMIT {effective_default}")

    return "\n".join(processed_statements)

