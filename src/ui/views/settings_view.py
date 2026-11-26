"""
views/settings_view.py
────────────────────────────────────────────────────────────────
One UI 9.0 스타일 설정 뷰 (마스터-디테일 가로 2-Pane 분할 레이아웃)

구조:
  - 좌측 서브메뉴 패널 (240px): One UI 유색 원형 뱃지 & 타원형 알약 캡슐 네비게이션
    · ⚙️ 앱 설정 (소프트 블루 뱃지)
    · 📜 오픈소스 라이선스 (소프트 민트 뱃지)
    · ℹ️ 프로그램 정보 (소프트 레드 뱃지)
  - 우측 상세 컨텐츠 영역 (QStackedWidget):
    · One UI 9.0 아일랜드 Focus Blocks (20px 스쿼클 곡률, 순백색 카드)
    · 단정하고 슬림한 여백과 명확한 타이포그래피 계층
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.geo_resolver import GeoLanguage
from src.core.i18n import LOCALE_FLAGS, SUPPORTED_LOCALES, i18n, t
from src.data.database import DatabaseManager
from src.data.licenses_data import OPEN_SOURCE_PACKAGES
from src.services.process_service import FolderStrategy
from src.ui.theme import Colors, Fonts

APP_VERSION = "0.9.1"


class OneUISettingRow(QWidget):
    """One UI 스타일의 단일 설정 항목 행 (좌측 라벨/설명, 우측 컨트롤)"""

    def __init__(self, title: str, description: str, control: QWidget, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(2)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #212529; border: none; background: transparent;")
        left.addWidget(self._title_lbl)

        self._desc_lbl = QLabel(description)
        self._desc_lbl.setObjectName("SubLabel")
        self._desc_lbl.setStyleSheet("border: none; background: transparent;")
        self._desc_lbl.setWordWrap(True)
        left.addWidget(self._desc_lbl)

        container = QWidget()
        container.setLayout(left)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout.addWidget(container, stretch=1)
        layout.addWidget(control)

    def set_text(self, title: str, description: str):
        self._title_lbl.setText(title)
        self._desc_lbl.setText(description)


class OneUINavButton(QFrame):
    """One UI 9.0 태블릿 설정 서브네비 아이템 (유색 뱃지 + 볼드 타이포 + 알약 캡슐)"""

    def __init__(self, icon: str, icon_bg: str, title: str, idx: int, parent=None):
        super().__init__(parent)
        self.idx = idx
        self._is_active = False
        self.setObjectName("OneUINavButton")
        self.setFrameShape(QFrame.NoFrame)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        self._badge = QLabel(icon)
        self._badge.setFixedSize(32, 32)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(f"background-color: {icon_bg}; border-radius: 16px; font-size: 16px; border: none;")
        layout.addWidget(self._badge)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 13px; font-weight: 600; color: #495057; border: none;")
        layout.addWidget(self._title, stretch=1)

        self.set_active(False)

    def set_title(self, title: str):
        self._title.setText(title)

    def set_active(self, active: bool):
        self._is_active = active
        if active:
            self.setStyleSheet("""
                QFrame#OneUINavButton {
                    background-color: #E8F2FD;
                    border-radius: 14px;
                    border: none;
                }
            """)
            self._title.setStyleSheet("font-size: 13px; font-weight: bold; color: #0072DE; border: none; background: transparent;")
        else:
            self.setStyleSheet("""
                QFrame#OneUINavButton {
                    background-color: transparent;
                    border-radius: 14px;
                    border: none;
                }
                QFrame#OneUINavButton:hover {
                    background-color: #F1F3F6;
                }
            """)
            self._title.setStyleSheet("font-size: 13px; font-weight: 600; color: #495057; border: none; background: transparent;")


class SettingsView(QWidget):
    """
    One UI 9.0 마스터-디테일 가로 2-Pane 분할 설정 뷰
    """

    def __init__(self, parent=None, on_db_reset: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setObjectName("SettingsView")
        self.on_db_reset = on_db_reset
        self._db_path_lbl = QLabel("")
        self._db_stat_lbl = QLabel("")
        self._setup_ui()
        self.retranslate_ui()
        i18n.language_changed.connect(lambda _: self.retranslate_ui())

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 1. 좌측 서브네비게이션 패널 (폭 240px) ─────────────────
        sub_nav = QFrame()
        sub_nav.setObjectName("OneUISubNav")
        sub_nav.setFixedWidth(240)
        sub_nav.setStyleSheet("background-color: #FAFBFD; border-right: 1px solid #E5E8EB;")
        sub_nav_layout = QVBoxLayout(sub_nav)
        sub_nav_layout.setContentsMargins(16, 24, 16, 20)
        sub_nav_layout.setSpacing(6)

        self._nav_title = QLabel("설정")
        self._nav_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #1C1D1F; padding-left: 8px; padding-bottom: 12px;")
        sub_nav_layout.addWidget(self._nav_title)

        nav_specs = [
            ("⚙️", "#E8F2FD", t("settings.nav_app", "앱 설정"), 0),
            ("📜", "#E6FCF5", t("settings.nav_licenses", "오픈소스 라이선스"), 1),
            ("💡", "#FFF9DB", t("settings.nav_about_app", "이 프로그램에 관하여"), 2),
            ("ℹ️", "#FFF5F5", t("settings.nav_about", "프로그램 정보"), 3),
        ]

        self._nav_items: list[OneUINavButton] = []
        for icon, icon_bg, title, idx in nav_specs:
            btn = OneUINavButton(icon, icon_bg, title, idx)
            btn.mousePressEvent = lambda e, i=idx: self._on_nav_clicked(i)
            self._nav_items.append(btn)
            sub_nav_layout.addWidget(btn)

        sub_nav_layout.addStretch()
        main_layout.addWidget(sub_nav)

        # ── 2. 우측 세부 컨텐츠 스택 (QStackedWidget) ──────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background-color: #F4F6F9;")

        self._page_app_settings = self._build_app_settings_page()
        self._page_licenses = self._build_licenses_page()
        self._page_about_app = self._build_about_app_page()
        self._page_about = self._build_about_page()

        self._stack.addWidget(self._page_app_settings)
        self._stack.addWidget(self._page_licenses)
        self._stack.addWidget(self._page_about_app)
        self._stack.addWidget(self._page_about)

        self._on_nav_clicked(0)
        main_layout.addWidget(self._stack, stretch=1)

    def _on_nav_clicked(self, index: int):
        for i, item in enumerate(self._nav_items):
            item.set_active(i == index)
        self._stack.setCurrentIndex(index)

    def _wrap_in_scroll(self, content_widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        scroll.setWidget(content_widget)
        return scroll

    def _build_focus_block(self, title: str, icon_symbol: str, icon_bg: str, rows: list[QWidget]) -> QFrame:
        """One UI 9.0 시그니처 20px 스쿼클 Focus Block 카드"""
        card = QFrame()
        card.setObjectName("OneUIFocusCard")
        card.setStyleSheet("""
            QFrame#OneUIFocusCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 20px;
            }
            QLabel {
                border: none;
                background-color: transparent;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        # 카드 헤더 (유색 뱃지 + 섹션 타이틀)
        c_hdr = QHBoxLayout()
        c_hdr.setSpacing(10)
        c_badge = QLabel(icon_symbol)
        c_badge.setFixedSize(30, 30)
        c_badge.setAlignment(Qt.AlignCenter)
        c_badge.setStyleSheet(f"background-color: {icon_bg}; border-radius: 15px; font-size: 15px; border: none;")
        c_hdr.addWidget(c_badge)

        c_title = QLabel(title)
        c_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1C1D1F; border: none;")
        c_hdr.addWidget(c_title)
        c_hdr.addStretch()
        layout.addLayout(c_hdr)
        layout.addSpacing(10)

        # 항목 목록
        for i, row in enumerate(rows):
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("background-color: #F1F3F6; max-height: 1px; border: none; margin: 4px 0px;")
            layout.addWidget(sep)
            layout.addWidget(row)

        card._title_label = c_title
        return card

    # ── 1) 앱 설정 페이지 ───────────────────────────────────────

    def _build_app_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(4)
        self._app_title_lbl = QLabel()
        self._app_title_lbl.setStyleSheet("font-size: 22px; font-weight: 800; color: #1C1D1F;")
        hdr_box.addWidget(self._app_title_lbl)

        self._app_sub_lbl = QLabel()
        self._app_sub_lbl.setStyleSheet("font-size: 12px; color: #6C757D;")
        hdr_box.addWidget(self._app_sub_lbl)
        layout.addLayout(hdr_box)

        db = DatabaseManager()

        # ── 카드 0: 언어 및 지역 설정 ────────────────────────────────
        self.app_lang_combo = QComboBox()
        for loc_code, loc_name in SUPPORTED_LOCALES.items():
            flag = LOCALE_FLAGS.get(loc_code, "🌐")
            self.app_lang_combo.addItem(f"{flag} {loc_name} ({loc_code})", loc_code)
        
        # 현재 설정된 언어 복원 (DB -> i18n -> 기본)
        saved_lang = db.get_setting("app_language", i18n.current_locale)
        idx = self.app_lang_combo.findData(saved_lang)
        if idx >= 0:
            self.app_lang_combo.setCurrentIndex(idx)
        self.app_lang_combo.setFixedWidth(280)
        self.app_lang_combo.setStyleSheet("""
            QComboBox {
                background-color: #F8F9FA;
                border: 1px solid #DCE1E7;
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 12px;
                color: #1C1D1F;
            }
        """)

        self.geo_lang_combo = QComboBox()
        self._populate_geo_lang_combo()
        self.geo_lang_combo.setFixedWidth(280)
        self.geo_lang_combo.setStyleSheet("""
            QComboBox {
                background-color: #F8F9FA;
                border: 1px solid #DCE1E7;
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 12px;
                color: #1C1D1F;
            }
        """)

        # 저장된 역지오코딩 언어 복원
        saved_geo_lang = db.get_setting("geo_language")
        if saved_geo_lang:
            geo_idx = self.geo_lang_combo.findData(saved_geo_lang)
            if geo_idx >= 0:
                self.geo_lang_combo.setCurrentIndex(geo_idx)
        else:
            # 기본값 규칙: 한국어면 KOREAN, 그 외면 ENGLISH
            init_geo = GeoLanguage.KOREAN if saved_lang == "ko_KR" else GeoLanguage.ENGLISH
            geo_idx = self.geo_lang_combo.findData(init_geo)
            if geo_idx >= 0:
                self.geo_lang_combo.setCurrentIndex(geo_idx)

        def _on_app_lang_changed(index: int):
            new_lang = self.app_lang_combo.currentData()
            if not new_lang:
                return
            db.set_setting("app_language", new_lang)
            i18n.set_locale(new_lang)

            # 언어 변경 시 역지오코딩 언어 자동 매칭 규칙:
            # 한국어(ko_KR)이면 한국어(KOREAN), 그 외 언어이면 영어(ENGLISH)
            target_geo = GeoLanguage.KOREAN if new_lang == "ko_KR" else GeoLanguage.ENGLISH
            g_idx = self.geo_lang_combo.findData(target_geo)
            if g_idx >= 0:
                self.geo_lang_combo.setCurrentIndex(g_idx)
                db.set_setting("geo_language", target_geo.value if hasattr(target_geo, 'value') else str(target_geo))

        def _on_geo_lang_changed(index: int):
            new_geo = self.geo_lang_combo.currentData()
            if new_geo:
                val = new_geo.value if hasattr(new_geo, 'value') else str(new_geo)
                db.set_setting("geo_language", val)

        self.app_lang_combo.currentIndexChanged.connect(_on_app_lang_changed)
        self.geo_lang_combo.currentIndexChanged.connect(_on_geo_lang_changed)

        self._card0_row0 = OneUISettingRow("", "", self.app_lang_combo)
        self._card0_row1 = OneUISettingRow("", "", self.geo_lang_combo)
        self._card0 = self._build_focus_block("", "🌐", "#EBFBEE", [self._card0_row0, self._card0_row1])
        layout.addWidget(self._card0)

        # 카드 1: 미디어 정리 및 저장 전략
        self.strategy_combo = QComboBox()
        self._populate_strategy_combo()
        self.strategy_combo.setFixedWidth(280)
        self.strategy_combo.setStyleSheet("""
            QComboBox {
                background-color: #F8F9FA;
                border: 1px solid #DCE1E7;
                border-radius: 10px;
                padding: 6px 12px;
                font-size: 12px;
                color: #1C1D1F;
            }
        """)

        saved_strategy = db.get_setting("folder_strategy")
        if saved_strategy:
            s_idx = self.strategy_combo.findData(saved_strategy)
            if s_idx >= 0:
                self.strategy_combo.setCurrentIndex(s_idx)

        def _on_strategy_changed(index: int):
            strat = self.strategy_combo.currentData()
            if strat:
                val = strat.value if hasattr(strat, 'value') else str(strat)
                db.set_setting("folder_strategy", val)

        self.strategy_combo.currentIndexChanged.connect(_on_strategy_changed)

        mode_box = QWidget()
        mode_box.setStyleSheet("background: transparent;")
        m_layout = QHBoxLayout(mode_box)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.setSpacing(12)
        self._r_copy = QRadioButton()
        self._r_move = QRadioButton()
        self._r_copy.setChecked(True)
        self._r_copy.setStyleSheet("color: #0072DE; font-weight: bold; font-size: 12px;")
        self._r_move.setStyleSheet("color: #495057; font-size: 12px;")
        m_layout.addWidget(self._r_copy)
        m_layout.addWidget(self._r_move)

        self._card1_row0 = OneUISettingRow("", "", self.strategy_combo)
        self._card1_row1 = OneUISettingRow("", "", mode_box)
        self._card1 = self._build_focus_block("", "📁", "#E8F2FD", [self._card1_row0, self._card1_row1])
        layout.addWidget(self._card1)

        # 카드 2: 데이터베이스 및 시스템 관리
        self._db_path_lbl.setStyleSheet("font-size: 11px; font-family: monospace; color: #495057; border: none; background: transparent;")
        self._db_stat_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #0072DE; border: none; background: transparent;")

        self._reset_btn = QPushButton()
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.setFixedHeight(30)
        self._reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF5F5;
                color: #FA5252;
                border: 1px solid #FFC9C9;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 14px;
            }
            QPushButton:hover {
                background-color: #FFE3E3;
                border-color: #FFA8A8;
            }
            QPushButton:pressed {
                background-color: #FFC9C9;
            }
        """)
        self._reset_btn.clicked.connect(self._on_reset_database)

        self._update_db_storage_stats()

        self._card2_row0 = OneUISettingRow("", "", self._db_path_lbl)
        self._card2_row1 = OneUISettingRow("", "", self._db_stat_lbl)
        self._card2_row2 = OneUISettingRow("", "", self._reset_btn)
        self._card2 = self._build_focus_block("", "🛠", "#FFF3BF", [self._card2_row0, self._card2_row1, self._card2_row2])
        layout.addWidget(self._card2)
        layout.addStretch()

        return self._wrap_in_scroll(page)

    def _populate_geo_lang_combo(self):
        cur_data = self.geo_lang_combo.currentData() if hasattr(self, 'geo_lang_combo') else None
        self.geo_lang_combo.blockSignals(True)
        self.geo_lang_combo.clear()
        self.geo_lang_combo.addItem(t("geo_languages.SYSTEM", "💻 시스템 언어 (자동 감지)"), GeoLanguage.SYSTEM)
        self.geo_lang_combo.addItem(t("geo_languages.KOREAN", "🇰🇷 한국어 (대한민국 / 서울)"), GeoLanguage.KOREAN)
        self.geo_lang_combo.addItem(t("geo_languages.ENGLISH", "🇺🇸 영어 (South Korea / Seoul)"), GeoLanguage.ENGLISH)
        if cur_data is not None:
            idx = self.geo_lang_combo.findData(cur_data)
            if idx >= 0:
                self.geo_lang_combo.setCurrentIndex(idx)
        self.geo_lang_combo.blockSignals(False)

    def _populate_strategy_combo(self):
        cur_data = self.strategy_combo.currentData() if hasattr(self, 'strategy_combo') else None
        self.strategy_combo.blockSignals(True)
        self.strategy_combo.clear()
        self.strategy_combo.addItem(t("strategies.YEAR_MONTH", "📅 YYYY/MM (연도/월별)"), FolderStrategy.YEAR_MONTH)
        self.strategy_combo.addItem(t("strategies.YEAR_YEAR_MONTH", "📅 YYYY/YYYY-MM (연도/연도-월)"), FolderStrategy.YEAR_YEAR_MONTH)
        self.strategy_combo.addItem(t("strategies.YEAR_ONLY", "📅 YYYY (연도별)"), FolderStrategy.YEAR_ONLY)
        self.strategy_combo.addItem(t("strategies.YEAR_MONTH_DAY", "📅 YYYY/MM/DD (연도/월/일자별 정밀)"), FolderStrategy.YEAR_MONTH_DAY)
        self.strategy_combo.addItem(t("strategies.CAMERA_YEAR_MONTH", "📷 촬영기기/YYYY/MM (기종별 분류 후 날짜)"), FolderStrategy.CAMERA_YEAR_MONTH)
        self.strategy_combo.addItem(t("strategies.YEAR_MONTH_CAMERA", "📷 YYYY/MM/촬영기기 (날짜 분류 후 기종별)"), FolderStrategy.YEAR_MONTH_CAMERA)
        self.strategy_combo.addItem(t("strategies.TYPE_YEAR_MONTH", "🎬 미디어유형/YYYY/MM (사진/동영상 분리)"), FolderStrategy.TYPE_YEAR_MONTH)
        self.strategy_combo.addItem(t("strategies.GEO_COUNTRY_CITY", "🌍 국가/도시/YYYY/MM (여행지·지역별 분류)"), FolderStrategy.GEO_COUNTRY_CITY)
        self.strategy_combo.addItem(t("strategies.GEO_COUNTRY", "🌍 국가/YYYY/MM (국가별 분류 후 날짜)"), FolderStrategy.GEO_COUNTRY)
        self.strategy_combo.addItem(t("strategies.ALBUM_NAME", "🏷️ 원본 앨범명 (Google 포토 앨범 유지)"), FolderStrategy.ALBUM_NAME)
        if cur_data is not None:
            idx = self.strategy_combo.findData(cur_data)
            if idx >= 0:
                self.strategy_combo.setCurrentIndex(idx)
        self.strategy_combo.blockSignals(False)

    def retranslate_ui(self):
        """다국어 변경 시 설정 뷰 UI 실시간 갱신"""
        self._nav_title.setText(t("settings.title", "설정"))
        if len(self._nav_items) >= 4:
            self._nav_items[0].set_title(t("settings.nav_app", "앱 설정"))
            self._nav_items[1].set_title(t("settings.nav_licenses", "오픈소스 라이선스"))
            self._nav_items[2].set_title(t("settings.nav_about_app", "이 프로그램에 관하여"))
            self._nav_items[3].set_title(t("settings.nav_about", "프로그램 정보"))

        self._app_title_lbl.setText(t("settings.title", "앱 설정"))
        self._app_sub_lbl.setText(t("settings.subtitle", "Google Takeout 사진 정리 전략 및 애플리케이션 기본 동작을 맞춤 설정합니다."))

        # 카드 0
        self._card0._title_label.setText(t("settings.card_lang_title", "언어 및 지역 설정"))
        self._card0_row0.set_text(t("settings.row_app_lang", "프로그램 표시 언어"), t("settings.row_app_lang_desc", "애플리케이션 전체 사용자 인터페이스(UI)에 적용할 언어를 선택합니다."))
        self._card0_row1.set_text(t("settings.row_geo_lang", "기본 위치 표기 언어"), t("settings.row_geo_lang_desc", "GPS 기반 폴더 분류 및 지명 표기 시 사용할 기본 언어입니다 (한국어 UI는 한국어, 그 외는 영어 자동 매칭)."))
        self._populate_geo_lang_combo()

        # 카드 1
        self._card1._title_label.setText(t("settings.card_strategy_title", "기본 정리 전략"))
        self._card1_row0.set_text(t("settings.row_default_strategy", "기본 폴더 구조"), t("settings.row_default_strategy_desc", "새 정리 작업 시 기본으로 적용될 디렉토리 계층 구조입니다."))
        self._card1_row1.set_text(t("settings.row_default_mode", "기본 처리 방식"), t("settings.row_default_mode_desc", "안전하게 복사할지, 원본을 이동할지 결정합니다."))
        self._r_copy.setText(t("job.mode_copy", "복사 (원본 보존)"))
        self._r_move.setText(t("job.mode_move", "이동 (원본 삭제)"))
        self._populate_strategy_combo()

        # 카드 2
        self._card2._title_label.setText(t("settings.card_db_title", "데이터베이스 및 저장공간 관리"))
        self._card2_row0.set_text(t("settings.row_db_path", "로컬 색인 데이터베이스"), t("settings.row_db_path_desc", "미디어 메타데이터 검색 및 중복 방지용 SQLite 저장소입니다."))
        self._card2_row1.set_text(t("settings.row_db_stat", "저장된 미디어 색인 현황"), t("settings.row_db_stat_desc", "현재 데이터베이스에 등록된 전체 파일 및 용량 정보입니다."))
        self._card2_row2.set_text(t("settings.row_db_reset", "데이터베이스 초기화"), t("settings.row_db_reset_desc", "이전 작업 이력과 파일 색인을 모두 삭제하여 중복 스킵 문제를 해결합니다."))
        self._reset_btn.setText(t("settings.btn_reset_db", "🗑 데이터베이스 초기화"))
        self._update_db_storage_stats()

        # 서브페이지 동적 리빌드 및 스택 교체 (언어 변경 즉시 반영)
        cur_idx = self._stack.currentIndex()

        # 1. 라이선스 페이지
        new_lic = self._build_licenses_page()
        self._stack.removeWidget(self._page_licenses)
        self._page_licenses.deleteLater()
        self._page_licenses = new_lic
        self._stack.insertWidget(1, self._page_licenses)

        # 2. 이 프로그램에 관하여 페이지
        new_about_app = self._build_about_app_page()
        self._stack.removeWidget(self._page_about_app)
        self._page_about_app.deleteLater()
        self._page_about_app = new_about_app
        self._stack.insertWidget(2, self._page_about_app)

        # 3. 프로그램 정보 페이지
        new_about = self._build_about_page()
        self._stack.removeWidget(self._page_about)
        self._page_about.deleteLater()
        self._page_about = new_about
        self._stack.insertWidget(3, self._page_about)

        self._stack.setCurrentIndex(cur_idx)

    def _update_db_storage_stats(self):
        """현재 DB 저장 경로 및 등록된 레코드 통계 갱신"""
        try:
            db = DatabaseManager()
            info = db.get_storage_info()
            records = info.get("total_records", 0)
            size_b = info.get("file_size_bytes", 0)
            if size_b > 1024 * 1024:
                size_str = f"{size_b / (1024 * 1024):.2f} MB"
            else:
                size_str = f"{size_b / 1024:.1f} KB"
            self._db_stat_lbl.setText(f"{records:,}{t('common.files', '개 파일')} ({size_str})")

            full_path = str(info.get("db_path", ""))
            short_path = Path(full_path).name if full_path else "library.db"
            self._db_path_lbl.setText(f".../data/{short_path}")
            self._db_path_lbl.setToolTip(full_path)
        except Exception:
            self._db_stat_lbl.setText("-")

    def _on_reset_database(self):
        """사용자 확인 후 SQLite DB 레코드 완전 초기화"""
        reply = QMessageBox.question(
            self,
            t("settings.reset_confirm_title", "데이터베이스 초기화 확인"),
            t("settings.reset_confirm_msg", "정말로 데이터베이스를 초기화하시겠습니까?\n\n이 작업은 되돌릴 수 없으며, 모든 미디어 색인 레코드와 작업 이력이 삭제됩니다.\n(※ 실제 디스크에 저장된 사진/동영상 원본 파일은 삭제되지 않습니다.)"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            db = DatabaseManager()
            if db.reset_database():
                self._update_db_storage_stats()
                QMessageBox.information(
                    self,
                    t("settings.reset_success_title", "초기화 완료"),
                    t("settings.reset_success_msg", "데이터베이스가 성공적으로 초기화되었습니다.\n모든 이전 작업 내역과 색인이 정리되었습니다."),
                )
                if callable(self.on_db_reset):
                    self.on_db_reset()
            else:
                QMessageBox.critical(
                    self,
                    t("settings.reset_fail_title", "초기화 실패"),
                    t("settings.reset_fail_msg", "데이터베이스 초기화 중 오류가 발생했습니다. 로그를 확인해 주세요."),
                )

    # ── 2) 오픈소스 라이선스 페이지 ──────────────────────────────

    def _build_licenses_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(4)
        title = QLabel(t("settings.licenses.title", "오픈소스 라이선스"))
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #1C1D1F;")
        hdr_box.addWidget(title)

        sub = QLabel(t("settings.licenses.subtitle", "본 소프트웨어는 검증된 안정적인 오픈소스 라이브러리를 활용하여 제작되었습니다."))
        sub.setStyleSheet("font-size: 12px; color: #6C757D;")
        hdr_box.addWidget(sub)
        layout.addLayout(hdr_box)

        rows = []
        for pkg in OPEN_SOURCE_PACKAGES:
            name = pkg["name"]
            lic = pkg["license"]
            author = pkg["author"]
            url = pkg.get("url", "")
            notice = pkg.get("notice", "")
            desc_key = pkg.get("desc_key", "")
            desc_default = pkg.get("desc_default", "")
            desc = t(f"settings.licenses.{desc_key}", desc_default) if desc_key else desc_default

            item_widget = QWidget()
            item_widget.setStyleSheet("background: transparent; border: none;")
            i_layout = QVBoxLayout(item_widget)
            i_layout.setContentsMargins(0, 8, 0, 8)
            i_layout.setSpacing(6)

            # 상단 헤더 행 (이름 + 라이선스 뱃지 + 토글 버튼)
            top = QHBoxLayout()
            top.setSpacing(8)

            n_lbl = QLabel(name)
            n_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #1C1D1F;")
            top.addWidget(n_lbl)

            lic_badge = QLabel(f" {lic} ")
            lic_badge.setStyleSheet(
                "background-color: #E8F2FD; color: #0072DE; border-radius: 6px; font-size: 11px; font-weight: bold; padding: 2px 8px;"
            )
            top.addWidget(lic_badge)
            top.addStretch()

            toggle_btn = QPushButton(f"📄 {t('settings.licenses.btn_view', '라이선스 보기')} ▼")
            toggle_btn.setObjectName("SecondaryButton")
            toggle_btn.setCursor(Qt.PointingHandCursor)
            toggle_btn.setFixedHeight(26)
            toggle_btn.setStyleSheet("""
                QPushButton#SecondaryButton {
                    background-color: #F8F9FA;
                    border: 1px solid #DCE1E7;
                    border-radius: 8px;
                    color: #495057;
                    font-size: 11px;
                    font-weight: 500;
                    padding: 2px 10px;
                }
                QPushButton#SecondaryButton:hover {
                    background-color: #E8F2FD;
                    color: #0072DE;
                    border-color: #0072DE;
                }
            """)
            top.addWidget(toggle_btn)
            i_layout.addLayout(top)

            desc_lbl = QLabel(t("settings.licenses.author_format", f"{desc} • 저작권자: {author}", desc=desc, author=author))
            desc_lbl.setObjectName("SubLabel")
            desc_lbl.setStyleSheet("font-size: 12px; color: #6C757D;")
            i_layout.addWidget(desc_lbl)

            # 하단 접이식 라이선스 상세 박스
            detail_frame = QFrame()
            detail_frame.setVisible(False)
            detail_frame.setStyleSheet("""
                QFrame {
                    background-color: #F8F9FA;
                    border: 1px solid #E9ECEF;
                    border-radius: 12px;
                }
            """)
            d_layout = QVBoxLayout(detail_frame)
            d_layout.setContentsMargins(14, 12, 14, 12)
            d_layout.setSpacing(8)

            notice_edit = QPlainTextEdit(notice)
            notice_edit.setReadOnly(True)
            notice_edit.setFixedHeight(120)
            notice_edit.setStyleSheet(
                "font-family: monospace; font-size: 11px; background: transparent; border: none; color: #343A40; line-height: 1.4;"
            )
            d_layout.addWidget(notice_edit)

            # 하단 링크 및 복사 버튼 액션 행
            act_row = QHBoxLayout()
            if url:
                link_lbl = QLabel(f"<a href='{url}' style='color: #0072DE; text-decoration: none;'>🌐 {t('settings.licenses.homepage', '공식 웹사이트')} ↗</a>")
                link_lbl.setOpenExternalLinks(True)
                link_lbl.setStyleSheet("font-size: 11px;")
                act_row.addWidget(link_lbl)

            act_row.addStretch()

            copy_btn = QPushButton(f"📋 {t('settings.licenses.btn_copy', '전문 복사')}")
            copy_btn.setCursor(Qt.PointingHandCursor)
            copy_btn.setFixedHeight(24)
            copy_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FFFFFF;
                    border: 1px solid #CED4DA;
                    border-radius: 6px;
                    color: #495057;
                    font-size: 11px;
                    padding: 2px 8px;
                }
                QPushButton:hover {
                    background-color: #E8F2FD;
                    color: #0072DE;
                    border-color: #0072DE;
                }
            """)

            def _make_copy_handler(btn: QPushButton, text: str):
                def _copy():
                    clipboard = QGuiApplication.clipboard()
                    if clipboard:
                        clipboard.setText(text)
                    btn.setText(f"✅ {t('settings.licenses.copied', '복사됨!')}")
                    QTimer.singleShot(1500, lambda: btn.setText(f"📋 {t('settings.licenses.btn_copy', '전문 복사')}"))
                return _copy

            copy_btn.clicked.connect(_make_copy_handler(copy_btn, notice))
            act_row.addWidget(copy_btn)

            d_layout.addLayout(act_row)
            i_layout.addWidget(detail_frame)

            def _make_toggle_handler(btn: QPushButton, frame: QFrame):
                def _toggle():
                    vis = not frame.isVisible()
                    frame.setVisible(vis)
                    btn.setText(
                        f"📄 {t('settings.licenses.btn_hide', '접기')} ▲"
                        if vis
                        else f"📄 {t('settings.licenses.btn_view', '라이선스 보기')} ▼"
                    )
                return _toggle

            toggle_btn.clicked.connect(_make_toggle_handler(toggle_btn, detail_frame))

            rows.append(item_widget)

        layout.addWidget(self._build_focus_block(t("settings.licenses.sec_packages", "사용된 오픈소스 패키지 고지"), "📜", "#E6FCF5", rows))
        layout.addStretch()

        return self._wrap_in_scroll(page)

    # ── 3) 이 프로그램에 관하여 페이지 (About This Program) ──────

    def _build_how_it_works_page(self) -> QWidget:
        """하위 호환성을 위한 alias"""
        return self._build_about_app_page()

    def _build_about_app_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        # 상단 인트로 헤더
        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(4)
        title = QLabel(t("settings.about_app.title", "이 프로그램에 관하여"))
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #1C1D1F;")
        hdr_box.addWidget(title)

        sub = QLabel(
            t(
                "settings.about_app.subtitle",
                "Google Photos Takeout 데이터의 구조적 결함을 완벽히 해결하고, 안전한 무손실 메타데이터 복원 및 지능형 미디어 관리를 제공하는 올인원 데스크톱 솔루션입니다."
            )
        )
        sub.setStyleSheet("font-size: 12px; color: #6C757D; line-height: 1.5;")
        sub.setWordWrap(True)
        hdr_box.addWidget(sub)
        layout.addLayout(hdr_box)

        # ── 1. 개발 배경 & Takeout의 4대 구조적 문제점 ──
        p1_rows = [
            self._create_info_row(
                t("settings.about_app.takeout_1_title", "1. 메타데이터 분리 (Sidecar JSON 분할)"),
                t("settings.about_app.takeout_1_desc", "구글 포토는 다운로드 시 사진/동영상 파일에서 촬영 일시, GPS 좌표, 설명(캡션)을 분리하여 별도의 .json 파일에 따로 담아 배포합니다. 이로 인해 미디어 파일 자체는 메타데이터가 텅 빈 상태가 됩니다.")
            ),
            self._create_info_row(
                t("settings.about_app.takeout_2_title", "2. OS 파일 타임스탬프 변조 (시간순 정렬 파괴)"),
                t("settings.about_app.takeout_2_desc", "압축을 해제하면 모든 파일의 생성일·수정일이 '다운로드 받은 시점(오늘)'으로 덮어씌워집니다. 스마트폰, PC 갤러리 앱, NAS에 넣었을 때 10년 전 사진이 오늘 촬영된 것으로 인식되어 정렬이 완전히 무너집니다.")
            ),
            self._create_info_row(
                t("settings.about_app.takeout_3_title", "3. 파일명 47자/51자 잘림 및 넘버링 불일치"),
                t("settings.about_app.takeout_3_desc", "구글의 Takeout 패키징 시스템은 긴 파일명을 47자~51자 부근에서 임의로 자릅니다. 또한 동일 파일명이 존재할 때 미디어는 '사진(1).jpg'로, 메타데이터는 '사진.jpg(1).json'으로 규칙 없이 어긋나게 생성합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.takeout_4_title", "4. 앨범별 중복 복사로 인한 극심한 용량 낭비"),
                t("settings.about_app.takeout_4_desc", "하나의 사진이 여러 앨범에 함께 등록되어 있다면, Takeout 압축 파일 안에는 완전히 동일한 사진 파일이 각 앨범 폴더마다 물리적으로 복사되어 다운로드 용량이 수 배로 낭비됩니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_takeout_title", "Google Takeout의 4대 구조적 한계와 해결"), "🚨", "#FFF5F5", p1_rows))

        # ── 2. 미디어-메타데이터 5단계 정밀 매칭 엔진 ──
        p2_rows = [
            self._create_step_row(
                t("settings.about_app.engine_step_1_tag", "1단계"),
                t("settings.about_app.engine_step_1_title", "직접 1:1 매칭 (Exact Direct Match)"),
                t("settings.about_app.engine_step_1_desc", "미디어 파일명과 완전히 일치하는 JSON 파일을 우선 탐색합니다."),
                t("settings.about_app.engine_step_1_example", "IMG_1234.jpg ➔ IMG_1234.jpg.json 또는 IMG_1234.json")
            ),
            self._create_step_row(
                t("settings.about_app.engine_step_2_tag", "2단계"),
                t("settings.about_app.engine_step_2_title", "괄호 넘버링 정규화 (Numbering Normalization)"),
                t("settings.about_app.engine_step_2_desc", "구글의 불규칙한 중복 번호 표기 위치를 정규화하여 교차 매핑합니다."),
                t("settings.about_app.engine_step_2_example", "IMG_1234(1).jpg ➔ IMG_1234.jpg(1).json, IMG_1234(1).json")
            ),
            self._create_step_row(
                t("settings.about_app.engine_step_3_tag", "3단계"),
                t("settings.about_app.engine_step_3_title", "잘림 역추적 매칭 (Truncation Reversal)"),
                t("settings.about_app.engine_step_3_desc", "47자~51자 길이 제한으로 인해 잘려나간 JSON 파일명의 접두어와 확장자를 역추적합니다."),
                t("settings.about_app.engine_step_3_example", "20230731_VeryLongFileNameIsTruncatedH...jpg ➔ 20230731_VeryLongFileNameIsTruncatedH....json")
            ),
            self._create_step_row(
                t("settings.about_app.engine_step_4_tag", "4단계"),
                t("settings.about_app.engine_step_4_title", "편집본 파생 상속 (Edited / Effects Derivative)"),
                t("settings.about_app.engine_step_4_desc", "구글 포토에서 필터를 적용했거나 회전한 편집본에 원본의 메타데이터를 계승합니다."),
                t("settings.about_app.engine_step_4_example", "IMG_1234-edited.jpg, IMG_1234-effects.jpg ➔ IMG_1234.jpg.json 상속")
            ),
            self._create_step_row(
                t("settings.about_app.engine_step_5_tag", "5단계"),
                t("settings.about_app.engine_step_5_title", "타임스탬프 휴리스틱 검증 (Timestamp Verification)"),
                t("settings.about_app.engine_step_5_desc", "파일명이 변형된 경우, 파일 내부의 잔존 헤더 시간과 JSON의 photoTakenTime 오차를 비교 검증합니다."),
                t("settings.about_app.engine_step_5_example", "오차 범위 ±60초 이내의 동일 폴더 내 유일 후보군 최종 매칭")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_engine_title", "미디어 & 메타데이터 5단계 정밀 매칭 엔진"), "🧬", "#E8F2FD", p2_rows))

        # ── 3. 실제 처리 예시 (Before vs After 대조) ──
        compare_card = self._build_comparison_card()
        layout.addWidget(compare_card)

        # ── 4. 오프라인 GPS 역지오코딩 & 3단계 계층화 ──
        p4_rows = [
            self._create_info_row(
                t("settings.about_app.geo_1_title", "172,038개 전 세계 거점 K-D Tree 초고속 색인"),
                t("settings.about_app.geo_1_desc", "인구 1,000명 이상의 전 세계 17만 개 도시(GeoNames) 좌표를 5.37MB 초경량 바이너리로 패킹하여 메모리에 상주시킵니다. 2D K-D Tree 알고리즘을 통해 인터넷 연결 없이도 사진 1장당 0.05ms(0.00005초) 만에 가장 가까운 거점을 산출합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.geo_2_title", "3단계 행정구역 계층화 (Top-down Hierarchy)"),
                t("settings.about_app.geo_2_desc", "위치 정보를 '국가 ➔ 주/도 ➔ 시/군/구'의 3단계로 표준화합니다. 용량 트리맵이나 라이브러리 검색 시 상위 권역부터 하위 도시까지 자연스럽게 드릴다운 탐색할 수 있습니다.")
            ),
            self._create_info_row(
                t("settings.about_app.geo_3_title", "주요 관광 명소 우선 보정 엔진"),
                t("settings.about_app.geo_3_desc", "전 세계 주요 여행 거점 및 관광 명소를 최우선 색인하여, 단순 행정구역명을 넘어 사용자가 실제 체감하는 여행지 중심의 직관적 명칭을 부여합니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_geocoding_title", "오프라인 GPS 역지오코딩 & 계층화 엔진"), "🌍", "#E6FCF5", p4_rows))

        # ── 5. 파일명 일괄 변경 마법사 (신규) ──
        p_rename_rows = [
            self._create_info_row(
                t("settings.about_app.rename_1_title", "메타데이터 기반 실시간 토큰 빌더"),
                t("settings.about_app.rename_1_desc", "복원된 촬영 날짜·시간, 카메라 제조사/모델, 국가/도시 위치 등 풍부한 메타데이터 토큰을 조합하여 원하는 형식의 파일명으로 손쉽게 일괄 변환합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.rename_2_title", "풍부한 서식 옵션 및 라이브 미리보기"),
                t("settings.about_app.rename_2_desc", "구분자 기호(언더바, 하이픈 등), 대소문자 변환, 괄호 스타일을 실시간으로 설정하고 변경 결과를 즉각 라이브 테이블에서 사전 검증할 수 있습니다.")
            ),
            self._create_info_row(
                t("settings.about_app.rename_3_title", "Zero Data Loss 무손실 안전 변환"),
                t("settings.about_app.rename_3_desc", "디스크 쓰기 전 이름 충돌을 사전 감지하여 중복 번호를 자동 할당하며, 원본 미디어의 데이터 손상 없이 파일명만 안전하게 갱신합니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_rename_title", "지능형 파일명 일괄 변경 마법사 (Batch Rename)"), "🏷️", "#FFF5F5", p_rename_rows))

        # ── 6. 미디어 폴더 구조 재구성 마법사 (신규) ──
        p_reorg_rows = [
            self._create_info_row(
                t("settings.about_app.reorg_1_title", "10가지 맞춤형 디스크 보관 전략"),
                t("settings.about_app.reorg_1_desc", "'년/월', '년/월/일', '촬영기기/년/월', '국가/도시/년/월' 등 미디어 특성에 맞춘 10가지 자유로운 보관 전략을 제공합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.reorg_2_title", "제자리 고속 이동 및 신규 위치 정리 지원"),
                t("settings.about_app.reorg_2_desc", "동일 드라이브 내 제자리(In-place) 고속 디렉토리 재배치뿐 아니라 새로운 외장 디스크나 대상 폴더로의 정리 이동을 모두 지원합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.reorg_3_title", "빈 디렉토리 자동 청소 & 안전 이동"),
                t("settings.about_app.reorg_3_desc", "파일 이동 후 잔여 빈 폴더들을 깨끗하게 자동 정리하며, 동일 드라이브 내 초고속 파일 시스템 포인터 이동으로 대용량 라이브러리도 수 초 만에 정리합니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_reorganize_title", "초고속 미디어 폴더 구조 재구성 (Reorganize)"), "📁", "#FFF9DB", p_reorg_rows))

        # ── 7. 스마트 검사 및 시각화 도구 (신규) ──
        p_tools_rows = [
            self._create_info_row(
                t("settings.about_app.tools_1_title", "11개 주요 메타데이터 Before/After 가로 정밀 대조표"),
                t("settings.about_app.tools_1_desc", "촬영일시, GPS, 카메라, 렌즈 등 11개 핵심 항목의 정리 전후 상태를 1:1로 대조하고, 미디어 바이너리에 저장된 Raw EXIF 및 QuickTime 헤더를 실시간 파싱하여 검사합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.tools_2_title", "Squarified Treemap 디스크 용량 시각화 탐색기"),
                t("settings.about_app.tools_2_desc", "수만 장의 사진이 디스크 용량을 얼마나 차지하고 있는지 날짜별, 카메라 기종별, 국가/도시별, 폴더 계층별로 인터랙티브하게 드릴다운하며 직관적으로 분석합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.tools_3_title", "비동기 지연 로딩(Lazy Loading) & SQLite 로컬 색인"),
                t("settings.about_app.tools_3_desc", "QThreadPool 기반의 멀티스레드 비동기 지연 로딩으로 수만 건의 파일 트리도 끊김 없이 부드럽게 탐색하며, SQLite3 FTS5 전문 검색을 통해 즉각적인 파일 검색을 지원합니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_tools_title", "스마트 검사 및 시각화 도구 (Inspector & Treemap)"), "🔍", "#E8F2FD", p_tools_rows))

        # ── 8. 글로벌 6개 국어 지원 및 시스템 최적화 (신규) ──
        p_i18n_rows = [
            self._create_info_row(
                t("settings.about_app.i18n_1_title", "글로벌 6개 국어 실시간 무중단 전환"),
                t("settings.about_app.i18n_1_desc", "한국어, 영어, 일본어, 중국어 간체, 중국어 번체(대만/홍콩)를 완벽 지원하며, 앱을 재시작할 필요 없이 설정 변경 즉시 모든 UI가 실시간 전환됩니다.")
            ),
            self._create_info_row(
                t("settings.about_app.i18n_2_title", "OS 시스템 로케일 자동 감지 및 스마트 연동"),
                t("settings.about_app.i18n_2_desc", "사용자의 OS 기본 언어를 자동 감지하여 최적의 인터페이스와 지오코딩 언어를 기본 매칭합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.i18n_3_title", "크로스플랫폼 최적화 (macOS / Windows)"),
                t("settings.about_app.i18n_3_desc", "장시간 대용량 파일 정리 중 시스템 절전 모드로의 진입을 방지하는 스마트 웨이크락(Wakelock)과 OS 탐색기/클립보드 연동을 기본 탑재했습니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_i18n_cross_title", "글로벌 6개 국어 지원 및 시스템 최적화"), "🌐", "#E6FCF5", p_i18n_rows))

        # ── 9. 핵심 안전 원칙 및 데이터 무결성 보장 ──
        p_safety_rows = [
            self._create_info_row(
                t("settings.about_app.safety_1_title", "100% 로컬 오프라인 (완벽한 프라이버시)"),
                t("settings.about_app.safety_1_desc", "인터넷 연결이 필요 없으며, 소중한 가족 사진과 개인 위치 정보가 외부 네트워크로 단 1바이트도 유출되지 않습니다.")
            ),
            self._create_info_row(
                t("settings.about_app.safety_2_title", "비파괴 무손실 바이너리 패칭"),
                t("settings.about_app.safety_2_desc", "사진이나 동영상의 화질을 재압축하거나 손상시키지 않고, 메타데이터 헤더 청크만 안전하게 삽입하여 원본 화질을 100% 보존합니다.")
            ),
            self._create_info_row(
                t("settings.about_app.safety_3_title", "SHA-256 해시 검사 기반 무결성 중복 필터링"),
                t("settings.about_app.safety_3_desc", "동일 파일명 충돌 시 해시 비교를 통해 중복 파일은 스킵하고, 다른 내용일 경우 시퀀스 번호를 자동 부여하여 데이터 손실을 원천 차단합니다.")
            ),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_app.sec_safety_title", "핵심 안전 원칙 및 데이터 무결성 보장"), "🛡️", "#F3F0FF", p_safety_rows))

        layout.addStretch()
        return self._wrap_in_scroll(page)

    def _create_info_row(self, title: str, desc: str) -> QWidget:
        """설명 텍스트 행 위젯"""
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1C1D1F;")
        layout.addWidget(t_lbl)

        d_lbl = QLabel(desc)
        d_lbl.setStyleSheet("font-size: 12px; color: #495057; line-height: 1.6;")
        d_lbl.setWordWrap(True)
        layout.addWidget(d_lbl)

        return widget

    def _create_step_row(self, step_tag: str, title: str, desc: str, example: str) -> QWidget:
        """단계별 파이프라인 행 위젯"""
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        tag_badge = QLabel(f" {step_tag} ")
        tag_badge.setStyleSheet(
            "background-color: #E8F2FD; color: #0072DE; border-radius: 6px; font-size: 11px; font-weight: bold; padding: 2px 6px;"
        )
        top_row.addWidget(tag_badge)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1C1D1F;")
        top_row.addWidget(t_lbl)
        top_row.addStretch()
        layout.addLayout(top_row)

        d_lbl = QLabel(desc)
        d_lbl.setStyleSheet("font-size: 12px; color: #495057; line-height: 1.5;")
        d_lbl.setWordWrap(True)
        layout.addWidget(d_lbl)

        ex_lbl = QLabel(f"💡 {example}")
        ex_lbl.setStyleSheet("font-size: 11px; color: #0072DE; font-weight: 500; padding: 3px 6px; background-color: #F8F9FA; border-radius: 4px;")
        ex_lbl.setWordWrap(True)
        layout.addWidget(ex_lbl)

        return widget

    def _build_comparison_card(self) -> QFrame:
        """실제 처리 예시 Before vs After 2열 대조 카드"""
        card = QFrame()
        card.setObjectName("OneUIFocusCard")
        card.setStyleSheet("""
            QFrame#OneUIFocusCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 20px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 카드 헤더
        c_hdr = QHBoxLayout()
        c_hdr.setSpacing(10)
        c_badge = QLabel("📊")
        c_badge.setFixedSize(30, 30)
        c_badge.setAlignment(Qt.AlignCenter)
        c_badge.setStyleSheet("background-color: #F3F0FF; border-radius: 15px; font-size: 15px; border: none;")
        c_hdr.addWidget(c_badge)

        c_title = QLabel(t("settings.about_app.sec_compare_title", "실제 처리 예시 (Before vs After)"))
        c_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1C1D1F; border: none; background: transparent;")
        c_hdr.addWidget(c_title)
        c_hdr.addStretch()
        layout.addLayout(c_hdr)

        # 2열 비교 박스
        boxes_layout = QHBoxLayout()
        boxes_layout.setSpacing(14)

        # 좌측: Before 박스
        before_box = QFrame()
        before_box.setStyleSheet("""
            QFrame {
                background-color: #FFF5F5;
                border: 1px solid #FFD8D8;
                border-radius: 14px;
                padding: 12px;
            }
        """)
        b_layout = QVBoxLayout(before_box)
        b_layout.setSpacing(8)

        b_title = QLabel(t("settings.about_app.compare_before_title", "❌ 정리 전 (Takeout 다운로드 상태)"))
        b_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #E03131; border: none; background: transparent;")
        b_layout.addWidget(b_title)

        b_items = [
            (
                t("settings.about_app.compare_row1_label", "📁 파일 구조"),
                t("settings.about_app.compare_row1_before", "20230731_155804.jpg (EXIF 없음)\n20230731_155804.jpg.json (분리된 파일)")
            ),
            (
                t("settings.about_app.compare_row2_label", "⏱️ 촬영 날짜"),
                t("settings.about_app.compare_row2_before", "2026-11-19 (다운로드 받은 오늘 날짜로 변조)")
            ),
            (
                t("settings.about_app.compare_row3_label", "📍 위치 정보"),
                t("settings.about_app.compare_row3_before", "GPS 좌표 없음 (지도 앱 및 위치별 정렬 불가)")
            ),
            (
                t("settings.about_app.compare_row4_label", "🛡️ 중복 파일"),
                t("settings.about_app.compare_row4_before", "여러 앨범 폴더마다 같은 사진이 3장 존재 (용량 3배)")
            ),
            (
                t("settings.about_app.compare_row5_label", "📂 보관 경로"),
                t("settings.about_app.compare_row5_before", "Takeout/Google Photos/Photos from 2023/...")
            ),
        ]
        for label, val in b_items:
            row = QVBoxLayout()
            row.setSpacing(2)
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #C92A2A; border: none; background: transparent;")
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet("font-size: 11px; color: #495057; border: none; background: transparent;")
            v_lbl.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(v_lbl)
            b_layout.addLayout(row)

        boxes_layout.addWidget(before_box, stretch=1)

        # 우측: After 박스
        after_box = QFrame()
        after_box.setStyleSheet("""
            QFrame {
                background-color: #E8F2FD;
                border: 1px solid #D0EBFF;
                border-radius: 14px;
                padding: 12px;
            }
        """)
        a_layout = QVBoxLayout(after_box)
        a_layout.setSpacing(8)

        a_title = QLabel(t("settings.about_app.compare_after_title", "✅ 본 프로그램 처리 후 (정밀 복원 완료)"))
        a_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #1971C2; border: none; background: transparent;")
        a_layout.addWidget(a_title)

        a_items = [
            (
                t("settings.about_app.compare_row1_label", "📁 파일 구조"),
                t("settings.about_app.compare_row1_after", "20230731_155804.jpg (내부에 EXIF/GPS 주입 완료)\n분리된 JSON 파일은 안전하게 정리")
            ),
            (
                t("settings.about_app.compare_row2_label", "⏱️ 촬영 날짜"),
                t("settings.about_app.compare_row2_after", "2023-07-31 15:58:04 (실제 촬영 시점으로 완벽 복원)")
            ),
            (
                t("settings.about_app.compare_row3_label", "📍 위치 정보"),
                t("settings.about_app.compare_row3_after", "위도 37.419, 경도 126.883 EXIF 주입\n➔ 대한민국 > 경기도 > 광명시 자동 분류")
            ),
            (
                t("settings.about_app.compare_row4_label", "🛡️ 중복 파일"),
                t("settings.about_app.compare_row4_after", "SHA-256 해시 검사로 1장만 보존, 중복 2장 자동 스킵")
            ),
            (
                t("settings.about_app.compare_row5_label", "📂 보관 경로"),
                t("settings.about_app.compare_row5_after", "정리완료/2023/07/20230731_155804.jpg (사용자 전략)")
            ),
        ]
        for label, val in a_items:
            row = QVBoxLayout()
            row.setSpacing(2)
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #1864AB; border: none; background: transparent;")
            v_lbl = QLabel(val)
            v_lbl.setStyleSheet("font-size: 11px; color: #343A40; border: none; background: transparent;")
            v_lbl.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(v_lbl)
            a_layout.addLayout(row)

        boxes_layout.addWidget(after_box, stretch=1)
        layout.addLayout(boxes_layout)

        card._title_label = c_title
        return card

    # ── 4) 프로그램 정보 페이지 ──────────────────────────────────

    def _build_about_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        # One UI 시그니처 상단 앱 프로필 카드
        profile_card = QFrame()
        profile_card.setObjectName("OneUIProfileCard")
        profile_card.setStyleSheet("""
            QFrame#OneUIProfileCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 20px;
            }
            QLabel {
                border: none;
                background-color: transparent;
            }
        """)
        p_layout = QVBoxLayout(profile_card)
        p_layout.setContentsMargins(24, 22, 24, 22)
        p_layout.setSpacing(8)
        p_layout.setAlignment(Qt.AlignCenter)

        # 앱 아이콘 표시 (없을 경우 🦀 이모지 폴백)
        root_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent.parent.parent
        icon_path = root_dir / "assets" / "icons" / "app_icon.png"

        icon_lbl = QLabel()
        if icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_lbl.setPixmap(pix)
        else:
            icon_lbl.setText("🦀")
            icon_lbl.setStyleSheet("font-size: 48px; background: transparent; border: none;")
        icon_lbl.setAlignment(Qt.AlignCenter)
        p_layout.addWidget(icon_lbl)

        title_lbl = QLabel(t("common.app_title", "Smile Crab [Google Photo Takeout Tools]"))
        title_lbl.setStyleSheet("font-size: 19px; font-weight: 800; color: #1C1D1F; border: none;")
        title_lbl.setAlignment(Qt.AlignCenter)
        p_layout.addWidget(title_lbl)

        sub_title_lbl = QLabel(t("common.app_subtitle", "스마일크랩 - 구글포토 테이크아웃 툴"))
        sub_title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #0072DE; border: none;")
        sub_title_lbl.setAlignment(Qt.AlignCenter)
        p_layout.addWidget(sub_title_lbl)

        ver_badge = QLabel(t("settings.about_info.version", f"버전 {APP_VERSION}", version=APP_VERSION))
        ver_badge.setStyleSheet(
            "background-color: #E8F2FD; color: #0072DE; border-radius: 12px; font-size: 11px; font-weight: bold; padding: 3px 12px; border: none;"
        )
        ver_badge.setAlignment(Qt.AlignCenter)
        p_layout.addWidget(ver_badge, 0, Qt.AlignCenter)

        desc_lbl = QLabel(t("settings.about_info.desc", "구글 테이크아웃 사진/동영상 메타데이터 정밀 복원 및 자동 분류 도구"))
        desc_lbl.setStyleSheet("font-size: 12px; color: #6C757D; border: none;")
        desc_lbl.setAlignment(Qt.AlignCenter)
        p_layout.addWidget(desc_lbl)

        layout.addWidget(profile_card)

        # 시스템 환경 상세 정보 카드
        sys_rows = [
            OneUISettingRow(t("settings.about_info.row_os", "운영체제 환경"), platform.platform(), QLabel("")),
            OneUISettingRow(t("settings.about_info.row_python", "Python 런타임"), f"Python {platform.python_version()} ({platform.machine()})", QLabel("")),
            OneUISettingRow(t("settings.about_info.row_dev", "개발 및 저작권"), "LittlePlanet Development Team • MIT License", QLabel("")),
        ]
        layout.addWidget(self._build_focus_block(t("settings.about_info.sec_system", "시스템 및 빌드 정보"), "ℹ️", "#FFF5F5", sys_rows))
        layout.addStretch()

        return self._wrap_in_scroll(page)
