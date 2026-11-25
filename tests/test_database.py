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
            camera_make="Apple",
            camera_model="iPhone 13 Pro",
            country_code="KR",
            country_name="대한민국",
            city_name="제주",
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
        self.assertEqual(results[0]["camera_model"], "iPhone 13 Pro")
        self.assertEqual(results[0]["country_name"], "대한민국")
        self.assertEqual(results[0]["city_name"], "제주")

        # 2-1. 카메라 기종 키워드 검색 ("iPhone")
        results_cam = self.repo.search_media(keyword="iPhone")
        self.assertEqual(len(results_cam), 1)
        self.assertEqual(results_cam[0]["camera_make"], "Apple")

        # 3. 연도 필터 (2023)
        res_year = self.repo.search_media(year=2023)
        self.assertEqual(len(res_year), 1)

        # 4. 연도 필터 (2022 - 없음)
        res_empty = self.repo.search_media(year=2022)
        self.assertEqual(len(res_empty), 0)

    def test_reset_database(self):
        # 1. 미디어 등록
        media_file = MediaFile(
            path=Path("/tmp/sample2.jpg"),
            normalized_name="sample2.jpg",
            extension=".jpg",
            media_type=MediaType.PHOTO,
            file_size=1024,
        )
        self.repo.insert_media(
            final_path=Path("/dest/sample2.jpg"),
            original_path=Path("/tmp/sample2.jpg"),
            file_hash="hash_to_reset",
            media_file=media_file,
        )
        self.assertIsNotNone(self.repo.find_by_hash("hash_to_reset"))
        info = self.db_mgr.get_storage_info()
        self.assertGreaterEqual(info["total_records"], 1)

        # 2. 초기화 실행
        ok = self.db_mgr.reset_database()
        self.assertTrue(ok)

        # 3. 데이터 검증 (0건 확인)
        self.assertIsNone(self.repo.find_by_hash("hash_to_reset"))
        info_after = self.db_mgr.get_storage_info()
        self.assertEqual(info_after["total_records"], 0)

    def test_job_history_record_and_summary(self):
        # 1. 1회 실행 세션 기록
        job_id = self.db_mgr.record_job_history(
            source_dir="/Users/test/Takeout",
            target_dir="/Users/test/Organized",
            total_files=10000,
            processed_count=9800,
            skipped_duplicate=180,
            failed_count=20,
            photo_count=9000,
            video_count=800,
            total_bytes=104857600,
            status="COMPLETED",
        )
        self.assertGreater(job_id, 0)

        # 2. 이력 요약 조회
        history = self.db_mgr.get_history_summary()
        self.assertEqual(len(history), 1)
        item = history[0]
        self.assertEqual(item["source_dir"], "/Users/test/Takeout")
        self.assertEqual(item["target_dir"], "/Users/test/Organized")
        self.assertEqual(item["count"], 9800)
        self.assertIn("사진 9000개", item["media_types"])
        self.assertIn("동영상 800개", item["media_types"])
        self.assertEqual(item["total_size"], 104857600)
        self.assertEqual(item["status"], "COMPLETED")

        # 3. reset_database 호출 시 job_history도 깨끗이 초기화되는지 확인
        self.db_mgr.reset_database()
        self.assertEqual(len(self.db_mgr.get_history_summary()), 0)


if __name__ == "__main__":
    unittest.main()
