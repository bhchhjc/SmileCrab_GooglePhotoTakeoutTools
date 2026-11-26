"""
tests/test_exif_merge_pipeline.py
원본 EXIF 통합 추출, geoDataExif 폴백 파싱, 파일명 추측 차단, EXIF_FIRST vs JSON_FIRST 병합 우선순위 검증
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from src.core.exif_writer import ExifWriter
from src.core.geo_resolver import GeoLanguage
from src.core.models import GeoLocation, MediaMetadata
from src.core.parser import JsonParser
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.process_service import (
    FolderStrategy,
    MetadataPriority,
    ProcessMode,
    ProcessService,
)


def _create_jpeg(path: Path, exif_meta: MediaMetadata = None) -> Path:
    img = Image.new("RGB", (32, 32), color=(100, 150, 200))
    img.save(path, format="JPEG")
    if exif_meta:
        ExifWriter.update_metadata_fields(
            image_path=path,
            taken_at=exif_meta.best_datetime,
            latitude=exif_meta.geo_data.latitude,
            longitude=exif_meta.geo_data.longitude,
            altitude=exif_meta.geo_data.altitude,
            description=exif_meta.description,
            camera_make=exif_meta.camera_make,
            camera_model=exif_meta.camera_model,
        )
    return path


class TestExifMergePipeline(unittest.TestCase):
    """원본 EXIF 선행 분석 및 스마트 병합 파이프라인 테스트"""

    def test_extract_metadata_reads_all_exif_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            jpg = Path(tmp_dir) / "orig.jpg"
            dt = datetime(2022, 7, 15, 11, 22, 33)
            _create_jpeg(
                jpg,
                MediaMetadata(
                    photo_taken_time=dt,
                    geo_data=GeoLocation(37.5665, 126.9780, 42.5),
                    description="원본 EXIF 설명",
                    camera_make="Samsung",
                    camera_model="SM-S908N",
                ),
            )
            extracted = ExifWriter.extract_metadata(jpg)
            self.assertEqual(extracted.best_datetime, dt)
            self.assertAlmostEqual(extracted.geo_data.latitude, 37.5665, places=3)
            self.assertAlmostEqual(extracted.geo_data.longitude, 126.9780, places=3)
            self.assertAlmostEqual(extracted.geo_data.altitude, 42.5, places=1)
            self.assertEqual(extracted.description, "원본 EXIF 설명")
            self.assertEqual(extracted.camera_make, "Samsung")
            self.assertEqual(extracted.camera_model, "SM-S908N")

    def test_json_parser_falls_back_to_geo_data_exif_when_geo_data_is_zero(self):
        data = {
            "title": "photo.jpg",
            "geoData": {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0},
            "geoDataExif": {"latitude": 35.1796, "longitude": 129.0756, "altitude": 12.0},
        }
        meta = JsonParser.parse_dict(data)
        self.assertAlmostEqual(meta.geo_data.latitude, 35.1796, places=4)
        self.assertAlmostEqual(meta.geo_data.longitude, 129.0756, places=4)
        self.assertAlmostEqual(meta.geo_data.altitude, 12.0, places=1)

    def test_process_service_uses_original_exif_without_json_and_blocks_filename_guess(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            src_dir = tmp / "takeout"
            out_dir = tmp / "output"
            src_dir.mkdir()
            out_dir.mkdir()

            # 1) JSON 없지만 원본 EXIF에 날짜/GPS/카메라가 있는 파일
            exif_dt = datetime(2021, 9, 3, 16, 20, 10)
            _create_jpeg(
                src_dir / "photo_with_exif.jpg",
                MediaMetadata(
                    photo_taken_time=exif_dt,
                    geo_data=GeoLocation(37.5665, 126.9780, 10.0),
                    camera_make="Apple",
                    camera_model="iPhone 13",
                ),
            )

            # 2) EXIF도 JSON도 없지만 파일명만 날짜 형식인 파일 (추측 날짜 차단 검증)
            _create_jpeg(src_dir / "20180101_120000.jpg")

            db = DatabaseManager(db_path=tmp / "test.db")
            db.initialize()
            repo = MediaRepository(db)

            svc = ProcessService(
                media_repo=repo,
                folder_strategy=FolderStrategy.YEAR_MONTH,
                process_mode=ProcessMode.COPY,
                geo_language=GeoLanguage.KOREAN,
                metadata_priority=MetadataPriority.EXIF_FIRST,
            )
            summary = svc.run_pipeline(src_dir, out_dir)
            self.assertEqual(summary.processed_count, 2)

            items = {it["file_name"]: it for it in repo.search_media()}
            with_exif = items["photo_with_exif.jpg"]
            self.assertEqual(with_exif["taken_at"], "2021-09-03 16:20:10")
            self.assertAlmostEqual(with_exif["latitude"], 37.5665, places=3)
            self.assertNotEqual(with_exif["country_name"], "")
            self.assertEqual(with_exif["camera_make"], "Apple")

            no_exif = items["20180101_120000.jpg"]
            self.assertIsNone(no_exif["taken_at"])
            self.assertIn("Unknown_Year", no_exif["file_path"])

    def test_exif_first_vs_json_first_priority(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            exif_dt = datetime(2020, 3, 10, 8, 0, 0)
            json_dt = datetime(2023, 12, 25, 15, 30, 0, tzinfo=timezone.utc)
            json_ts = int(json_dt.timestamp())

            for mode_name, prio, expected_year, expected_lat in [
                ("exif", MetadataPriority.EXIF_FIRST, "2020-03-10 08:00:00", 37.5665),
                ("json", MetadataPriority.JSON_FIRST, json_dt.strftime("%Y-%m-%d %H:%M:%S"), 35.1796),
            ]:
                src_dir = tmp / f"src_{mode_name}"
                out_dir = tmp / f"out_{mode_name}"
                src_dir.mkdir()
                out_dir.mkdir()

                _create_jpeg(
                    src_dir / "conflict.jpg",
                    MediaMetadata(
                        photo_taken_time=exif_dt,
                        geo_data=GeoLocation(37.5665, 126.9780, 0.0),
                        camera_make="Samsung",
                        camera_model="SM-N986N",
                    ),
                )
                (src_dir / "conflict.jpg.json").write_text(
                    json.dumps(
                        {
                            "title": "conflict.jpg",
                            "description": "JSON 메모",
                            "photoTakenTime": {"timestamp": str(json_ts)},
                            "geoData": {"latitude": 35.1796, "longitude": 129.0756, "altitude": 0.0},
                        }
                    ),
                    encoding="utf-8",
                )

                db = DatabaseManager(db_path=tmp / f"{mode_name}.db")
                db.initialize()
                repo = MediaRepository(db)
                svc = ProcessService(repo, metadata_priority=prio)
                svc.run_pipeline(src_dir, out_dir)

                saved = repo.search_media()[0]
                self.assertEqual(saved["taken_at"], expected_year)
                self.assertAlmostEqual(saved["latitude"], expected_lat, places=3)
                self.assertEqual(saved["description"], "JSON 메모")
                self.assertEqual(saved["camera_make"], "Samsung")
