"""
tests/test_metadata_edit_service.py
개별 미디어 메타데이터 편집, DB 스냅샷 백업/복원, 레거시 DB 마이그레이션 및 다이얼로그 검증
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image
from PySide6.QtWidgets import QApplication

from src.core.geo_resolver import GeoLanguage
from src.core.models import GeoLocation, MediaFile, MediaMetadata
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.metadata_edit_service import EditMetadataRequest, MetadataEditService
from src.ui.components.media_edit_dialog import MediaEditDialog


def _create_sample_jpeg(path: Path) -> Path:
    img = Image.new("RGB", (32, 32), color=(120, 180, 220))
    img.save(path, format="JPEG")
    return path


class TestMetadataEditService(unittest.TestCase):
    """개별 미디어 메타데이터 편집/복원 서비스 및 다이얼로그 테스트"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_legacy_db_migration_adds_snapshot_columns(self):
        """이전 버전 DB에 original_snapshot, is_user_edited 컬럼이 없어도 안전하게 마이그레이션되는지 검증"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"
            conn = sqlite3.connect(str(db_path))
            conn.executescript(
                """
                CREATE TABLE media_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    original_path TEXT,
                    file_name TEXT NOT NULL,
                    file_ext TEXT NOT NULL,
                    file_size INTEGER,
                    file_hash TEXT,
                    media_type TEXT,
                    album_name TEXT,
                    status TEXT DEFAULT 'COMPLETED',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE metadata (
                    media_id INTEGER PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    taken_at TEXT,
                    taken_timestamp INTEGER,
                    latitude REAL DEFAULT 0.0,
                    longitude REAL DEFAULT 0.0,
                    altitude REAL DEFAULT 0.0,
                    people TEXT,
                    is_favorited INTEGER DEFAULT 0
                );
                INSERT INTO media_files (file_path, file_name, file_ext, media_type)
                VALUES ('/tmp/old.jpg', 'old.jpg', '.jpg', 'photo');
                INSERT INTO metadata (media_id, title, taken_at)
                VALUES (1, 'old.jpg', '2020-01-01 10:00:00');
                """
            )
            conn.commit()
            conn.close()

            db = DatabaseManager(db_path=db_path)
            db.initialize()
            repo = MediaRepository(db)
            item = repo.get_media_by_id(1)

            self.assertIsNotNone(item)
            self.assertEqual(item["taken_at"], "2020-01-01 10:00:00")
            self.assertIsNone(item["original_snapshot"])
            self.assertEqual(item["is_user_edited"], 0)

    def test_apply_edit_and_restore_original_with_jpeg_exif(self):
        """메타데이터 수정(1차/2차) 시 최초 스냅샷 보존 및 EXIF/OS시간 반영, 이후 원본 복원 검증"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db = DatabaseManager(db_path=tmp_path / "test.db")
            db.initialize()
            repo = MediaRepository(db)

            jpg_path = _create_sample_jpeg(tmp_path / "sample.jpg")
            orig_dt = datetime(2021, 5, 10, 14, 30, 0)
            mf = MediaFile.from_path(jpg_path)
            meta = MediaMetadata(
                title="sample.jpg",
                description="원본 설명",
                photo_taken_time=orig_dt,
                photo_taken_timestamp=int(orig_dt.timestamp()),
                geo_data=GeoLocation(0.0, 0.0, 0.0),
                camera_make="Samsung",
                camera_model="SM-G998N",
            )
            media_id = repo.insert_media(jpg_path, jpg_path, "hash123", mf, meta)
            item = repo.get_media_by_id(media_id)
            self.assertIsNotNone(item)

            service = MetadataEditService(db)

            # 1차 수정: 날짜, GPS(서울), 설명, 카메라 변경
            dt_edit_1 = datetime(2023, 8, 15, 9, 15, 30)
            res1 = service.apply_edit(
                item,
                EditMetadataRequest(
                    taken_at=dt_edit_1,
                    latitude=37.5665,
                    longitude=126.9780,
                    altitude=35.0,
                    description="수정된 설명 1",
                    camera_make="Apple",
                    camera_model="iPhone 15 Pro",
                ),
                geo_lang=GeoLanguage.KOREAN,
            )
            self.assertTrue(res1.success)
            self.assertTrue(res1.exif_updated)
            self.assertTrue(res1.os_time_synced)
            self.assertIsNotNone(res1.updated_item)
            self.assertEqual(res1.updated_item["is_user_edited"], 1)
            self.assertEqual(res1.updated_item["taken_at"], "2023-08-15 09:15:30")
            self.assertNotEqual(res1.updated_item["country_name"], "")
            self.assertEqual(res1.updated_item["camera_make"], "Apple")

            # EXIF 실제 기록 검증
            exif_dict = piexif.load(str(jpg_path))
            self.assertEqual(exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal], b"2023:08:15 09:15:30")
            self.assertEqual(exif_dict["0th"][piexif.ImageIFD.Make], b"Apple")
            self.assertEqual(exif_dict["0th"][piexif.ImageIFD.Model], b"iPhone 15 Pro")
            self.assertIn(piexif.GPSIFD.GPSLatitude, exif_dict["GPS"])
            self.assertEqual(int(os.stat(jpg_path).st_mtime), int(dt_edit_1.timestamp()))

            # 2차 수정: 최초 스냅샷이 덮어씌워지지 않고 유지되어야 함
            dt_edit_2 = datetime(2024, 1, 1, 0, 0, 0)
            res2 = service.apply_edit(
                res1.updated_item,
                EditMetadataRequest(
                    taken_at=dt_edit_2,
                    latitude=0.0,
                    longitude=0.0,
                    altitude=0.0,
                    description="",
                    camera_make="",
                    camera_model="",
                ),
            )
            self.assertTrue(res2.success)
            self.assertIsNotNone(res2.updated_item)
            snapshot = json.loads(res2.updated_item["original_snapshot"])
            self.assertEqual(snapshot["taken_at"], "2021-05-10 14:30:00")
            self.assertEqual(snapshot["camera_make"], "Samsung")
            self.assertEqual(snapshot["description"], "원본 설명")

            # GPS 및 설명 제거가 EXIF에도 반영되었는지 검증
            exif_after_clear = piexif.load(str(jpg_path))
            self.assertEqual(exif_after_clear["GPS"], {})
            self.assertNotIn(piexif.ImageIFD.ImageDescription, exif_after_clear["0th"])

            # 원본으로 초기화 검증
            res_reset = service.restore_original(res2.updated_item)
            self.assertTrue(res_reset.success)
            self.assertIsNotNone(res_reset.updated_item)
            self.assertEqual(res_reset.updated_item["is_user_edited"], 0)
            self.assertEqual(res_reset.updated_item["taken_at"], "2021-05-10 14:30:00")
            self.assertEqual(res_reset.updated_item["camera_make"], "Samsung")
            self.assertEqual(res_reset.updated_item["description"], "원본 설명")

            exif_restored = piexif.load(str(jpg_path))
            self.assertEqual(exif_restored["Exif"][piexif.ExifIFD.DateTimeOriginal], b"2021:05:10 14:30:00")
            self.assertEqual(int(os.stat(jpg_path).st_mtime), int(orig_dt.timestamp()))

    def test_media_edit_dialog_initialization(self):
        """MediaEditDialog 위젯 초기화 및 DatePicker/TimePicker 값 바인딩 검증"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = DatabaseManager(db_path=Path(tmp_dir) / "ui_test.db")
            db.initialize()
            sample_item = {
                "id": 1,
                "file_name": "test_photo.jpg",
                "file_path": str(Path(tmp_dir) / "test_photo.jpg"),
                "media_type": "photo",
                "taken_at": "2022-11-05 18:45:12",
                "latitude": 37.5665,
                "longitude": 126.9780,
                "altitude": 10.0,
                "description": "테스트 캡션",
                "camera_make": "Samsung",
                "camera_model": "SM-S908N",
                "is_user_edited": 0,
                "original_snapshot": None,
            }
            dlg = MediaEditDialog(sample_item, db_manager=db)
            dt = dlg._current_selected_datetime()
            self.assertEqual(dt, datetime(2022, 11, 5, 18, 45, 12))
            self.assertIn("2022-11-05 18:45:12", dlg._lbl_preview_dt.text())
            self.assertEqual(dlg._desc_edit.toPlainText(), "테스트 캡션")
            self.assertEqual(dlg._make_edit.text(), "Samsung")
            self.assertEqual(dlg._model_edit.text(), "SM-S908N")
            dlg.close()
