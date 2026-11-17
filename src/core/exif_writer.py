"""
GooglePhotoTakeoutTools - EXIF Writer
사진 파일(JPEG 등)에 촬영 일시, GPS 좌표, 설명(캡션) EXIF 메타데이터를 주입하는 엔진
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import piexif
from PIL import Image

from .models import GeoLocation, MediaMetadata

logger = logging.getLogger(__name__)


def _to_rational(value: float, precision: int = 100) -> Tuple[int, int]:
    """실수값을 (분자, 분모) 정수 튜플로 변환"""
    return int(round(value * precision)), precision


def _decimal_to_dms(deg: float) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """
    10진수 위도/경도를 EXIF GPS 표준 규격인 (도, 분, 초) Rational 튜플로 변환합니다.
    예: 33.3617 -> ((33, 1), (21, 1), (4212, 100))
    """
    abs_deg = abs(deg)
    d = int(abs_deg)
    m_float = (abs_deg - d) * 60.0
    m = int(m_float)
    s_float = (m_float - m) * 60.0

    return ((d, 1), (m, 1), _to_rational(s_float, 1000))


class ExifWriter:
    """
    사진 파일에 MediaMetadata를 안전하게 주입/병합하는 클래스.
    기존 EXIF가 있을 경우 카메라 기종 등 원본 정보를 최대한 보존하면서
    누락된 날짜/GPS/설명 태그를 보강합니다.
    """

    @classmethod
    def inject_metadata(cls, image_path: Path, metadata: MediaMetadata) -> bool:
        """
        image_path 파일에 metadata(촬영일시, GPS, 설명)를 주입합니다.
        지원 포맷: JPEG (.jpg, .jpeg)
        """
        ext = image_path.suffix.lower()
        if ext not in (".jpg", ".jpeg"):
            # JPEG 이외의 포맷(HEIC, PNG 등)은 piexif 단독으로 안전한 재인코딩 없는 주입이 제한되므로
            # 추후 확장 모듈에서 처리하거나 OS 파일 날짜 동기화로 우선 보정
            return False

        try:
            # 1. 기존 EXIF 로드 시도 (없거나 깨진 경우 빈 구조체 생성)
            try:
                exif_dict = piexif.load(str(image_path))
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

            if not isinstance(exif_dict, dict):
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

            for key in ["0th", "Exif", "GPS", "1st"]:
                if key not in exif_dict or not isinstance(exif_dict[key], dict):
                    exif_dict[key] = {}

            modified = False

            # 2. 촬영 일시 (DateTimeOriginal, DateTimeDigitized) 주입
            target_dt = metadata.best_datetime
            if target_dt:
                exif_date_str = target_dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii")
                exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_date_str
                exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_date_str
                exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_date_str
                modified = True

            # 3. 설명 (ImageDescription) 주입
            if metadata.description:
                desc_bytes = metadata.description.encode("utf-8")
                exif_dict["0th"][piexif.ImageIFD.ImageDescription] = desc_bytes
                modified = True

            # 4. GPS 위치 정보 주입
            if metadata.geo_data and metadata.geo_data.has_valid_coordinates:
                lat = metadata.geo_data.latitude
                lon = metadata.geo_data.longitude
                alt = metadata.geo_data.altitude

                # 위도 (Latitude)
                lat_ref = b"N" if lat >= 0 else b"S"
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = _decimal_to_dms(lat)

                # 경도 (Longitude)
                lon_ref = b"E" if lon >= 0 else b"W"
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _decimal_to_dms(lon)

                # 고도 (Altitude)
                alt_ref = 0 if alt >= 0 else 1
                exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef] = alt_ref
                exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = _to_rational(abs(alt), 100)

                # GPS 버전 (2.3.0.0)
                exif_dict["GPS"][piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)
                modified = True

            if modified:
                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, str(image_path))
                return True

            return False

        except Exception as e:
            logger.warning("EXIF 주입 실패 [%s]: %s", image_path, e)
            return False
