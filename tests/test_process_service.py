"""
Unit tests for ProcessService
전체 정리 파이프라인(JSON 분리, YYYY/MM 폴더 생성, 중복 스킵, DB 연동) 검증
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.process_service import FolderStrategy, ProcessMode, ProcessService


class TestProcessService(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.src_dir = self.test_dir / "Takeout_Source"
        self.out_dir = self.test_dir / "Cleaned_Output"
        self.db_path = self.test_dir / "catalog.db"

        self.src_dir.mkdir(parents=True)
        self.out_dir.mkdir(parents=True)

        self.db_mgr = DatabaseManager(self.db_path)
        self.repo = MediaRepository(self.db_mgr)
        self.service = ProcessService(
            media_repo=self.repo,
            folder_strategy=FolderStrategy.YEAR_MONTH,
            process_mode=ProcessMode.COPY,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_pipeline_organize_and_strip_json(self):
        # 1. 원본 폴더에 사진과 JSON 생성
        album_folder = self.src_dir / "2023년 사진"
        album_folder.mkdir()

        img_path = album_folder / "test_photo.jpg"
        img = Image.new("RGB", (50, 50), color=(0, 255, 0))
        img.save(str(img_path), "JPEG")

        json_path = album_folder / "test_photo.jpg.supplemental-metadata.json"
        json_content = {
            "title": "test_photo.jpg",
            "description": "파이프라인 테스트",
            "photoTakenTime": {"timestamp": "1684152000"},  # 2023-05-15
        }
        json_path.write_text(json.dumps(json_content), encoding="utf-8")

        # 2. 동일한 사진을 다른 앨범에 중복 생성
        duplicate_folder = self.src_dir / "즐겨찾기"
        duplicate_folder.mkdir()
        shutil.copy2(img_path, duplicate_folder / "test_photo.jpg")

        # 3. 파이프라인 실행
        summary = self.service.run_pipeline(self.src_dir, self.out_dir)

        # 4. 검증
        self.assertEqual(summary.total_scanned, 2)
        self.assertEqual(summary.processed_count, 1)
        self.assertEqual(summary.skipped_duplicate, 1)  # 중복 파일 1건 정상 감지 및 스킵!

        # 5. 출력 디렉토리 검증
        # 2023/05/ 폴더 생성 여부 확인
        expected_folder = self.out_dir / "2023" / "05"
        self.assertTrue(expected_folder.exists())
        self.assertTrue((expected_folder / "test_photo.jpg").exists())

        # 중요: 출력 디렉토리 내에 .json 파일이 절대 없어야 함!
        output_jsons = list(self.out_dir.rglob("*.json"))
        self.assertEqual(len(output_jsons), 0)

        # 6. DB 레코드 검증
        stats = self.repo.get_statistics()
        self.assertEqual(stats["total_count"], 1)
        self.assertEqual(stats["photo_count"], 1)


if __name__ == "__main__":
    unittest.main()
