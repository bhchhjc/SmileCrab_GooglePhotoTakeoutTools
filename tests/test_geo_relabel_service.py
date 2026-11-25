"""
tests/test_geo_relabel_service.py
────────────────────────────────────────────────────────────────
미디어 역지오코딩 지명 언어 일괄 변경 서비스 단위 테스트
"""

import tempfile
import unittest
from pathlib import Path

from src.core.geo_resolver import GeoLanguage
from src.core.models import GeoLocation, MediaFile, MediaMetadata, MediaType
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.geo_relabel_service import GeoRelabelService


class TestGeoRelabelService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_geo_relabel.db"
        self.db = DatabaseManager(self.db_path)
        self.db.initialize()
        self.repo = MediaRepository(self.db)
        self.service = GeoRelabelService(self.db)

        # 샘플 미디어 파일 삽입
        self.root_a = Path(self.temp_dir.name) / "Output_A"
        self.root_b = Path(self.temp_dir.name) / "Output_B"
        self.root_a.mkdir(parents=True, exist_ok=True)
        self.root_b.mkdir(parents=True, exist_ok=True)

        # 1. 서울 종로 (한국어 초기 상태)
        f1 = self.root_a / "seoul.jpg"
        mf1 = MediaFile(path=f1, normalized_name="seoul.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=1000)
        meta1 = MediaMetadata(
            geo_data=GeoLocation(latitude=37.5665, longitude=126.9780),
        )
        # 초기 메타데이터는 한국어로 설정
        self.repo.insert_media(f1, Path("/src/seoul.jpg"), "hash1", mf1, meta1)
        # DB에 지명 초기화 (대한민국, 서울특별시, 종로구)
        self.repo.update_media_geo_names([("KR", "대한민국", "서울특별시", "종로구", 1)])

        # 2. 파리 에펠탑 (한국어 초기 상태)
        f2 = self.root_a / "paris.jpg"
        mf2 = MediaFile(path=f2, normalized_name="paris.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=2000)
        meta2 = MediaMetadata(
            geo_data=GeoLocation(latitude=48.8566, longitude=2.3522),
        )
        self.repo.insert_media(f2, Path("/src/paris.jpg"), "hash2", mf2, meta2)
        self.repo.update_media_geo_names([("FR", "프랑스", "일드프랑스", "파리", 2)])

        # 3. GPS 없는 파일 (Output_A)
        f3 = self.root_a / "no_gps.jpg"
        mf3 = MediaFile(path=f3, normalized_name="no_gps.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=500)
        self.repo.insert_media(f3, Path("/src/no_gps.jpg"), "hash3", mf3, None)

        # 4. 도쿄 (Output_B)
        f4 = self.root_b / "tokyo.jpg"
        mf4 = MediaFile(path=f4, normalized_name="tokyo.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=1500)
        meta4 = MediaMetadata(
            geo_data=GeoLocation(latitude=35.6895, longitude=139.6917),
        )
        self.repo.insert_media(f4, Path("/src/tokyo.jpg"), "hash4", mf4, meta4)
        self.repo.update_media_geo_names([("JP", "일본", "도쿄도", "신주쿠구", 4)])

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_repo_geo_stats_and_items(self):
        """MediaRepository의 GPS 통계 및 아이템 조회 검증"""
        # 전체 통계
        tot, geo = self.repo.get_geo_media_stats()
        self.assertEqual(tot, 4)
        self.assertEqual(geo, 3)

        # Root A 한정 통계
        tot_a, geo_a = self.repo.get_geo_media_stats(str(self.root_a))
        self.assertEqual(tot_a, 3)
        self.assertEqual(geo_a, 2)

        # GPS 보유 목록 조회
        items = self.repo.get_geo_media_items(str(self.root_a))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["file_name"], "seoul.jpg")
        self.assertEqual(items[1]["file_name"], "paris.jpg")

    def test_service_preview_relabel(self):
        """GeoRelabelService의 Before/After 미리보기 검증"""
        tot, geo, previews = self.service.get_preview(
            target_root=str(self.root_a),
            target_lang=GeoLanguage.ENGLISH,
        )
        self.assertEqual(tot, 3)
        self.assertEqual(geo, 2)
        self.assertEqual(len(previews), 2)

        # Seoul preview: Before=대한민국, After=South Korea
        p1 = previews[0]
        self.assertEqual(p1.file_name, "seoul.jpg")
        self.assertEqual(p1.cur_country, "대한민국")
        self.assertEqual(p1.new_country, "South Korea")
        self.assertTrue(p1.is_changed)

        # Paris preview: Before=프랑스, After=France
        p2 = previews[1]
        self.assertEqual(p2.file_name, "paris.jpg")
        self.assertEqual(p2.cur_country, "프랑스")
        self.assertEqual(p2.new_country, "France")
        self.assertTrue(p2.is_changed)

    def test_service_execute_relabel_to_english(self):
        """GeoRelabelService의 영어 일괄 재변환 실행 검증"""
        progress_calls = []

        def cb(cur, tot, fname, spd, eta):
            progress_calls.append((cur, tot, fname))

        result = self.service.execute_relabel(
            target_root=str(self.root_a),
            target_lang=GeoLanguage.ENGLISH,
            progress_callback=cb,
        )

        self.assertEqual(result.total_count, 3)
        self.assertEqual(result.geo_count, 2)
        self.assertEqual(result.updated_count, 2)
        self.assertEqual(result.no_gps_count, 1)
        self.assertEqual(result.target_lang, GeoLanguage.ENGLISH)
        self.assertTrue(result.duration_seconds >= 0.0)

        # DB 검증: Output_A 미디어들의 지명이 영어로 갱신되었는지 확인
        items_a = self.repo.get_geo_media_items(str(self.root_a))
        self.assertEqual(items_a[0]["country_name"], "South Korea")
        self.assertEqual(items_a[1]["country_name"], "France")

        # DB 검증: Output_B 미디어(도쿄)는 Root A 대상이 아니므로 한국어 "일본" 유지 확인
        items_b = self.repo.get_geo_media_items(str(self.root_b))
        self.assertEqual(items_b[0]["country_name"], "일본")

    def test_service_execute_relabel_all_roots(self):
        """전체 라이브러리(target_root=None) 대상 일괄 재변환 검증"""
        result = self.service.execute_relabel(
            target_root=None,
            target_lang=GeoLanguage.ENGLISH,
        )
        self.assertEqual(result.total_count, 4)
        self.assertEqual(result.geo_count, 3)
        self.assertEqual(result.updated_count, 3)

        # 도쿄도 "Japan"으로 변경되었는지 확인
        items_b = self.repo.get_geo_media_items(str(self.root_b))
        self.assertEqual(items_b[0]["country_name"], "Japan")

    def test_service_cancellation(self):
        """작업 취소 플래그 정상 감지 및 중단 검증"""
        cancelled = True
        result = self.service.execute_relabel(
            target_root=None,
            target_lang=GeoLanguage.ENGLISH,
            is_cancelled=lambda: cancelled,
        )
        self.assertEqual(result.updated_count, 0)

    def test_dialog_lifecycle_and_transition(self):
        """GeoRelabelDialog의 Step 1 -> Step 2 -> Step 3 전환 및 ProgressCircle 라이프사이클 검증"""
        from PySide6.QtWidgets import QApplication
        from src.ui.components.geo_relabel_dialog import GeoRelabelDialog
        
        app = QApplication.instance() or QApplication([])
        dlg = GeoRelabelDialog(current_base_dir=self.root_a, db_manager=self.db)
        self.assertEqual(dlg.stack.currentIndex(), 0)
        
        # Step 2 시작 및 프로그레스 서클 가동 검증
        dlg._start_relabel()
        self.assertEqual(dlg.stack.currentIndex(), 1)
        self.assertTrue(dlg.step2_circle._timer.isActive())
        
        # 프로그레스 시그널 수신 시뮬레이션 (set_progress 오류가 발생하지 않는지)
        dlg._on_worker_progress(1, 2, "seoul.jpg", 10.0, 0.1)
        self.assertEqual(dlg.step2_bar.value(), 50)
        
        # 완료 핸들러 시뮬레이션
        from src.services.geo_relabel_service import GeoRelabelResult
        mock_res = GeoRelabelResult(
            total_count=3,
            geo_count=2,
            updated_count=2,
            no_gps_count=1,
            duration_seconds=0.1,
            target_lang=GeoLanguage.ENGLISH,
        )
        dlg._on_worker_finished(mock_res)
        self.assertEqual(dlg.stack.currentIndex(), 2)
        self.assertFalse(dlg.step2_circle._timer.isActive())
        dlg.close()



if __name__ == "__main__":
    unittest.main()
