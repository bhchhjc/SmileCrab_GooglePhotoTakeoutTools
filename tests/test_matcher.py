"""
Unit tests for MetadataMatcher using standard library unittest
다양한 Google Takeout 변칙 상황 매칭 검증
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.core.models import MatchType, MediaFile
from src.core.matcher import MetadataMatcher


def create_json(directory: Path, name: str, title: str, timestamp: int = 1684121445) -> Path:
    path = directory / name
    content = {
        "title": title,
        "photoTakenTime": {"timestamp": str(timestamp)}
    }
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return path


class TestMetadataMatcher(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.matcher = MetadataMatcher()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_match_exact_and_supplemental(self):
        # 1. Exact match (.jpg.json)
        media1_path = self.test_dir / "photo1.jpg"
        media1_path.touch()
        create_json(self.test_dir, "photo1.jpg.json", "photo1.jpg")
        media1 = MediaFile.from_path(media1_path)
        res1 = self.matcher.match(media1)
        self.assertEqual(res1.match_type, MatchType.EXACT)
        self.assertTrue(res1.is_matched)

        # 2. Supplemental match (.jpg.supplemental-metadata.json)
        media2_path = self.test_dir / "photo2.jpg"
        media2_path.touch()
        create_json(self.test_dir, "photo2.jpg.supplemental-metadata.json", "photo2.jpg")
        media2 = MediaFile.from_path(media2_path)
        res2 = self.matcher.match(media2)
        self.assertEqual(res2.match_type, MatchType.SUPPLEMENTAL)
        self.assertTrue(res2.is_matched)

    def test_match_truncated_prefix(self):
        # 51자 잘림: 20150530_174017-COLLAGE.jpg.supplemental-metad.json
        media_path = self.test_dir / "20150530_174017-COLLAGE.jpg"
        media_path.touch()
        create_json(self.test_dir, "20150530_174017-COLLAGE.jpg.supplemental-metad.json", "20150530_174017-COLLAGE.jpg")

        media = MediaFile.from_path(media_path)
        res = self.matcher.match(media)
        self.assertTrue(res.is_matched)
        self.assertIn(res.match_type, (MatchType.TRUNCATED_PREFIX, MatchType.REVERSE_TITLE_LOOKUP))

    def test_match_edited_korean_suffix(self):
        # 원본 JSON만 존재하고, 파일은 한국어 수정본(-수정됨)인 경우
        media_path = self.test_dir / "20140104_014552-수정됨.jpg"
        media_path.touch()
        create_json(self.test_dir, "20140104_014552.jpg.supplemental-metadata.json", "20140104_014552.jpg")

        media = MediaFile.from_path(media_path)
        self.assertTrue(media.is_edited_version)

        res = self.matcher.match(media)
        self.assertTrue(res.is_matched)
        self.assertIn(res.match_type, (MatchType.EDITED_ORIGINAL, MatchType.REVERSE_TITLE_LOOKUP))

    def test_match_bracket_counter(self):
        # photo(1).jpg <-> photo.jpg(1).json
        media_path = self.test_dir / "IMG_0001(1).jpg"
        media_path.touch()
        create_json(self.test_dir, "IMG_0001.jpg(1).json", "IMG_0001.jpg")

        media = MediaFile.from_path(media_path)
        res = self.matcher.match(media)
        self.assertTrue(res.is_matched)
        self.assertEqual(res.match_type, MatchType.BRACKET_COUNTER)

    def test_match_fallback_filename(self):
        # JSON이 전혀 없는 경우 파일명 정규식 폴백
        media_path = self.test_dir / "IMG_20230515_123045.jpg"
        media_path.touch()

        media = MediaFile.from_path(media_path)
        res = self.matcher.match(media)
        self.assertTrue(res.is_matched)
        self.assertEqual(res.match_type, MatchType.FALLBACK_FILENAME)
        self.assertEqual(res.metadata.photo_taken_time.year, 2023)
        self.assertEqual(res.metadata.photo_taken_time.month, 5)
        self.assertEqual(res.metadata.photo_taken_time.day, 15)


if __name__ == "__main__":
    unittest.main()
