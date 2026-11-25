"""
tests/test_reorganize_service.py
────────────────────────────────────────────────────────────────
폴더 구조 재구성(ReorganizeService) 및 전원 관리(SleepInhibitor) 단위 테스트
"""

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from src.core.power_management import SleepInhibitor
from src.data.database import DatabaseManager
from src.services.process_service import FolderStrategy
from src.services.reorganize_service import ReorganizeItem, ReorganizeService


class TestReorganizeService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.source_dir = (Path(self.temp_dir) / "output").resolve()
        self.source_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = Path(self.temp_dir) / "test.db"
        self.db_manager = DatabaseManager(self.db_path)
        self.db_manager.initialize()
        self.service = ReorganizeService(self.db_manager)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sleep_inhibitor_context_manager(self):
        """SleepInhibitor의 정상 진입 및 안전 해제 검증"""
        inhibitor = SleepInhibitor("단위 테스트")
        self.assertFalse(inhibitor.is_active)

        with inhibitor:
            self.assertTrue(inhibitor.is_active)

        self.assertFalse(inhibitor.is_active)

    def test_reorganize_in_place_preserves_timestamp_and_cleans_empty_dirs(self):
        """제자리 재구성: 타임스탬프 무손실 보존, 빈 폴더 청소, DB 갱신 검증"""
        # 1. 기존 폴더 구조 생성: 2023/07/photo1.jpg, 2023/08/photo2.jpg
        old_folder1 = self.source_dir / "2023" / "07"
        old_folder2 = self.source_dir / "2023" / "08"
        old_folder1.mkdir(parents=True, exist_ok=True)
        old_folder2.mkdir(parents=True, exist_ok=True)

        f1 = old_folder1 / "photo1.jpg"
        f2 = old_folder2 / "photo2.jpg"
        f1.write_bytes(b"image data 1")
        f2.write_bytes(b"image data 2")

        # 특정 타임스탬프 부여 (2023-07-15 10:00:00)
        target_ts = datetime(2023, 7, 15, 10, 0, 0).timestamp()
        os.utime(f1, (target_ts, target_ts))

        # 2. DB에 기록 추가
        conn = self.db_manager.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO media_files (file_path, file_name, file_ext, media_type, album_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(f1), "photo1.jpg", "jpg", "photo", "Summer 2023")
        )
        id1 = cur.lastrowid
        cur.execute(
            """
            INSERT INTO metadata (media_id, taken_at, camera_make, camera_model, country_name, city_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (id1, "2023-07-15 10:00:00", "Apple", "iPhone 13", "대한민국", "인천")
        )

        cur.execute(
            """
            INSERT INTO media_files (file_path, file_name, file_ext, media_type, album_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(f2), "photo2.jpg", "jpg", "photo", "Summer 2023")
        )
        id2 = cur.lastrowid
        cur.execute(
            """
            INSERT INTO metadata (media_id, taken_at, camera_make, camera_model, country_name, city_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (id2, "2023-08-20 15:30:00", "Samsung", "Galaxy", "대한민국", "서울")
        )
        conn.commit()

        # 3. YEAR_YEAR_MONTH (2023/2023-07/) 전략으로 제자리 재구성 실행
        result = self.service.execute_reorganize(
            source_base_dir=self.source_dir,
            target_base_dir=self.source_dir,
            strategy=FolderStrategy.YEAR_YEAR_MONTH,
        )

        self.assertEqual(result.total_count, 2)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.failed_count, 0)

        # 4. 새 경로 확인
        expected_f1 = self.source_dir / "2023" / "2023-07" / "photo1.jpg"
        expected_f2 = self.source_dir / "2023" / "2023-08" / "photo2.jpg"
        self.assertTrue(expected_f1.exists())
        self.assertTrue(expected_f2.exists())

        # 5. 타임스탬프 보존 검증 (초 단위 일치)
        self.assertEqual(int(expected_f1.stat().st_mtime), int(target_ts))

        # 6. 이전 빈 폴더(2023/07, 2023/08) 및 임시 폴더 삭제 확인
        self.assertFalse(old_folder1.exists())
        self.assertFalse(old_folder2.exists())
        self.assertFalse((self.source_dir / ".reorganize_tmp").exists())

        # 7. DB 업데이트 확인
        cur.execute("SELECT file_path FROM media_files WHERE id = ?", (id1,))
        db_path1 = cur.fetchone()[0]
        self.assertEqual(db_path1, str(expected_f1))

        # 8. job_history 기록 확인
        cur.execute("SELECT status FROM job_history ORDER BY id DESC LIMIT 1")
        status = cur.fetchone()[0]
        self.assertIn("REORGANIZED", status)

    def test_reorganize_duplicate_filename_handling(self):
        """다른 폴더의 동일 파일명이 동일 목표 폴더로 모일 때 충돌 방지 (1) 접미사 검증"""
        dir_a = self.source_dir / "folder_a"
        dir_b = self.source_dir / "folder_b"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        f_a = dir_a / "IMG_0001.jpg"
        f_b = dir_b / "IMG_0001.jpg"
        f_a.write_bytes(b"content a")
        f_b.write_bytes(b"content b")

        conn = self.db_manager.get_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO media_files (file_path, file_name, file_ext) VALUES (?, ?, ?)", (str(f_a), "IMG_0001.jpg", "jpg"))
        id_a = cur.lastrowid
        cur.execute("INSERT INTO metadata (media_id, taken_at) VALUES (?, ?)", (id_a, "2023-07-01 12:00:00"))

        cur.execute("INSERT INTO media_files (file_path, file_name, file_ext) VALUES (?, ?, ?)", (str(f_b), "IMG_0001.jpg", "jpg"))
        id_b = cur.lastrowid
        cur.execute("INSERT INTO metadata (media_id, taken_at) VALUES (?, ?)", (id_b, "2023-07-02 12:00:00"))
        conn.commit()

        # YEAR_MONTH 전략 -> 둘 다 2023/07 폴더로 모임
        result = self.service.execute_reorganize(
            source_base_dir=self.source_dir,
            target_base_dir=self.source_dir,
            strategy=FolderStrategy.YEAR_MONTH,
        )

        self.assertEqual(result.success_count, 2)
        target_dir = self.source_dir / "2023" / "07"
        self.assertTrue((target_dir / "IMG_0001.jpg").exists())
        self.assertTrue((target_dir / "IMG_0001(1).jpg").exists())

        # 내용 보존 확인
        files = list(target_dir.glob("*.jpg"))
        contents = {p.read_bytes() for p in files}
        self.assertIn(b"content a", contents)
        self.assertIn(b"content b", contents)

    def test_reorganize_with_runtime_geocoding_resolves_country(self):
        """country_name이 비어있어도 GPS 좌표가 있으면 실시간 역지오코딩하여 대한민국 폴더로 정상 배치"""
        old_folder = self.source_dir / "temp_folder"
        old_folder.mkdir(parents=True)
        f = old_folder / "photo_geo.jpg"
        f.write_bytes(b"geo test image")

        conn = self.db_manager.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO media_files (file_path, file_name, file_ext) VALUES (?, ?, ?)",
            (str(f), "photo_geo.jpg", "jpg")
        )
        m_id = cur.lastrowid
        # country_name과 city_name을 None으로 비워두고, 인천 GPS 좌표만 부여
        cur.execute(
            """
            INSERT INTO metadata (media_id, taken_at, latitude, longitude, country_name, city_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (m_id, "2023-07-20 12:00:00", 37.4574, 126.6986, None, None)
        )
        conn.commit()

        # GEO_COUNTRY_STATE 전략으로 재구성 실행
        result = self.service.execute_reorganize(
            source_base_dir=self.source_dir,
            target_base_dir=self.source_dir,
            strategy=FolderStrategy.GEO_COUNTRY_STATE,
        )

        self.assertEqual(result.success_count, 1)

        # "위치 정보 없음"이 아니라 "대한민국/인천광역시/2023/07/photo_geo.jpg"로 이동되었는지 검증!
        expected_path = self.source_dir / "대한민국" / "인천광역시" / "2023" / "07" / "photo_geo.jpg"
        self.assertTrue(expected_path.exists())

        # DB metadata 테이블에도 역지오코딩 결과가 영구 캐시되었는지 검증!
        cur.execute("SELECT country_name, city_name FROM metadata WHERE media_id = ?", (m_id,))
        c_name, city = cur.fetchone()
        self.assertEqual(c_name, "대한민국")
        self.assertEqual(city, "남동구")

    def test_all_geo_hierarchy_strategies_target_dir(self):
        """4가지 위치 계층 및 년/월 유무에 따른 대상 디렉토리 계산 정밀 검증"""
        item = ReorganizeItem(
            media_id=1,
            current_path=Path("/tmp/sample.jpg"),
            file_name="sample.jpg",
            file_ext="jpg",
            media_type="photo",
            album_name="가족여행",
            taken_at=datetime(2023, 5, 15, 10, 0, 0),
            camera_make="Apple",
            camera_model="iPhone 13",
            country_name="대한민국",
            state_name="인천광역시",
            city_name="남동구",
            latitude=37.4574,
            longitude=126.6986,
        )
        base = Path("/output")

        # 1. 3단계 + YYYY/MM
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_STATE_CITY)
        self.assertEqual(p, base / "대한민국" / "인천광역시" / "남동구" / "2023" / "05")

        # 2. 3단계 ONLY
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_STATE_CITY_ONLY)
        self.assertEqual(p, base / "대한민국" / "인천광역시" / "남동구")

        # 3. 2단계 광역 + YYYY/MM
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_STATE)
        self.assertEqual(p, base / "대한민국" / "인천광역시" / "2023" / "05")

        # 4. 2단계 광역 ONLY
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_STATE_ONLY)
        self.assertEqual(p, base / "대한민국" / "인천광역시")

        # 5. 2단계 도시 + YYYY/MM
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_CITY)
        self.assertEqual(p, base / "대한민국" / "남동구" / "2023" / "05")

        # 6. 2단계 도시 ONLY
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_CITY_ONLY)
        self.assertEqual(p, base / "대한민국" / "남동구")

        # 7. 1단계 국가 + YYYY/MM
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY)
        self.assertEqual(p, base / "대한민국" / "2023" / "05")

        # 8. 1단계 국가 ONLY
        p = self.service.calculate_target_dir(base, item, FolderStrategy.GEO_COUNTRY_ONLY)
        self.assertEqual(p, base / "대한민국")


if __name__ == "__main__":
    unittest.main()
