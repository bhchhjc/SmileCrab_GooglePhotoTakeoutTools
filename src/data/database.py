"""
GooglePhotoTakeoutTools - Database Manager
SQLite 데이터베이스 초기화, 연결 관리 및 스키마 마이그레이션 모듈
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 데이터베이스 기본 스키마 DDL
_SCHEMA_SQL = """
-- 1. 미디어 파일 기본 정보 테이블
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,      -- 정리된 최종 파일 경로
    original_path TEXT,                 -- Takeout 원본 경로
    file_name TEXT NOT NULL,
    file_ext TEXT NOT NULL,             -- jpg, heic, mp4 등
    file_size INTEGER,                  -- 바이트 단위
    file_hash TEXT,                     -- SHA-256 해시 (중복 식별용)
    media_type TEXT,                    -- photo, video, unknown
    album_name TEXT,                    -- 원본 폴더/앨범명
    status TEXT DEFAULT 'COMPLETED',    -- COMPLETED, FAILED, SKIPPED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_hash ON media_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_media_type ON media_files(media_type);

-- 2. 메타데이터 (JSON 및 EXIF 통합) 테이블
CREATE TABLE IF NOT EXISTS metadata (
    media_id INTEGER PRIMARY KEY,
    title TEXT,
    description TEXT,                   -- Google 포토 설명/캡션
    taken_at TEXT,                      -- ISO8601 (YYYY-MM-DD HH:MM:SS)
    taken_timestamp INTEGER,            -- Unix Epoch Time
    latitude REAL DEFAULT 0.0,
    longitude REAL DEFAULT 0.0,
    altitude REAL DEFAULT 0.0,
    people TEXT,                        -- JSON 형식의 인물 목록
    is_favorited INTEGER DEFAULT 0,
    FOREIGN KEY (media_id) REFERENCES media_files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meta_taken_at ON metadata(taken_at);
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
    SQLite 데이터베이스 커넥션 및 트랜잭션 관리자
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_db_dir()
        self.init_schema()

    def _ensure_db_dir(self) -> None:
        """데이터베이스 파일이 저장될 상위 디렉토리 생성"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """새로운 SQLite 커넥션을 생성하고 Row 팩토리를 설정하여 반환"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_schema(self) -> None:
        """데이터베이스 테이블 및 인덱스 초기화"""
        with self.get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
            # FTS5 가상 테이블 생성 시도 (지원되지 않는 SQLite 빌드 대비 방어)
            try:
                conn.executescript(_FTS_SCHEMA_SQL)
            except sqlite3.OperationalError as e:
                logger.warning("FTS5 가상 테이블 생성 생략 (SQLite FTS5 미지원 환경): %s", e)
