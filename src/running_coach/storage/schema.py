"""Runtime schema compatibility helpers."""

from __future__ import annotations

from pathlib import Path

from ..utils.logger import get_logger
from .database import DatabaseClient

logger = get_logger(__name__)


def ensure_core_schema(db: DatabaseClient) -> None:
    """Apply idempotent core schema SQL for existing Docker volumes."""
    schema_path = Path(__file__).resolve().parents[3] / "db" / "init" / "001_core_schema.sql"
    if not schema_path.exists():
        logger.warning(
            "DB 스키마 파일을 찾을 수 없어 런타임 스키마 확인을 건너뜁니다: %s",
            schema_path,
        )
        return

    sql = schema_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql)
    with db.connection() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL statements while preserving PostgreSQL dollar-quoted blocks."""
    statements: list[str] = []
    current: list[str] = []
    dollar_tag: str | None = None
    in_single_quote = False
    index = 0

    while index < len(sql):
        char = sql[index]

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
                continue
            current.append(char)
            index += 1
            continue

        if char == "'" and not in_single_quote:
            in_single_quote = True
            current.append(char)
            index += 1
            continue
        if char == "'" and in_single_quote:
            current.append(char)
            if index + 1 < len(sql) and sql[index + 1] == "'":
                current.append("'")
                index += 2
                continue
            in_single_quote = False
            index += 1
            continue

        if not in_single_quote and char == "$":
            end = sql.find("$", index + 1)
            if end != -1:
                tag = sql[index : end + 1]
                if tag == "$$" or tag[1:-1].replace("_", "").isalnum():
                    dollar_tag = tag
                    current.append(tag)
                    index = end + 1
                    continue

        if char == ";" and not in_single_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements
