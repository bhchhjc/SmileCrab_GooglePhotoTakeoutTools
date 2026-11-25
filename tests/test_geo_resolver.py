"""
tests/test_geo_resolver.py
────────────────────────────────────────────────────────────────
오프라인 역지오코더 (GeoResolver) 단위 테스트
"""

import time
import unittest
from src.core.geo_resolver import GeoLanguage, GeoResolver, resolve_location


class TestGeoResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = GeoResolver()

    def test_korean_addresses_and_cities(self):
        # 1. 전남 곡성군 옥과면 부근 (35.275, 127.133)
        loc = self.resolver.resolve(35.275, 127.133, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "KR")
        self.assertEqual(loc.country_name, "대한민국")
        self.assertEqual(loc.state_name, "전라남도")
        self.assertEqual(loc.city_name, "곡성군")

        # 2. 인천 미추홀구/중구 부근 (37.452, 126.643) - 자치구 정밀 분리
        loc = self.resolver.resolve(37.452, 126.643, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "KR")
        self.assertEqual(loc.country_name, "대한민국")
        self.assertEqual(loc.state_name, "인천광역시")
        self.assertIn(loc.city_name, ("미추홀구", "중구"))

        # 3. 서울 종로/시청 부근 (37.5665, 126.9780) - 자치구 정밀 분리
        loc = self.resolver.resolve(37.5665, 126.9780, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "KR")
        self.assertEqual(loc.country_name, "대한민국")
        self.assertEqual(loc.state_name, "서울특별시")
        self.assertIn(loc.city_name, ("종로구", "중구"))

    def test_overseas_tourist_cities(self):
        # 4. 오스트리아 할슈타트 (47.562, 13.649)
        loc = self.resolver.resolve(47.562, 13.649, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "AT")
        self.assertEqual(loc.country_name, "오스트리아")
        self.assertEqual(loc.state_name, "상부오스트리아주")
        self.assertEqual(loc.city_name, "할슈타트")

        # 5. 일본 오사카/이즈미사노 부근 (34.434, 135.244)
        loc = self.resolver.resolve(34.434, 135.244, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "JP")
        self.assertEqual(loc.country_name, "일본")
        self.assertEqual(loc.state_name, "오사카부")
        self.assertIn(loc.city_name, ("이즈미사노", "난바", "오사카"))

        # 6. 프랑스 파리 (48.8566, 2.3522)
        loc = self.resolver.resolve(48.8566, 2.3522, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "FR")
        self.assertEqual(loc.country_name, "프랑스")
        self.assertEqual(loc.city_name, "파리")

        # 7. 크로아티아 플리트비체 국립공원 (44.9047, 15.6111)
        loc = self.resolver.resolve(44.904722, 15.611111, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "HR")
        self.assertEqual(loc.country_name, "크로아티아")
        self.assertEqual(loc.state_name, "리카세니주")
        self.assertEqual(loc.city_name, "플리트비체")

        # 8. 오스트리아 암슈테텐 기차역 (48.0936, 14.7958)
        loc = self.resolver.resolve(48.093611, 14.795833, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "AT")
        self.assertEqual(loc.country_name, "오스트리아")
        self.assertEqual(loc.state_name, "하부오스트리아주")
        self.assertEqual(loc.city_name, "암슈테텐")

        # 9. 크로아티아 리예카 항구 (45.3264, 14.4428)
        loc = self.resolver.resolve(45.3263889, 14.4427778, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "HR")
        self.assertEqual(loc.country_name, "크로아티아")
        self.assertEqual(loc.city_name, "리예카")

        # 10. 크로아티아 자그레브 (45.8147, 15.9769) - 동어반복 방어 및 도심 매핑
        loc = self.resolver.resolve(45.814722, 15.976944, GeoLanguage.KOREAN)
        self.assertEqual(loc.country_code, "HR")
        self.assertEqual(loc.country_name, "크로아티아")
        self.assertEqual(loc.state_name, "자그레브")
        self.assertIn(loc.city_name, ("고르니그라드", "자그레브 도심", "자그레브"))

    def test_english_language_mode(self):
        # 할슈타트 영어 모드
        loc = self.resolver.resolve(47.562, 13.649, GeoLanguage.ENGLISH)
        self.assertEqual(loc.country_code, "AT")
        self.assertEqual(loc.country_name, "Austria")
        self.assertEqual(loc.city_name, "Hallstatt")

        # 서울 영어 모드
        loc = self.resolver.resolve(37.5665, 126.9780, GeoLanguage.ENGLISH)
        self.assertEqual(loc.country_code, "KR")
        self.assertEqual(loc.country_name, "South Korea")
        self.assertEqual(loc.state_name, "Seoul")
        self.assertIn(loc.city_name, ("Jongno-gu", "Seoul"))

    def test_no_gps_fallback(self):
        # 좌표 None
        _, country, city = self.resolver.resolve(None, None, GeoLanguage.KOREAN)
        self.assertEqual(country, "위치정보없음")
        self.assertEqual(city, "")

        # 좌표 0.0, 0.0
        _, country, city = self.resolver.resolve(0.0, 0.0, GeoLanguage.ENGLISH)
        self.assertEqual(country, "Unknown_Location")
        self.assertEqual(city, "")

    def test_benchmark_speed(self):
        # 1,000건 좌표 반복 변환 시 0.02초 이내 수행되는지 벤치마크
        t0 = time.time()
        for _ in range(1000):
            self.resolver.resolve(37.5665, 126.9780, GeoLanguage.KOREAN)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.05, f"1,000건 변환에 {elapsed:.4f}초 소요 (목표: 0.05초 미만)")


if __name__ == "__main__":
    unittest.main()
