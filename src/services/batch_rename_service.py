"""
GooglePhotoTakeoutTools - Batch Rename Service
메타데이터 기반 파일명 일괄 변경(Batch Rename) 엔진
- 스택형 토큰 조합 (촬영일시, 카메라 기종/제조사, 역지오코딩 위치, 원본명, 사용자 지정 문구 등)
- 괄호([], ()) 및 스마트 구분자 자동 정돈
- 정보 누락 시 유연한 Fallback 처리 및 동일 폴더 중복 방지
- 타임스탬프(mtime, birthtime) 및 EXIF 100% 무손실 보존
- SQLite 일괄 트랜잭션 및 부재 파일 자동 동기화
"""

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.i18n import t
from src.core.os_sync import OsDateSync
from src.core.power_management import SleepInhibitor
from src.data.database import DatabaseManager

logger = logging.getLogger(__name__)


class RenameTokenType(str, Enum):
    """파일명 조합 토큰 종류"""
    DATE = "date"                  # 촬영 일시
    MAKE = "make"                  # 기기 제조사 (Apple, Samsung 등)
    MODEL = "model"                # 기기 모델명 (iPhone 14 Pro, SM-S908N 등)
    COUNTRY = "country"            # 국가명 (대한민국 등)
    STATE = "state"                # 시·도명 (경기도 등)
    CITY = "city"                  # 시·군·구명 (고양시 등)
    ORIGINAL_NAME = "original"     # 원본 파일명 (확장자 제외)
    CUSTOM_TEXT = "custom"         # 사용자 직접 입력 문구
    SEQUENCE = "seq"               # 일련번호 (001, 002...)


TOKEN_I18N_KEYS: Dict[RenameTokenType, str] = {
    RenameTokenType.DATE: "tokens.DATETIME",
    RenameTokenType.MAKE: "tokens.CAMERA_MAKE",
    RenameTokenType.MODEL: "tokens.CAMERA_MODEL",
    RenameTokenType.COUNTRY: "tokens.GEO_COUNTRY",
    RenameTokenType.STATE: "tokens.GEO_STATE",
    RenameTokenType.CITY: "tokens.GEO_CITY",
    RenameTokenType.ORIGINAL_NAME: "tokens.ORIGINAL_NAME",
    RenameTokenType.CUSTOM_TEXT: "tokens.CUSTOM_TEXT",
    RenameTokenType.SEQUENCE: "tokens.SEQUENCE",
}


def get_token_display_name(token_type: RenameTokenType) -> str:
    """토큰의 다국어 표시 라벨 반환"""
    key = TOKEN_I18N_KEYS.get(token_type)
    if key:
        return t(key)
    return token_type.value



class BracketStyle(str, Enum):
    """토큰을 감싸는 괄호 스타일"""
    NONE = "none"                  # 괄호 없음
    SQUARE = "square"              # 대괄호 [ 값 ]
    ROUND = "round"                # 소괄호 ( 값 )


@dataclass
class RenameTokenConfig:
    """개별 토큰 설정"""
    token_type: RenameTokenType
    bracket_style: BracketStyle = BracketStyle.NONE
    custom_text: str = ""          # CUSTOM_TEXT일 때 사용
    date_format: str = "%Y%m%d-%H%M%S"  # DATE일 때 사용
    next_delimiter: Optional[str] = None  # 다음 토큰과의 개별 연결 구분자 (None: 전역 규칙 따름, "": 붙여쓰기)


@dataclass
class RenamePatternConfig:
    """전체 파일명 생성 패턴 규칙"""
    tokens: List[RenameTokenConfig] = field(default_factory=list)
    delimiter: str = "_"           # 토큰 간 기본 구분자 ("_", "-", " ", "")
    fallback_text: str = ""        # 메타데이터 누락 시 대체 텍스트 (비어있으면 자동 생략 및 구분자 정돈)
    preserve_extension: bool = True
    auto_remove_bracket_delimiters: bool = True  # 괄호 항목 인접 연결 구분자 자동 제거 (예: [모델]날짜)


@dataclass
class BatchRenameFailureDetail:
    """파일명 변경 중 정리되거나 실패한 파일 상세 정보"""
    file_name: str
    relative_path: str
    status: str                    # "CLEANED" (존재하지 않아 DB 정리), "FAILED" (변경 실패)
    reason: str                    # 상세 사유


@dataclass
class BatchRenameResult:
    """파일명 일괄 변경 실행 결과 요약"""
    total_count: int = 0
    success_count: int = 0
    cleaned_missing_count: int = 0 # 디스크 부재로 DB 정리된 수
    skipped_count: int = 0
    failed_count: int = 0
    elapsed_seconds: float = 0.0
    source_dir: str = ""
    pattern_summary: str = ""
    errors: List[str] = field(default_factory=list)
    failed_details: List[BatchRenameFailureDetail] = field(default_factory=list)


def sanitize_filename_part(text: str) -> str:
    """OS 파일명에 사용할 수 없는 특수문자 제거 및 정돈"""
    if not text:
        return ""
    # OS 금지 문자 제거: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/:*?"<>|]', "", text)
    # 제어문자 및 앞뒤 공백 제거
    cleaned = re.sub(r'[\r\n\t]', " ", cleaned).strip()
    return cleaned


class BatchRenameService:
    """
    메타데이터 기반 파일명 일괄 변경 엔진.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()

    @staticmethod
    def format_token_value(
        token: RenameTokenConfig,
        item: Dict[str, Any],
        sequence_num: int = 1,
        fallback_text: str = "",
    ) -> str:
        """개별 토큰의 실제 텍스트 값 추출 및 괄호 포맷팅"""
        val = ""
        tt = token.token_type

        if tt == RenameTokenType.DATE:
            dt = item.get("taken_at")
            if dt:
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt.replace("T", " "))
                    except Exception:
                        dt = None
            if dt and isinstance(dt, datetime):
                try:
                    val = dt.strftime(token.date_format)
                except Exception:
                    val = dt.strftime("%Y%m%d-%H%M%S")
            else:
                val = fallback_text

        elif tt == RenameTokenType.MAKE:
            make = (item.get("camera_make") or "").strip()
            val = sanitize_filename_part(make) or fallback_text

        elif tt == RenameTokenType.MODEL:
            model = (item.get("camera_model") or "").strip()
            val = sanitize_filename_part(model) or fallback_text

        elif tt == RenameTokenType.COUNTRY:
            country = (item.get("country_name") or "").strip()
            if country in ("위치 정보 없음", "위치정보 없음", "위치 정보없음"):
                country = "위치정보없음"
            val = sanitize_filename_part(country) or fallback_text

        elif tt == RenameTokenType.STATE:
            state = (item.get("state_name") or "").strip()
            if state in ("위치 정보 없음", "위치정보 없음", "위치 정보없음"):
                state = "위치정보없음"
            val = sanitize_filename_part(state) or fallback_text

        elif tt == RenameTokenType.CITY:
            city = (item.get("city_name") or "").strip()
            if city in ("위치 정보 없음", "위치정보 없음", "위치 정보없음"):
                city = "위치정보없음"
            val = sanitize_filename_part(city) or fallback_text

        elif tt == RenameTokenType.ORIGINAL_NAME:
            orig_name = item.get("file_name") or Path(item.get("file_path", "")).name
            stem = Path(orig_name).stem
            val = sanitize_filename_part(stem)

        elif tt == RenameTokenType.CUSTOM_TEXT:
            val = sanitize_filename_part(token.custom_text)

        elif tt == RenameTokenType.SEQUENCE:
            val = f"{sequence_num:03d}"

        val = val.strip()
        if not val:
            return ""

        # 괄호 적용
        if token.bracket_style == BracketStyle.SQUARE:
            return f"[{val}]"
        elif token.bracket_style == BracketStyle.ROUND:
            return f"({val})"
        return val

    @classmethod
    def generate_filename(
        cls,
        pattern: RenamePatternConfig,
        item: Dict[str, Any],
        sequence_num: int = 1,
    ) -> str:
        """패턴 규칙과 미디어 항목 정보를 조합하여 새 파일명을 생성 (스마트 구분자 정돈)"""
        valid_parts: List[Tuple[str, RenameTokenConfig]] = []
        for t in pattern.tokens:
            val = cls.format_token_value(t, item, sequence_num=sequence_num, fallback_text=pattern.fallback_text)
            if val:
                valid_parts.append((val, t))

        if not valid_parts:
            # 모든 메타데이터가 누락된 경우 안전하게 원본 파일명 유지
            orig_p = item.get("file_path") or item.get("file_name") or "media"
            return Path(orig_p).name

        combined = ""
        for i, (val, tok) in enumerate(valid_parts):
            if i == 0:
                combined = val
                continue

            prev_val, prev_tok = valid_parts[i - 1]
            delim = prev_tok.next_delimiter if prev_tok.next_delimiter is not None else "_"
            combined += f"{delim}{val}"

        # 연속된 기본 구분자 정돈 (예: "__" -> "_", "--" -> "-")
        if pattern.delimiter:
            escaped_d = re.escape(pattern.delimiter)
            combined = re.sub(f"{escaped_d}+", pattern.delimiter, combined)
            combined = combined.strip(pattern.delimiter)

        combined = sanitize_filename_part(combined)
        if not combined:
            orig_p = item.get("file_path") or item.get("file_name") or "media"
            return Path(orig_p).name

        # 확장자 처리 (이중 점 ..ext 방지)
        if pattern.preserve_extension:
            orig_ext = (item.get("file_ext") or "").strip()
            if not orig_ext and item.get("file_path"):
                orig_ext = Path(item.get("file_path")).suffix
            clean_ext = orig_ext.lstrip(".")
            if clean_ext:
                clean_ext_lower = clean_ext.lower()
                if not combined.lower().endswith(f".{clean_ext_lower}"):
                    combined = f"{combined}.{clean_ext_lower}"

        return combined

    def execute_batch_rename(
        self,
        items: List[Dict[str, Any]],
        pattern: RenamePatternConfig,
        source_base_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, int, str, float, float], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> BatchRenameResult:
        """
        파일명 일괄 변경을 실제로 실행합니다.
        
        - 타임스탬프 원자적 보존 (mtime, birthtime)
        - 동일 폴더 내 중복 충돌 방지 (1), (2) 접미사
        - 디스크 부재 파일 자동 식별 및 DB 레코드 동시 청소
        - SQLite 트랜잭션 일괄 업데이트
        """
        start_time = time.time()
        total_count = len(items)

        # 패턴 요약 문자열 생성 (i18n 다국어 지원)
        pattern_summary = ""
        for i, t in enumerate(pattern.tokens):
            lbl = get_token_display_name(t.token_type)
            if t.token_type == RenameTokenType.CUSTOM_TEXT and t.custom_text:
                lbl = f'"{t.custom_text}"'
            if t.bracket_style == BracketStyle.SQUARE:
                lbl = f"[{lbl}]"
            elif t.bracket_style == BracketStyle.ROUND:
                lbl = f"({lbl})"
            pattern_summary += lbl
            if i < len(pattern.tokens) - 1:
                delim = t.next_delimiter if t.next_delimiter is not None else "_"
                pattern_summary += delim

        result = BatchRenameResult(
            total_count=total_count,
            source_dir=str(source_base_dir) if source_base_dir else "",
            pattern_summary=pattern_summary,
        )

        if total_count == 0:
            result.elapsed_seconds = round(time.time() - start_time, 2)
            return result

        with SleepInhibitor("미디어 파일명 일괄 변경 작업"):
            # 1. 대상 경로 계산 및 중복 방지 예약
            # planned_renames: List of (item, curr_path, final_new_path)
            planned_renames: List[Tuple[Dict[str, Any], Path, Path]] = []
            used_folder_paths: Dict[Path, set] = {}  # folder_dir -> set of final_path

            for seq_idx, item in enumerate(items, start=1):
                raw_path = item.get("file_path")
                if not raw_path:
                    continue
                curr_p = Path(raw_path)
                folder = curr_p.parent

                if folder not in used_folder_paths:
                    used_folder_paths[folder] = set()

                new_fname = self.generate_filename(pattern, item, sequence_num=seq_idx)
                final_p = folder / new_fname

                # 중복 충돌 방지
                # 1) 이번 작업에서 앞서 같은 파일명을 예약한 경우
                # 2) 디스크에 이미 해당 파일이 존재하는데 내가 아닌 다른 파일인 경우
                stem = final_p.stem
                suffix = final_p.suffix
                counter = 1
                while (final_p in used_folder_paths[folder]) or (
                    final_p.exists() and final_p.resolve() != curr_p.resolve()
                ):
                    final_p = folder / f"{stem}({counter}){suffix}"
                    counter += 1

                used_folder_paths[folder].add(final_p)
                planned_renames.append((item, curr_p, final_p))

            db_updates: List[Tuple[str, str, int]] = []  # (new_file_path, new_file_name, media_id)
            missing_media_ids: List[int] = []
            processed = 0
            last_speed_time = time.time()
            last_speed_count = 0
            current_speed = 0.0

            # 2. 파일명 변경 실행
            for idx, (item, curr_p, final_p) in enumerate(planned_renames):
                if is_cancelled and is_cancelled():
                    logger.warning("사용자에 의해 파일명 일괄 변경 작업이 취소되었습니다.")
                    break

                try:
                    rel_p = str(curr_p.relative_to(source_base_dir)) if source_base_dir else curr_p.name
                except Exception:
                    rel_p = curr_p.name

                # 디스크 실재 여부 검사
                if not curr_p.exists():
                    result.cleaned_missing_count += 1
                    m_id = item.get("id") or item.get("media_id")
                    if m_id:
                        missing_media_ids.append(m_id)
                    result.failed_details.append(
                        BatchRenameFailureDetail(
                            file_name=curr_p.name,
                            relative_path=rel_p,
                            status="CLEANED",
                            reason="존재하지 않는 파일 (DB 자동 정리)",
                        )
                    )
                    processed += 1
                    continue

                # 이미 파일명이 일치하는 경우
                if curr_p.resolve() == final_p.resolve():
                    result.success_count += 1
                    processed += 1
                    continue

                try:
                    # 원본 타임스탬프 백업
                    stat_orig = curr_p.stat()

                    # 파일명 원자적 변경
                    os.replace(curr_p, final_p)

                    # 타임스탬프 원자적 보존 (mtime, atime)
                    os.utime(final_p, (stat_orig.st_atime, stat_orig.st_mtime))

                    # 촬영 일시 기반 OS 생성일시(birthtime) 동기화
                    dt = item.get("taken_at")
                    if dt:
                        if isinstance(dt, str):
                            try:
                                dt = datetime.fromisoformat(dt.replace("T", " "))
                            except Exception:
                                dt = None
                        if dt and isinstance(dt, datetime):
                            OsDateSync.sync_file_time(final_p, dt)

                    m_id = item.get("id") or item.get("media_id")
                    if m_id:
                        db_updates.append((str(final_p), final_p.name, m_id))

                    result.success_count += 1

                except Exception as e:
                    logger.error("파일명 변경 실패 [%s -> %s]: %s", curr_p.name, final_p.name, e)
                    result.failed_count += 1
                    result.errors.append(f"변경 실패: {curr_p.name} -> {e}")
                    result.failed_details.append(
                        BatchRenameFailureDetail(
                            file_name=curr_p.name,
                            relative_path=rel_p,
                            status="FAILED",
                            reason=f"변경 오류 ({e})",
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

                remaining = total_count - processed
                eta = (remaining / current_speed) if current_speed > 0 else 0.0

                if progress_callback:
                    progress_callback(processed, total_count, final_p.name, current_speed, eta)

            # 3. DB 트랜잭션 동기화 (성공 건 UPDATE, 부재 건 DELETE)
            if db_updates or missing_media_ids:
                if progress_callback:
                    progress_callback(total_count, total_count, "데이터베이스에 새 파일명 및 누락 레코드 동기화 중...", current_speed, 0.0)
                try:
                    self._update_db_records(db_updates, missing_media_ids)
                except Exception as e:
                    logger.error("파일명 DB 일괄 업데이트 실패: %s", e)
                    result.errors.append(f"DB 업데이트 실패: {e}")
                    raise RuntimeError(f"데이터베이스 파일명 갱신에 실패했습니다: {e}") from e

        result.elapsed_seconds = round(time.time() - start_time, 2)
        logger.info(
            "파일명 일괄 변경 완료: 성공=%d, 정리=%d, 실패=%d, 소요시간=%.2f초",
            result.success_count, result.cleaned_missing_count, result.failed_count, result.elapsed_seconds
        )
        return result

    def _update_db_records(
        self,
        updates: List[Tuple[str, str, int]],
        missing_ids: List[int],
    ) -> None:
        """
        media_files 테이블의 file_path, file_name을 갱신하고,
        존재하지 않는 누락 레코드를 안전하게 삭제합니다.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. 파일명 및 경로 UPDATE
        if updates:
            cursor.executemany(
                """
                UPDATE media_files
                SET file_path = ?, file_name = ?
                WHERE id = ?
                """,
                updates,
            )

        # 2. 존재하지 않는 누락 레코드 DELETE
        if missing_ids:
            chunk_size = 500
            for i in range(0, len(missing_ids), chunk_size):
                chunk = missing_ids[i:i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                cursor.execute(f"DELETE FROM metadata WHERE media_id IN ({placeholders});", chunk)
                cursor.execute(f"DELETE FROM media_files WHERE id IN ({placeholders});", chunk)
            logger.info("부재 파일 DB 레코드 %d건 자동 정리 완료", len(missing_ids))

        conn.commit()
