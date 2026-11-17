"""
GooglePhotoTakeoutTools - Process Service
Takeout 미디어 파일을 분석/메타데이터 주입/폴더 정리 및 SQLite 인덱싱하는 핵심 파이프라인
"""

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.core.exif_writer import ExifWriter
from src.core.matcher import DirectoryMetadataIndex, MetadataMatcher
from src.core.models import MatchResult, MatchType, MediaFile, MediaMetadata
from src.core.os_sync import OsDateSync
from src.core.utils import normalize_unicode
from src.data.repositories.media_repo import MediaRepository

logger = logging.getLogger(__name__)


class FolderStrategy(str, Enum):
    """정리 폴더 계층 구조 규칙"""
    YEAR_MONTH = "year_month"              # YYYY/MM/ (예: 2023/05/)
    YEAR_YEAR_MONTH = "year_year_month"    # YYYY/YYYY-MM/ (예: 2023/2023-05/)
    YEAR_ONLY = "year_only"                # YYYY/ (예: 2023/)


class ProcessMode(str, Enum):
    """파일 처리 모드"""
    COPY = "copy"    # 원본 유지, 대상 폴더에 복사
    MOVE = "move"    # 디스크 공간 절약, 대상 폴더로 이동


@dataclass
class ProcessSummary:
    """파이프라인 실행 결과 요약 통계"""
    total_scanned: int = 0
    processed_count: int = 0
    skipped_duplicate: int = 0
    failed_count: int = 0
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
    ):
        self.media_repo = media_repo
        self.folder_strategy = folder_strategy
        self.process_mode = process_mode
        self.matcher = MetadataMatcher()

    def get_destination_folder(self, base_output: Path, dt: Optional[datetime]) -> Path:
        """선택된 폴더 규칙에 따라 타겟 디렉토리 경로 계산"""
        if not dt:
            return base_output / "Unknown_Date"

        year_str = f"{dt.year:04d}"
        month_str = f"{dt.month:02d}"

        if self.folder_strategy == FolderStrategy.YEAR_MONTH:
            return base_output / year_str / month_str
        elif self.folder_strategy == FolderStrategy.YEAR_YEAR_MONTH:
            return base_output / year_str / f"{year_str}-{month_str}"
        elif self.folder_strategy == FolderStrategy.YEAR_ONLY:
            return base_output / year_str

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
                    match_res = self.matcher.match(media, index=index)
                    # 메타데이터가 존재하는 파일 우선(0), fallback/None은 후순위(1~2)
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
        for idx, (_, media, match_res, album_name) in enumerate(candidates, 1):
            if should_stop and should_stop():
                logger.info("작업 중단 요청이 감지되어 파이프라인을 종료합니다.")
                break

            fname = media.normalized_name
            if progress_callback:
                progress_callback(idx, summary.total_scanned, fname, "처리 중...")

            try:
                # 2.1 SHA-256 해시 계산
                file_hash = calculate_file_hash(media.path)

                # 2.2 중복 검사 (이미 동일 내용의 파일이 DB에 있는 경우)
                existing = self.media_repo.find_by_hash(file_hash)
                if existing:
                    summary.skipped_duplicate += 1
                    if progress_callback:
                        progress_callback(idx, summary.total_scanned, fname, "중복 파일 스킵")
                    continue

                # 2.3 대상 디렉토리 및 파일명 결정
                best_dt = match_res.metadata.best_datetime if match_res.metadata else None
                target_folder = self.get_destination_folder(output_dir, best_dt)
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

                # 2.6 메타데이터 주입 (사진인 경우 EXIF 주입)
                if match_res.metadata:
                    ExifWriter.inject_metadata(dest_file, match_res.metadata)

                # 2.7 파일 시스템 날짜(mtime / birthtime) 동기화
                if best_dt:
                    OsDateSync.sync_file_time(dest_file, best_dt)

                # 2.8 SQLite DB 적재
                self.media_repo.insert_media(
                    final_path=dest_file,
                    original_path=media.path,
                    file_hash=file_hash,
                    media_file=media,
                    metadata=match_res.metadata,
                    album_name=album_name,
                    status="COMPLETED",
                )

                summary.processed_count += 1
                summary.total_bytes += media.file_size

            except Exception as e:
                logger.error("파일 처리 실패 [%s]: %s", media.path, e)
                summary.failed_count += 1

        summary.end_time = datetime.now()
        return summary
