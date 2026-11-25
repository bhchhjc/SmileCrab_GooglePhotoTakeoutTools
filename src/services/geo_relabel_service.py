"""
GooglePhotoTakeoutTools - Geo Relabel Service
저장된 미디어의 역지오코딩 지명을 원하는 언어로 일괄 무손실 재변환하는 서비스
"""

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.power_management import SleepInhibitor
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository

logger = logging.getLogger(__name__)


@dataclass
class GeoRelabelPreviewItem:
    """지역명 언어 변경 미리보기 아이템"""
    media_id: int
    file_name: str
    file_path: str
    latitude: float
    longitude: float
    cur_country: str
    cur_state: str
    cur_city: str
    new_country: str
    new_state: str
    new_city: str
    is_changed: bool

    @property
    def cur_display(self) -> str:
        parts = [p for p in [self.cur_country, self.cur_state, self.cur_city] if p]
        return " > ".join(parts) if parts else "-"

    @property
    def new_display(self) -> str:
        parts = [p for p in [self.new_country, self.new_state, self.new_city] if p]
        return " > ".join(parts) if parts else "-"


@dataclass
class GeoRelabelResult:
    """지역명 언어 변경 실행 결과 요약"""
    total_count: int = 0
    geo_count: int = 0
    updated_count: int = 0
    no_gps_count: int = 0
    duration_seconds: float = 0.0
    target_lang: GeoLanguage = GeoLanguage.KOREAN


class GeoRelabelService:
    """
    미디어 DB 내 저장된 위치 정보를 오프라인 17만 KD-Tree 엔진을 통해
    지정 언어로 초고속 재지오코딩하여 일괄 업데이트하는 서비스
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        self.repo = MediaRepository(self.db)
        self.resolver = GeoResolver()

    def get_preview(
        self,
        target_root: Optional[str] = None,
        target_lang: GeoLanguage = GeoLanguage.KOREAN,
        limit: int = 50,
    ) -> Tuple[int, int, List[GeoRelabelPreviewItem]]:
        """
        미리보기 데이터와 통계 반환.
        Returns:
            (total_count, geo_count, preview_items)
        """
        total_cnt, geo_cnt = self.repo.get_geo_media_stats(target_root)
        if geo_cnt == 0:
            return total_cnt, 0, []

        items = self.repo.get_geo_media_items(target_root, limit=limit)
        preview_list: List[GeoRelabelPreviewItem] = []

        for item in items:
            lat = item.get("latitude")
            lon = item.get("longitude")
            cur_country = item.get("country_name") or ""
            cur_state = item.get("state_name") or ""
            cur_city = item.get("city_name") or ""

            loc = self.resolver.resolve(lat, lon, language=target_lang)
            new_country = loc.country_name
            new_state = loc.state_name
            new_city = loc.city_name

            is_changed = (
                cur_country != new_country
                or cur_state != new_state
                or cur_city != new_city
            )

            preview_list.append(
                GeoRelabelPreviewItem(
                    media_id=item["id"],
                    file_name=item["file_name"],
                    file_path=item["file_path"],
                    latitude=lat or 0.0,
                    longitude=lon or 0.0,
                    cur_country=cur_country,
                    cur_state=cur_state,
                    cur_city=cur_city,
                    new_country=new_country,
                    new_state=new_state,
                    new_city=new_city,
                    is_changed=is_changed,
                )
            )

        return total_cnt, geo_cnt, preview_list

    def execute_relabel(
        self,
        target_root: Optional[str] = None,
        target_lang: GeoLanguage = GeoLanguage.KOREAN,
        progress_callback: Optional[Callable[[int, int, str, float, float], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> GeoRelabelResult:
        """
        전체 대상 파일의 위치명을 목표 언어로 일괄 재변환하고 DB에 일괄 반영합니다.
        """
        start_time = time.time()
        total_cnt, geo_cnt = self.repo.get_geo_media_stats(target_root)
        result = GeoRelabelResult(
            total_count=total_cnt,
            geo_count=geo_cnt,
            no_gps_count=max(0, total_cnt - geo_cnt),
            target_lang=target_lang,
        )

        if geo_cnt == 0:
            result.duration_seconds = time.time() - start_time
            return result

        items = self.repo.get_geo_media_items(target_root)
        update_batch: List[Tuple[str, str, str, str, int]] = []
        updated_count = 0

        with SleepInhibitor("GeoRelabelService"):
            for idx, item in enumerate(items, 1):
                if is_cancelled and is_cancelled():
                    logger.info("GeoRelabelService was cancelled by user.")
                    break

                lat = item.get("latitude")
                lon = item.get("longitude")
                loc = self.resolver.resolve(lat, lon, language=target_lang)

                cur_country = item.get("country_name") or ""
                cur_state = item.get("state_name") or ""
                cur_city = item.get("city_name") or ""

                # 변경이 발생했거나 코드가 누락된 경우
                if (
                    cur_country != loc.country_name
                    or cur_state != loc.state_name
                    or cur_city != loc.city_name
                    or not item.get("country_code")
                ):
                    updated_count += 1

                update_batch.append(
                    (
                        loc.country_code,
                        loc.country_name,
                        loc.state_name,
                        loc.city_name,
                        item["id"],
                    )
                )

                if progress_callback and (idx % 50 == 0 or idx == len(items)):
                    elapsed = max(0.001, time.time() - start_time)
                    speed = idx / elapsed
                    remaining = max(0, len(items) - idx)
                    eta = remaining / speed if speed > 0 else 0.0
                    progress_callback(idx, len(items), item.get("file_name", ""), speed, eta)

            # 트랜잭션 일괄 업데이트
            if update_batch and not (is_cancelled and is_cancelled()):
                self.repo.update_media_geo_names(update_batch)
                result.updated_count = updated_count
            else:
                result.updated_count = 0

        result.duration_seconds = time.time() - start_time
        return result
