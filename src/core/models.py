"""
GooglePhotoTakeoutTools - Core Models
미디어 파일 및 메타데이터 표현을 위한 도메인 모델 정의
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional


class MediaType(str, Enum):
    """미디어 유형 열거형"""
    PHOTO = "photo"
    VIDEO = "video"
    UNKNOWN = "unknown"


class MatchType(str, Enum):
    """JSON 메타데이터 매칭 전략 유형"""
    EXACT = "exact"                                  # filename.ext.json 완전 일치
    SUPPLEMENTAL = "supplemental"                    # filename.ext.supplemental-metadata.json 완전 일치
    BRACKET_COUNTER = "bracket_counter"              # filename(1).ext <-> filename.ext(1).json 매칭
    EDITED_ORIGINAL = "edited_original"              # -edited, -수정됨 접미사 제거 후 원본 매칭
    TRUNCATED_PREFIX = "truncated_prefix"            # 46~51자 파일명 잘림 접두사 매칭
    REVERSE_TITLE_LOOKUP = "reverse_title_lookup"    # JSON 내부 'title' 속성 기반 역방향 매칭
    FALLBACK_FILENAME = "fallback_filename"          # 파일명 날짜 정규식 기반 폴백
    NONE = "none"                                    # 매칭 실패 (메타데이터 없음)


@dataclass
class GeoLocation:
    """위치 정보 (GPS) 도메인 모델"""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0

    @property
    def has_valid_coordinates(self) -> bool:
        """위도/경도가 0.0이 아닌 유효한 좌표인지 확인"""
        return not (self.latitude == 0.0 and self.longitude == 0.0)


@dataclass
class MediaMetadata:
    """
    Takeout JSON으로부터 파싱된 통합 메타데이터 모델
    """
    title: str = ""
    description: str = ""
    photo_taken_time: Optional[datetime] = None
    photo_taken_timestamp: int = 0
    creation_time: Optional[datetime] = None
    creation_timestamp: int = 0
    geo_data: GeoLocation = field(default_factory=GeoLocation)
    people: List[str] = field(default_factory=list)
    is_favorited: bool = False
    camera_make: str = ""                    # 촬영 기기 제조사 (예: Apple, Samsung)
    camera_model: str = ""                   # 촬영 기기 모델명 (예: iPhone 13 Pro, SM-S908N)
    country_code: str = ""                   # 역지오코딩 국가 코드 (예: KR, US, JP)
    country_name: str = ""                   # 역지오코딩 국가명 (예: 대한민국, South Korea)
    state_name: str = ""                     # 역지오코딩 주/도명 (예: 경기도, 캘리포니아주, 하부오스트리아주)
    city_name: str = ""                      # 역지오코딩 도시/지역명 (예: 서울, 곡성군, 할슈타트)
    raw_json: dict = field(default_factory=dict)

    @property
    def best_datetime(self) -> Optional[datetime]:
        """가장 신뢰할 수 있는 촬영 일시 반환 (photo_taken_time -> creation_time 순)"""
        return self.photo_taken_time or self.creation_time


@dataclass
class MediaFile:
    """
    디스크 상의 미디어 파일 도메인 모델
    """
    path: Path
    normalized_name: str
    extension: str
    media_type: MediaType
    file_size: int = 0
    is_edited_version: bool = False  # -edited 또는 -수정됨 여부

    @classmethod
    def from_path(cls, path: Path) -> "MediaFile":
        """파일 경로로부터 MediaFile 인스턴스를 안전하게 생성"""
        from .utils import normalize_unicode
        
        norm_name = normalize_unicode(path.name)
        ext = path.suffix.lower()
        
        # 대표적인 사진/비디오 확장자 판별
        photo_exts = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp", ".tiff", ".dng"}
        video_exts = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".mts", ".m2ts"}
        
        if ext in photo_exts:
            media_type = MediaType.PHOTO
        elif ext in video_exts:
            media_type = MediaType.VIDEO
        else:
            media_type = MediaType.UNKNOWN

        # 편집본 접미사(-edited, -수정됨) 감지
        stem = path.stem
        is_edited = stem.endswith("-edited") or stem.endswith("-수정됨")

        file_size = 0
        try:
            file_size = path.stat().st_size
        except OSError:
            pass

        return cls(
            path=path,
            normalized_name=norm_name,
            extension=ext,
            media_type=media_type,
            file_size=file_size,
            is_edited_version=is_edited
        )


@dataclass
class MatchResult:
    """
    미디어 파일과 JSON 메타데이터 간의 최종 매칭 결과
    """
    media_file: MediaFile
    json_path: Optional[Path] = None
    match_type: MatchType = MatchType.NONE
    metadata: Optional[MediaMetadata] = None

    @property
    def is_matched(self) -> bool:
        """메타데이터 매칭 성공 여부"""
        return self.metadata is not None
