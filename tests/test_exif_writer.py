"""
Unit tests for ExifWriter & OsDateSync
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import piexif
from PIL import Image

from src.core.exif_writer import ExifWriter
from src.core.models import GeoLocation, MediaMetadata
from src.core.os_sync import OsDateSync


class TestExifWriterAndOsSync(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_inject_exif_metadata(self):
        # 1. 테스트용 빈 JPEG 이미지 생성
        img_path = self.test_dir / "test.jpg"
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img.save(str(img_path), "JPEG")

        # 2. 메타데이터 구성 (2023-05-15 12:30:45, 제주도 좌표, 캡션)
        target_dt = datetime(2023, 5, 15, 12, 30, 45, tzinfo=timezone.utc)
        meta = MediaMetadata(
            title="test.jpg",
            description="테스트 사진 설명",
            photo_taken_time=target_dt,
            geo_data=GeoLocation(latitude=33.3617, longitude=126.5292, altitude=50.0),
        )

        # 3. 주입 실행
        success = ExifWriter.inject_metadata(img_path, meta)
        self.assertTrue(success)

        # 4. 주입된 EXIF 로드하여 검증
        exif_dict = piexif.load(str(img_path))
        date_orig = exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal].decode("ascii")
        self.assertEqual(date_orig, "2023:05:15 12:30:45")

        desc = exif_dict["0th"][piexif.ImageIFD.ImageDescription].decode("utf-8")
        self.assertEqual(desc, "테스트 사진 설명")

        lat_ref = exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef]
        self.assertEqual(lat_ref, b"N")

    def test_inject_exif_with_nonstandard_tags(self):
        """삼성 갤럭시 등에서 생성되는 비표준 태그(SceneType=1 int)가 있어도 정상 주입되는지 검증"""
        img_path = self.test_dir / "galaxy_sample.jpg"
        img = Image.new("RGB", (100, 100), color=(0, 255, 0))
        img.save(str(img_path), "JPEG")

        # 인위적으로 41729(SceneType), 41728(FileSource)를 int로 주입
        # piexif.dump는 int를 거부하므로 low-level로 바이트를 넣거나 dummy EXIF 구성
        raw_exif = {
            "0th": {},
            "Exif": {
                piexif.ExifIFD.SceneType: b"\x01",  # 바이트 형태 생성 후 파일에 저장
            },
            "GPS": {},
            "1st": {},
            "thumbnail": None,
        }
        piexif.insert(piexif.dump(raw_exif), str(img_path))

        # 이제 piexif.load로 읽어온 딕셔너리에 int 태그를 강제로 심어서 ExifWriter가 잘 처리하는지 검증
        target_dt = datetime(2022, 6, 25, 14, 55, 8, tzinfo=timezone.utc)
        meta = MediaMetadata(
            title="galaxy_sample.jpg",
            description="갤럭시 사진",
            photo_taken_time=target_dt,
        )

        # ExifWriter 실행 (내부에서 비표준 int 태그가 있어도 safe dump로 성공해야 함)
        success = ExifWriter.inject_metadata(img_path, meta)
        self.assertTrue(success)

        # 41729가 int 형태인 mock dict 테스트도 검증
        from src.core.exif_writer import _dump_exif_safely
        faulty_dict = {
            "0th": {},
            "Exif": {
                41729: 1,      # SceneType int
                41728: 3,      # FileSource int
                37500: 99999,  # MakerNote int (알 수 없는 비표준 타입)
            },
            "GPS": {},
            "1st": {},
            "thumbnail": None,
        }
        dumped = _dump_exif_safely(faulty_dict)
        self.assertIsInstance(dumped, bytes)
        self.assertGreater(len(dumped), 0)

    def test_extract_camera_info(self):
        # 카메라 기기 정보가 있는 이미지 생성
        img_path = self.test_dir / "camera_test.jpg"
        img = Image.new("RGB", (50, 50), color=(0, 255, 0))
        img.save(str(img_path), "JPEG")

        exif_dict = {
            "0th": {
                piexif.ImageIFD.Make: b"Samsung\x00",
                piexif.ImageIFD.Model: b"SM-S908N\x00",
            }
        }
        piexif.insert(piexif.dump(exif_dict), str(img_path))

        make, model = ExifWriter.extract_camera_info(img_path)
        self.assertEqual(make, "Samsung")
        self.assertEqual(model, "SM-S908N")

    def test_os_date_sync(self):
        file_path = self.test_dir / "test_file.txt"
        file_path.write_text("sample content")

        target_dt = datetime(2021, 8, 10, 15, 0, 0)
        success = OsDateSync.sync_file_time(file_path, target_dt)
        self.assertTrue(success)

        # mtime 검증
        stat = file_path.stat()
        synced_mtime = datetime.fromtimestamp(stat.st_mtime)
        self.assertEqual(synced_mtime.year, 2021)
        self.assertEqual(synced_mtime.month, 8)
        self.assertEqual(synced_mtime.day, 10)


if __name__ == "__main__":
    unittest.main()
