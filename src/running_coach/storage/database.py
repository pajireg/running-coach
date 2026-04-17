"""Postgres 데이터베이스 클라이언트."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from psycopg import Connection, connect
from psycopg.rows import dict_row


class DatabaseClient:
    """간단한 Postgres 연결 래퍼."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[Connection[Any]]:
        """자동 commit/rollback 연결 컨텍스트."""
        conn = connect(self.dsn, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ping(self) -> None:
        """DB 연결 확인."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
