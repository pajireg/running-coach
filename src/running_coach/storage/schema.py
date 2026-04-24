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
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    with db.connection() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
