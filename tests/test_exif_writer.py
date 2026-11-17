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
