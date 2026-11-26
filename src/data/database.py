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
    camera_make     TEXT,                    -- 촬영 기기 제조사 (예: Apple, Samsung)
    camera_model    TEXT,                    -- 촬영 기기 모델명 (예: iPhone 13 Pro, SM-S908N)
    country_code    TEXT,                    -- 역지오코딩 국가 코드 (예: KR, US)
    country_name    TEXT,                    -- 역지오코딩 국가명 (예: 대한민국, South Korea)
    state_name      TEXT,                    -- 역지오코딩 주/도명 (예: 경기도, 캘리포니아, 하부오스트리아)
    city_name       TEXT,                    -- 역지오코딩 도시명 (예: 서울, 곡성군, 할슈타트)
    original_snapshot TEXT,                  -- 사용자 수정 전 원본 메타데이터 JSON 스냅샷
    is_user_edited  INTEGER DEFAULT 0,       -- 사용자 직접 수정 여부 (0: 원본, 1: 수정됨)
    FOREIGN KEY (media_id) REFERENCES media_files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_meta_taken_at  ON metadata(taken_at);
CREATE INDEX IF NOT EXISTS idx_meta_timestamp ON metadata(taken_timestamp);

-- 4. 작업 세션 단위 이력 테이블
CREATE TABLE IF NOT EXISTS job_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_dir        TEXT NOT NULL,
    target_dir        TEXT NOT NULL,
    total_files       INTEGER DEFAULT 0,
    processed_count   INTEGER DEFAULT 0,
    skipped_duplicate INTEGER DEFAULT 0,
    failed_count      INTEGER DEFAULT 0,
    photo_count       INTEGER DEFAULT 0,
    video_count       INTEGER DEFAULT 0,
    total_bytes       INTEGER DEFAULT 0,
    status            TEXT DEFAULT 'COMPLETED',
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. 애플리케이션 전역 설정 키-값 테이블
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
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
        if str(self.db_path) != ":memory:":
            self.db_path = Path(self.db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        """테이블 및 인덱스 초기화."""
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
            # 기존 DB 호환용 컬럼 마이그레이션
            for col in ["camera_make", "camera_model", "country_code", "country_name", "state_name", "city_name", "original_snapshot"]:
                try:
                    self._conn.execute(f"ALTER TABLE metadata ADD COLUMN {col} TEXT;")
                except sqlite3.OperationalError:
                    pass
            try:
                self._conn.execute("ALTER TABLE metadata ADD COLUMN is_user_edited INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass
            try:
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_camera ON metadata(camera_make, camera_model);")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_location ON metadata(country_name, state_name, city_name);")
                self._conn.execute("UPDATE metadata SET country_name = '위치정보없음' WHERE country_name = '위치 정보 없음';")
            except sqlite3.OperationalError:
                pass

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

    # ── 설정 키-값 저장소 ──────────────────────────────────

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """애플리케이션 전역 설정 값 조회"""
        try:
            cur = self.conn.execute("SELECT value FROM app_settings WHERE key = ? LIMIT 1;", (key,))
            row = cur.fetchone()
            if row:
                return str(row["value"])
        except Exception as exc:
            logger.warning("get_setting 실패 [%s]: %s", key, exc)
        return default

    def set_setting(self, key: str, value: str) -> bool:
        """애플리케이션 전역 설정 값 저장 (UPSERT)"""
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (key, str(value)),
                )
            return True
        except Exception as exc:
            logger.error("set_setting 실패 [%s=%s]: %s", key, value, exc)
            return False

    # ── 집계 쿼리 (대시보드 / 이력 뷰용) ───────────────────

    def get_statistics(self) -> dict:
        """
        전체 미디어 통계를 반환한다.
        
        반환 키:
            total_files       : 전체 파일 수
            total_size_bytes  : 전체 파일 용량 합계 (bytes)
            photo_count       : 사진 파일 수
            video_count       : 동영상 파일 수
            skipped_duplicate : 중복 제거(스킵) 파일 수
            job_count         : 총 실행된 작업 수
            last_updated      : 가장 최근 작업/생성 일시 문자열
        """
        try:
            cur = self.conn.execute(
                """
                SELECT COUNT(*) AS cnt, 
                       SUM(file_size) AS total_size,
                       SUM(CASE WHEN media_type='photo' THEN 1 ELSE 0 END) AS photo_cnt,
                       SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END) AS video_cnt,
                       MAX(created_at) AS last_updated
                  FROM media_files
                """
            )
            row = cur.fetchone()

            # job_history 집계 (중복 방지 수치 및 총 작업 수)
            cur_job = self.conn.execute(
                "SELECT SUM(skipped_duplicate), COUNT(*), MAX(created_at) FROM job_history"
            )
            job_row = cur_job.fetchone()
            skipped_cnt = (job_row[0] or 0) if job_row else 0
            job_cnt     = (job_row[1] or 0) if job_row else 0
            last_job_dt = (job_row[2] or None) if job_row else None

            last_dt = last_job_dt or (row["last_updated"] if row else None)

            if row:
                return {
                    "total_files":       row["cnt"]          or 0,
                    "total_size_bytes":  row["total_size"]   or 0,
                    "photo_count":       row["photo_cnt"]    or 0,
                    "video_count":       row["video_cnt"]    or 0,
                    "skipped_duplicate": skipped_cnt,
                    "job_count":         job_cnt,
                    "last_updated":      last_dt,
                }
        except Exception as exc:
            logger.warning("get_statistics 실패: %s", exc)
        return {
            "total_files": 0,
            "total_size_bytes": 0,
            "photo_count": 0,
            "video_count": 0,
            "skipped_duplicate": 0,
            "job_count": 0,
            "last_updated": None,
        }

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

    def record_job_history(
        self,
        source_dir: str,
        target_dir: str,
        total_files: int = 0,
        processed_count: int = 0,
        skipped_duplicate: int = 0,
        failed_count: int = 0,
        photo_count: int = 0,
        video_count: int = 0,
        total_bytes: int = 0,
        status: str = "COMPLETED",
    ) -> int:
        """
        1회 작업 세션(Run) 단위로 작업 이력을 기록합니다.
        """
        try:
            with self.conn:
                cur = self.conn.execute(
                    """
                    INSERT INTO job_history (
                        source_dir, target_dir, total_files,
                        processed_count, skipped_duplicate, failed_count,
                        photo_count, video_count, total_bytes, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                    """,
                    (
                        source_dir,
                        target_dir,
                        total_files,
                        processed_count,
                        skipped_duplicate,
                        failed_count,
                        photo_count,
                        video_count,
                        total_bytes,
                        status,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            logger.error("record_job_history 실패: %s", exc)
            return -1

    def get_history_summary(self) -> list[dict]:
        """
        처리 이력 뷰용 — 작업 실행 세션(Task) 단위 집계.
        job_history 테이블에서 1회 실행 단위로 정확하게 조회합니다.
        (job_history 데이터가 없는 과거 레거시의 경우 media_files 기반 폴백)
        
        반환 항목 키:
            session_time : 작업 실행 일시 (YYYY-MM-DD HH:MM)
            source_dir   : 원본 입력 폴더 대표 경로
            target_dir   : 정리 출력 폴더 대표 경로
            count        : 총 처리 파일 수
            media_types  : 미디어 유형 요약 (사진 N, 동영상 M)
            total_size   : 총 용량 바이트
            status       : 대표 상태 (COMPLETED / FAILED)
        """
        try:
            # 1. job_history 테이블 조회 우선
            cur = self.conn.execute(
                """
                SELECT 
                    id,
                    strftime('%Y-%m-%d %H:%M', created_at) AS session_time,
                    source_dir,
                    target_dir,
                    total_files,
                    processed_count AS count,
                    skipped_duplicate,
                    failed_count,
                    photo_count,
                    video_count,
                    total_bytes AS total_size,
                    status
                FROM job_history
                ORDER BY id DESC
                """
            )
            rows = []
            for row in cur.fetchall():
                r = dict(row)
                parts = []
                if r.get("photo_count"):
                    parts.append(f"사진 {r['photo_count']}개")
                if r.get("video_count"):
                    parts.append(f"동영상 {r['video_count']}개")
                r["media_types"] = ", ".join(parts) if parts else "-"
                rows.append(r)

            if rows:
                return rows

            # 2. job_history가 비어 있는 경우 (레거시 DB 데이터 폴백)
            cur = self.conn.execute(
                """
                SELECT 
                    strftime('%Y-%m-%d %H:%M', created_at) AS session_time,
                    MIN(original_path)                      AS sample_orig,
                    MIN(file_path)                          AS sample_dest,
                    COUNT(*)                                AS count,
                    SUM(CASE WHEN media_type='photo' THEN 1 ELSE 0 END) AS photo_cnt,
                    SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END) AS video_cnt,
                    SUM(file_size)                          AS total_size,
                    MAX(CASE WHEN status='FAILED' THEN 'FAILED' ELSE 'COMPLETED' END) AS status
                FROM media_files
                GROUP BY strftime('%Y-%m-%d %H:%M', created_at)
                ORDER BY session_time DESC
                """
            )
            for row in cur.fetchall():
                r = dict(row)
                parts = []
                if r.get("photo_cnt"):
                    parts.append(f"사진 {r['photo_cnt']}개")
                if r.get("video_cnt"):
                    parts.append(f"동영상 {r['video_cnt']}개")
                r["media_types"] = ", ".join(parts) if parts else "-"

                # 경로 추출
                s_orig = r.get("sample_orig")
                s_dest = r.get("sample_dest")
                r["source_dir"] = str(Path(s_orig).parent.parent) if s_orig else "-"
                r["target_dir"] = str(Path(s_dest).parent.parent) if s_dest else "-"

                rows.append(r)
            return rows
        except Exception as exc:
            logger.warning("get_history_summary 실패: %s", exc)
        return []

    def reset_database(self) -> bool:
        """
        데이터베이스의 모든 레코드(media_files, metadata, FTS5, job_history)를 안전하게 삭제하고
        VACUUM을 수행하여 저장 공간을 초기화합니다.
        """
        try:
            with self.conn:
                self.conn.execute("DELETE FROM metadata;")
                self.conn.execute("DELETE FROM media_files;")
                self.conn.execute("DELETE FROM job_history;")
                try:
                    self.conn.execute("DELETE FROM metadata_fts;")
                except Exception:
                    pass
            self.conn.execute("VACUUM;")
            logger.info("데이터베이스 레코드 초기화 및 VACUUM 완료")
            return True
        except Exception as exc:
            logger.error("데이터베이스 초기화 실패: %s", exc)
            return False

    def get_storage_info(self) -> dict:
        """
        데이터베이스 파일 크기 및 전체 레코드 건수를 반환합니다.
        """
        total_records = 0
        file_size_bytes = 0
        db_path_str = str(self.db_path)

        try:
            cur = self.conn.execute("SELECT COUNT(*) FROM media_files")
            row = cur.fetchone()
            if row:
                total_records = row[0]
        except Exception as exc:
            logger.warning("get_storage_info 레코드 수 조회 실패: %s", exc)

        if str(self.db_path) != ":memory:":
            p = Path(self.db_path)
            if p.exists():
                file_size_bytes = p.stat().st_size

        return {
            "db_path": db_path_str,
            "total_records": total_records,
            "file_size_bytes": file_size_bytes,
        }

    # ── 소멸자 ───────────────────────────────────────────────

    def close(self) -> None:
        """커넥션을 명시적으로 닫는다."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()
