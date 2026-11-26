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


def _rational_to_float(val: Any) -> float:
    """EXIF Rational((num, den) 또는 IFDRational/float)을 float으로 안전하게 변환"""
    try:
        if isinstance(val, tuple) and len(val) == 2:
            num, den = val
            return float(num) / float(den) if den else 0.0
        return float(val)
    except Exception:
        return 0.0


def _dms_to_decimal(dms: Any, ref: Any) -> float:
    """EXIF GPS DMS 튜플과 방위(N/S/E/W)를 10진수 좌표로 변환"""
    try:
        if not isinstance(dms, (tuple, list)) or len(dms) != 3:
            return 0.0
        d = _rational_to_float(dms[0])
        m = _rational_to_float(dms[1])
        s = _rational_to_float(dms[2])
        decimal = d + (m / 60.0) + (s / 3600.0)

        if isinstance(ref, bytes):
            ref_str = ref.decode("ascii", "ignore").strip("\x00 ").upper()
        else:
            ref_str = str(ref or "").strip("\x00 ").upper()

        if ref_str in ("S", "W"):
            decimal = -abs(decimal)
        return decimal
    except Exception:
        return 0.0


def _decode_exif_str(raw: Any) -> str:
    """EXIF bytes/str 값을 UTF-8 문자열로 안전하게 디코딩"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "ignore").strip("\x00 \t\r\n")
    return str(raw).strip("\x00 \t\r\n")


def _parse_exif_datetime(raw: Any) -> Optional[datetime]:
    """EXIF 날짜 문자열(YYYY:MM:DD HH:MM:SS 등)을 datetime으로 파싱"""
    text = _decode_exif_str(raw)
    if not text or text.startswith("0000:00:00"):
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
            if 1970 <= dt.year <= 2100:
                return dt
        except ValueError:
            continue
    return None


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

    @classmethod
    def update_metadata_fields(
        cls,
        image_path: Path,
        taken_at: Optional[datetime] = None,
        latitude: float = 0.0,
        longitude: float = 0.0,
        altitude: float = 0.0,
        description: str = "",
        camera_make: str = "",
        camera_model: str = "",
    ) -> Tuple[bool, str]:
        """
        사용자 편집/초기화 시 JPEG 파일의 EXIF 태그를 일괄 갱신하거나 빈 값은 제거합니다.
        반환: (성공 여부, 상태 메시지)
        """
        if not image_path.exists() or not image_path.is_file():
            return False, "file_not_found"

        if image_path.suffix.lower() not in (".jpg", ".jpeg"):
            return False, "unsupported_format"

        try:
            try:
                exif_dict = piexif.load(str(image_path))
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

            if not isinstance(exif_dict, dict):
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

            for key in ("0th", "Exif", "GPS", "1st"):
                if key not in exif_dict or not isinstance(exif_dict[key], dict):
                    exif_dict[key] = {}

            # 1. 촬영 일시
            if taken_at is not None:
                exif_date_str = taken_at.strftime("%Y:%m:%d %H:%M:%S").encode("ascii")
                exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_date_str
                exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_date_str
                exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_date_str
            else:
                exif_dict["Exif"].pop(piexif.ExifIFD.DateTimeOriginal, None)
                exif_dict["Exif"].pop(piexif.ExifIFD.DateTimeDigitized, None)
                exif_dict["0th"].pop(piexif.ImageIFD.DateTime, None)

            # 2. 설명 / 캡션
            desc_clean = (description or "").strip()
            if desc_clean:
                exif_dict["0th"][piexif.ImageIFD.ImageDescription] = desc_clean.encode("utf-8")
            else:
                exif_dict["0th"].pop(piexif.ImageIFD.ImageDescription, None)

            # 3. GPS 좌표
            if latitude != 0.0 or longitude != 0.0:
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N" if latitude >= 0 else b"S"
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = _decimal_to_dms(latitude)
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = b"E" if longitude >= 0 else b"W"
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _decimal_to_dms(longitude)
                exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef] = 0 if altitude >= 0 else 1
                exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = _to_rational(abs(altitude), 100)
                exif_dict["GPS"][piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)
            else:
                exif_dict["GPS"] = {}

            # 4. 촬영 기기 (Make / Model)
            make_clean = (camera_make or "").strip()
            model_clean = (camera_model or "").strip()
            if make_clean:
                exif_dict["0th"][piexif.ImageIFD.Make] = make_clean.encode("utf-8")
            else:
                exif_dict["0th"].pop(piexif.ImageIFD.Make, None)

            if model_clean:
                exif_dict["0th"][piexif.ImageIFD.Model] = model_clean.encode("utf-8")
            else:
                exif_dict["0th"].pop(piexif.ImageIFD.Model, None)

            exif_bytes = _dump_exif_safely(exif_dict)
            piexif.insert(exif_bytes, str(image_path))
            return True, "ok"

        except Exception as exc:
            logger.warning("EXIF 일괄 갱신 실패 [%s]: %s", image_path, exc)
            return False, f"error: {exc}"

    @staticmethod
    def extract_camera_info(image_path: Path) -> Tuple[str, str]:
        """
        사진 파일(JPEG 등)로부터 카메라 제조사(Make) 및 모델명(Model)을 안전하게 추출합니다.
        
        반환:
            (camera_make, camera_model) 튜플 (정보 없을 경우 빈 문자열 반환)
        """
        meta = ExifWriter.extract_metadata(image_path)
        return meta.camera_make, meta.camera_model

    @staticmethod
    def extract_metadata(image_path: Path) -> MediaMetadata:
        """
        원본/최종 이미지 파일에서 EXIF 촬영 일시, GPS 좌표/고도, 설명, 카메라 정보를
        통합 추출하여 MediaMetadata 객체로 반환합니다.
        """
        meta = MediaMetadata()
        if not image_path.exists() or not image_path.is_file():
            return meta

        # 1. piexif 기반 정밀 추출 시도
        try:
            exif_dict = piexif.load(str(image_path))
            if isinstance(exif_dict, dict):
                zeroth = exif_dict.get("0th", {}) or {}
                exif_ifd = exif_dict.get("Exif", {}) or {}
                gps_ifd = exif_dict.get("GPS", {}) or {}

                # 카메라 제조사 / 모델 / 설명
                meta.camera_make = _decode_exif_str(zeroth.get(piexif.ImageIFD.Make))
                meta.camera_model = _decode_exif_str(zeroth.get(piexif.ImageIFD.Model))
                meta.description = _decode_exif_str(zeroth.get(piexif.ImageIFD.ImageDescription))

                # 촬영 일시 (DateTimeOriginal -> DateTimeDigitized -> DateTime)
                for dt_raw in (
                    exif_ifd.get(piexif.ExifIFD.DateTimeOriginal),
                    exif_ifd.get(piexif.ExifIFD.DateTimeDigitized),
                    zeroth.get(piexif.ImageIFD.DateTime),
                ):
                    dt = _parse_exif_datetime(dt_raw)
                    if dt:
                        meta.photo_taken_time = dt
                        meta.photo_taken_timestamp = int(dt.timestamp())
                        break

                # GPS 좌표 / 고도
                lat = _dms_to_decimal(
                    gps_ifd.get(piexif.GPSIFD.GPSLatitude),
                    gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef),
                )
                lon = _dms_to_decimal(
                    gps_ifd.get(piexif.GPSIFD.GPSLongitude),
                    gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef),
                )
                alt = _rational_to_float(gps_ifd.get(piexif.GPSIFD.GPSAltitude))
                if gps_ifd.get(piexif.GPSIFD.GPSAltitudeRef) == 1:
                    alt = -abs(alt)

                if lat != 0.0 or lon != 0.0:
                    meta.geo_data = GeoLocation(latitude=lat, longitude=lon, altitude=alt)

                return meta
        except Exception:
            pass

        # 2. Pillow getexif 폴백 (HEIC/TIFF 등 비JPEG 포맷 대응)
        try:
            with Image.open(image_path) as img:
                exif = img.getexif()
                if exif:
                    meta.camera_make = _decode_exif_str(exif.get(271))
                    meta.camera_model = _decode_exif_str(exif.get(272))
                    meta.description = _decode_exif_str(exif.get(270))

                    for tag_id in (36867, 36868, 306):
                        dt = _parse_exif_datetime(exif.get(tag_id))
                        if dt:
                            meta.photo_taken_time = dt
                            meta.photo_taken_timestamp = int(dt.timestamp())
                            break

                    # GPS IFD (0x8825 = 34853)
                    if hasattr(exif, "get_ifd"):
                        gps_ifd = exif.get_ifd(34853) or {}
                        lat = _dms_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
                        lon = _dms_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
                        alt = _rational_to_float(gps_ifd.get(6))
                        if gps_ifd.get(5) == 1:
                            alt = -abs(alt)
                        if lat != 0.0 or lon != 0.0:
                            meta.geo_data = GeoLocation(latitude=lat, longitude=lon, altitude=alt)
        except Exception:
            pass

        return meta
