"""
GooglePhotoTakeoutTools - Media Repository
미디어 파일 및 메타데이터 영속성 CRUD 및 검색 쿼리 모듈
"""

import json
import logging
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
            media_id, title, description, taken_at, taken_timestamp, latitude, longitude, altitude, people, is_favorited
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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

    def search_media(
        self,
        keyword: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        media_type: Optional[str] = None,
        has_gps: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        복합 조건(키워드, 연/월, 미디어 유형, GPS 유무)으로 미디어 목록을 초고속 조회
        """
        conditions = ["1=1"]
        params: List[Any] = []

        if keyword:
            conditions.append(
                "(m.file_name LIKE ? OR meta.description LIKE ? OR meta.people LIKE ? OR m.album_name LIKE ?)"
            )
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw])

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
            m.id, m.file_path, m.file_name, m.file_ext, m.file_size, m.media_type, m.album_name,
            meta.taken_at, meta.description, meta.latitude, meta.longitude, meta.people, meta.is_favorited
        FROM media_files m
        LEFT JOIN metadata meta ON m.id = meta.media_id
        WHERE {' AND '.join(conditions)}
        ORDER BY meta.taken_at DESC, m.file_name ASC
        LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        results = []
        with self.db.get_connection() as conn:
            cursor = conn.execute(sql, params)
            for row in cursor.fetchall():
                results.append(dict(row))
        return results
