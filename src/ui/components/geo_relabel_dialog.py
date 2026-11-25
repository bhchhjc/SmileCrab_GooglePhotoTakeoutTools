"""
geo_relabel_dialog.py
────────────────────────────────────────────────────────────────
미디어 역지오코딩 지역명 언어 일괄 변경 3단계 위자드 모달 다이얼로그

단계:
  Step 1: 대상 확인, 목표 언어 선택, 실시간 Live 대조 미리보기
  Step 2: 비동기 고속 재변환 진행 (진행률, 속도/ETA, 절전방지, 안전주의 배너, 창닫기 잠금)
  Step 3: 결과 요약 격자 표 및 연계 마법사(폴더 재구성, 파일명 변경) 바로가기
"""

import os
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.core.geo_resolver import GeoLanguage
from src.core.i18n import t
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.geo_relabel_service import (
    GeoRelabelPreviewItem, GeoRelabelResult, GeoRelabelService,
)
from src.ui.components.progress_circle import ProgressCircle
from src.ui.theme import Colors, Fonts
from src.ui.workers import GeoRelabelWorker


class GeoRelabelDialog(QDialog):
    """지역명 언어 일괄 변경 마법사 다이얼로그 (One UI 9.0)"""

    def __init__(
        self,
        current_base_dir: Optional[Path] = None,
        db_manager: Optional[DatabaseManager] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.db_manager = db_manager or DatabaseManager()
        self.repo = MediaRepository(self.db_manager)
        self.service = GeoRelabelService(self.db_manager)
        self._output_roots = self.repo.get_output_roots()

        if current_base_dir:
            self.current_base_dir = Path(current_base_dir)
        elif self._output_roots:
            self.current_base_dir = Path(self._output_roots[0])
        else:
            self.current_base_dir = None

        self._is_running = False
        self._worker: Optional[GeoRelabelWorker] = None
        self._last_result: Optional[GeoRelabelResult] = None
        self._preview_items: List[GeoRelabelPreviewItem] = []

        self._setup_window()
        self._setup_ui()
        self._populate_target_root_combo()
        self._update_preview()

    def _setup_window(self):
        self.setWindowTitle(t("dialog.geolang.window_title", "지역명 언어 일괄 변경 마법사"))
        self.setModal(True)
        self.resize(720, 580)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Colors.BG_APP};
            }}
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_step1_widget())
        self.stack.addWidget(self._create_step2_widget())
        self.stack.addWidget(self._create_step3_widget())

        main_layout.addWidget(self.stack, 1)

    # ─────────────────────────────────────────────────────────────
    # Step 1: 설정 및 실시간 Live 대조 미리보기
    # ─────────────────────────────────────────────────────────────
    def _create_step1_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 1. 헤더 안내 바
        header_card = QFrame()
        header_card.setStyleSheet(f"""
            QFrame {{
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
                padding: 10px 14px;
            }}
        """)
        hc_layout = QVBoxLayout(header_card)
        hc_layout.setContentsMargins(0, 0, 0, 0)
        hc_layout.setSpacing(3)

        title_lbl = QLabel(f"🌐 {t('dialog.geolang.step1_title', '지역명 표기 언어 일괄 변경')}")
        title_lbl.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        desc_lbl = QLabel(
            t(
                "dialog.geolang.step1_desc",
                "DB에 저장된 미디어의 GPS 좌표를 오프라인 17만 도시 색인으로 재변환하여 지명을 일괄 변경합니다.",
            )
        )
        desc_lbl.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        desc_lbl.setWordWrap(True)

        hc_layout.addWidget(title_lbl)
        hc_layout.addWidget(desc_lbl)
        layout.addWidget(header_card)

        # 2. 옵션 설정 카드 (대상 위치 + 언어 선택 + GPS 통계)
        opt_card = QFrame()
        opt_card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
            }
        """)
        opt_layout = QGridLayout(opt_card)
        opt_layout.setContentsMargins(14, 12, 14, 12)
        opt_layout.setHorizontalSpacing(14)
        opt_layout.setVerticalSpacing(8)

        lbl_style = "font-size: 11px; font-weight: bold; color: #495057;"

        # 2-1. 작업 대상 위치 선택
        lbl_root = QLabel(f"📂 {t('dialog.geolang.label_target_root', '작업 대상 저장 위치')}")
        lbl_root.setStyleSheet(lbl_style)
        self.root_combo = QComboBox()
        self.root_combo.setFixedHeight(28)
        self.root_combo.currentIndexChanged.connect(self._on_options_changed)
        opt_layout.addWidget(lbl_root, 0, 0)
        opt_layout.addWidget(self.root_combo, 0, 1)

        # 2-2. 변경할 지명 언어 선택
        lbl_lang = QLabel(f"🌐 {t('dialog.geolang.label_target_lang', '목표 지명 표기 언어')}")
        lbl_lang.setStyleSheet(lbl_style)
        self.lang_combo = QComboBox()
        self.lang_combo.setFixedHeight(28)
        self.lang_combo.addItem(t("geo_languages.KOREAN", "🇰🇷 한국어 (대한민국 / 서울)"), GeoLanguage.KOREAN)
        self.lang_combo.addItem(t("geo_languages.ENGLISH", "🇺🇸 영어 (South Korea / Seoul)"), GeoLanguage.ENGLISH)
        self.lang_combo.addItem(t("geo_languages.SYSTEM", "💻 시스템 언어 (자동 감지)"), GeoLanguage.SYSTEM)

        # 초기 언어 설정 (DB 저장값 동기화)
        saved_geo = self.db_manager.get_setting("geo_language") or GeoLanguage.KOREAN
        idx = self.lang_combo.findData(saved_geo)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        self.lang_combo.currentIndexChanged.connect(self._on_options_changed)
        opt_layout.addWidget(lbl_lang, 1, 0)
        opt_layout.addWidget(self.lang_combo, 1, 1)

        # 2-3. GPS 통계 배너
        lbl_stat_title = QLabel(f"📍 {t('dialog.geolang.label_gps_stats', 'GPS 보유 현황')}")
        lbl_stat_title.setStyleSheet(lbl_style)
        self.stat_val_lbl = QLabel()
        self.stat_val_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #1971C2;")
        opt_layout.addWidget(lbl_stat_title, 2, 0)
        opt_layout.addWidget(self.stat_val_lbl, 2, 1)

        opt_layout.setColumnStretch(1, 1)
        layout.addWidget(opt_card)

        # 3. 실시간 Live 대조 미리보기 테이블
        preview_hdr_box = QHBoxLayout()
        preview_hdr_lbl = QLabel(f"🔍 {t('dialog.geolang.label_preview', '실시간 변경 대조 미리보기 (최대 50건)')}")
        preview_hdr_lbl.setStyleSheet(lbl_style)
        preview_hdr_box.addWidget(preview_hdr_lbl)
        preview_hdr_box.addStretch()

        self.preview_cnt_lbl = QLabel()
        self.preview_cnt_lbl.setStyleSheet("font-size: 11px; color: #868E96;")
        preview_hdr_box.addWidget(self.preview_cnt_lbl)
        layout.addLayout(preview_hdr_box)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(4)
        self.preview_table.setHorizontalHeaderLabels([
            t("dialog.geolang.col_filename", "파일명"),
            t("dialog.geolang.col_cur_geo", "현재 저장된 지명 (Before)"),
            t("dialog.geolang.col_new_geo", "변경될 지명 (After)"),
            t("dialog.geolang.col_status", "상태"),
        ])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.preview_table.setColumnWidth(0, 180)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 8px;
                gridline-color: #F1F3F5;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: #F8F9FA;
                color: #495057;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #DEE2E6;
                padding: 6px;
                font-size: 11px;
            }}
        """)
        layout.addWidget(self.preview_table, 1)

        # 4. Zero Data Loss 안전 배너
        safe_card = QFrame()
        safe_card.setStyleSheet("""
            QFrame {
                background-color: #E7F5FF;
                border: 1px solid #A5D8FF;
                border-radius: 8px;
                padding: 6px 12px;
            }
        """)
        sc_layout = QHBoxLayout(safe_card)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(6)
        safe_icon = QLabel("🛡️")
        safe_icon.setStyleSheet("font-size: 14px; background: transparent;")
        safe_text = QLabel(
            t(
                "dialog.geolang.safety_tip",
                "안전 보장: 원본 파일 이동이나 파일 내용 수정 없이 DB의 지명 메타데이터만 100% 무손실 갱신됩니다.",
            )
        )
        safe_text.setStyleSheet("font-size: 11px; color: #1864AB; background: transparent;")
        sc_layout.addWidget(safe_icon)
        sc_layout.addWidget(safe_text, 1)
        layout.addWidget(safe_card)

        # 5. 하단 액션 버튼 바
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        self.btn_cancel = QPushButton(t("common.cancel", "취소"))
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        btn_box.addStretch()

        self.btn_start = QPushButton(f"🌐 {t('dialog.geolang.btn_start', '지역명 언어 일괄 변경 시작')}")
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(32)
        self.btn_start.setStyleSheet(f"""
            QPushButton#PrimaryButton {{
                background-color: {Colors.ACCENT};
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 10px;
                padding: 0 16px;
                font-size: 12px;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: {Colors.ACCENT_HOVER};
            }}
            QPushButton#PrimaryButton:disabled {{
                background-color: #ADB5BD;
                color: #F8F9FA;
            }}
        """)
        self.btn_start.clicked.connect(self._start_relabel)
        btn_box.addWidget(self.btn_start)

        layout.addLayout(btn_box)
        return w

    # ─────────────────────────────────────────────────────────────
    # Step 2: 비동기 진행 화면
    # ─────────────────────────────────────────────────────────────
    def _create_step2_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(18, 24, 18, 24)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignCenter)

        # 1. 프로그레스 서클
        self.step2_circle = ProgressCircle(size=52, color=Colors.ACCENT)
        layout.addWidget(self.step2_circle, alignment=Qt.AlignCenter)

        # 2. 타이틀 & 퍼센트
        self.step2_title = QLabel(t("dialog.geolang.progress_title", "지역명 언어를 일괄 변환하는 중입니다..."))
        self.step2_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        self.step2_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.step2_title)

        # 3. 진행률 바
        self.step2_bar = QProgressBar()
        self.step2_bar.setFixedHeight(8)
        self.step2_bar.setTextVisible(False)
        self.step2_bar.setMaximum(100)
        self.step2_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #E5E8EB;
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {Colors.ACCENT};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.step2_bar)

        # 4. 속도, ETA, 파일명 상세 라벨
        self.step2_detail = QLabel()
        self.step2_detail.setStyleSheet("font-size: 11px; color: #495057;")
        self.step2_detail.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.step2_detail)

        self.step2_cur_file = QLabel()
        self.step2_cur_file.setStyleSheet("font-size: 11px; color: #868E96;")
        self.step2_cur_file.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.step2_cur_file)

        # 5. 경고 배너
        warn_card = QFrame()
        warn_card.setStyleSheet("""
            QFrame {
                background-color: #FFF9DB;
                border: 1px solid #FFE066;
                border-radius: 8px;
                padding: 10px 14px;
            }
        """)
        wc_layout = QHBoxLayout(warn_card)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.setSpacing(8)

        warn_icon = QLabel("⚠️")
        warn_icon.setStyleSheet("font-size: 16px; background: transparent;")
        wc_layout.addWidget(warn_icon)

        warn_text = QLabel(
            t(
                "dialog.geolang.progress_warn",
                "<b>데이터베이스 업데이트가 진행 중입니다.</b><br>무결성 유지를 위해 작업을 강제 종료하지 마세요.",
            )
        )
        warn_text.setStyleSheet("font-size: 11px; color: #7A5300; background: transparent;")
        warn_text.setWordWrap(True)
        wc_layout.addWidget(warn_text, 1)

        layout.addWidget(warn_card, alignment=Qt.AlignCenter)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────
    # Step 3: 완료 및 결과 요약 화면
    # ─────────────────────────────────────────────────────────────
    def _create_step3_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. 완료 타이틀
        header_box = QHBoxLayout()
        header_box.setAlignment(Qt.AlignCenter)
        header_box.setSpacing(8)

        done_icon = QLabel("🎉")
        done_icon.setStyleSheet("font-size: 26px; background: transparent;")
        header_box.addWidget(done_icon)

        self.step3_title = QLabel(t("dialog.geolang.done_title", "지역명 언어 일괄 변경이 완료되었습니다!"))
        self.step3_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        header_box.addWidget(self.step3_title)
        layout.addLayout(header_box)

        # 2. 작업 요약 카드
        summary_card = QFrame()
        summary_card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 10px;
            }
        """)
        sc_layout = QVBoxLayout(summary_card)
        sc_layout.setContentsMargins(14, 12, 14, 12)
        sc_layout.setSpacing(8)

        lbl_summary_hdr = QLabel(f"📋 {t('dialog.geolang.summary_header', '작업 결과 요약')}")
        lbl_summary_hdr.setStyleSheet("font-size: 12px; font-weight: bold; color: #495057;")
        sc_layout.addWidget(lbl_summary_hdr)

        grid_frame = QFrame()
        grid_frame.setStyleSheet("""
            QFrame {
                background-color: #E9ECEF;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
            }
        """)
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setContentsMargins(1, 1, 1, 1)
        grid_layout.setSpacing(1)

        def _make_key_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("""
                background-color: #F8F9FA;
                color: #495057;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 10px;
            """)
            return lbl

        def _make_val_lbl(val: str, color: str = "#212529") -> QLabel:
            lbl = QLabel(val)
            lbl.setStyleSheet(f"""
                background-color: #FFFFFF;
                color: {color};
                font-size: 11px;
                font-weight: bold;
                padding: 6px 10px;
            """)
            return lbl

        grid_layout.addWidget(_make_key_lbl(t("dialog.geolang.sum_total", "총 대상 파일")), 0, 0)
        self.val_total = _make_val_lbl("0 건")
        grid_layout.addWidget(self.val_total, 0, 1)

        grid_layout.addWidget(_make_key_lbl(t("dialog.geolang.sum_geo", "GPS 보유 (변환 대상)")), 0, 2)
        self.val_geo = _make_val_lbl("0 건", "#1971C2")
        grid_layout.addWidget(self.val_geo, 0, 3)

        grid_layout.addWidget(_make_key_lbl(t("dialog.geolang.sum_updated", "지명 변경 완료")), 1, 0)
        self.val_updated = _make_val_lbl("0 건", "#2B8A3E")
        grid_layout.addWidget(self.val_updated, 1, 1)

        grid_layout.addWidget(_make_key_lbl(t("dialog.geolang.sum_no_gps", "GPS 미보유 (건너뜀)")), 1, 2)
        self.val_no_gps = _make_val_lbl("0 건", "#868E96")
        grid_layout.addWidget(self.val_no_gps, 1, 3)

        grid_layout.addWidget(_make_key_lbl(t("dialog.geolang.sum_lang", "적용된 지명 언어")), 2, 0)
        self.val_lang = _make_val_lbl("-")
        grid_layout.addWidget(self.val_lang, 2, 1)

        grid_layout.addWidget(_make_key_lbl(t("dialog.geolang.sum_time", "소요 시간")), 2, 2)
        self.val_time = _make_val_lbl("0.0초")
        grid_layout.addWidget(self.val_time, 2, 3)

        sc_layout.addWidget(grid_frame)
        layout.addWidget(summary_card)

        # 3. 연계 후속 작업 안내 카드
        next_card = QFrame()
        next_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.ACCENT_LIGHT};
                border: 1px solid #BAC8FF;
                border-radius: 10px;
                padding: 10px 14px;
            }}
        """)
        nc_layout = QVBoxLayout(next_card)
        nc_layout.setContentsMargins(0, 0, 0, 0)
        nc_layout.setSpacing(6)

        nc_title = QLabel(f"💡 {t('dialog.geolang.next_title', '연계 추천 작업 안내')}")
        nc_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #364FC7;")
        nc_desc = QLabel(
            t(
                "dialog.geolang.next_desc",
                "지명 언어가 성공적으로 갱신되었습니다! 새로 반영된 지명을 기반으로 폴더 구조를 재구성하거나 파일명을 일괄 변경할 수 있습니다.",
            )
        )
        nc_desc.setStyleSheet("font-size: 11px; color: #495057;")
        nc_desc.setWordWrap(True)

        nc_btns = QHBoxLayout()
        nc_btns.setSpacing(8)

        self.btn_open_reorganize = QPushButton(f"📁 {t('dialog.geolang.btn_open_reorganize', '폴더 구조 재구성 마법사 실행')}")
        self.btn_open_reorganize.setObjectName("SecondaryButton")
        self.btn_open_reorganize.setCursor(Qt.PointingHandCursor)
        self.btn_open_reorganize.setFixedHeight(28)
        self.btn_open_reorganize.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #364FC7;
                border: 1px solid #748FFC;
                font-weight: bold;
                border-radius: 8px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #EDF2FF;
            }
        """)
        self.btn_open_reorganize.clicked.connect(self._launch_reorganize)
        nc_btns.addWidget(self.btn_open_reorganize)

        self.btn_open_rename = QPushButton(f"🏷️ {t('dialog.geolang.btn_open_rename', '파일명 일괄 변경 마법사 실행')}")
        self.btn_open_rename.setObjectName("SecondaryButton")
        self.btn_open_rename.setCursor(Qt.PointingHandCursor)
        self.btn_open_rename.setFixedHeight(28)
        self.btn_open_rename.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #364FC7;
                border: 1px solid #748FFC;
                font-weight: bold;
                border-radius: 8px;
                padding: 0 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #EDF2FF;
            }
        """)
        self.btn_open_rename.clicked.connect(self._launch_rename)
        nc_btns.addWidget(self.btn_open_rename)
        nc_btns.addStretch()

        nc_layout.addWidget(nc_title)
        nc_layout.addWidget(nc_desc)
        nc_layout.addLayout(nc_btns)
        layout.addWidget(next_card)

        layout.addStretch()

        # 4. 하단 닫기 버튼
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_done = QPushButton(t("common.close", "닫기"))
        self.btn_done.setObjectName("PrimaryButton")
        self.btn_done.setCursor(Qt.PointingHandCursor)
        self.btn_done.setFixedHeight(32)
        self.btn_done.setStyleSheet(f"""
            QPushButton#PrimaryButton {{
                background-color: {Colors.ACCENT};
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 10px;
                padding: 0 20px;
                font-size: 12px;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: {Colors.ACCENT_HOVER};
            }}
        """)
        self.btn_done.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_done)

        layout.addLayout(btn_box)
        return w

    # ─────────────────────────────────────────────────────────────
    # 데이터 로드 및 콤보박스 세팅
    # ─────────────────────────────────────────────────────────────
    def _populate_target_root_combo(self):
        self.root_combo.blockSignals(True)
        self.root_combo.clear()

        # 전체 라이브러리 항목
        self.root_combo.addItem(f"🌐 {t('dialog.geolang.all_roots', '전체 라이브러리 (모든 작업 결과)')}", "")

        # 개별 작업 결과 루트 항목들
        for r in self._output_roots:
            p = Path(r)
            display_name = f"📁 {p.name} ({p.parent})" if p.parent != p else f"📁 {p}"
            self.root_combo.addItem(display_name, r)

        if self.current_base_dir:
            idx = self.root_combo.findData(str(self.current_base_dir))
            if idx >= 0:
                self.root_combo.setCurrentIndex(idx)

        self.root_combo.blockSignals(False)

    def _on_options_changed(self):
        self._update_preview()

    def _update_preview(self):
        target_root = self.root_combo.currentData() or None
        target_lang = self.lang_combo.currentData() or GeoLanguage.KOREAN

        total_cnt, geo_cnt, preview_items = self.service.get_preview(
            target_root=target_root,
            target_lang=target_lang,
            limit=50,
        )
        self._preview_items = preview_items

        pct = (geo_cnt / total_cnt * 100) if total_cnt > 0 else 0
        self.stat_val_lbl.setText(
            f"{geo_cnt:,}개 / {total_cnt:,}개 ({pct:.1f}%)"
        )
        self.preview_cnt_lbl.setText(f"{len(preview_items)}건 표시됨")

        self.btn_start.setEnabled(geo_cnt > 0)

        # 테이블 갱신
        self.preview_table.setRowCount(len(preview_items))
        for row, item in enumerate(preview_items):
            # 0: 파일명
            fn_item = QTableWidgetItem(item.file_name)
            fn_item.setToolTip(item.file_path)

            # 1: 현재 지명 (Before)
            cur_item = QTableWidgetItem(item.cur_display)
            cur_item.setToolTip(item.cur_display)

            # 2: 변경 지명 (After)
            new_item = QTableWidgetItem(item.new_display)
            new_item.setToolTip(item.new_display)

            # 3: 상태
            if item.is_changed:
                status_item = QTableWidgetItem(f"✨ {t('dialog.geolang.status_changed', '변경 예정')}")
                status_item.setForeground(QColor("#2B8A3E"))
                font = status_item.font()
                font.setBold(True)
                status_item.setFont(font)
                new_item.setForeground(QColor("#2B8A3E"))
            else:
                status_item = QTableWidgetItem(f"✓ {t('dialog.geolang.status_unchanged', '유지')}")
                status_item.setForeground(QColor("#868E96"))

            self.preview_table.setItem(row, 0, fn_item)
            self.preview_table.setItem(row, 1, cur_item)
            self.preview_table.setItem(row, 2, new_item)
            self.preview_table.setItem(row, 3, status_item)

    # ─────────────────────────────────────────────────────────────
    # 실행 및 진행 핸들러
    # ─────────────────────────────────────────────────────────────
    def _start_relabel(self):
        target_root = self.root_combo.currentData() or None
        target_lang = self.lang_combo.currentData() or GeoLanguage.KOREAN

        self._is_running = True
        self.btn_cancel.setEnabled(False)
        self.btn_start.setEnabled(False)

        # Step 2로 전환
        self.step2_bar.setValue(0)
        self.step2_circle.start()
        self.step2_detail.setText(t("dialog.geolang.progress_preparing", "준비 중..."))
        self.step2_cur_file.setText("")
        self.stack.setCurrentIndex(1)

        # 백그라운드 워커 구동
        self._worker = GeoRelabelWorker(
            target_root=target_root,
            target_lang=target_lang,
            db_manager=self.db_manager,
        )
        self._worker.signals.progress.connect(self._on_worker_progress)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.signals.error.connect(self._on_worker_error)

        QThreadPool.globalInstance().start(self._worker)

    def _on_worker_progress(self, current: int, total: int, fname: str, speed: float, eta: float):
        if total > 0:
            pct = int((current / total) * 100)
            self.step2_bar.setValue(pct)
            self.step2_detail.setText(
                f"{current:,} / {total:,} ({pct}%) | ⚡ {speed:.0f} files/s | ⏱ 남은 시간: {int(eta)}초"
            )
            self.step2_cur_file.setText(fname)

    def _on_worker_finished(self, result: GeoRelabelResult):
        self.step2_circle.stop()
        self._is_running = False
        self._last_result = result

        # Step 3 요약 채우기
        self.val_total.setText(f"{result.total_count:,} 건")
        self.val_geo.setText(f"{result.geo_count:,} 건")
        self.val_updated.setText(f"{result.updated_count:,} 건")
        self.val_no_gps.setText(f"{result.no_gps_count:,} 건")

        lang_name = {
            GeoLanguage.KOREAN: "🇰🇷 한국어",
            GeoLanguage.ENGLISH: "🇺🇸 영어",
            GeoLanguage.SYSTEM: "💻 시스템 언어",
        }.get(result.target_lang, str(result.target_lang))
        self.val_lang.setText(lang_name)
        self.val_time.setText(f"{result.duration_seconds:.2f} 초")

        # Step 3 전환
        self.stack.setCurrentIndex(2)

    def _on_worker_error(self, err_msg: str):
        self.step2_circle.stop()
        self._is_running = False
        self.stack.setCurrentIndex(0)
        self.btn_cancel.setEnabled(True)
        self.btn_start.setEnabled(True)
        QMessageBox.critical(
            self,
            t("common.error", "오류"),
            f"{t('dialog.geolang.error_prefix', '지역명 변경 중 오류가 발생했습니다:')}\n{err_msg}",
        )

    def _launch_reorganize(self):
        """연계: 폴더 구조 재구성 마법사 실행"""
        from src.ui.components.reorganize_dialog import ReorganizeDialog
        self.accept()
        base_dir = self.current_base_dir
        dialog = ReorganizeDialog(current_base_dir=base_dir, db_manager=self.db_manager, parent=self.parent())
        dialog.exec()

    def _launch_rename(self):
        """연계: 파일명 일괄 변경 마법사 실행"""
        from src.ui.components.batch_rename_dialog import BatchRenameDialog
        self.accept()
        base_dir = self.current_base_dir
        dialog = BatchRenameDialog(current_base_dir=base_dir, db_manager=self.db_manager, parent=self.parent())
        dialog.exec()

    def closeEvent(self, event):
        if self._is_running:
            event.ignore()
            return
        super().closeEvent(event)
