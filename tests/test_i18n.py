"""
tests/test_i18n.py
────────────────────────────────────────────────────────────────
i18n 엔진, 언어 리소스 및 신규 리포지토리/설정 메서드 단위 테스트
"""

import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.core.i18n import SUPPORTED_LOCALES, I18nManager, i18n, t
from src.core.models import MediaFile, MediaType
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository

# QApplication 초기화 (QObject 시그널 테스트용)
_app = QApplication.instance() or QApplication([])


class TestI18nAndSettings(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_i18n.db"
        self.db = DatabaseManager(self.db_path)
        self.db.initialize()
        self.repo = MediaRepository(self.db)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_supported_locales_count(self):
        """6개 언어 셋이 정상 등록되었는지 검증"""
        self.assertEqual(len(SUPPORTED_LOCALES), 6)
        expected = ["ko_KR", "en_US", "ja_JP", "zh_CN", "zh_TW", "zh_HK"]
        for loc in expected:
            self.assertIn(loc, SUPPORTED_LOCALES)

    def test_translations_loaded_for_all_locales(self):
        """모든 로케일의 JSON 파일이 로드되어 기본 키가 존재하는지 확인"""
        for loc in SUPPORTED_LOCALES.keys():
            i18n.set_locale(loc)
            app_title = t("common.app_title")
            self.assertTrue(len(app_title) > 0)
            self.assertNotEqual(app_title, "common.app_title")

    def test_template_substitution(self):
        """kwargs를 활용한 템플릿 변수 치환 검증"""
        i18n.set_locale("ko_KR")
        msg = t("dialog.rename.target_summary", total=10, photos=8, videos=2)
        self.assertIn("10개", msg)
        self.assertIn("8개", msg)
        self.assertIn("2개", msg)

        i18n.set_locale("en_US")
        msg_en = t("dialog.rename.target_summary", total=10, photos=8, videos=2)
        self.assertIn("Total 10", msg_en)

    def test_fallback_behavior(self):
        """존재하지 않는 키 요청 시 default 또는 키 자체 반환 검증"""
        val = t("non_existent_key_12345", default="기본값")
        self.assertEqual(val, "기본값")

        val_raw = t("non_existent_key_67890")
        self.assertEqual(val_raw, "non_existent_key_67890")

    def test_language_changed_signal(self):
        """언어 변경 시 language_changed 시그널이 정상 수신되는지 검증"""
        received = []
        i18n.language_changed.connect(lambda loc: received.append(loc))
        i18n.set_locale("ja_JP")
        self.assertIn("ja_JP", received)
        # 원상 복구
        i18n.set_locale("ko_KR")

    def test_database_settings_crud(self):
        """DatabaseManager 설정 키-값 저장 및 조회 테스트"""
        self.assertIsNone(self.db.get_setting("custom_key"))
        self.assertEqual(self.db.get_setting("custom_key", "default_val"), "default_val")

        self.assertTrue(self.db.set_setting("custom_key", "stored_val"))
        self.assertEqual(self.db.get_setting("custom_key"), "stored_val")

        # UPSERT 테스트
        self.assertTrue(self.db.set_setting("custom_key", "updated_val"))
        self.assertEqual(self.db.get_setting("custom_key"), "updated_val")

    def test_media_repo_root_stats(self):
        """MediaRepository의 root 기반 카운트 및 통계 쿼리 테스트"""
        root_dir = Path("/mock/target/root")
        file1 = root_dir / "2023" / "01" / "photo1.jpg"
        file2 = root_dir / "2023" / "01" / "video1.mp4"

        mf1 = MediaFile(path=file1, normalized_name="photo1.jpg", extension=".jpg", media_type=MediaType.PHOTO, file_size=1000)
        mf2 = MediaFile(path=file2, normalized_name="video1.mp4", extension=".mp4", media_type=MediaType.VIDEO, file_size=2000)

        self.repo.insert_media(file1, Path("/src/photo1.jpg"), "hash1", mf1)
        self.repo.insert_media(file2, Path("/src/video1.mp4"), "hash2", mf2)

        total_cnt = self.repo.get_root_media_count(str(root_dir))
        self.assertEqual(total_cnt, 2)

        total, photos, videos = self.repo.get_root_media_stats(str(root_dir))
        self.assertEqual(total, 2)
        self.assertEqual(photos, 1)
        self.assertEqual(videos, 1)

        items = self.repo.get_media_items_for_rename(str(root_dir))
        self.assertEqual(len(items), 2)

    def test_exact_key_parity_across_all_6_files(self):
        """6개 언어 JSON 파일 전체의 키 세트가 100% 동일한지 완전 일치 검증"""
        import glob
        files = glob.glob("src/locales/*.json")
        self.assertEqual(len(files), 6)

        def extract_keys(d, prefix=""):
            keys = set()
            for k, v in d.items():
                full = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    keys.update(extract_keys(v, full))
                else:
                    keys.add(full)
            return keys

        data_keys = {}
        for f in files:
            with open(f, encoding="utf-8") as fp:
                data_keys[f] = extract_keys(json.load(fp))

        base_keys = data_keys["src/locales/ko_KR.json"]
        self.assertTrue(len(base_keys) >= 300)

        for f, kset in data_keys.items():
            diff_missing = base_keys - kset
            diff_extra = kset - base_keys
            self.assertEqual(len(diff_missing), 0, f"{f} is missing keys: {diff_missing}")
            self.assertEqual(len(diff_extra), 0, f"{f} has extra keys: {diff_extra}")

    def test_views_dynamic_retranslation_on_locale_change(self):
        """언어 변경 시 Dashboard, Job, History, Library, Settings 모든 뷰가 실시간 retranslate 되는지 검증"""
        from src.ui.views.dashboard_view import DashboardView
        from src.ui.views.job_view import JobView
        from src.ui.views.history_view import HistoryView
        from src.ui.views.library_view import LibraryView
        from src.ui.views.settings_view import SettingsView

        # 1. 한국어 상태로 생성
        i18n.set_locale("ko_KR")
        dash = DashboardView()
        job = JobView()
        hist = HistoryView()
        lib = LibraryView()
        sett = SettingsView()

        self.assertIn("대시보드", dash._welcome_lbl.text())
        self.assertEqual(dash._card_last.label(), "최근 작업 일시")
        self.assertEqual(lib._title_lbl.text(), "🖼 미디어 라이브러리")
        self.assertEqual(lib._reorganize_btn.text(), "📁 폴더 구조 재구성")

        # 2. 영어(en_US)로 변경 -> 모든 뷰 즉시 영문화 확인
        i18n.set_locale("en_US")
        self.assertIn("Media Overview Dashboard", dash._welcome_lbl.text())
        self.assertEqual(dash._card_last.label(), "Last Run Time")
        self.assertEqual(dash._table.horizontalHeaderItem(0).text(), "Job Type")
        self.assertEqual(job._step_indicator._labels[0].text(), "Step 1: Folders & Options")
        self.assertIn("Session", hist._title_lbl.text())
        self.assertEqual(lib._title_lbl.text(), "🖼 Media Library")
        self.assertEqual(lib._reorganize_btn.text(), "📁 Reorganize Folders")
        self.assertEqual(sett._app_title_lbl.text(), "Settings")

        # 3. 일본어(ja_JP)로 변경 -> 모든 뷰 즉시 일본어화 확인
        i18n.set_locale("ja_JP")
        self.assertEqual(dash._card_last.label(), "前回の実行日時")
        self.assertEqual(lib._title_lbl.text(), "🖼 メディアライブラリ")
        self.assertEqual(lib._reorganize_btn.text(), "📁 フォルダ構造再構成")

        # 4. 원복
        i18n.set_locale("ko_KR")
        self.assertEqual(dash._card_last.label(), "최근 작업 일시")

    def test_geo_lang_auto_match_rules(self):
        """UI 언어에 따른 역지오코딩 언어 자동 매칭 규칙 검증 (ko_KR -> KOREAN, 기타 -> ENGLISH)"""
        from src.core.geo_resolver import GeoLanguage
        from src.ui.views.settings_view import SettingsView

        view = SettingsView()
        
        # 1. 한국어 선택 -> 역지오코딩은 KOREAN
        k_idx = view.app_lang_combo.findData("ko_KR")
        view.app_lang_combo.setCurrentIndex(k_idx)
        self.assertEqual(view.geo_lang_combo.currentData(), GeoLanguage.KOREAN)

        # 2. 영어 선택 -> 역지오코딩은 ENGLISH
        e_idx = view.app_lang_combo.findData("en_US")
        view.app_lang_combo.setCurrentIndex(e_idx)
        self.assertEqual(view.geo_lang_combo.currentData(), GeoLanguage.ENGLISH)

        # 3. 일본어 선택 -> 역지오코딩은 ENGLISH
        j_idx = view.app_lang_combo.findData("ja_JP")
        view.app_lang_combo.setCurrentIndex(j_idx)
        self.assertEqual(view.geo_lang_combo.currentData(), GeoLanguage.ENGLISH)

        # 4. 중국어 간체 선택 -> 역지오코딩은 ENGLISH
        c_idx = view.app_lang_combo.findData("zh_CN")
        view.app_lang_combo.setCurrentIndex(c_idx)
        self.assertEqual(view.geo_lang_combo.currentData(), GeoLanguage.ENGLISH)

        # 원복
        view.app_lang_combo.setCurrentIndex(k_idx)
        view.close()


if __name__ == "__main__":
    unittest.main()
