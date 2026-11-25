"""
단위 테스트: BatchRenameService (파일명 일괄 변경 엔진)
- 토큰 스택 순서 조합 및 괄호 포맷팅
- 스마트 구분자 정돈 및 사용자 지정 문구
- 메타데이터 누락 시 Fallback 및 중복 충돌 방지
- 타임스탬프 무손실 보존 및 DB 원자적 동기화
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.data.database import DatabaseManager
from src.services.batch_rename_service import (
    BatchRenameService, BracketStyle, RenamePatternConfig,
    RenameTokenConfig, RenameTokenType,
)


class TestBatchRenameService(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.db = DatabaseManager(self.db_path)
        self.service = BatchRenameService(self.db)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_token_order_and_brackets(self):
        """순서에 따른 토큰 결합 및 대괄호/소괄호 포맷 검증"""
        item = {
            "taken_at": "2023-07-30 15:47:40",
            "camera_make": "Apple",
            "camera_model": "iPhone 14 Pro",
            "country_name": "대한민국",
            "city_name": "고양시",
            "file_name": "original.jpg",
            "file_ext": "jpg",
        }

        # 패턴 1: [Make] + Date (대괄호 + 날짜, 뒤 구분자="" -> 밀착 연결)
        p1 = RenamePatternConfig(
            tokens=[
                RenameTokenConfig(RenameTokenType.MAKE, bracket_style=BracketStyle.SQUARE, next_delimiter=""),
                RenameTokenConfig(RenameTokenType.DATE, bracket_style=BracketStyle.NONE, date_format="%Y%m%d-%H%M%S"),
            ],
        )
        fname1 = self.service.generate_filename(p1, item)
        self.assertEqual(fname1, "[Apple]20230730-154740.jpg")

        # 패턴 1-B: [Make] + Date (뒤 구분자="_" -> 언더스코어 유지)
        p1_b = RenamePatternConfig(
            tokens=[
                RenameTokenConfig(RenameTokenType.MAKE, bracket_style=BracketStyle.SQUARE, next_delimiter="_"),
                RenameTokenConfig(RenameTokenType.DATE, bracket_style=BracketStyle.NONE, date_format="%Y%m%d-%H%M%S"),
            ],
        )
        fname1_b = self.service.generate_filename(p1_b, item)
        self.assertEqual(fname1_b, "[Apple]_20230730-154740.jpg")

        # 패턴 1-C: [Make] + Date (토큰별 개별 뒤 구분자 지정: 공백)
        p1_c = RenamePatternConfig(
            tokens=[
                RenameTokenConfig(RenameTokenType.MAKE, bracket_style=BracketStyle.SQUARE, next_delimiter=" "),
                RenameTokenConfig(RenameTokenType.DATE, bracket_style=BracketStyle.NONE, date_format="%Y%m%d-%H%M%S"),
            ],
        )
        fname1_c = self.service.generate_filename(p1_c, item)
        self.assertEqual(fname1_c, "[Apple] 20230730-154740.jpg")

        # 패턴 1-D: Date (%Y%m%d%H%M%S 연속숫자) + Make
        p1_d = RenamePatternConfig(
            tokens=[
                RenameTokenConfig(RenameTokenType.DATE, bracket_style=BracketStyle.NONE, date_format="%Y%m%d%H%M%S", next_delimiter="_"),
                RenameTokenConfig(RenameTokenType.MAKE, bracket_style=BracketStyle.NONE),
            ],
        )
        fname1_d = self.service.generate_filename(p1_d, item)
        self.assertEqual(fname1_d, "20230730154740_Apple.jpg")

        # 패턴 2: Date + (Model) + CustomText (개별 뒤 구분자 조합)
        p2 = RenamePatternConfig(
            tokens=[
                RenameTokenConfig(RenameTokenType.DATE, bracket_style=BracketStyle.NONE, date_format="%Y%m%d", next_delimiter="_"),
                RenameTokenConfig(RenameTokenType.MODEL, bracket_style=BracketStyle.ROUND, next_delimiter=""),
                RenameTokenConfig(RenameTokenType.CUSTOM_TEXT, custom_text="가족여행"),
            ],
        )
        fname2 = self.service.generate_filename(p2, item)
        self.assertEqual(fname2, "20230730_(iPhone 14 Pro)가족여행.jpg")

    def test_smart_delimiter_cleanup_when_missing_meta(self):
        """메타데이터(Make, City 등)가 누락되었을 때 구분자가 겹치지 않고 깔끔하게 정돈되는지 검증"""
        item = {
            "taken_at": "2023-07-30 15:47:40",
            "camera_make": "",      # 없음
            "camera_model": None,  # 없음
            "country_name": "대한민국",
            "city_name": "",       # 없음
            "file_name": "IMG_0001.jpg",
            "file_ext": "jpg",
        }

        # 패턴: Make_Model_Date_City
        pattern = RenamePatternConfig(
            tokens=[
                RenameTokenConfig(RenameTokenType.MAKE),
                RenameTokenConfig(RenameTokenType.MODEL),
                RenameTokenConfig(RenameTokenType.DATE, date_format="%Y%m%d"),
                RenameTokenConfig(RenameTokenType.CITY),
            ],
            delimiter="_",
        )

        fname = self.service.generate_filename(pattern, item)
        # Make, Model, City가 없으므로 Date 하나만 남고 앞뒤 언더스코어가 없어야 함
        self.assertEqual(fname, "20230730.jpg")

    def test_execute_rename_duplicate_handling_and_missing_file_cleanup(self):
        """실제 파일명 변경, 중복 충돌 (1) 접미사, 부재 파일 감지 및 DB 삭제 검증"""
        folder = Path(self.temp_dir) / "photos"
        folder.mkdir()

        f1 = folder / "test1.jpg"
        f1.write_text("photo1")
        f2 = folder / "test2.jpg"
        f2.write_text("photo2")
        # f3는 디스크에 생성하지 않음 (파인더에서 삭제된 상황 시뮬레이션)
        f3_missing = folder / "missing.jpg"

        # DB에 3개 파일 등록
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO media_files (file_path, file_name, file_ext) VALUES (?, ?, ?)", (str(f1), "test1.jpg", "jpg"))
        id1 = cursor.lastrowid
        cursor.execute("INSERT INTO media_files (file_path, file_name, file_ext) VALUES (?, ?, ?)", (str(f2), "test2.jpg", "jpg"))
        id2 = cursor.lastrowid
        cursor.execute("INSERT INTO media_files (file_path, file_name, file_ext) VALUES (?, ?, ?)", (str(f3_missing), "missing.jpg", "jpg"))
        id3 = cursor.lastrowid
        conn.commit()

        items = [
            {"id": id1, "file_path": str(f1), "file_name": "test1.jpg", "file_ext": "jpg", "camera_make": "Sony"},
            {"id": id2, "file_path": str(f2), "file_name": "test2.jpg", "file_ext": "jpg", "camera_make": "Sony"}, # 동일한 이름 생성 유도
            {"id": id3, "file_path": str(f3_missing), "file_name": "missing.jpg", "file_ext": "jpg", "camera_make": "Sony"},
        ]

        pattern = RenamePatternConfig(
            tokens=[RenameTokenConfig(RenameTokenType.MAKE)],
            delimiter="_",
        )

        result = self.service.execute_batch_rename(items, pattern, source_base_dir=folder)

        self.assertEqual(result.total_count, 3)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.cleaned_missing_count, 1)

        # 디스크 확인
        renamed1 = folder / "Sony.jpg"
        renamed2 = folder / "Sony(1).jpg"
        self.assertTrue(renamed1.exists())
        self.assertTrue(renamed2.exists())

        # DB 확인: id1, id2는 갱신되고, id3는 삭제되어야 함
        cursor.execute("SELECT id, file_name FROM media_files ORDER BY id ASC")
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["file_name"], "Sony.jpg")
        self.assertEqual(rows[1]["file_name"], "Sony(1).jpg")


if __name__ == "__main__":
    unittest.main()
