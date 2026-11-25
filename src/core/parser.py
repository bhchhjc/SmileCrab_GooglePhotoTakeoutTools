"""
GooglePhotoTakeoutTools - Takeout JSON Parser
Google Takeout 형식의 JSON 메타데이터를 안전하게 파싱하는 모듈
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import GeoLocation, MediaMetadata
from .utils import normalize_unicode

logger = logging.getLogger(__name__)


class JsonParser:
    """
    Google Takeout 메타데이터 JSON 파일 파서.
    스키마 변경, 누락된 키, 유니코드 정규화 이슈에 견고하게 동작하도록 설계되었습니다.
    """

    @classmethod
    def parse_file(cls, json_path: Path) -> Optional[MediaMetadata]:
        """
        주어진 경로의 JSON 파일을 읽어 MediaMetadata 객체로 반환합니다.
        파일이 없거나 JSON 포맷이 깨진 경우 None을 안전하게 반환합니다.
        """
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.parse_dict(data)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            logger.warning("JSON 파싱 실패 [%s]: %s", json_path, e)
            return None

    @classmethod
    def parse_dict(cls, data: Dict[str, Any]) -> MediaMetadata:
        """
        파이썬 딕셔너리 형태의 Takeout JSON 데이터를 MediaMetadata 인스턴스로 변환합니다.
        """
        title = normalize_unicode(data.get("title", ""))
        description = normalize_unicode(data.get("description", ""))

        # 1. photoTakenTime 파싱
        taken_time, taken_ts = cls._extract_time_info(data.get("photoTakenTime"))

        # 2. creationTime 파싱
        created_time, created_ts = cls._extract_time_info(data.get("creationTime"))

        # 3. GPS 위치 정보 파싱 (geoData 우선, 없으면 geoDataExif 참조)
        geo_dict = data.get("geoData") or data.get("geoDataExif") or {}
        geo_location = GeoLocation(
            latitude=float(geo_dict.get("latitude", 0.0)),
            longitude=float(geo_dict.get("longitude", 0.0)),
            altitude=float(geo_dict.get("altitude", 0.0)),
        )

        # 4. 태그된 인물 (people) 목록 추출
        people_list: List[str] = []
        raw_people = data.get("people", [])
        if isinstance(raw_people, list):
            for p in raw_people:
                if isinstance(p, dict) and "name" in p:
                    name = normalize_unicode(p["name"]).strip()
                    if name:
                        people_list.append(name)

        # 5. 즐겨찾기(favorited) 여부
        is_favorited = bool(data.get("favorited", False))

        # 6. 카메라 기기 정보 추출 (JSON에 명시된 경우)
        camera_make = normalize_unicode(str(data.get("cameraMake") or data.get("deviceMake") or "")).strip()
        camera_model = normalize_unicode(str(data.get("cameraModel") or data.get("deviceModel") or "")).strip()

        return MediaMetadata(
            title=title,
            description=description,
            photo_taken_time=taken_time,
            photo_taken_timestamp=taken_ts,
            creation_time=created_time,
            creation_timestamp=created_ts,
            geo_data=geo_location,
            people=people_list,
            is_favorited=is_favorited,
            camera_make=camera_make,
            camera_model=camera_model,
            raw_json=data,
        )

    @staticmethod
    def _extract_time_info(time_dict: Optional[Dict[str, Any]]) -> tuple[Optional[datetime], int]:
        """
        Takeout JSON의 시간 블록({"timestamp": "1675470711", "formatted": "..."})에서
        (datetime, timestamp_int) 튜플을 안전하게 추출합니다.
        """
        if not time_dict or not isinstance(time_dict, dict):
            return None, 0

        ts_raw = time_dict.get("timestamp")
        if not ts_raw:
            return None, 0

        try:
            timestamp = int(ts_raw)
            # 타임스탬프가 음수이거나 비정상적인 값인 경우 방어
            if timestamp <= 0:
                return None, 0

            # UTC datetime 객체 생성 (tz-aware)
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return dt, timestamp
        except (ValueError, OSError, OverflowError):
            return None, 0
