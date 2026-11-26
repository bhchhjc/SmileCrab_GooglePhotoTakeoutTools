"""
Unit tests for JsonParser using standard library unittest
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from src.core.parser import JsonParser
from src.core.models import GeoLocation


class TestJsonParser(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_standard_json(self):
        json_content = {
            "title": "IMG_20230515_120000.jpg",
            "description": "제주도 가족 여행",
            "photoTakenTime": {
                "timestamp": "1684121445",
                "formatted": "2023. 5. 15. AM 3:30:45 UTC"
            },
            "creationTime": {
                "timestamp": "1684132800",
                "formatted": "2023. 5. 15. AM 6:40:00 UTC"
            },
            "geoData": {
                "latitude": 33.3617,
                "longitude": 126.5292,
                "altitude": 50.2
            },
            "people": [
                {"name": "홍길동"},
                {"name": "김철수"}
            ],
            "favorited": True
        }
        file_path = self.test_dir / "sample.json"
        file_path.write_text(json.dumps(json_content, ensure_ascii=False), encoding="utf-8")

        meta = JsonParser.parse_file(file_path)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "IMG_20230515_120000.jpg")
        self.assertEqual(meta.description, "제주도 가족 여행")
        self.assertEqual(meta.photo_taken_timestamp, 1684121445)
        self.assertEqual(meta.photo_taken_time, datetime.fromtimestamp(1684121445, tz=timezone.utc))
        self.assertEqual(meta.geo_data.latitude, 33.3617)
        self.assertEqual(meta.geo_data.longitude, 126.5292)
        self.assertTrue(meta.geo_data.has_valid_coordinates)
        self.assertEqual(meta.people, ["홍길동", "김철수"])
        self.assertTrue(meta.is_favorited)

    def test_parse_invalid_or_missing_json(self):
        empty_file = self.test_dir / "broken.json"
        empty_file.write_text("{ broken json content", encoding="utf-8")

        meta = JsonParser.parse_file(empty_file)
        self.assertIsNone(meta)

        non_exist = self.test_dir / "not_found.json"
        self.assertIsNone(JsonParser.parse_file(non_exist))

    def test_parse_non_string_fields_and_list_root(self):
        # title/description/people.name 에 list가 들어와도 TypeError 없이 안전 파싱
        weird_json = self.test_dir / "weird.json"
        weird_json.write_text(
            json.dumps({
                "title": ["IMG_0001.jpg"],
                "description": ["메모1", "메모2"],
                "people": [{"name": ["홍길동"]}],
            }),
            encoding="utf-8",
        )
        meta = JsonParser.parse_file(weird_json)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "IMG_0001.jpg")
        self.assertEqual(meta.description, "메모1 메모2")
        self.assertEqual(meta.people, ["홍길동"])

        # 루트가 JSON 배열인 경우 None 반환
        list_root = self.test_dir / "list_root.json"
        list_root.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(JsonParser.parse_file(list_root))


if __name__ == "__main__":
    unittest.main()
