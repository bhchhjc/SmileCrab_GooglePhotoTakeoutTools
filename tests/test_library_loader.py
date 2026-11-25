"""
tests/test_library_loader.py
────────────────────────────────────────────────────────────────
LibraryLoaderWorker 비동기 쿼리 및 그룹핑 단위 테스트
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QCoreApplication

from src.core.models import MediaFile, MediaMetadata, MediaType
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.ui.workers import LibraryLoaderWorker


class TestLibraryLoaderWorker(unittest.TestCase):
    def setUp(self):
        self._app = QCoreApplication.instance() or QCoreApplication([])
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

        self.db = DatabaseManager(self.db_path)
        self.db.initialize()
        self.repo = MediaRepository(self.db)

        # 더미 파일 3개 생성
        self.f1 = Path(self.temp_dir) / "img1.jpg"
        self.f2 = Path(self.temp_dir) / "img2.jpg"
        self.f3 = Path(self.temp_dir) / "img3.jpg"
        for f in (self.f1, self.f2, self.f3):
            f.write_bytes(b"dummy image data")

        m1 = MediaFile(path=self.f1, normalized_name="img1.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=16)
        meta1 = MediaMetadata(title="img1.jpg", photo_taken_time=datetime(2023, 8, 15, 10, 0, 0, tzinfo=timezone.utc), camera_make="Samsung", camera_model="Galaxy S23")
        self.repo.insert_media(self.f1, self.f1, "hash1", m1, meta1)

        m2 = MediaFile(path=self.f2, normalized_name="img2.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=16)
        meta2 = MediaMetadata(title="img2.jpg", photo_taken_time=datetime(2023, 8, 15, 11, 0, 0, tzinfo=timezone.utc), camera_make="Samsung", camera_model="Galaxy S23")
        self.repo.insert_media(self.f2, self.f2, "hash2", m2, meta2)

        m3 = MediaFile(path=self.f3, normalized_name="img3.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=16)
        meta3 = MediaMetadata(title="img3.jpg", photo_taken_time=datetime(2022, 5, 1, 12, 0, 0, tzinfo=timezone.utc), camera_make="Apple", camera_model="iPhone 14 Pro")
        self.repo.insert_media(self.f3, self.f3, "hash3", m3, meta3)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_worker_run_and_grouping(self):
        # 1. 가나다순(기본값) 검증: Apple iPhone 14 Pro가 Samsung Galaxy S23보다 먼저 정렬
        worker_name = LibraryLoaderWorker(group_by="camera", sort_by="name", db_path=self.db_path)
        received_name = {}
        worker_name.signals.finished.connect(lambda g, v, t: received_name.update({"groups": g, "total": t}))
        worker_name.run()

        self.assertEqual(received_name.get("total"), 3)
        groups_name = received_name.get("groups", [])
        self.assertEqual(len(groups_name), 2)
        self.assertIn("Apple iPhone 14 Pro", groups_name[0][0])
        self.assertIn("Samsung Galaxy S23", groups_name[1][0])

        # 2. 건수순(사진 많은 순) 검증: Samsung Galaxy S23 (2개)이 Apple iPhone 14 Pro (1개)보다 우선 정렬
        worker_count = LibraryLoaderWorker(group_by="camera", sort_by="count", db_path=self.db_path)
        received_count = {}
        worker_count.signals.finished.connect(lambda g, v, t: received_count.update({"groups": g, "total": t}))
        worker_count.run()

        groups_count = received_count.get("groups", [])
        self.assertEqual(len(groups_count), 2)
        self.assertIn("Samsung Galaxy S23", groups_count[0][0])
        self.assertEqual(len(groups_count[0][1]["items"]), 2)
        self.assertIn("Apple iPhone 14 Pro", groups_count[1][0])

    def test_location_grouping_unknown_at_bottom(self):
        """위치 정보 없는 항목(No GPS)은 건수와 무관하게 항상 최하단에 배치되는지 검증"""
        # m1, m2는 위치 없음, m3에만 GPS(오스트리아 할슈타트) 부여 (커밋 필수)
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE metadata SET latitude = 47.5622, longitude = 13.6493, "
                "country_name = '오스트리아', city_name = '할슈타트' "
                "WHERE media_id = (SELECT id FROM media_files WHERE file_name = 'img3.jpg')"
            )

        # 1. 가나다순 정렬 시
        worker_name = LibraryLoaderWorker(group_by="location", sort_by="name", db_path=self.db_path)
        res_name = {}
        worker_name.signals.finished.connect(lambda g, v, t: res_name.update({"groups": g}))
        worker_name.run()
        groups_name = res_name["groups"]
        self.assertEqual(len(groups_name), 2)
        self.assertIn("오스트리아", groups_name[0][0])
        self.assertIn("위치 정보 없음", groups_name[1][0])  # 최하단

        # 2. 건수순 정렬 시 (위치 없음이 2개로 더 많아도 최하단에 위치해야 함!)
        worker_count = LibraryLoaderWorker(group_by="location", sort_by="count", db_path=self.db_path)
        res_count = {}
        worker_count.signals.finished.connect(lambda g, v, t: res_count.update({"groups": g}))
        worker_count.run()
        groups_count = res_count["groups"]
        self.assertEqual(len(groups_count), 2)
        self.assertIn("오스트리아", groups_count[0][0])
        self.assertIn("위치 정보 없음", groups_count[1][0])  # 건수가 많아도 최하단!


if __name__ == "__main__":
    unittest.main()
