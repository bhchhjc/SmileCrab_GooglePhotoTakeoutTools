"""
GooglePhotoTakeoutTools - Metadata Matcher
미디어 파일과 Google Takeout JSON 메타데이터를 다단계 휴리스틱 전략으로 매칭하는 엔진
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from .models import MatchResult, MatchType, MediaFile, MediaMetadata
from .parser import JsonParser
from .utils import extract_datetime_from_filename, normalize_unicode

logger = logging.getLogger(__name__)

# 중복 괄호 패턴: 예) IMG_1234(1).jpg -> group(1): IMG_1234, group(2): 1, group(3): .jpg
_BRACKET_REGEX = re.compile(r"^(.*?)(?:\((\d+)\))?(\.[^.]+)$")


class DirectoryMetadataIndex:
    """
    한 디렉토리 내의 모든 JSON 파일 및 미디어 파일들을 사전에 인덱싱하여,
    수천 개의 파일에 대한 반복 디스크 I/O를 방지하고 초고속 매칭을 지원하는 인덱서.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.json_files: Dict[str, Path] = {}            # normalized_filename -> Path
        self.title_to_json: Dict[str, Path] = {}          # JSON 내 title -> Path (Reverse Lookup)
        self.parsed_metadata_cache: Dict[Path, MediaMetadata] = {}

        self._build_index()

    def _build_index(self) -> None:
        """디렉토리 내의 모든 JSON 파일을 스캔하여 인덱스 구축"""
        try:
            for entry in self.directory.iterdir():
                if not entry.is_file():
                    continue

                norm_name = normalize_unicode(entry.name)
                if norm_name.lower().endswith(".json"):
                    self.json_files[norm_name] = entry

                    # 역방향 탐색용 title 필드 사전 파싱
                    meta = JsonParser.parse_file(entry)
                    if meta:
                        self.parsed_metadata_cache[entry] = meta
                        if meta.title:
                            norm_title = normalize_unicode(meta.title)
                            self.title_to_json[norm_title] = entry
        except OSError as e:
            logger.error("디렉토리 인덱싱 실패 [%s]: %s", self.directory, e)

    def get_metadata(self, json_path: Path) -> Optional[MediaMetadata]:
        """캐시된 MediaMetadata 반환 또는 파싱"""
        if json_path in self.parsed_metadata_cache:
            return self.parsed_metadata_cache[json_path]
        meta = JsonParser.parse_file(json_path)
        if meta:
            self.parsed_metadata_cache[json_path] = meta
        return meta


class MetadataMatcher:
    """
    5단계 휴리스틱 체인을 통해 미디어 파일에 대응하는 메타데이터를 매칭하는 엔진
    """

    def __init__(self, index: Optional[DirectoryMetadataIndex] = None):
        self.index = index

    def match(
        self,
        media_file: MediaFile,
        index: Optional[DirectoryMetadataIndex] = None,
        allow_filename_fallback: bool = True,
    ) -> MatchResult:
        """
        단일 MediaFile에 대해 최적의 JSON 메타데이터를 찾아 MatchResult로 반환합니다.
        """
        active_index = index or self.index
        if not active_index:
            active_index = DirectoryMetadataIndex(media_file.path.parent)

        filename = media_file.normalized_name

        # ----------------------------------------------------
        # 1단계: 완전 일치 (Exact Match)
        # ----------------------------------------------------
        # 예: photo.jpg -> photo.jpg.json
        candidate_exact = f"{filename}.json"
        if candidate_exact in active_index.json_files:
            target_json = active_index.json_files[candidate_exact]
            meta = active_index.get_metadata(target_json)
            if meta:
                return MatchResult(media_file, target_json, MatchType.EXACT, meta)

        # 예: photo.jpg -> photo.jpg.supplemental-metadata.json
        candidate_suppl = f"{filename}.supplemental-metadata.json"
        if candidate_suppl in active_index.json_files:
            target_json = active_index.json_files[candidate_suppl]
            meta = active_index.get_metadata(target_json)
            if meta:
                return MatchResult(media_file, target_json, MatchType.SUPPLEMENTAL, meta)

        # ----------------------------------------------------
        # 2단계: 중복 카운터 괄호 매칭 (Bracket Counter Match)
        # ----------------------------------------------------
        # 예: photo(1).jpg <-> photo.jpg(1).json 또는 photo(1).jpg.supplemental-metadata.json 등
        bracket_match = _BRACKET_REGEX.match(filename)
        if bracket_match:
            stem, counter, ext = bracket_match.groups()
            if counter:
                bracket_candidates = [
                    f"{stem}{ext}({counter}).json",
                    f"{stem}{ext}({counter}).supplemental-metadata.json",
                    f"{stem}{ext}.supplemental-metadata({counter}).json",
                    f"{stem}({counter}){ext}.json",
                    f"{stem}({counter}){ext}.supplemental-metadata.json",
                ]
                for cand in bracket_candidates:
                    norm_cand = normalize_unicode(cand)
                    if norm_cand in active_index.json_files:
                        target_json = active_index.json_files[norm_cand]
                        meta = active_index.get_metadata(target_json)
                        if meta:
                            return MatchResult(media_file, target_json, MatchType.BRACKET_COUNTER, meta)

        # ----------------------------------------------------
        # 3단계: 편집본/수정본 접미사 제거 매칭 (Edited Match)
        # ----------------------------------------------------
        # 예: photo-수정됨.jpg 또는 photo-edited.jpg -> 원본 photo.jpg의 JSON 매칭
        if media_file.is_edited_version:
            original_stem = media_file.path.stem
            for suffix in ["-edited", "-수정됨"]:
                if original_stem.endswith(suffix):
                    original_filename = normalize_unicode(original_stem[:-len(suffix)] + media_file.extension)
                    # 원본 파일명으로 1~2단계 후보군 검색
                    for orig_cand in [
                        f"{original_filename}.supplemental-metadata.json",
                        f"{original_filename}.json",
                    ]:
                        if orig_cand in active_index.json_files:
                            target_json = active_index.json_files[orig_cand]
                            meta = active_index.get_metadata(target_json)
                            if meta:
                                return MatchResult(media_file, target_json, MatchType.EDITED_ORIGINAL, meta)

        # ----------------------------------------------------
        # 4단계: 역방향 제목 조회 (Reverse Title Lookup)
        # ----------------------------------------------------
        # JSON 내부의 "title" 필드가 미디어 파일명(또는 수정본의 원본명)과 일치하는지 확인
        if filename in active_index.title_to_json:
            target_json = active_index.title_to_json[filename]
            meta = active_index.get_metadata(target_json)
            if meta:
                return MatchResult(media_file, target_json, MatchType.REVERSE_TITLE_LOOKUP, meta)

        # 편집본인 경우 원본 제목으로 역방향 조회
        if media_file.is_edited_version:
            orig_stem = media_file.path.stem
            for suffix in ["-edited", "-수정됨"]:
                if orig_stem.endswith(suffix):
                    orig_name = normalize_unicode(orig_stem[:-len(suffix)] + media_file.extension)
                    if orig_name in active_index.title_to_json:
                        target_json = active_index.title_to_json[orig_name]
                        meta = active_index.get_metadata(target_json)
                        if meta:
                            return MatchResult(media_file, target_json, MatchType.REVERSE_TITLE_LOOKUP, meta)

        # ----------------------------------------------------
        # 5단계: 파일명 잘림 접두사 퍼지 매칭 (Truncated Prefix Match)
        # ----------------------------------------------------
        # 예: 20150530_174017-COLLAGE.jpg.supplemental-metad.json (51자 잘림)
        # 미디어 파일명 전체가 JSON 파일명의 시작 부분과 일치하는 JSON 탐색
        prefix = f"{filename}."
        for json_name, target_json in active_index.json_files.items():
            if json_name.startswith(prefix) and (
                "supplemental" in json_name or "suppl" in json_name or json_name.endswith(".json")
            ):
                meta = active_index.get_metadata(target_json)
                if meta:
                    return MatchResult(media_file, target_json, MatchType.TRUNCATED_PREFIX, meta)

        # ----------------------------------------------------
        # 6단계: Fallback - 파일명 날짜 정규식 파싱 (허용된 경우에만)
        # ----------------------------------------------------
        if allow_filename_fallback:
            extracted_dt = extract_datetime_from_filename(filename)
            if extracted_dt:
                fallback_meta = MediaMetadata(
                    title=filename,
                    photo_taken_time=extracted_dt,
                    photo_taken_timestamp=int(extracted_dt.timestamp()),
                )
                return MatchResult(media_file, None, MatchType.FALLBACK_FILENAME, fallback_meta)

        # 모든 전략 실패
        return MatchResult(media_file, None, MatchType.NONE, None)
