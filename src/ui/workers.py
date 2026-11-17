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

from src.core.matcher import DirectoryMetadataIndex, MetadataMatcher
from src.core.models import MatchType, MediaFile
from src.services.process_service import (
    FolderStrategy, ProcessMode, ProcessService, ProcessSummary,
)


# ── 공통 시그널 ──────────────────────────────────────────────

class WorkerSignals(QObject):
    """
    워커 → 메인 스레드 간 안전한 시그널 채널.
    
    Signals:
        progress(current, total, message): 진행 상황
        finished(result_dict):             완료 결과
        error(error_message):              예외 발생
    """
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(object)          # dict (scan stats 또는 process summary)
    error    = Signal(str)             # 에러 메시지


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
            seen_hashes  = set()
            dup_count    = 0

            # ── 1단계: 파일 목록 수집 ──────────────────────────
            for root, _dirs, files in os.walk(self.source_dir):
                if self._cancelled:
                    return
                root_path = Path(root)
                index     = DirectoryMetadataIndex(root_path)

                for f in sorted(files):
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

            total_items   = len(media_list)
            matched_count = 0

            # ── 2단계: 메타데이터 매칭 분석 ───────────────────
            for idx, (media, index) in enumerate(media_list, 1):
                if self._cancelled:
                    return

                res = matcher.match(media, index=index)
                if res.is_matched and res.match_type != MatchType.NONE:
                    matched_count += 1

                # 중복 체크 (SHA-256 해시 비교)
                if media.file_hash:
                    if media.file_hash in seen_hashes:
                        dup_count += 1
                    else:
                        seen_hashes.add(media.file_hash)

                # 10개마다 또는 마지막 항목에서 진행 상황 방출
                if idx % 10 == 0 or idx == total_items:
                    self.signals.progress.emit(
                        idx, total_items,
                        f"스캔 중: {media.normalized_name}"
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
    ):
        super().__init__()
        self.input_path     = Path(input_path)
        self.output_path    = Path(output_path)
        self.strategy       = strategy
        self.mode           = mode
        self._should_stop   = should_stop_fn or (lambda: False)
        self.signals        = WorkerSignals()

    def run(self):
        """처리 파이프라인 실행 (별도 스레드)."""
        try:
            service = ProcessService(
                output_dir       = self.output_path,
                folder_strategy  = self.strategy,
                process_mode     = self.mode,
            )

            def on_progress(cur: int, total: int, fname: str, status: str):
                # (cur, total, message) 형식으로 변환하여 방출
                self.signals.progress.emit(cur, total, f"{status} — {fname}")

            summary: ProcessSummary = service.run_pipeline(
                source_dir        = self.input_path,
                output_dir        = self.output_path,
                progress_callback = on_progress,
                should_stop       = self._should_stop,
            )

            # ProcessSummary → dict 변환
            self.signals.finished.emit({
                "processed": getattr(summary, "processed_count", 0),
                "skipped":   getattr(summary, "skipped_count",   0),
                "errors":    getattr(summary, "error_count",     0),
            })

        except Exception as exc:
            self.signals.error.emit(str(exc))
