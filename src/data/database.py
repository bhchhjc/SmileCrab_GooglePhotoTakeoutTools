"""
data/database.py
────────────────────────────────────────────────────────────────
SQLite 데이터베이스 초기화, 연결 관리 및 집계 쿼리 모듈

기본 DB 경로: 프로젝트 루트 / data / library.db
(경로 변경이 필요하면 DatabaseManager(db_path=...) 로 주입 가능)
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 기본 DB 경로 (프로젝트 루트 기준)
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "library.db"

# ── DDL ──────────────────────────────────────────────────────

_SCHEMA_SQL = """
-- 1. 미디어 파일 기본 정보 테이블
CREATE TABLE IF NOT EXISTS media_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT UNIQUE NOT NULL,       -- 정리된 최종 파일 경로
    original_path TEXT,                      -- Takeout 원본 경로
    file_name    TEXT NOT NULL,
    file_ext     TEXT NOT NULL,              -- jpg, heic, mp4 등
    file_size    INTEGER,                    -- 바이트 단위
    file_hash    TEXT,                       -- SHA-256 해시 (중복 식별용)
    media_type   TEXT,                       -- photo, video, unknown
    album_name   TEXT,                       -- 원본 폴더/앨범명
    status       TEXT DEFAULT 'COMPLETED',   -- COMPLETED, FAILED, SKIPPED
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_hash ON media_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_media_type ON media_files(media_type);

-- 2. 메타데이터 (JSON 및 EXIF 통합) 테이블
CREATE TABLE IF NOT EXISTS metadata (
    media_id        INTEGER PRIMARY KEY,
    title           TEXT,
    description     TEXT,                    -- Google 포토 설명/캡션
    taken_at        TEXT,                    -- ISO8601 (YYYY-MM-DD HH:MM:SS)
    taken_timestamp INTEGER,                 -- Unix Epoch Time
    latitude        REAL DEFAULT 0.0,
    longitude       REAL DEFAULT 0.0,
    altitude        REAL DEFAULT 0.0,
    people          TEXT,                    -- JSON 형식의 인물 목록
    is_favorited    INTEGER DEFAULT 0,
    FOREIGN KEY (media_id) REFERENCES media_files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meta_taken_at  ON metadata(taken_at);
CREATE INDEX IF NOT EXISTS idx_meta_timestamp ON metadata(taken_timestamp);
"""

_FTS_SCHEMA_SQL = """
-- 3. 풀텍스트 검색(FTS5) 가상 테이블
CREATE VIRTUAL TABLE IF NOT EXISTS metadata_fts USING fts5(
    file_name,
    description,
    people,
    album_name,
    content='media_files',
    content_rowid='id'
);
"""


class DatabaseManager:
    """
    SQLite 데이터베이스 커넥션 및 트랜잭션 관리자.
    
    사용 예:
        db = DatabaseManager()          # 기본 경로 사용
        db = DatabaseManager(db_path=Path("custom.db"))  # 사용자 지정 경로
        db.initialize()
        conn = db.conn
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    # ── 초기화 ───────────────────────────────────────────────

    def initialize(self) -> None:
        """DB 디렉토리 생성 + 스키마 초기화. 이미 초기화된 경우 재실행하지 않는다."""
        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        """테이블 및 인덱스 초기화."""
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
            try:
                self._conn.executescript(_FTS_SCHEMA_SQL)
            except sqlite3.OperationalError as exc:
                logger.warning("FTS5 가상 테이블 생성 생략 (SQLite FTS5 미지원): %s", exc)

    # ── 커넥션 접근 ──────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        """
        현재 커넥션을 반환한다.
        미초기화 상태라면 자동으로 initialize()를 호출한다.
        """
        if self._conn is None:
            self.initialize()
        return self._conn

    def get_connection(self) -> sqlite3.Connection:
        """
        하위 호환 메서드 — conn 프로퍼티와 동일.
        ProcessService 등 기존 코드에서 사용 중.
        """
        return self.conn

    # ── 집계 쿼리 (대시보드 / 이력 뷰용) ───────────────────

    def get_statistics(self) -> dict:
        """
        전체 미디어 통계를 반환한다.
        
        반환 키:
            total_files      : 전체 파일 수
            total_size_bytes : 전체 파일 용량 합계 (bytes)
            last_updated     : 가장 최근 created_at 날짜 문자열
        """
        try:
            cur = self.conn.execute(
                "SELECT COUNT(*) AS cnt, SUM(file_size) AS total_size,"
                "       MAX(created_at) AS last_updated"
                "  FROM media_files"
            )
            row = cur.fetchone()
            if row:
                return {
                    "total_files":       row["cnt"]          or 0,
                    "total_size_bytes":  row["total_size"]   or 0,
                    "last_updated":      row["last_updated"] or None,
                }
        except Exception as exc:
            logger.warning("get_statistics 실패: %s", exc)
        return {"total_files": 0, "total_size_bytes": 0, "last_updated": None}

    def get_recent_jobs(self, limit: int = 10) -> list[dict]:
        """
        최근 처리 작업 목록을 반환한다 (날짜 + 앨범 그룹 기준).
        
        반환 항목 키: date, album, count
        """
        try:
            cur = self.conn.execute(
                "SELECT DATE(created_at) AS date,"
                "       album_name        AS album,"
                "       COUNT(*)          AS count"
                "  FROM media_files"
                " GROUP BY DATE(created_at), album_name"
                " ORDER BY DATE(created_at) DESC"
                " LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("get_recent_jobs 실패: %s", exc)
        return []

    def get_history_summary(self) -> list[dict]:
        """
        처리 이력 뷰용 — 날짜 + 앨범 단위 집계.
        
        반환 항목 키:
            date        : 처리 날짜 (YYYY-MM-DD)
            album_name  : 앨범/입력 폴더명
            count       : 처리 파일 수
            media_types : 미디어 유형 요약 (예: "사진 10, 동영상 2")
            status      : 대표 상태 (COMPLETED / FAILED 혼합 시 FAILED)
        """
        try:
            cur = self.conn.execute(
                "SELECT DATE(created_at)                                        AS date,"
                "       album_name,"
                "       COUNT(*)                                                AS count,"
                "       SUM(CASE WHEN media_type='photo' THEN 1 ELSE 0 END)    AS photo_cnt,"
                "       SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END)    AS video_cnt,"
                "       MAX(CASE WHEN status='FAILED' THEN 'FAILED' ELSE 'COMPLETED' END) AS status"
                "  FROM media_files"
                " GROUP BY DATE(created_at), album_name"
                " ORDER BY DATE(created_at) DESC"
            )
            rows = []
            for row in cur.fetchall():
                r = dict(row)
                parts = []
                if r.get("photo_cnt"):
                    parts.append(f"사진 {r['photo_cnt']}")
                if r.get("video_cnt"):
                    parts.append(f"동영상 {r['video_cnt']}")
                r["media_types"] = ", ".join(parts) if parts else "-"
                rows.append(r)
            return rows
        except Exception as exc:
            logger.warning("get_history_summary 실패: %s", exc)
        return []

    # ── 소멸자 ───────────────────────────────────────────────

    def close(self) -> None:
        """커넥션을 명시적으로 닫는다."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()
