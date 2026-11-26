"""
GooglePhotoTakeoutTools - Process Service
Takeout 미디어 파일을 분석/메타데이터 주입/폴더 정리 및 SQLite 인덱싱하는 핵심 파이프라인
"""

import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.core.exif_writer import ExifWriter
from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.i18n import t
from src.core.matcher import DirectoryMetadataIndex, MetadataMatcher
from src.core.models import MatchResult, MatchType, MediaFile, MediaMetadata, MediaType, GeoLocation
from src.core.os_sync import OsDateSync
from src.core.utils import normalize_unicode
from src.data.repositories.media_repo import MediaRepository

logger = logging.getLogger(__name__)


def _sanitize_folder_name(name: str) -> str:
    """OS 파일시스템에서 금지된 특수문자를 안전한 문자로 정제"""
    if not name:
        return ""
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name.strip())
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()


class FolderStrategy(str, Enum):
    """정리 폴더 계층 구조 규칙"""
    YEAR_MONTH = "year_month"                              # YYYY/MM/ (기본값)
    YEAR_YEAR_MONTH = "year_year_month"                    # YYYY/YYYY-MM/
    YEAR_ONLY = "year_only"                                # YYYY/
    YEAR_MONTH_DAY = "year_month_day"                      # YYYY/MM/DD/ (일자별 정밀)
    CAMERA_YEAR_MONTH = "camera_year_month"                # 촬영기기/YYYY/MM/
    YEAR_MONTH_CAMERA = "year_month_camera"                # YYYY/MM/촬영기기/
    TYPE_YEAR_MONTH = "type_year_month"                    # 미디어유형/YYYY/MM/ (사진 vs 동영상)
    GEO_COUNTRY_STATE_CITY = "geo_country_state_city"      # 국가/시도/시군구/YYYY/MM/
    GEO_COUNTRY_STATE = "geo_country_state"                # 국가/시도/YYYY/MM/
    GEO_COUNTRY_CITY = "geo_country_city"                  # 국가/도시/YYYY/MM/
    GEO_COUNTRY = "geo_country"                            # 국가/YYYY/MM/
    GEO_COUNTRY_STATE_CITY_ONLY = "geo_country_state_city_only"  # 국가/시도/시군구/
    GEO_COUNTRY_STATE_ONLY = "geo_country_state_only"      # 국가/시도/
    GEO_COUNTRY_CITY_ONLY = "geo_country_city_only"        # 국가/도시/
    GEO_COUNTRY_ONLY = "geo_country_only"                  # 국가/
    ALBUM_NAME = "album_name"                              # 원본 앨범명/


STRATEGY_I18N_KEYS: Dict[FolderStrategy, str] = {
    FolderStrategy.YEAR_MONTH: "strategies.YEAR_MONTH",
    FolderStrategy.YEAR_YEAR_MONTH: "strategies.YEAR_YEAR_MONTH",
    FolderStrategy.YEAR_ONLY: "strategies.YEAR_ONLY",
    FolderStrategy.YEAR_MONTH_DAY: "strategies.YEAR_MONTH_DAY",
    FolderStrategy.CAMERA_YEAR_MONTH: "strategies.CAMERA_YEAR_MONTH",
    FolderStrategy.YEAR_MONTH_CAMERA: "strategies.YEAR_MONTH_CAMERA",
    FolderStrategy.TYPE_YEAR_MONTH: "strategies.TYPE_YEAR_MONTH",
    FolderStrategy.GEO_COUNTRY_CITY: "strategies.GEO_COUNTRY_CITY",
    FolderStrategy.GEO_COUNTRY: "strategies.GEO_COUNTRY",
    FolderStrategy.ALBUM_NAME: "strategies.ALBUM_NAME",
}


def get_strategy_display_name(strategy: FolderStrategy) -> str:
    """폴더 전략의 다국어 표시 라벨 반환"""
    key = STRATEGY_I18N_KEYS.get(strategy)
    if key:
        return t(key)
    return strategy.value


class ProcessMode(str, Enum):
    """파일 처리 모드"""
    COPY = "copy"    # 원본 유지, 대상 폴더에 복사
    MOVE = "move"    # 디스크 공간 절약, 대상 폴더로 이동


class MetadataPriority(str, Enum):
    """원본 EXIF와 Takeout JSON 충돌 시 병합 우선순위"""
    EXIF_FIRST = "exif_first"    # 원본 EXIF 우선 (누락 시 JSON 보완, 기본값)
    JSON_FIRST = "json_first"    # Takeout JSON 우선 (누락 시 원본 EXIF 보완)


def merge_metadata(
    orig_exif: Optional[MediaMetadata],
    json_meta: Optional[MediaMetadata],
    priority: MetadataPriority = MetadataPriority.EXIF_FIRST,
) -> MediaMetadata:
    """
    원본 파일 EXIF 메타데이터와 Takeout JSON 메타데이터를 정책에 따라 병합합니다.
    """
    oe = orig_exif or MediaMetadata()
    jm = json_meta or MediaMetadata()

    # 1. 촬영 일시 (파일명 폴백 없이 EXIF vs JSON만 비교/보완)
    if priority == MetadataPriority.JSON_FIRST:
        if jm.best_datetime is not None:
            taken_dt = jm.photo_taken_time
            taken_ts = jm.photo_taken_timestamp
            created_dt = jm.creation_time
            created_ts = jm.creation_timestamp
        else:
            taken_dt = oe.photo_taken_time
            taken_ts = oe.photo_taken_timestamp
            created_dt = oe.creation_time
            created_ts = oe.creation_timestamp
    else:
        if oe.best_datetime is not None:
            taken_dt = oe.photo_taken_time
            taken_ts = oe.photo_taken_timestamp
            created_dt = oe.creation_time
            created_ts = oe.creation_timestamp
        else:
            taken_dt = jm.photo_taken_time
            taken_ts = jm.photo_taken_timestamp
            created_dt = jm.creation_time
            created_ts = jm.creation_timestamp

    # 2. GPS 위치 (0.0, 0.0 무효 좌표 제외 후 우선순위 적용)
    oe_has_gps = oe.geo_data.has_valid_coordinates
    jm_has_gps = jm.geo_data.has_valid_coordinates
    if priority == MetadataPriority.JSON_FIRST:
        geo = jm.geo_data if jm_has_gps else (oe.geo_data if oe_has_gps else GeoLocation())
    else:
        geo = oe.geo_data if oe_has_gps else (jm.geo_data if jm_has_gps else GeoLocation())

    # 3. 촬영 기기 (원본 EXIF 우선 -> JSON 보완)
    camera_make = oe.camera_make or jm.camera_make
    camera_model = oe.camera_model or jm.camera_model

    # 4. 설명/캡션 (JSON 우선 -> 원본 EXIF 보완)
    description = jm.description or oe.description

    return MediaMetadata(
        title=jm.title or oe.title,
        description=description,
        photo_taken_time=taken_dt,
        photo_taken_timestamp=taken_ts,
        creation_time=created_dt,
        creation_timestamp=created_ts,
        geo_data=geo,
        people=list(jm.people),
        is_favorited=jm.is_favorited,
        camera_make=camera_make,
        camera_model=camera_model,
        raw_json=jm.raw_json,
    )


@dataclass
class ProcessSummary:
    """파이프라인 실행 결과 요약 통계"""
    total_scanned: int = 0
    processed_count: int = 0
    skipped_duplicate: int = 0
    failed_count: int = 0
    photo_count: int = 0
    video_count: int = 0
    total_bytes: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0


def calculate_file_hash(file_path: Path, chunk_size: int = 65536) -> str:
    """대용량 미디어 파일도 메모리 점유 없이 안전하게 SHA-256 해시를 계산"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


class ProcessService:
    """
    Google Takeout 데이터를 정리하고 메타데이터를 통합 복원하는 메인 서비스
    """

    def __init__(
        self,
        media_repo: MediaRepository,
        folder_strategy: FolderStrategy = FolderStrategy.YEAR_MONTH,
        process_mode: ProcessMode = ProcessMode.COPY,
        geo_language: GeoLanguage = GeoLanguage.KOREAN,
        metadata_priority: MetadataPriority = MetadataPriority.EXIF_FIRST,
    ):
        self.media_repo = media_repo
        self.folder_strategy = folder_strategy
        self.process_mode = process_mode
        self.geo_language = geo_language
        self.metadata_priority = metadata_priority
        self.matcher = MetadataMatcher()

    def get_destination_folder(
        self,
        base_output: Path,
        dt: Optional[datetime],
        meta: Optional[MediaMetadata] = None,
        media_type: MediaType = MediaType.PHOTO,
        album_name: str = "",
    ) -> Path:
        """선택된 10종 폴더 규칙에 따라 타겟 디렉토리 경로 계산"""
        year_str = f"{dt.year:04d}" if dt else "Unknown_Year"
        month_str = f"{dt.month:02d}" if dt else "Unknown_Month"
        day_str = f"{dt.day:02d}" if dt else "Unknown_Day"

        strat = self.folder_strategy

        if strat == FolderStrategy.YEAR_MONTH:
            return base_output / year_str / month_str
        elif strat == FolderStrategy.YEAR_YEAR_MONTH:
            return base_output / year_str / f"{year_str}-{month_str}"
        elif strat == FolderStrategy.YEAR_ONLY:
            return base_output / year_str
        elif strat == FolderStrategy.YEAR_MONTH_DAY:
            return base_output / year_str / month_str / day_str
        elif strat == FolderStrategy.CAMERA_YEAR_MONTH:
            cam_str = ""
            if meta:
                c_make = (meta.camera_make or "").strip()
                c_model = (meta.camera_model or "").strip()
                cam_str = f"{c_make} {c_model}".strip() if (c_make or c_model) else ""
            cam_folder = _sanitize_folder_name(cam_str) or "기타 기기 (Unknown)"
            return base_output / cam_folder / year_str / month_str
        elif strat == FolderStrategy.YEAR_MONTH_CAMERA:
            cam_str = ""
            if meta:
                c_make = (meta.camera_make or "").strip()
                c_model = (meta.camera_model or "").strip()
                cam_str = f"{c_make} {c_model}".strip() if (c_make or c_model) else ""
            cam_folder = _sanitize_folder_name(cam_str) or "기타 기기 (Unknown)"
            return base_output / year_str / month_str / cam_folder
        elif strat == FolderStrategy.TYPE_YEAR_MONTH:
            type_folder = "사진" if media_type == MediaType.PHOTO else "동영상"
            return base_output / type_folder / year_str / month_str
        elif strat in (
            FolderStrategy.GEO_COUNTRY_STATE_CITY,
            FolderStrategy.GEO_COUNTRY_STATE,
            FolderStrategy.GEO_COUNTRY_CITY,
            FolderStrategy.GEO_COUNTRY,
            FolderStrategy.GEO_COUNTRY_STATE_CITY_ONLY,
            FolderStrategy.GEO_COUNTRY_STATE_ONLY,
            FolderStrategy.GEO_COUNTRY_CITY_ONLY,
            FolderStrategy.GEO_COUNTRY_ONLY,
        ):
            country = _sanitize_folder_name(meta.country_name if meta else "") or "위치정보없음"
            state = _sanitize_folder_name(meta.state_name if meta else "")
            city = _sanitize_folder_name(meta.city_name if meta else "")

            # 특·광역시 등 동어반복 방지
            if state and city:
                s_c = state.replace("광역시", "").replace("특별시", "").replace("도", "").replace("주", "")
                c_c = city.replace("시", "").replace("도심", "")
                if s_c == c_c:
                    city = ""

            path = base_output / country
            if strat in (FolderStrategy.GEO_COUNTRY_STATE_CITY, FolderStrategy.GEO_COUNTRY_STATE_CITY_ONLY):
                if state:
                    path = path / state
                if city:
                    path = path / city
            elif strat in (FolderStrategy.GEO_COUNTRY_STATE, FolderStrategy.GEO_COUNTRY_STATE_ONLY):
                if state:
                    path = path / state
                elif city:
                    path = path / city
            elif strat in (FolderStrategy.GEO_COUNTRY_CITY, FolderStrategy.GEO_COUNTRY_CITY_ONLY):
                if city:
                    path = path / city
                elif state:
                    path = path / state

            if strat in (
                FolderStrategy.GEO_COUNTRY_STATE_CITY,
                FolderStrategy.GEO_COUNTRY_STATE,
                FolderStrategy.GEO_COUNTRY_CITY,
                FolderStrategy.GEO_COUNTRY,
            ):
                path = path / year_str / month_str

            return path
        elif strat == FolderStrategy.ALBUM_NAME:
            alb = _sanitize_folder_name(album_name) or "미분류 앨범"
            return base_output / alb

        return base_output / year_str / month_str

    def run_pipeline(
        self,
        source_dir: Path,
        output_dir: Path,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> ProcessSummary:
        """
        source_dir 전체를 탐색하여 output_dir로 사진/동영상을 정리하고 DB에 적재합니다.
        """
        summary = ProcessSummary(start_time=datetime.now())
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 파일 목록 사전 스캔 및 메타데이터 사전 매칭
        # 메타데이터가 있는 원본 파일을 중복 파일보다 먼저 처리하기 위해 우선순위 부여
        candidates: List[Tuple[int, MediaFile, MatchResult, str]] = []
        for root, dirs, files in os.walk(source_dir):
            root_path = Path(root)
            album_name = normalize_unicode(root_path.name)
            index = DirectoryMetadataIndex(root_path)

            for file_name in sorted(files):
                if file_name.lower().endswith(".json") or file_name.startswith("."):
                    continue

                full_path = root_path / file_name
                media = MediaFile.from_path(full_path)
                if media.media_type.value != "unknown":
                    match_res = self.matcher.match(media, index=index, allow_filename_fallback=False)
                    # 메타데이터가 존재하는 파일 우선(0), 없음(2)
                    if match_res.is_matched and match_res.match_type not in (MatchType.FALLBACK_FILENAME, MatchType.NONE):
                        priority = 0
                    elif match_res.is_matched and match_res.match_type == MatchType.FALLBACK_FILENAME:
                        priority = 1
                    else:
                        priority = 2

                    candidates.append((priority, media, match_res, album_name))

        # 우선순위 기준 정렬 (우선순위 높은 파일 먼저 처리)
        candidates.sort(key=lambda x: x[0])
        summary.total_scanned = len(candidates)

        # 2. 순차 파이프라인 처리
        def notify_progress(cur_idx: int, cur_fname: str, cur_status: str):
            if not progress_callback:
                return
            stats = {
                "processed": summary.processed_count,
                "skipped": summary.skipped_duplicate,
                "errors": summary.failed_count,
            }
            try:
                progress_callback(cur_idx, summary.total_scanned, cur_fname, cur_status, stats)
            except TypeError:
                progress_callback(cur_idx, summary.total_scanned, cur_fname, cur_status)

        for idx, (_, media, match_res, album_name) in enumerate(candidates, 1):
            if should_stop and should_stop():
                logger.info("작업 중단 요청이 감지되어 파이프라인을 종료합니다.")
                break

            fname = media.normalized_name
            notify_progress(idx, fname, "처리 중...")

            try:
                # 2.1 SHA-256 해시 계산
                file_hash = calculate_file_hash(media.path)

                # 2.2 중복 검사 (이미 동일 내용의 파일이 DB에 있는 경우)
                existing = self.media_repo.find_by_hash(file_hash)
                if existing:
                    summary.skipped_duplicate += 1
                    notify_progress(idx, fname, "중복 파일 스킵")
                    continue

                # 2.3 원본 파일 EXIF 선행 분석 및 Takeout JSON 스마트 병합
                orig_exif = ExifWriter.extract_metadata(media.path)
                meta = merge_metadata(orig_exif, match_res.metadata, self.metadata_priority)
                best_dt = meta.best_datetime

                # 2.3.1 GPS 역지오코딩 선행 추출 (위치별 폴더 전략용)
                if not meta.country_name:
                    geo = meta.geo_data
                    lat = geo.latitude if geo else None
                    lon = geo.longitude if geo else None
                    loc = GeoResolver().resolve(lat, lon, self.geo_language)
                    meta.country_code = loc.country_code
                    meta.country_name = loc.country_name
                    meta.state_name = loc.state_name
                    meta.city_name = loc.city_name

                target_folder = self.get_destination_folder(
                    output_dir,
                    best_dt,
                    meta=meta,
                    media_type=media.media_type,
                    album_name=album_name,
                )
                target_folder.mkdir(parents=True, exist_ok=True)
                dest_file = target_folder / fname

                # 대상 경로에 동명 파일이 이미 있는 경우 안전하게 카운터 붙임
                counter = 1
                base_stem = dest_file.stem
                while dest_file.exists():
                    dest_file = target_folder / f"{base_stem}_{counter}{media.extension}"
                    counter += 1

                # 2.5 복사 또는 이동
                if self.process_mode == ProcessMode.MOVE:
                    shutil.move(str(media.path), str(dest_file))
                else:
                    shutil.copy2(str(media.path), str(dest_file))

                # 2.6 메타데이터 주입 (원본 EXIF에서 누락되었거나 우선순위로 덮어쓸 항목만 주입)
                need_dt = meta.best_datetime if meta.best_datetime and meta.best_datetime != orig_exif.best_datetime else None
                need_desc = meta.description if meta.description and meta.description != orig_exif.description else ""
                need_geo = (
                    meta.geo_data
                    if meta.geo_data.has_valid_coordinates
                    and (
                        not orig_exif.geo_data.has_valid_coordinates
                        or (
                            self.metadata_priority == MetadataPriority.JSON_FIRST
                            and (
                                meta.geo_data.latitude != orig_exif.geo_data.latitude
                                or meta.geo_data.longitude != orig_exif.geo_data.longitude
                            )
                        )
                    )
                    else GeoLocation()
                )
                if need_dt or need_desc or need_geo.has_valid_coordinates:
                    ExifWriter.inject_metadata(
                        dest_file,
                        MediaMetadata(
                            photo_taken_time=need_dt,
                            description=need_desc,
                            geo_data=need_geo,
                        ),
                    )

                # 2.7 파일 시스템 날짜(mtime / birthtime) 동기화
                if best_dt:
                    OsDateSync.sync_file_time(dest_file, best_dt)

                # 2.8 SQLite DB 적재 (사전 추출된 meta 사용)
                self.media_repo.insert_media(
                    final_path=dest_file,
                    original_path=media.path,
                    file_hash=file_hash,
                    media_file=media,
                    metadata=meta,
                    album_name=album_name,
                    status="COMPLETED",
                )

                summary.processed_count += 1
                if media.media_type.value == "photo":
                    summary.photo_count += 1
                elif media.media_type.value == "video":
                    summary.video_count += 1
                summary.total_bytes += media.file_size
                notify_progress(idx, fname, "완료")

            except Exception as e:
                logger.error("파일 처리 실패 [%s]: %s", media.path, e)
                summary.failed_count += 1
                notify_progress(idx, fname, f"오류 발생: {e}")

        summary.end_time = datetime.now()
        return summary
