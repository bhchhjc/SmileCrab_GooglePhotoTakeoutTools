"""
workers.py
────────────────────────────────────────────────────────────────
UI 비동기 워커 모듈 (QRunnable + QThreadPool 기반)

UI 프리징 없이 백그라운드에서 무거운 작업을 처리한다.

Workers:
  ScanWorker    — Takeout 폴더 사전 스캔 (Dry-run, 매칭률/통계 계산)
  ProcessWorker — 실제 처리 파이프라인 (파일 복사/이동, EXIF, DB 저장)

시그널 흐름:
  Worker → signals.progress / finished / error → JobView slot

주의:
  모든 UI 조작은 메인 스레드에서만 가능.
  워커에서는 Signal만 방출하고, slot은 메인 스레드에서 받는다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Signal

from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.matcher import DirectoryMetadataIndex, MetadataMatcher
from src.core.models import MatchType, MediaFile
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.process_service import (
    FolderStrategy, ProcessMode, ProcessService, ProcessSummary,
    calculate_file_hash,
)
from src.services.reorganize_service import (
    ReorganizeItem, ReorganizeResult, ReorganizeService,
)
from src.services.batch_rename_service import (
    BatchRenameResult, BatchRenameService, RenamePatternConfig,
)
from src.services.geo_relabel_service import (
    GeoRelabelResult, GeoRelabelService,
)


# ── 공통 시그널 ──────────────────────────────────────────────

class WorkerSignals(QObject):
    """
    워커 → 메인 스레드 간 안전한 시그널 채널.
    
    Signals:
        progress(current, total, message):             기본 진행 상황
        stats_progress(current, total, message, stats): 상세 통계(완료/스킵/오류) 포함 진행 상황
        finished(result_dict):                         완료 결과
        error(error_message):                          예외 발생
    """
    progress       = Signal(int, int, str)
    stats_progress = Signal(int, int, str, dict)
    finished       = Signal(object)          # dict (scan stats 또는 process summary)
    error          = Signal(str)             # 에러 메시지


# ── ScanWorker ───────────────────────────────────────────────

class ScanWorker(QRunnable):
    """
    Takeout 원본 폴더를 Dry-run으로 스캔하여 통계를 계산한다.
    
    실제 파일 복사/수정은 하지 않고, 메타데이터 매칭률 및 파일 개수만 집계.
    
    finished 시그널로 방출하는 dict 키:
        total_files  : 전체 파일 수 (JSON 포함)
        media_files  : 미디어 파일 수
        json_files   : JSON 파일 수
        matched      : 매칭 성공 수
        unmatched    : 매칭 실패 수
        duplicates   : 중복 파일 수 (동일 해시)
        total_bytes  : 전체 용량 (bytes)
    """

    def __init__(self, source_dir: str, output_dir: str):
        super().__init__()
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.signals    = WorkerSignals()
        self._cancelled = False

    def cancel(self):
        """취소 플래그 설정 (run() 루프에서 확인)."""
        self._cancelled = True

    def run(self):
        """스캔 작업 실행 (별도 스레드)."""
        try:
            matcher      = MetadataMatcher()
            media_list   = []
            json_count   = 0
            total_bytes  = 0
            seen_sizes   = {}   # size -> hash 매핑 (동일 크기 파일만 해시 비교하여 속도 극대화)
            seen_hashes  = set()
            dup_count    = 0
            scanned_so_far = 0

            # ── 1단계: 파일 목록 수집 ──────────────────────────
            for root, _dirs, files in os.walk(self.source_dir):
                if self._cancelled:
                    return
                root_path = Path(root)
                index     = DirectoryMetadataIndex(root_path)

                for f in sorted(files):
                    if self._cancelled:
                        return
                    if f.startswith("."):
                        continue
                    if f.lower().endswith(".json"):
                        json_count += 1
                        continue

                    full_p = root_path / f
                    media  = MediaFile.from_path(full_p)
                    if media.media_type.value != "unknown":
                        media_list.append((media, index))
                        total_bytes += media.file_size

                    scanned_so_far += 1
                    if scanned_so_far % 200 == 0:
                        self.signals.progress.emit(
                            0, 0,
                            f"폴더 순회 및 미디어 탐색 중... ({len(media_list):,}개 미디어 발견)"
                        )

            total_items   = len(media_list)
            matched_count = 0

            if total_items == 0:
                self.signals.finished.emit({
                    "total_files": json_count,
                    "media_files": 0,
                    "json_files":  json_count,
                    "matched":     0,
                    "unmatched":   0,
                    "duplicates":  0,
                    "total_bytes": 0,
                })
                return

            # ── 2단계: 메타데이터 매칭 및 지능형 중복 분석 ───────────────────
            emit_interval = max(1, min(100, total_items // 200))
            for idx, (media, index) in enumerate(media_list, 1):
                if self._cancelled:
                    return

                res = matcher.match(media, index=index)
                if res.is_matched and res.match_type != MatchType.NONE:
                    matched_count += 1

                # 중복 체크 최적화: 동일 파일 크기가 존재할 때만 SHA-256 계산
                sz = media.file_size
                if sz in seen_sizes:
                    try:
                        # 기존 동일 크기 파일의 해시가 아직 계산 안 되어 있다면 계산
                        prev_path, prev_hash = seen_sizes[sz]
                        if prev_hash is None:
                            prev_hash = calculate_file_hash(prev_path)
                            seen_sizes[sz] = (prev_path, prev_hash)
                            seen_hashes.add(prev_hash)

                        curr_hash = calculate_file_hash(media.path)
                        if curr_hash in seen_hashes:
                            dup_count += 1
                        else:
                            seen_hashes.add(curr_hash)
                    except OSError:
                        pass
                else:
                    # 크기가 처음 등장한 파일은 해시 계산 생략(None 보관)하여 I/O 극적 절약
                    seen_sizes[sz] = (media.path, None)

                # 주기적 또는 마지막 항목에서 진행 상황 방출
                if idx % emit_interval == 0 or idx == total_items:
                    self.signals.progress.emit(
                        idx, total_items,
                        f"미디어 분석 중: {media.normalized_name}"
                    )

            # ── 결과 방출 ──────────────────────────────────────
            self.signals.finished.emit({
                "total_files": total_items + json_count,
                "media_files": total_items,
                "json_files":  json_count,
                "matched":     matched_count,
                "unmatched":   total_items - matched_count,
                "duplicates":  dup_count,
                "total_bytes": total_bytes,
            })

        except Exception as exc:
            self.signals.error.emit(str(exc))


# ── ProcessWorker ────────────────────────────────────────────

class ProcessWorker(QRunnable):
    """
    실제 Takeout 처리 파이프라인을 백그라운드에서 실행한다.
    
    - 파일 복사 또는 이동
    - EXIF 메타데이터 주입
    - OS 파일 타임스탬프 동기화
    - SQLite DB 저장
    
    finished 시그널로 방출하는 dict 키:
        processed : 처리 완료 파일 수
        skipped   : 중복으로 건너뛴 파일 수
        errors    : 오류 발생 파일 수
    """

    def __init__(
        self,
        input_path:     str,
        output_path:    str,
        strategy:       FolderStrategy,
        mode:           ProcessMode,
        should_stop_fn: Optional[Callable[[], bool]] = None,
        geo_language:   GeoLanguage = GeoLanguage.KOREAN,
    ):
        super().__init__()
        self.input_path     = Path(input_path)
        self.output_path    = Path(output_path)
        self.strategy       = strategy
        self.mode           = mode
        self.geo_language   = geo_language
        self._should_stop   = should_stop_fn or (lambda: False)
        self.signals        = WorkerSignals()

    def run(self):
        """처리 파이프라인 실행 (별도 스레드)."""
        try:
            db = DatabaseManager()
            db.initialize()
            repo = MediaRepository(db)

            service = ProcessService(
                media_repo       = repo,
                folder_strategy  = self.strategy,
                process_mode     = self.mode,
                geo_language     = self.geo_language,
            )

            def on_progress(cur: int, total: int, fname: str, status: str, stats: Optional[dict] = None):
                msg = f"{status} — {fname}"
                self.signals.progress.emit(cur, total, msg)
                if stats is not None:
                    self.signals.stats_progress.emit(cur, total, msg, stats)

            summary: ProcessSummary = service.run_pipeline(
                source_dir        = self.input_path,
                output_dir        = self.output_path,
                progress_callback = on_progress,
                should_stop       = self._should_stop,
            )

            # 1회 Run 세션 단위 작업 이력 DB 기록
            db.record_job_history(
                source_dir        = str(self.input_path),
                target_dir        = str(self.output_path),
                total_files       = getattr(summary, "total_scanned", 0),
                processed_count   = getattr(summary, "processed_count", 0),
                skipped_duplicate = getattr(summary, "skipped_duplicate", 0),
                failed_count      = getattr(summary, "failed_count", 0),
                photo_count       = getattr(summary, "photo_count", 0),
                video_count       = getattr(summary, "video_count", 0),
                total_bytes       = getattr(summary, "total_bytes", 0),
                status            = "COMPLETED" if getattr(summary, "failed_count", 0) == 0 else "PARTIAL",
            )

            # ProcessSummary → dict 변환
            self.signals.finished.emit({
                "processed": getattr(summary, "processed_count", 0),
                "skipped":   getattr(summary, "skipped_duplicate", 0),
                "errors":    getattr(summary, "failed_count", 0),
            })

        except Exception as exc:
            self.signals.error.emit(str(exc))


# ── LibraryLoaderWorker ──────────────────────────────────────

def group_media_items(items: list, group_by: str = "date", sort_by: str = "name") -> list[tuple[str, dict]]:
    """
    미디어 항목 리스트를 지정된 기준으로 그룹화하고 정렬하여 반환합니다.
    (메모리 연산: 1만 건 기준 약 1~2ms 소요)
    """
    groups: dict[str, dict] = {}
    for it in items:
        fp = it.get("file_path") or ""
        f_dir = str(Path(fp).parent) if fp else ""
        dt_str = it.get("taken_at") or ""

        if group_by == "camera":
            make = (it.get("camera_make") or "").strip()
            model = (it.get("camera_model") or "").strip()
            if make and model:
                grp_name = f"📷 {make} {model}"
            elif make or model:
                grp_name = f"📷 {make or model}"
            else:
                grp_name = "📷 기기 정보 없음 (Unknown)"
        elif group_by == "day":
            if dt_str and len(dt_str) >= 10:
                parts = dt_str[:10].split("-")
                grp_name = f"📅 {parts[0]}년 {parts[1]}월 {parts[2]}일" if len(parts) == 3 else dt_str[:10]
            else:
                grp_name = "📅 촬영 일자 불명"
        elif group_by == "album":
            grp_name = f"🏷️ {it.get('album_name') or '미분류 앨범'}"
        elif group_by in ("location", "location_3tier", "location_country_state", "location_country_city", "location_country"):
            c_name = (it.get("country_name") or "").strip()
            state = (it.get("state_name") or "").strip()
            city = (it.get("city_name") or "").strip()
            lat = it.get("latitude") or 0.0
            lon = it.get("longitude") or 0.0
            if not c_name and (lat != 0.0 or lon != 0.0):
                info = GeoResolver().resolve(lat, lon, GeoLanguage.KOREAN)
                c_name = info.country_name
                state = info.state_name
                city = info.city_name
                it["country_name"] = c_name
                it["state_name"] = state
                it["city_name"] = city

            if not c_name and not city and not state:
                grp_name = "📍 위치 정보 없음 (No GPS)"
            elif group_by == "location_3tier":
                parts = [p for p in (c_name, state, city) if p]
                grp_name = f"🌍 {' > '.join(parts)}" if parts else "📍 위치 정보 없음 (No GPS)"
            elif group_by == "location_country_state":
                parts = [p for p in (c_name, state) if p]
                grp_name = f"🌍 {' > '.join(parts)}" if parts else "📍 위치 정보 없음 (No GPS)"
            elif group_by == "location_country":
                grp_name = f"🌍 {c_name}" if c_name else "📍 위치 정보 없음 (No GPS)"
            else:  # location_country_city or legacy location
                parts = [p for p in (c_name, city) if p]
                grp_name = f"🌍 {' '.join(parts)}" if parts else "📍 위치 정보 없음 (No GPS)"
        elif group_by == "folder":
            p = Path(f_dir)
            if len(p.parents) >= 1 and p.parent.name:
                grp_name = f"📁 {p.parent.name}/{p.name}"
            else:
                grp_name = f"📁 {p.name or '최상위'}"
        else:  # date
            if dt_str and len(dt_str) >= 7:
                parts = dt_str[:7].split("-")
                grp_name = f"📅 {parts[0]}년 {parts[1]}월" if len(parts) == 2 else dt_str[:7]
            else:
                grp_name = "📅 날짜 불명"

        if grp_name not in groups:
            groups[grp_name] = {"items": [], "dir_path": f_dir}
        groups[grp_name]["items"].append(it)

    # ── 정렬 방식 (sort_by: 'name' 가나다/최신순 vs 'count' 사진 많은 순) ──
    # '위치 정보 없음' 또는 '기기 정보 없음'은 사용자가 쉽게 구분할 수 있도록 항상 최하단에 배치
    unknown_location_key = "📍 위치 정보 없음 (No GPS)"
    unknown_camera_key = "📷 기기 정보 없음 (Unknown)"

    if sort_by == "count":
        # 건수 내림차순 정렬하되, 정보 없음 그룹은 맨 끝으로
        def count_sort_key(item):
            name, data = item
            is_unknown = 1 if name in (unknown_location_key, unknown_camera_key) else 0
            return (is_unknown, -len(data["items"]), name)

        return sorted(groups.items(), key=count_sort_key)
    else:
        # 이름/일자순 기본 정렬
        if group_by in ("location", "location_3tier", "location_country_state", "location_country_city", "location_country"):
            def loc_sort_key(item):
                name, _ = item
                is_unknown = 1 if name == unknown_location_key else 0
                return (is_unknown, name)
            return sorted(groups.items(), key=loc_sort_key)
        elif group_by == "camera":
            def cam_sort_key(item):
                name, _ = item
                is_unknown = 1 if name == unknown_camera_key else 0
                return (is_unknown, name)
            return sorted(groups.items(), key=cam_sort_key)
        elif group_by in ("date", "day"):
            return sorted(groups.items(), key=lambda x: x[0], reverse=True)
        else:
            return sorted(groups.items(), key=lambda x: x[0])


class LibraryLoaderSignals(QObject):
    """라이브러리 로더 워커 시그널"""
    finished = Signal(list, list, int)  # (sorted_groups, valid_results, total_count)
    error    = Signal(str)


class LibraryLoaderWorker(QRunnable):
    """
    미디어 라이브러리 목록을 백그라운드 스레드에서 비동기 조회 및 그룹화하는 워커.
    - 대량(1만 건 이상) DB 쿼리 및 디스크 파일 실시간 존재 확인(os.path.exists)을
      UI 스레드와 완전히 분리하여 UI 프리징을 100% 방지합니다.
    """
    def __init__(
        self,
        keyword: Optional[str] = None,
        media_type: Optional[str] = None,
        has_gps: Optional[bool] = None,
        root_path: Optional[str] = None,
        group_by: str = "date",
        sort_by: str = "name",
        db_path: Optional[Path] = None,
    ):
        super().__init__()
        self.keyword    = keyword
        self.media_type = media_type
        self.has_gps    = has_gps
        self.root_path  = root_path
        self.group_by   = group_by
        self.sort_by    = sort_by
        self.db_path    = db_path
        self.signals    = LibraryLoaderSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if self._cancelled:
                return

            db = DatabaseManager(self.db_path)
            db.initialize()
            repo = MediaRepository(db)

            results = repo.search_media(
                keyword    = self.keyword,
                media_type = self.media_type,
                has_gps    = self.has_gps,
                root_path  = self.root_path,
                limit      = None,
            )

            if self._cancelled:
                return

            # 디스크 유효성 검증 (백그라운드에서 실행)
            valid_results = []
            for idx, it in enumerate(results):
                if idx % 100 == 0 and self._cancelled:
                    return
                fp = it.get("file_path")
                if fp and os.path.exists(fp):
                    valid_results.append(it)

            if self._cancelled:
                return

            # 그룹화 (공통 헬퍼 활용)
            sorted_groups = group_media_items(valid_results, self.group_by, self.sort_by)

            if self._cancelled:
                return

            self.signals.finished.emit(sorted_groups, valid_results, len(valid_results))

        except Exception as exc:
            if not self._cancelled:
                self.signals.error.emit(str(exc))


class BatchRenameSignals(QObject):
    """파일명 일괄 변경 워커 시그널"""
    progress = Signal(int, int, str, float, float)
    finished = Signal(object)
    error = Signal(str)


class BatchRenameWorker(QRunnable):
    """
    메타데이터 기반 파일명 일괄 변경 비동기 백그라운드 워커.
    """
    def __init__(
        self,
        items: list,
        pattern: RenamePatternConfig,
        source_dir: Optional[Path] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        super().__init__()
        self.items = items
        self.pattern = pattern
        self.source_dir = source_dir
        self.db_manager = db_manager
        self.signals = BatchRenameSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            db_path = self.db_manager.db_path if self.db_manager else None
            thread_db = DatabaseManager(db_path=db_path)
            thread_db.initialize()

            service = BatchRenameService(thread_db)

            def progress_cb(cur: int, tot: int, fname: str, spd: float, eta: float):
                self.signals.progress.emit(cur, tot, fname, spd, eta)

            result = service.execute_batch_rename(
                items=self.items,
                pattern=self.pattern,
                source_base_dir=self.source_dir,
                progress_callback=progress_cb,
                is_cancelled=lambda: self._cancelled,
            )

            if not self._cancelled:
                self.signals.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.signals.error.emit(str(exc))


class GroupReorderSignals(QObject):
    """캐시된 미디어의 그룹 기준/정렬 기준 재계산 비동기 시그널"""
    finished = Signal(list, int)  # (sorted_groups, total_files)


class GroupReorderWorker(QRunnable):
    """
    캐시된 미디어 목록을 백그라운드 스레드에서 즉시 재그룹핑 및 정렬하는 워커.
    - 그룹 기준(날짜, 기기, 지역 등)이나 정렬 기준(가나다순, 건수순) 변경 시
      메인 UI 스레드의 이벤트 루프를 전혀 방해하지 않아 프로그레스 서클이 부드럽게 유지됩니다.
    """
    def __init__(self, items: list, group_by: str, sort_by: str):
        super().__init__()
        self.items = items
        self.group_by = group_by
        self.sort_by = sort_by
        self.signals = GroupReorderSignals()

    def run(self):
        sorted_groups = group_media_items(self.items, self.group_by, self.sort_by)
        self.signals.finished.emit(sorted_groups, len(self.items))


class ReorganizeSignals(QObject):
    """
    폴더 구조 재구성 워커 시그널
    
    Signals:
        progress(current, total, file_name, speed, eta_seconds): 실시간 진행 상황 및 속도/ETA
        finished(result): ReorganizeResult 결과 객체
        error(error_msg): 오류 발생 메시지
    """
    progress = Signal(int, int, str, float, float)
    finished = Signal(object)
    error = Signal(str)


class ReorganizeWorker(QRunnable):
    """
    미디어 폴더 구조 비동기 재구성 워커.
    
    메인 UI 스레드를 차단하지 않고 백그라운드에서 .reorganize_tmp 임시 스테이징,
    파일 재배치, 빈 폴더 청소, DB 일괄 트랜잭션 업데이트를 안전하게 수행합니다.
    """
    def __init__(
        self,
        source_dir: Path,
        target_dir: Path,
        strategy: FolderStrategy,
        db_manager: Optional[DatabaseManager] = None,
        items: Optional[list] = None,
    ):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.strategy = strategy
        self.db_manager = db_manager
        self.items = items
        self.signals = ReorganizeSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            # 백그라운드 워커 스레드 전용 DB 인스턴스 생성 (스레드 간 SQLite 커넥션 격리 보장)
            db_path = self.db_manager.db_path if self.db_manager else None
            thread_db = DatabaseManager(db_path=db_path)
            thread_db.initialize()

            service = ReorganizeService(thread_db)

            def progress_cb(cur: int, tot: int, fname: str, spd: float, eta: float):
                self.signals.progress.emit(cur, tot, fname, spd, eta)

            result = service.execute_reorganize(
                source_base_dir=self.source_dir,
                target_base_dir=self.target_dir,
                strategy=self.strategy,
                items=self.items,
                progress_callback=progress_cb,
                is_cancelled=lambda: self._cancelled,
            )

            if not self._cancelled:
                self.signals.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.signals.error.emit(str(exc))


class GeoRelabelSignals(QObject):
    """지역명 언어 변경 워커 시그널"""
    progress = Signal(int, int, str, float, float)
    finished = Signal(object)
    error = Signal(str)


class GeoRelabelWorker(QRunnable):
    """
    저장된 미디어의 역지오코딩 지명을 다른 언어로 일괄 재변환하는 비동기 워커
    """
    def __init__(
        self,
        target_root: Optional[str] = None,
        target_lang: GeoLanguage = GeoLanguage.KOREAN,
        db_manager: Optional[DatabaseManager] = None,
    ):
        super().__init__()
        self.target_root = target_root
        self.target_lang = target_lang
        self.db_manager = db_manager
        self.signals = GeoRelabelSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            db_path = self.db_manager.db_path if self.db_manager else None
            thread_db = DatabaseManager(db_path=db_path)
            thread_db.initialize()

            service = GeoRelabelService(thread_db)

            def progress_cb(cur: int, tot: int, fname: str, spd: float, eta: float):
                self.signals.progress.emit(cur, tot, fname, spd, eta)

            result = service.execute_relabel(
                target_root=self.target_root,
                target_lang=self.target_lang,
                progress_callback=progress_cb,
                is_cancelled=lambda: self._cancelled,
            )

            if not self._cancelled:
                self.signals.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.signals.error.emit(str(exc))




