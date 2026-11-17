"""
Unit tests for DatabaseManager and MediaRepository
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.core.models import GeoLocation, MediaFile, MediaType, MediaMetadata
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository


class TestDatabaseAndRepository(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test_catalog.db"
        self.db_mgr = DatabaseManager(self.db_path)
        self.repo = MediaRepository(self.db_mgr)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_insert_and_find_by_hash(self):
        media_file = MediaFile(
            path=Path("/tmp/sample.jpg"),
            normalized_name="sample.jpg",
            extension=".jpg",
            media_type=MediaType.PHOTO,
            file_size=1024,
        )
        metadata = MediaMetadata(
            title="sample.jpg",
            description="가족 사진",
            photo_taken_time=datetime(2023, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
            photo_taken_timestamp=1684152000,
            geo_data=GeoLocation(latitude=33.3, longitude=126.5),
            people=["홍길동"],
        )

        media_id = self.repo.insert_media(
            final_path=Path("/dest/2023/05/sample.jpg"),
            original_path=Path("/tmp/sample.jpg"),
            file_hash="dummy_sha256_hash",
            media_file=media_file,
            metadata=metadata,
            album_name="2023년 사진",
        )
        self.assertGreater(media_id, 0)

        # 해시 기반 검색
        found = self.repo.find_by_hash("dummy_sha256_hash")
        self.assertIsNotNone(found)
        self.assertEqual(found["file_name"], "sample.jpg")

    def test_search_media(self):
        # 1. 미디어 등록
        media_file = MediaFile(
            path=Path("/tmp/jeju.jpg"),
            normalized_name="jeju.jpg",
            extension=".jpg",
            media_type=MediaType.PHOTO,
            file_size=2048,
        )
        metadata = MediaMetadata(
            title="jeju.jpg",
            description="제주도 해변",
            photo_taken_time=datetime(2023, 7, 20, 15, 30, 0, tzinfo=timezone.utc),
            photo_taken_timestamp=1689867000,
            geo_data=GeoLocation(latitude=33.5, longitude=126.8),
            people=["배현철"],
        )
        self.repo.insert_media(
            final_path=Path("/dest/2023/07/jeju.jpg"),
            original_path=Path("/tmp/jeju.jpg"),
            file_hash="hash_jeju",
            media_file=media_file,
            metadata=metadata,
            album_name="신혼여행",
        )

        # 2. 키워드 검색 ("제주도")
        results = self.repo.search_media(keyword="제주도")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file_name"], "jeju.jpg")

        # 3. 연도 필터 (2023)
        res_year = self.repo.search_media(year=2023)
        self.assertEqual(len(res_year), 1)

        # 4. 연도 필터 (2022 - 없음)
        res_empty = self.repo.search_media(year=2022)
        self.assertEqual(len(res_empty), 0)


if __name__ == "__main__":
    unittest.main()
