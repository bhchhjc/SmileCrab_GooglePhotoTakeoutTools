"""
GooglePhotoTakeoutTools - Core Utilities
유니코드 정규화(NFC), 날짜 추출 헬퍼 등
"""

import re
import unicodedata
from datetime import datetime
from typing import Any, Optional


def normalize_unicode(text: Any) -> str:
    """
    macOS의 NFD(자소 분리) 문자열을 표준 NFC로 통일 정규화합니다.
    크로스플랫폼(Mac/Windows) 파일 비교 및 검색 시 필수적인 함수입니다.
    문자열 외(list, None 등)가 전달되어도 안전하게 문자열로 변환합니다.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        if isinstance(text, (list, tuple)):
            text = " ".join(str(item) for item in text if item is not None)
        else:
            text = str(text)
    return unicodedata.normalize("NFC", text)


# 카메라/스마트폰 표준 파일명 날짜 패턴들
_FILENAME_DATE_PATTERNS = [
    # YYYYMMDD_HHMMSS (예: IMG_20230515_123045.jpg, 20230102_084127.jpg)
    re.compile(r"(?:IMG_|VID_|PXL_)?(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})"),
    # YYYY-MM-DD-HH-MM-SS 또는 YYYY-MM-DD_HH-MM-SS (스크린샷 등)
    re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})"),
    # YYYYMMDD (시간 없음)
    re.compile(r"(?:IMG_|VID_|PXL_)?(\d{4})(\d{2})(\d{2})"),
]


def extract_datetime_from_filename(filename: str) -> Optional[datetime]:
    """
    파일명에 포함된 날짜/시간 패턴을 정규식으로 파싱하여 datetime 객체로 반환합니다.
    JSON 메타데이터가 유실된 경우를 대비한 2차 Fallback 전략으로 사용됩니다.
    """
    norm_name = normalize_unicode(filename)
    
    for pattern in _FILENAME_DATE_PATTERNS:
        match = pattern.search(norm_name)
        if match:
            groups = match.groups()
            try:
                if len(groups) == 6:
                    year, month, day, hour, minute, second = map(int, groups)
                    return datetime(year, month, day, hour, minute, second)
                elif len(groups) == 3:
                    year, month, day = map(int, groups)
                    return datetime(year, month, day, 12, 0, 0)
            except (ValueError, OverflowError):
                continue
    return None
