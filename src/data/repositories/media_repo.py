"""
GooglePhotoTakeoutTools - Media Repository
미디어 파일 및 메타데이터 영속성 CRUD 및 검색 쿼리 모듈
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.models import GeoLocation, MediaFile, MediaMetadata
from src.data.database import DatabaseManager

logger = logging.getLogger(__name__)


class MediaRepository:
    """
    미디어 파일 및 메타데이터 데이터베이스 저장소 (Repository Pattern)
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def find_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """
        주어진 SHA-256 해시를 가진 미디어 파일이 이미 DB에 존재하는지 조회 (중복 검사)
        """
        query = "SELECT * FROM media_files WHERE file_hash = ? LIMIT 1"
        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (file_hash,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def insert_media(
        self,
        final_path: Path,
        original_path: Path,
        file_hash: str,
        media_file: MediaFile,
        metadata: Optional[MediaMetadata] = None,
        album_name: str = "",
        status: str = "COMPLETED",
    ) -> int:
        """
        정리 완료된 미디어 파일과 메타데이터를 단일 트랜잭션으로 DB에 기록합니다.
        """
        insert_media_sql = """
        INSERT INTO media_files (
            file_path, original_path, file_name, file_ext, file_size, file_hash, media_type, album_name, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            original_path = excluded.original_path,
            file_hash = excluded.file_hash,
            status = excluded.status;
        """

        insert_meta_sql = """
        INSERT OR REPLACE INTO metadata (
            media_id, title, description, taken_at, taken_timestamp,
            latitude, longitude, altitude, people, is_favorited,
            camera_make, camera_model, country_code, country_name, state_name, city_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                insert_media_sql,
                (
                    str(final_path),
                    str(original_path),
                    media_file.normalized_name,
                    media_file.extension,
                    media_file.file_size,
                    file_hash,
                    media_file.media_type.value,
                    album_name,
                    status,
                ),
            )
            media_id = cursor.lastrowid

            if metadata and media_id:
                taken_at_str = (
                    metadata.best_datetime.strftime("%Y-%m-%d %H:%M:%S")
                    if metadata.best_datetime
                    else None
                )
                people_json = json.dumps(metadata.people, ensure_ascii=False) if metadata.people else "[]"
                geo = metadata.geo_data or GeoLocation()

                cursor.execute(
                    insert_meta_sql,
                    (
                        media_id,
                        metadata.title or media_file.normalized_name,
                        metadata.description,
                        taken_at_str,
                        metadata.photo_taken_timestamp,
                        geo.latitude,
                        geo.longitude,
                        geo.altitude,
                        people_json,
                        1 if metadata.is_favorited else 0,
                        metadata.camera_make or "",
                        metadata.camera_model or "",
                        metadata.country_code or "",
                        metadata.country_name or "",
                        metadata.state_name or "",
                        metadata.city_name or "",
                    ),
                )

            conn.commit()
            return media_id or 0

    def get_statistics(self) -> Dict[str, Any]:
        """라이브러리 전체 통계 (총 파일 수, 사진 수, 비디오 수, 위치정보 보유 수 등) 반환"""
        query = """
        SELECT 
            COUNT(m.id) as total_count,
            SUM(CASE WHEN m.media_type = 'photo' THEN 1 ELSE 0 END) as photo_count,
            SUM(CASE WHEN m.media_type = 'video' THEN 1 ELSE 0 END) as video_count,
            SUM(m.file_size) as total_size,
            SUM(CASE WHEN meta.latitude != 0.0 OR meta.longitude != 0.0 THEN 1 ELSE 0 END) as gps_count
        FROM media_files m
        LEFT JOIN metadata meta ON m.id = meta.media_id;
        """
        with self.db.get_connection() as conn:
            row = conn.execute(query).fetchone()
            if row:
                return dict(row)
        return {}

    def get_output_roots(self) -> List[str]:
        """
        DB에 저장된 정리 파일들의 실제 고유 출력 루트 디렉토리 목록을 정확히 반환합니다.
        
        1순위: job_history 테이블에 기록된 실제 target_dir 경로 중 media_files를 포함하는 유효 경로
        2순위: 미디어 파일 경로들의 공통 조상 디렉토리(os.path.commonpath) 지능형 도출
        """
        roots = set()
        with self.db.get_connection() as conn:
            # 1. job_history 테이블의 target_dir 조회
            try:
                cur = conn.execute(
                    """
                    SELECT DISTINCT target_dir FROM job_history
                    WHERE target_dir IS NOT NULL AND target_dir != '' AND target_dir != '-'
                    ORDER BY id DESC
                    """
                )
                for row in cur.fetchall():
                    td = row["target_dir"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
                    if td and str(td).strip():
                        td_str = str(Path(td).resolve())
                        roots.add(td_str)
            except Exception as e:
                logger.debug("job_history target_dir 조회 중 참고: %s", e)

            # 2. media_files의 file_path 조회하여 검증 및 Fallback
            cur = conn.execute("SELECT DISTINCT file_path FROM media_files WHERE file_path IS NOT NULL AND file_path != ''")
            all_files = [
                str(Path(r["file_path"] if isinstance(r, dict) or hasattr(r, "keys") else r[0]).resolve())
                for r in cur.fetchall()
            ]

            if not all_files:
                return sorted(list(roots))

            # roots에 있는 경로들이 실제로 파일들을 포함하고 있는지 필터링
            valid_roots = set()
            uncovered_files = list(all_files)

            for r in roots:
                matching = [f for f in uncovered_files if f.startswith(r)]
                if matching:
                    valid_roots.add(r)
                    uncovered_files = [f for f in uncovered_files if not f.startswith(r)]

            # 아직 커버되지 않은 파일들이 있다면 공통 경로(commonpath)로 도출
            if uncovered_files:
                try:
                    common = os.path.commonpath(uncovered_files)
                    if common and common != "/" and os.path.isdir(common):
                        valid_roots.add(str(Path(common).resolve()))
                    elif common:
                        valid_roots.add(str(Path(common).parent.resolve()))
                except Exception:
                    pass

        return sorted(list(valid_roots))

    def search_media(
        self,
        keyword: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        media_type: Optional[str] = None,
        has_gps: Optional[bool] = None,
        root_path: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        복합 조건(키워드, 연/월, 미디어 유형, GPS 유무, 루트 경로)으로 미디어 목록을 초고속 조회.
        limit=None인 경우 전체 레코드를 반환합니다.
        """
        conditions = ["1=1"]
        params: List[Any] = []

        if root_path:
            conditions.append("m.file_path LIKE ?")
            params.append(f"{root_path}%")

        if keyword:
            conditions.append(
                "(m.file_name LIKE ? OR meta.description LIKE ? OR meta.people LIKE ? OR m.album_name LIKE ? OR meta.camera_make LIKE ? OR meta.camera_model LIKE ? OR meta.country_name LIKE ? OR meta.state_name LIKE ? OR meta.city_name LIKE ?)"
            )
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw, kw, kw, kw, kw, kw])

        if year:
            conditions.append("strftime('%Y', meta.taken_at) = ?")
            params.append(f"{year:04d}")

        if month:
            conditions.append("strftime('%m', meta.taken_at) = ?")
            params.append(f"{month:02d}")

        if media_type:
            conditions.append("m.media_type = ?")
            params.append(media_type)

        if has_gps is True:
            conditions.append("(meta.latitude != 0.0 OR meta.longitude != 0.0)")
        elif has_gps is False:
            conditions.append("(meta.latitude = 0.0 AND meta.longitude = 0.0)")

        sql = f"""
        SELECT 
            m.id, m.file_path, m.original_path, m.file_name, m.file_ext, m.file_size, m.file_hash, m.media_type, m.album_name,
            meta.taken_at, meta.description, meta.latitude, meta.longitude, meta.people, meta.is_favorited,
            meta.camera_make, meta.camera_model, meta.country_code, meta.country_name, meta.state_name, meta.city_name
        FROM media_files m
        LEFT JOIN metadata meta ON m.id = meta.media_id
        WHERE {' AND '.join(conditions)}
        ORDER BY meta.taken_at DESC, m.file_name ASC
        """
        if limit is not None:
            sql += " LIMIT ? OFFSET ?;"
            params.extend([limit, offset])
        elif offset > 0:
            sql += " LIMIT -1 OFFSET ?;"
            params.append(offset)
        else:
            sql += ";"

        results = []
        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, params)
            for row in cursor.fetchall():
                results.append(dict(row))
        return results

    def clean_missing_files(self) -> int:
        """
        실제 디스크 상에 존재하지 않는 미디어 파일 레코드를 DB에서 찾아 삭제합니다.
        삭제된 고아 레코드 수를 반환합니다.
        """
        deleted_count = 0
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, file_path FROM media_files;")
            rows = cursor.fetchall()

            missing_ids = []
            for row in rows:
                mid = row["id"]
                f_path = row["file_path"]
                if not f_path or not os.path.exists(f_path):
                    missing_ids.append(mid)

            if missing_ids:
                chunk_size = 500
                for i in range(0, len(missing_ids), chunk_size):
                    chunk = missing_ids[i:i + chunk_size]
                    placeholders = ",".join("?" * len(chunk))
                    cursor.execute(f"DELETE FROM metadata WHERE media_id IN ({placeholders});", chunk)
                    cursor.execute(f"DELETE FROM media_files WHERE id IN ({placeholders});", chunk)
                deleted_count = len(missing_ids)

        return deleted_count

    def get_root_media_count(self, root_path: str) -> int:
        """
        특정 타겟 루트 경로 하위에 속한 미디어 파일의 총 개수를 반환합니다.
        """
        norm = os.path.normpath(str(root_path))
        query = "SELECT COUNT(*) AS cnt FROM media_files WHERE file_path LIKE ?;"
        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (f"{norm}%",))
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0

    def get_root_media_stats(self, root_path: str) -> Tuple[int, int, int]:
        """
        특정 타겟 루트 경로 하위의 (총 미디어 수, 사진 수, 동영상 수)를 반환합니다.
        """
        norm = os.path.normpath(str(root_path))
        query = """
        SELECT 
            COUNT(*) AS total_cnt,
            SUM(CASE WHEN media_type = 'photo' THEN 1 ELSE 0 END) AS photo_cnt,
            SUM(CASE WHEN media_type = 'video' THEN 1 ELSE 0 END) AS video_cnt
        FROM media_files
        WHERE file_path LIKE ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(query, (f"{norm}%",))
            row = cursor.fetchone()
            if row:
                total = int(row["total_cnt"] or 0)
                photos = int(row["photo_cnt"] or 0)
                videos = int(row["video_cnt"] or 0)
                return total, photos, videos
            return 0, 0, 0

    def get_media_items_for_rename(self, root_path: str) -> List[Dict[str, Any]]:
        """
        파일명 일괄 변경을 위한 미디어 및 메타데이터 목록을 촬영일시 오름차순으로 조회합니다.
        """
        norm = os.path.normpath(str(root_path))
        sql = """
        SELECT 
            m.id, m.file_path, m.file_name, m.file_ext, m.media_type,
            meta.taken_at, meta.camera_make, meta.camera_model,
            meta.country_name, meta.state_name, meta.city_name
        FROM media_files m
        LEFT JOIN metadata meta ON m.id = meta.media_id
        WHERE m.file_path LIKE ?
        ORDER BY meta.taken_at ASC, m.id ASC;
        """
        results: List[Dict[str, Any]] = []
        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, (f"{norm}%",))
            for row in cursor.fetchall():
                results.append(dict(row))
        return results

    def get_geo_media_stats(self, root_path: Optional[str] = None) -> Tuple[int, int]:
        """
        지정된 대상 경로(또는 전체 DB)의 (전체 미디어 파일 수, GPS 좌표 보유 파일 수)를 반환합니다.
        """
        sql = """
        SELECT 
            COUNT(m.id) AS total_cnt,
            SUM(CASE WHEN meta.latitude IS NOT NULL AND meta.longitude IS NOT NULL 
                     AND (ABS(meta.latitude) > 0.0001 OR ABS(meta.longitude) > 0.0001) 
                     THEN 1 ELSE 0 END) AS geo_cnt
        FROM media_files m
        LEFT JOIN metadata meta ON m.id = meta.media_id
        """
        params: List[Any] = []
        if root_path:
            norm = os.path.normpath(str(root_path))
            sql += " WHERE m.file_path LIKE ?"
            params.append(f"{norm}%")

        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            if row:
                total = int(row["total_cnt"] or 0)
                geo = int(row["geo_cnt"] or 0)
                return total, geo
            return 0, 0

    def get_geo_media_items(
        self, root_path: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        GPS 좌표가 존재하는 미디어 파일 및 메타데이터 목록을 조회합니다.
        """
        sql = """
        SELECT 
            m.id, m.file_path, m.file_name, m.file_ext, m.media_type,
            meta.latitude, meta.longitude, meta.country_code,
            meta.country_name, meta.state_name, meta.city_name
        FROM media_files m
        INNER JOIN metadata meta ON m.id = meta.media_id
        WHERE meta.latitude IS NOT NULL AND meta.longitude IS NOT NULL
          AND (ABS(meta.latitude) > 0.0001 OR ABS(meta.longitude) > 0.0001)
        """
        params: List[Any] = []
        if root_path:
            norm = os.path.normpath(str(root_path))
            sql += " AND m.file_path LIKE ?"
            params.append(f"{norm}%")

        sql += " ORDER BY m.id ASC"
        if limit and limit > 0:
            sql += f" LIMIT {int(limit)}"
        sql += ";"

        results: List[Dict[str, Any]] = []
        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, params)
            for row in cursor.fetchall():
                results.append(dict(row))
        return results

    def update_media_geo_names(
        self, items: List[Tuple[str, str, str, str, int]]
    ) -> int:
        """
        재지오코딩된 지명 정보를 단일 트랜잭션으로 일괄 갱신합니다.
        items: List of (country_code, country_name, state_name, city_name, media_id)
        """
        if not items:
            return 0
        sql = """
        UPDATE metadata
        SET country_code = ?, country_name = ?, state_name = ?, city_name = ?
        WHERE media_id = ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, items)
            return cursor.rowcount


