"""
services/metadata_edit_service.py
────────────────────────────────────────────────────────────────
개별 미디어 파일의 메타데이터 수정 및 원본 스냅샷 복원 서비스.
DB(metadata) 업데이트, JPEG EXIF 태그 동기화, OS 파일 타임스탬프 동기화를
단일 트랜잭션 흐름으로 처리합니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.exif_writer import ExifWriter
from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.os_sync import OsDateSync
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository

logger = logging.getLogger(__name__)


@dataclass
class EditMetadataRequest:
    """사용자가 다이얼로그에서 입력한 메타데이터 수정 요청"""
    taken_at: Optional[datetime] = None
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    description: str = ""
    camera_make: str = ""
    camera_model: str = ""


@dataclass
class MetadataEditResult:
    """메타데이터 수정/복원 처리 결과"""
    success: bool
    updated_item: Optional[Dict[str, Any]] = None
    exif_updated: bool = False
    os_time_synced: bool = False
    message: str = ""


def parse_taken_at(value: Optional[str]) -> Optional[datetime]:
    """DB의 taken_at 문자열(YYYY-MM-DD HH:MM:SS 등)을 datetime으로 안전하게 파싱"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class MetadataEditService:
    """개별 미디어 메타데이터 편집 및 원본 복원 서비스"""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        self.repo = MediaRepository(self.db)

    def apply_edit(
        self,
        media_item: Dict[str, Any],
        request: EditMetadataRequest,
        geo_lang: GeoLanguage = GeoLanguage.KOREAN,
    ) -> MetadataEditResult:
        """
        수정된 메타데이터를 DB에 저장(최초 수정 시 원본 스냅샷 자동 백업)하고,
        실제 디스크 파일의 EXIF 및 OS 타임스탬프를 동기화합니다.
        """
        media_id = media_item.get("id")
        if not media_id:
            return MetadataEditResult(success=False, message="유효하지 않은 미디어 ID입니다.")

        # 1. 촬영 일시 변환
        if request.taken_at is not None:
            taken_at_str = request.taken_at.strftime("%Y-%m-%d %H:%M:%S")
            taken_ts = int(request.taken_at.timestamp())
        else:
            taken_at_str = None
            taken_ts = 0

        # 2. GPS 좌표 기반 역지오코딩 재계산
        lat = float(request.latitude or 0.0)
        lon = float(request.longitude or 0.0)
        alt = float(request.altitude or 0.0)
        if lat != 0.0 or lon != 0.0:
            geo_info = GeoResolver().resolve(lat, lon, geo_lang)
            country_code = geo_info.country_code
            country_name = geo_info.country_name
            state_name = geo_info.state_name
            city_name = geo_info.city_name
        else:
            country_code = ""
            country_name = ""
            state_name = ""
            city_name = ""

        updates = {
            "taken_at": taken_at_str,
            "taken_timestamp": taken_ts,
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "country_code": country_code,
            "country_name": country_name,
            "state_name": state_name,
            "city_name": city_name,
            "description": (request.description or "").strip(),
            "camera_make": (request.camera_make or "").strip(),
            "camera_model": (request.camera_model or "").strip(),
        }

        updated_item = self.repo.update_media_metadata(int(media_id), updates)
        if not updated_item:
            return MetadataEditResult(success=False, message="DB 업데이트에 실패했습니다.")

        exif_ok, os_ok = self._sync_file_on_disk(updated_item)
        return MetadataEditResult(
            success=True,
            updated_item=updated_item,
            exif_updated=exif_ok,
            os_time_synced=os_ok,
            message="ok",
        )

    def restore_original(self, media_item: Dict[str, Any]) -> MetadataEditResult:
        """
        original_snapshot에 백업된 최초 원본 메타데이터로 DB를 복원하고,
        디스크 파일의 EXIF 및 OS 타임스탬프를 함께 복원합니다.
        """
        media_id = media_item.get("id")
        if not media_id:
            return MetadataEditResult(success=False, message="유효하지 않은 미디어 ID입니다.")

        restored_item = self.repo.reset_media_metadata(int(media_id))
        if not restored_item:
            return MetadataEditResult(success=False, message="복원할 원본 스냅샷이 없습니다.")

        exif_ok, os_ok = self._sync_file_on_disk(restored_item)
        return MetadataEditResult(
            success=True,
            updated_item=restored_item,
            exif_updated=exif_ok,
            os_time_synced=os_ok,
            message="restored",
        )

    @staticmethod
    def _sync_file_on_disk(item: Dict[str, Any]) -> tuple[bool, bool]:
        """DB 레코드 상태를 기준으로 실제 파일의 EXIF 및 OS 시간을 동기화"""
        file_path_str = item.get("file_path") or ""
        if not file_path_str:
            return False, False

        target_path = Path(file_path_str)
        if not target_path.exists():
            return False, False

        taken_dt = parse_taken_at(item.get("taken_at"))
        exif_ok, _ = ExifWriter.update_metadata_fields(
            image_path=target_path,
            taken_at=taken_dt,
            latitude=float(item.get("latitude") or 0.0),
            longitude=float(item.get("longitude") or 0.0),
            altitude=float(item.get("altitude") or 0.0),
            description=item.get("description") or "",
            camera_make=item.get("camera_make") or "",
            camera_model=item.get("camera_model") or "",
        )

        os_ok = False
        if taken_dt is not None:
            os_ok = OsDateSync.sync_file_time(target_path, taken_dt)

        return exif_ok, os_ok
