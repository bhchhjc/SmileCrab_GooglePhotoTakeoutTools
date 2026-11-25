"""
GooglePhotoTakeoutTools - Reorganize Service
정리 완료된 미디어 파일들의 폴더 구조를 원하는 전략으로 초고속 무손실 재배치하는 서비스
"""

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.models import MediaType
from src.core.os_sync import OsDateSync
from src.core.power_management import SleepInhibitor
from src.data.database import DatabaseManager
from src.services.process_service import FolderStrategy, _sanitize_folder_name, get_strategy_display_name

logger = logging.getLogger(__name__)


@dataclass
class ReorganizeItem:
    """재구성 대상 파일 메타 정보"""
    media_id: int
    current_path: Path
    file_name: str
    file_ext: str
    media_type: str
    album_name: str
    taken_at: Optional[datetime]
    camera_make: str
    camera_model: str
    country_name: str
    state_name: str = ""
    city_name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0


@dataclass
class ReorganizeFailureDetail:
    """재구성 중 정리되거나 실패한 파일 상세 정보"""
    file_name: str
    relative_path: str
    status: str  # "CLEANED" (존재하지 않는 파일 자동 정리), "FAILED" (이동 실패)
    reason: str  # 상세 사유


@dataclass
class ReorganizeResult:
    """재구성 실행 결과 요약"""
    total_count: int = 0
    success_count: int = 0
    cleaned_missing_count: int = 0  # 존재하지 않는 파일 자동 정리 건수
    skipped_count: int = 0
    failed_count: int = 0
    new_folders_created: int = 0
    empty_folders_removed: int = 0
    elapsed_seconds: float = 0.0
    source_dir: str = ""
    target_dir: str = ""
    strategy_name: str = ""
    errors: List[str] = None
    failed_details: List[ReorganizeFailureDetail] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.failed_details is None:
            self.failed_details = []


class ReorganizeService:
    """
    미디어 폴더 구조 초고속 무손실 재구성 엔진.
    
    - .reorganize_tmp 임시 스테이징을 통한 대용량 꼬임 방지
    - mtime / birthtime 타임스탬프 및 EXIF 무손실 보존
    - SQLite 단일 트랜잭션 일괄 UPDATE
    - 빈 폴더 자동 정리
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()

    def load_target_items(self, base_folder: Optional[Path] = None) -> List[ReorganizeItem]:
        """
        DB에서 재구성 대상 미디어 목록을 로드합니다.
        base_folder가 주어지면 해당 폴더 하위 파일들만 필터링합니다.
        GPS 좌표가 있지만 country_name/city_name이 비어있는 경우 실시간 역지오코딩을 수행하고 DB를 동기화합니다.
        """
        conn = self.db.get_connection()
        query = """
            SELECT m.id, m.file_path, m.file_name, m.file_ext, m.media_type, m.album_name,
                   d.taken_at, d.camera_make, d.camera_model, d.country_name, d.state_name, d.city_name,
                   d.latitude, d.longitude
            FROM media_files m
            LEFT JOIN metadata d ON m.id = d.media_id
            ORDER BY m.id ASC
        """
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        items: List[ReorganizeItem] = []
        base_str = str(Path(base_folder).resolve()) if base_folder else None
        geo_resolver = GeoResolver()
        geo_updates_for_db = []

        for row in rows:
            m_id, f_path, f_name, f_ext, m_type, album = row[0], row[1], row[2], row[3], row[4], row[5]
            taken_at_str, c_make, c_model, country, state, city = row[6], row[7], row[8], row[9], row[10], row[11]
            lat = float(row[12]) if row[12] is not None else 0.0
            lon = float(row[13]) if row[13] is not None else 0.0

            p = Path(f_path)
            # base_folder 필터링
            if base_str:
                try:
                    resolved_p = p.resolve()
                    if not str(resolved_p).startswith(base_str):
                        continue
                except Exception:
                    continue

            # taken_at 파싱
            dt = None
            if taken_at_str:
                try:
                    clean_dt_str = taken_at_str.replace("T", " ")
                    dt = datetime.fromisoformat(clean_dt_str)
                except Exception:
                    dt = None

            # 실시간 역지오코딩 보완 (위치 좌표가 있으나 country_name이 비어있는 경우)
            if (not country or country.strip() == "") and (lat != 0.0 or lon != 0.0):
                loc = geo_resolver.resolve(lat, lon, language=GeoLanguage.KOREAN)
                if loc.country_name and loc.country_name not in ("위치 정보 없음", "위치정보없음"):
                    country = loc.country_name
                    state = loc.state_name
                    city = loc.city_name
                    geo_updates_for_db.append((loc.country_code, country, state, city, m_id))

            items.append(
                ReorganizeItem(
                    media_id=m_id,
                    current_path=p,
                    file_name=f_name or p.name,
                    file_ext=f_ext or p.suffix.lstrip(".").lower(),
                    media_type=m_type or "unknown",
                    album_name=album or "",
                    taken_at=dt,
                    camera_make=c_make or "",
                    camera_model=c_model or "",
                    country_name=country or "",
                    state_name=state or "",
                    city_name=city or "",
                    latitude=lat,
                    longitude=lon,
                )
            )

        # 역지오코딩된 결과가 있으면 DB metadata 테이블에도 영구 캐시 저장
        if geo_updates_for_db:
            try:
                cursor.executemany(
                    """
                    UPDATE metadata
                    SET country_code = ?, country_name = ?, state_name = ?, city_name = ?
                    WHERE media_id = ?
                    """,
                    geo_updates_for_db,
                )
                conn.commit()
                logger.info("누락되었던 GPS 좌표 %d건 실시간 역지오코딩 캐시 저장 완료", len(geo_updates_for_db))
            except Exception as e:
                logger.warning("역지오코딩 DB 캐시 저장 중 예외: %s", e)

        return items

    def calculate_target_dir(
        self,
        base_target_dir: Union[Path, str],
        item: ReorganizeItem,
        strategy: FolderStrategy,
    ) -> Path:
        """
        선택된 10종 폴더 전략에 맞춰 대상 디렉토리 경로를 계산합니다.
        """
        base_target_dir = Path(base_target_dir)
        dt = item.taken_at
        year_str = f"{dt.year:04d}" if dt else "Unknown_Year"
        month_str = f"{dt.month:02d}" if dt else "Unknown_Month"
        day_str = f"{dt.day:02d}" if dt else "Unknown_Day"

        strat = strategy

        if strat == FolderStrategy.YEAR_MONTH:
            return base_target_dir / year_str / month_str
        elif strat == FolderStrategy.YEAR_YEAR_MONTH:
            return base_target_dir / year_str / f"{year_str}-{month_str}"
        elif strat == FolderStrategy.YEAR_ONLY:
            return base_target_dir / year_str
        elif strat == FolderStrategy.YEAR_MONTH_DAY:
            return base_target_dir / year_str / month_str / day_str
        elif strat == FolderStrategy.CAMERA_YEAR_MONTH:
            cam_str = f"{item.camera_make} {item.camera_model}".strip() if (item.camera_make or item.camera_model) else ""
            cam_folder = _sanitize_folder_name(cam_str) or "기타 기기 (Unknown)"
            return base_target_dir / cam_folder / year_str / month_str
        elif strat == FolderStrategy.YEAR_MONTH_CAMERA:
            cam_str = f"{item.camera_make} {item.camera_model}".strip() if (item.camera_make or item.camera_model) else ""
            cam_folder = _sanitize_folder_name(cam_str) or "기타 기기 (Unknown)"
            return base_target_dir / year_str / month_str / cam_folder
        elif strat == FolderStrategy.TYPE_YEAR_MONTH:
            type_folder = "사진" if item.media_type == "photo" else "동영상"
            return base_target_dir / type_folder / year_str / month_str
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
            country = _sanitize_folder_name(item.country_name) or "위치정보없음"
            state = _sanitize_folder_name(item.state_name)
            city = _sanitize_folder_name(item.city_name)

            # 특·광역시 등 동어반복 방지
            if state and city:
                s_c = state.replace("광역시", "").replace("특별시", "").replace("도", "").replace("주", "")
                c_c = city.replace("시", "").replace("도심", "")
                if s_c == c_c:
                    city = ""

            path = base_target_dir / country
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
            alb = _sanitize_folder_name(item.album_name) or "미분류 앨범"
            return base_target_dir / alb

        return base_target_dir / year_str / month_str

    def execute_reorganize(
        self,
        source_base_dir: Union[Path, str],
        target_base_dir: Union[Path, str],
        strategy: FolderStrategy,
        items: Optional[List[ReorganizeItem]] = None,
        progress_callback: Optional[Callable[[int, int, str, float, float], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> ReorganizeResult:
        """
        폴더 구조 재구성을 실제로 실행합니다.
        
        매개변수:
            source_base_dir: 소스 디렉토리
            target_base_dir: 대상 디렉토리 (동일할 경우 제자리 재구성)
            strategy: 10종 폴더 전략
            items: 대상 아이템 목록 (None이면 source_base_dir 기준으로 자동 로드)
            progress_callback: (현재건수, 전체건수, 파일명, 속도fps, 남은시간초)
            is_cancelled: 취소 확인 함수
        """
        start_time = time.time()
        source_base_dir = Path(source_base_dir).resolve()
        target_base_dir = Path(target_base_dir).resolve()
        is_in_place = (source_base_dir == target_base_dir)

        if items is None:
            items = self.load_target_items(source_base_dir)

        total_count = len(items)
        result = ReorganizeResult(
            total_count=total_count,
            source_dir=str(source_base_dir),
            target_dir=str(target_base_dir),
            strategy_name=get_strategy_display_name(strategy),
        )

        if total_count == 0:
            result.elapsed_seconds = round(time.time() - start_time, 2)
            return result

        logger.info(
            "폴더 구조 재구성 시작: 총 %d개, 전략=%s, 제자리=%s",
            total_count, strategy, is_in_place
        )

        # 시스템 절전 방지 활성화
        with SleepInhibitor("미디어 폴더 구조 재구성 작업"):
            # 1. 대상 경로 계산 및 계획 수립
            # planned_moves: List of (item, current_path, final_target_path)
            planned_moves: List[Tuple[ReorganizeItem, Path, Path]] = []
            created_dirs = set()
            used_target_paths = set()

            for item in items:
                curr_path = item.current_path
                target_dir = self.calculate_target_dir(target_base_dir, item, strategy)
                final_path = target_dir / item.file_name

                # 이름 중복 충돌 방지:
                # 1) 이미 디스크에 존재하는 다른 파일
                # 2) 이번 배치에서 앞서 같은 목적지 경로를 예약한 다른 파일
                counter = 1
                stem = Path(item.file_name).stem
                suffix = Path(item.file_name).suffix
                while (final_path in used_target_paths) or (
                    final_path.exists() and final_path.resolve() != curr_path.resolve()
                ):
                    final_path = target_dir / f"{stem}({counter}){suffix}"
                    counter += 1

                used_target_paths.add(final_path)
                planned_moves.append((item, curr_path, final_path))

            # 2. 이동 실행
            # 제자리 이동일 경우: .reorganize_tmp 임시 스테이징으로 파일 꼬임 원천 차단
            tmp_staging_dir: Optional[Path] = None
            if is_in_place:
                tmp_staging_dir = source_base_dir / ".reorganize_tmp"
                tmp_staging_dir.mkdir(parents=True, exist_ok=True)

            db_updates: List[Tuple[str, str, str, int]] = []  # (new_file_path, new_file_name, new_folder_name, media_id)
            missing_media_ids: List[int] = []  # 디스크에 존재하지 않아 DB에서 정리할 id 목록
            processed = 0
            last_speed_time = time.time()
            last_speed_count = 0
            current_speed = 0.0

            try:
                # ── Step A: 디스크 실재 여부 검사 및 (제자리 이동 시) .reorganize_tmp 임시 격리 ──
                staged_moves: List[Tuple[ReorganizeItem, Path, Path]] = []
                for idx, (item, curr_path, final_path) in enumerate(planned_moves):
                    try:
                        rel_p = str(curr_path.relative_to(source_base_dir))
                    except Exception:
                        rel_p = str(curr_path.name)

                    # 디스크에 실제 파일이 존재하지 않는 경우 (파인더 등에서 외부 삭제됨)
                    if not curr_path.exists():
                        result.cleaned_missing_count += 1
                        missing_media_ids.append(item.media_id)
                        result.failed_details.append(
                            ReorganizeFailureDetail(
                                file_name=item.file_name,
                                relative_path=rel_p,
                                status="CLEANED",
                                reason="존재하지 않는 파일 (DB 자동 정리)",
                            )
                        )
                        processed += 1
                        continue

                    if is_in_place and tmp_staging_dir:
                        # 이미 최종 위치와 정확히 같은 경우 이동 불필요
                        if curr_path.resolve() == final_path.resolve():
                            staged_moves.append((item, curr_path, final_path))
                            continue

                        # 임시 격리 경로 (고유 id 기반)
                        tmp_file = tmp_staging_dir / f"stage_{item.media_id}_{item.file_name}"
                        try:
                            # 원본 타임스탬프 저장
                            stat_orig = curr_path.stat()
                            os.replace(curr_path, tmp_file)
                            # 타임스탬프 원자적 보존
                            os.utime(tmp_file, (stat_orig.st_atime, stat_orig.st_mtime))
                            staged_moves.append((item, tmp_file, final_path))
                        except Exception as e:
                            logger.error("임시 스테이징 실패 [%s]: %s", curr_path, e)
                            result.failed_count += 1
                            result.errors.append(f"임시 이동 실패: {curr_path} -> {e}")
                            result.failed_details.append(
                                ReorganizeFailureDetail(
                                    file_name=item.file_name,
                                    relative_path=rel_p,
                                    status="FAILED",
                                    reason=f"임시 격리 이동 실패 ({e})",
                                )
                            )
                            processed += 1
                    else:
                        staged_moves.append((item, curr_path, final_path))

                # ── Step B: 최종 목표 위치로 배치 ──
                for idx, (item, from_path, final_path) in enumerate(staged_moves):
                    if is_cancelled and is_cancelled():
                        logger.warning("사용자에 의해 재구성 작업이 중단되었습니다.")
                        break

                    try:
                        rel_p = str(item.current_path.relative_to(source_base_dir))
                    except Exception:
                        rel_p = str(item.current_path.name)

                    if not from_path.exists():
                        result.failed_count += 1
                        result.failed_details.append(
                            ReorganizeFailureDetail(
                                file_name=item.file_name,
                                relative_path=rel_p,
                                status="FAILED",
                                reason="스테이징 파일 누락 또는 접근 불가",
                            )
                        )
                        processed += 1
                        continue

                    try:
                        # 디렉토리 생성
                        target_dir = final_path.parent
                        if target_dir not in created_dirs:
                            target_dir.mkdir(parents=True, exist_ok=True)
                            created_dirs.add(target_dir)

                        # 파일 이동
                        if from_path.resolve() != final_path.resolve():
                            stat_orig = from_path.stat()
                            shutil.move(str(from_path), str(final_path))
                            # mtime, atime 확실한 보존
                            os.utime(final_path, (stat_orig.st_atime, stat_orig.st_mtime))
                            if item.taken_at:
                                OsDateSync.sync_file_time(final_path, item.taken_at)

                        # DB 업데이트 목록에 추가
                        folder_name = target_dir.name
                        db_updates.append((str(final_path), final_path.name, folder_name, item.media_id))
                        result.success_count += 1

                    except Exception as e:
                        logger.error("최종 위치 이동 실패 [%s -> %s]: %s", from_path, final_path, e)
                        result.failed_count += 1
                        result.errors.append(f"이동 실패: {from_path.name} -> {e}")
                        result.failed_details.append(
                            ReorganizeFailureDetail(
                                file_name=item.file_name,
                                relative_path=rel_p,
                                status="FAILED",
                                reason=f"최종 이동 실패 ({e})",
                            )
                        )

                    processed += 1

                    # 속도 및 ETA 계산
                    now = time.time()
                    if now - last_speed_time >= 0.3:
                        elapsed_interval = now - last_speed_time
                        count_interval = processed - last_speed_count
                        current_speed = count_interval / elapsed_interval if elapsed_interval > 0 else 0.0
                        last_speed_time = now
                        last_speed_count = processed

                    remaining_items = total_count - processed
                    eta = (remaining_items / current_speed) if current_speed > 0 else 0.0

                    if progress_callback:
                        progress_callback(processed, total_count, item.file_name, current_speed, eta)

            finally:
                # ── Step C: .reorganize_tmp 청소 및 빈 폴더 정리 ──
                if tmp_staging_dir and tmp_staging_dir.exists():
                    try:
                        # 혹시 남아있는 파일이 있는지 확인
                        leftovers = list(tmp_staging_dir.iterdir())
                        if not leftovers:
                            tmp_staging_dir.rmdir()
                        else:
                            logger.warning("스테이징 폴더에 미처리 잔여 파일 %d개 존재", len(leftovers))
                    except Exception as e:
                        logger.warning("스테이징 폴더 삭제 실패: %s", e)

                # 빈 디렉토리 재귀 청소 (OS 정크 파일 포함)
                empty_removed = self._remove_empty_dirs(source_base_dir)
                result.empty_folders_removed = empty_removed
                result.new_folders_created = len(created_dirs)

            # ── Step D: DB 트랜잭션 일괄 업데이트 및 누락 파일 정리 ──
            if db_updates or missing_media_ids:
                if progress_callback:
                    progress_callback(total_count, total_count, "데이터베이스 파일 경로 및 누락 레코드 동기화 중...", current_speed, 0.0)
                try:
                    self._update_db_records(db_updates, missing_media_ids, source_base_dir, target_base_dir, strategy, result)
                except Exception as e:
                    logger.error("DB 일괄 업데이트 실패: %s", e)
                    result.errors.append(f"DB 업데이트 실패: {e}")
                    raise RuntimeError(f"데이터베이스 파일 경로 일괄 업데이트에 실패했습니다: {e}") from e

        result.elapsed_seconds = round(time.time() - start_time, 2)
        logger.info(
            "폴더 구조 재구성 완료: 성공=%d, 정리=%d, 실패=%d, 소요시간=%.2f초",
            result.success_count, result.cleaned_missing_count, result.failed_count, result.elapsed_seconds
        )
        return result

    OS_JUNK_FILES = {".ds_store", "thumbs.db", ".localized", "desktop.ini"}

    def _remove_empty_dirs(self, root_dir: Path) -> int:
        """
        빈 디렉토리를 상향식(bottom-up)으로 청소하고 삭제된 폴더 수를 반환합니다.
        .DS_Store, Thumbs.db, .localized 등 OS 임시 정크 파일만 존재하는 경우
        이를 먼저 삭제한 후 빈 폴더로 인정하여 깨끗하게 제거합니다.
        """
        removed_count = 0
        try:
            for dirpath, dirnames, filenames in os.walk(str(root_dir), topdown=False):
                p = Path(dirpath)
                # 루트 디렉토리 자체는 삭제하지 않음
                if p.resolve() == root_dir.resolve():
                    continue
                # 숨김 폴더(.reorganize_tmp 등) 제외
                if p.name.startswith("."):
                    continue

                try:
                    children = list(p.iterdir())
                    if not children:
                        p.rmdir()
                        removed_count += 1
                        continue

                    # 하위 폴더는 없고 파일만 남아있는 경우, OS 정크 파일인지 검사
                    has_subdirs = any(c.is_dir() for c in children)
                    if not has_subdirs:
                        junk_only = all(c.is_file() and c.name.lower() in self.OS_JUNK_FILES for c in children)
                        if junk_only:
                            for c in children:
                                try:
                                    c.unlink()
                                except OSError:
                                    pass
                            p.rmdir()
                            removed_count += 1
                except (OSError, PermissionError):
                    continue
        except Exception as e:
            logger.warning("빈 폴더 정리 중 예외 발생: %s", e)
        return removed_count

    def _update_db_records(
        self,
        updates: List[Tuple[str, str, str, int]],
        missing_ids: List[int],
        source_dir: Path,
        target_dir: Path,
        strategy: FolderStrategy,
        result: ReorganizeResult,
    ) -> None:
        """
        media_files 테이블의 file_path, file_name, album_name을 갱신하고,
        존재하지 않는 누락 파일 레코드를 삭제하며, job_history에 재구성 이력을 기록합니다.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. 성공 파일들 media_files 일괄 UPDATE (file_path = ?, file_name = ?, album_name = ? WHERE id = ?)
        if updates:
            cursor.executemany(
                """
                UPDATE media_files
                SET file_path = ?, file_name = ?, album_name = ?
                WHERE id = ?
                """,
                updates,
            )

        # 2. 존재하지 않는 파일 고아 레코드 일괄 DELETE (DB 동기화 자동화)
        if missing_ids:
            chunk_size = 500
            for i in range(0, len(missing_ids), chunk_size):
                chunk = missing_ids[i:i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(f"DELETE FROM metadata WHERE media_id IN ({placeholders});", chunk)
                cursor.execute(f"DELETE FROM media_files WHERE id IN ({placeholders});", chunk)
            logger.info("존재하지 않는 미디어 DB 레코드 %d건 자동 정리 완료", len(missing_ids))

        # 통계 집계 (미디어 구성 및 용량)
        cursor.execute(
            """
            SELECT 
                SUM(CASE WHEN media_type='photo' THEN 1 ELSE 0 END),
                SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END),
                SUM(file_size)
            FROM media_files
            """
        )
        stat_row = cursor.fetchone()
        p_cnt = stat_row[0] or 0
        v_cnt = stat_row[1] or 0
        tot_bytes = stat_row[2] or 0

        # 2. job_history 이력 기록 (공통 record_job_history 호출로 한국 로컬 시각 및 스키마 일원화)
        strat_val = strategy.value if hasattr(strategy, "value") else str(strategy)
        self.db.record_job_history(
            source_dir=str(source_dir),
            target_dir=str(target_dir),
            total_files=result.total_count,
            processed_count=result.success_count,
            failed_count=result.failed_count,
            photo_count=p_cnt,
            video_count=v_cnt,
            total_bytes=tot_bytes,
            status=f"REORGANIZED ({strat_val})",
        )

        conn.commit()
        logger.info("DB 트랜잭션 커밋 완료: %d건 갱신, job_history 기록", len(updates))
