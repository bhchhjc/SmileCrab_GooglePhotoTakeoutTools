"""
GooglePhotoTakeoutTools - EXIF Writer
사진 파일(JPEG 등)에 촬영 일시, GPS 좌표, 설명(캡션) EXIF 메타데이터를 주입하는 엔진
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import piexif
from PIL import Image

from .models import GeoLocation, MediaMetadata

logger = logging.getLogger(__name__)


def _sanitize_exif_dict(exif_dict: Dict[str, Any]) -> None:
    """
    스마트폰(삼성 갤럭시 등) 카메라나 타 소프트웨어에서 EXIF 표준 규격(Undefined 타입)과
    다르게 잘못 int 또는 str 등으로 기록해 둔 비표준 태그들을 표준 바이트로 정제합니다.
    """
    if not isinstance(exif_dict, dict):
        return

    exif_ifd = exif_dict.get("Exif")
    if isinstance(exif_ifd, dict):
        # 41729: SceneType (Undefined, expects bytes e.g. b'\x01')
        if 41729 in exif_ifd and isinstance(exif_ifd[41729], int):
            try:
                exif_ifd[41729] = bytes([exif_ifd[41729]])
            except Exception:
                del exif_ifd[41729]

        # 41728: FileSource (Undefined, expects bytes e.g. b'\x03')
        if 41728 in exif_ifd and isinstance(exif_ifd[41728], int):
            try:
                exif_ifd[41728] = bytes([exif_ifd[41728]])
            except Exception:
                del exif_ifd[41728]

        # 37121: ComponentsConfiguration (Undefined, expects bytes)
        if 37121 in exif_ifd and isinstance(exif_ifd[37121], int):
            try:
                exif_ifd[37121] = bytes([exif_ifd[37121]])
            except Exception:
                del exif_ifd[37121]

        # 37510: UserComment (Undefined, string -> ascii/utf-8 bytes)
        if 37510 in exif_ifd and isinstance(exif_ifd[37510], str):
            exif_ifd[37510] = b"ASCII\x00\x00\x00" + exif_ifd[37510].encode("utf-8", "ignore")

        # 36864: ExifVersion (Undefined, str/int -> 4-byte bytes e.g. b"0230")
        if 36864 in exif_ifd and not isinstance(exif_ifd[36864], (bytes, bytearray)):
            try:
                exif_ifd[36864] = str(exif_ifd[36864]).encode("ascii")
            except Exception:
                del exif_ifd[36864]


def _dump_exif_safely(exif_dict: Dict[str, Any]) -> bytes:
    """
    piexif.dump()를 안전하게 실행하며, 비표준 타입 태그나 썸네일 용량 초과 발생 시
    자동으로 태그를 교정/제거하고 단계적으로 복구 재시도합니다.
    """
    _sanitize_exif_dict(exif_dict)

    max_retries = 10
    for attempt in range(max_retries):
        try:
            return piexif.dump(exif_dict)
        except ValueError as ve:
            err_msg = str(ve)

            # 1. 썸네일 64KB 초과 에러 시 썸네일 제거 후 재시도
            if "thumbnail" in err_msg.lower() or "too large" in err_msg.lower():
                if exif_dict.get("thumbnail") is not None:
                    exif_dict["thumbnail"] = None
                    continue

            # 2. 특정 태그 타입 불일치 에러 시 해당 태그 안전 제거 후 재시도
            # e.g. "41729 in Exif IFD. Got as <class 'int'>"
            match = re.search(r"(\d+)\s+in\s+(\w+)\s+IFD", err_msg)
            if match:
                tag_id = int(match.group(1))
                ifd_name = match.group(2)
                if ifd_name in exif_dict and isinstance(exif_dict[ifd_name], dict) and tag_id in exif_dict[ifd_name]:
                    logger.debug("비표준 EXIF 태그 자동 제거 후 재시도: IFD=%s, Tag=%d", ifd_name, tag_id)
                    del exif_dict[ifd_name][tag_id]
                    continue

            # 3. 추가 복구 불가 시 마지막 시도로 필수 메타데이터만 남겨 덤프 시도
            if attempt == max_retries - 1:
                raise
            raise


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
                exif_bytes = _dump_exif_safely(exif_dict)
                piexif.insert(exif_bytes, str(image_path))
                return True

            return False

        except Exception as e:
            logger.warning("EXIF 주입 실패 [%s]: %s", image_path, e)
            return False

    @staticmethod
    def extract_camera_info(image_path: Path) -> Tuple[str, str]:
        """
        사진 파일(JPEG 등)로부터 카메라 제조사(Make) 및 모델명(Model)을 안전하게 추출합니다.
        
        반환:
            (camera_make, camera_model) 튜플 (정보 없을 경우 빈 문자열 반환)
        """
        if not image_path.exists() or not image_path.is_file():
            return "", ""

        # 1. piexif 기반 빠른 추출 시도
        try:
            exif_dict = piexif.load(str(image_path))
            zeroth = exif_dict.get("0th", {})
            raw_make = zeroth.get(piexif.ImageIFD.Make)
            raw_model = zeroth.get(piexif.ImageIFD.Model)

            make = ""
            if isinstance(raw_make, bytes):
                make = raw_make.decode("utf-8", "ignore").strip("\x00 \t\r\n")
            elif raw_make is not None:
                make = str(raw_make).strip("\x00 \t\r\n")

            model = ""
            if isinstance(raw_model, bytes):
                model = raw_model.decode("utf-8", "ignore").strip("\x00 \t\r\n")
            elif raw_model is not None:
                model = str(raw_model).strip("\x00 \t\r\n")

            if make or model:
                return make, model
        except Exception:
            pass

        # 2. PIL Image._getexif() 폴백 시도 (HEIC/TIFF 등 타 포맷 대응)
        try:
            with Image.open(image_path) as img:
                exif = img._getexif()
                if exif:
                    # Tag 271: Make, Tag 272: Model
                    raw_make = exif.get(271, "")
                    raw_model = exif.get(272, "")

                    make = raw_make.decode("utf-8", "ignore") if isinstance(raw_make, bytes) else str(raw_make or "")
                    model = raw_model.decode("utf-8", "ignore") if isinstance(raw_model, bytes) else str(raw_model or "")

                    make = make.strip("\x00 \t\r\n")
                    model = model.strip("\x00 \t\r\n")
                    if make or model:
                        return make, model
        except Exception:
            pass

        return "", ""
