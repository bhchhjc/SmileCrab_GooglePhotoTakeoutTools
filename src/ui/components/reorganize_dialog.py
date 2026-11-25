"""
reorganize_dialog.py
────────────────────────────────────────────────────────────────
미디어 폴더 구조 재구성(Reorganize) 3단계 위자드 모달 다이얼로그

단계:
  Step 1: 대상 확인, 재구성 방식(제자리 vs 타폴더), 10종 전략 선택 및 미리보기
  Step 2: 비동기 재배치 진행 (진행률, 속도/ETA, 절전방지 안내, 안전주의 배너, 창닫기 잠금)
  Step 3: 결과 요약 및 Finder/탐색기 바로가기, 완료 시 라이브러리 자동 갱신
"""

import os
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from src.core.i18n import t
from src.core.models import MediaType
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.process_service import FolderStrategy, get_strategy_display_name
from src.services.reorganize_service import (
    ReorganizeItem, ReorganizeResult, ReorganizeService,
)
from src.ui.theme import (
    Colors, Fonts,
    ICON_RADIO_UNCHECKED, ICON_RADIO_CHECKED, ICON_RADIO_DISABLED,
    ICON_CHECKBOX_UNCHECKED, ICON_CHECKBOX_CHECKED, ICON_CHECKBOX_DISABLED,
)
from src.ui.components.progress_circle import ProgressCircle
from src.ui.workers import ReorganizeWorker


GEO_CUSTOM_KEY = "geo_custom"

STRATEGY_OPTIONS = [
    (FolderStrategy.YEAR_MONTH, "📅 01. 년/월 (예: 2023/07/)"),
    (FolderStrategy.YEAR_YEAR_MONTH, "📅 02. 년/년-월 (예: 2023/2023-07/)"),
    (FolderStrategy.YEAR_ONLY, "📅 03. 년도만 (예: 2023/)"),
    (FolderStrategy.YEAR_MONTH_DAY, "🗓 04. 년/월/일 (일자별 정밀) (예: 2023/07/31/)"),
    (FolderStrategy.CAMERA_YEAR_MONTH, "📷 05. 촬영기기/년/월 (예: Apple iPhone 13 Pro/2023/07/)"),
    (FolderStrategy.YEAR_MONTH_CAMERA, "📷 06. 년/월/촬영기기 (예: 2023/07/Apple iPhone 13 Pro/)"),
    (FolderStrategy.TYPE_YEAR_MONTH, "🎬 07. 미디어유형/년/월 (사진 vs 동영상) (예: 사진/2023/07/)"),
    (GEO_CUSTOM_KEY, "🌍 08. 촬영 위치 기반 맞춤 정리 (국가 / 시·도 / 시·군·구)"),
    (FolderStrategy.ALBUM_NAME, "🏷 09. 원본 앨범명 (예: 가족여행2023/)"),
]


class ReorganizeDialog(QDialog):
    """미디어 폴더 구조 재구성 마법사 다이얼로그"""

    def __init__(
        self,
        current_base_dir: Optional[Path] = None,
        db_manager: Optional[DatabaseManager] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.db_manager = db_manager or DatabaseManager()
        self.repo = MediaRepository(self.db_manager)
        self.service = ReorganizeService(self.db_manager)
        self._output_roots = self.repo.get_output_roots()

        if current_base_dir:
            self.current_base_dir = Path(current_base_dir)
        elif self._output_roots:
            self.current_base_dir = Path(self._output_roots[0])
        else:
            self.current_base_dir = self._detect_default_base_dir()

        self._items: List[ReorganizeItem] = []
        self._is_running = False
        self._worker: Optional[ReorganizeWorker] = None
        self._last_result: Optional[ReorganizeResult] = None

        self._setup_window()
        self._setup_ui()
        self._populate_target_root_combo()
        self._load_data()

    def _detect_default_base_dir(self) -> Path:
        """DB에 기록된 실제 작업 결과 루트 디렉토리 도출"""
        repo = MediaRepository(self.db_manager)
        roots = repo.get_output_roots()
        if roots:
            return Path(roots[0])
        return Path.home() / "Pictures"

    def _setup_window(self):
        self.setWindowTitle(t("dialog.reorganize.window_title", "미디어 폴더 구조 재구성 마법사"))
        self.setModal(True)
        self.resize(700, 580)
        self.setMinimumSize(660, 500)

        # macOS 및 전역 테마에서 다이얼로그 배경을 확실하게 #F4F6F9로 강제
        from PySide6.QtGui import QPalette, QColor
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#F4F6F9"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.setStyleSheet(f"""
            QDialog, QDialog > QWidget, QStackedWidget {{
                background-color: #F4F6F9;
            }}
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
                background-color: #F4F6F9;
                border: none;
            }}
            QFrame#Card {{
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
            }}
            QRadioButton {{
                color: {Colors.TEXT_PRIMARY};
                spacing: 8px;
                font-size: 13px;
                background-color: transparent;
            }}
            QRadioButton::indicator {{
                width: 18px;
                height: 18px;
                border: none;
                background: transparent;
                image: url({ICON_RADIO_UNCHECKED});
            }}
            QRadioButton::indicator:checked {{
                image: url({ICON_RADIO_CHECKED});
            }}
            QRadioButton::indicator:disabled {{
                image: url({ICON_RADIO_DISABLED});
            }}
            QCheckBox {{
                color: {Colors.TEXT_PRIMARY};
                spacing: 8px;
                font-size: 13px;
                background-color: transparent;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: none;
                background: transparent;
                image: url({ICON_CHECKBOX_UNCHECKED});
            }}
            QCheckBox::indicator:checked {{
                image: url({ICON_CHECKBOX_CHECKED});
            }}
            QCheckBox::indicator:disabled {{
                image: url({ICON_CHECKBOX_DISABLED});
            }}
            QComboBox {{
                background-color: #FFFFFF;
                border: 1px solid #CED4DA;
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 13px;
                font-weight: 500;
                color: #212529;
                min-height: 26px;
            }}
            QComboBox:hover {{
                border-color: #ADB5BD;
            }}
            QComboBox:focus {{
                border-color: #0072DE;
            }}
            QComboBox QAbstractItemView {{
                background-color: #FFFFFF;
                border: 1px solid #CED4DA;
                border-radius: 8px;
                selection-background-color: #E8F2FD;
                selection-color: #0072DE;
                padding: 4px;
                color: #212529;
            }}
            QScrollBar:vertical {{
                border: none;
                background-color: transparent;
                width: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #D6DADE;
                min-height: 20px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #B0B5BA;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QFrame#WarningBanner {{
                background-color: #FFF9DB;
                border: 1px solid #FFE066;
                border-radius: 10px;
                padding: 12px;
            }}
            QLabel#Title {{
                font-size: 17px;
                font-weight: bold;
                color: {Colors.TEXT_PRIMARY};
            }}
            QLabel#SubTitle {{
                font-size: 12px;
                color: {Colors.TEXT_SECONDARY};
            }}
            QPushButton#PrimaryBtn {{
                background-color: {Colors.ACCENT};
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                border: 1px solid transparent;
                min-height: 30px;
                max-height: 30px;
                padding: 0px 18px;
                font-size: 12px;
            }}
            QPushButton#PrimaryBtn:hover {{
                background-color: {Colors.ACCENT_HOVER};
            }}
            QPushButton#SecondaryBtn {{
                background-color: #FFFFFF;
                color: #495057;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                min-height: 30px;
                max-height: 30px;
                padding: 0px 16px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#SecondaryBtn:hover {{
                background-color: #F8F9FA;
                border-color: #ADB5BD;
            }}
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 10, 18, 10)
        main_layout.setSpacing(8)

        # 상단 공통 헤더
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        icon_lbl = QLabel("🔄")
        icon_lbl.setStyleSheet("font-size: 22px; background: transparent;")
        header_layout.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.header_title = QLabel(t("dialog.reorganize.header_title", "미디어 폴더 구조 재구성"), objectName="Title")
        self.header_desc = QLabel(
            t("dialog.reorganize.header_desc", "정리된 미디어 파일들의 폴더 체계를 원하는 규칙으로 초고속 무손실 재배치합니다."),
            objectName="SubTitle"
        )
        title_col.addWidget(self.header_title)
        title_col.addWidget(self.header_desc)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        main_layout.addLayout(header_layout)

        # 3단계 StackedWidget
        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_step1_widget())
        self.stack.addWidget(self._create_step2_widget())
        self.stack.addWidget(self._create_step3_widget())
        main_layout.addWidget(self.stack, 1)

    # ─────────────────────────────────────────────────────────────
    # Step 1: 옵션 선택 및 미리보기
    # ─────────────────────────────────────────────────────────────
    def _create_step1_widget(self) -> QWidget:
        main_w = QWidget()
        main_w.setObjectName("Step1Main")
        main_w.setStyleSheet("QWidget#Step1Main { background-color: #F4F6F9; }")
        main_vbox = QVBoxLayout(main_w)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(6)

        # ── 상단/본문 스크롤 영역 (설정 카드들) ────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: #F4F6F9; border: none; }")
        scroll.viewport().setStyleSheet("background-color: #F4F6F9; border: none;")

        content_w = QWidget()
        content_w.setObjectName("Step1Content")
        content_w.setStyleSheet("QWidget#Step1Content { background-color: #F4F6F9; }")
        layout = QVBoxLayout(content_w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        card_qss = f"""
            QFrame#Card {{
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
            }}
            QRadioButton {{
                background-color: transparent;
                background: transparent;
                spacing: 6px;
                font-size: 12px;
            }}
            QCheckBox {{
                background-color: transparent;
                background: transparent;
                spacing: 6px;
                font-size: 12px;
            }}
            QLabel {{
                background-color: transparent;
                background: transparent;
            }}
            QComboBox {{
                background-color: #FFFFFF;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 12px;
                font-weight: 500;
                color: #212529;
                min-height: 28px;
                max-height: 28px;
            }}
            QComboBox:hover {{
                border-color: #ADB5BD;
            }}
            QComboBox:focus {{
                border-color: #0072DE;
            }}
        """

        # 1. 대상 폴더 및 통계 카드 (방안 A: 수직 계층형 컴팩트 카드)
        target_card = QFrame(objectName="Card")
        target_card.setStyleSheet(card_qss)
        tc_layout = QVBoxLayout(target_card)
        tc_layout.setContentsMargins(14, 10, 14, 10)
        tc_layout.setSpacing(6)

        # 1행: 작업 대상 저장소 라벨 + 간결한 콤보박스 (폴더명 + 파일 수)
        row1_box = QHBoxLayout()
        row1_box.setSpacing(8)

        lbl_t1 = QLabel(t("dialog.reorganize.target_repo_label", "📁 작업 대상 저장소:"), objectName="SubLabel")
        lbl_t1.setStyleSheet("font-weight: bold; font-size: 11px; color: #495057; background: transparent;")
        row1_box.addWidget(lbl_t1)

        self.target_root_combo = QComboBox()
        self.target_root_combo.setMinimumHeight(28)
        self.target_root_combo.setStyleSheet("""
            QComboBox {
                font-size: 12px;
                font-weight: bold;
                padding: 2px 8px;
            }
        """)
        row1_box.addWidget(self.target_root_combo, 1)
        tc_layout.addLayout(row1_box)

        # 2행: 실제 전체 저장 경로 (별도 독립 행으로 분리하여 절대 잘리지 않음)
        row2_box = QHBoxLayout()
        row2_box.setSpacing(6)

        lbl_path_title = QLabel(t("dialog.reorganize.actual_path_label", "📍 실제 저장 경로:"), objectName="SubLabel")
        lbl_path_title.setStyleSheet("font-size: 11px; color: #6C757D; background: transparent;")
        row2_box.addWidget(lbl_path_title)

        self.source_path_lbl = QLabel(str(self.current_base_dir) if self.current_base_dir else "-")
        self.source_path_lbl.setStyleSheet("font-size: 11px; color: #343A40; background: transparent;")
        self.source_path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row2_box.addWidget(self.source_path_lbl, 1)
        tc_layout.addLayout(row2_box)

        # 3행: 미디어 구성 통계 및 안전 안내
        row3_box = QHBoxLayout()
        row3_box.setSpacing(8)

        self.stats_lbl = QLabel(t("common.loading", "대상 파일 분석 중..."), objectName="SubLabel")
        self.stats_lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Colors.ACCENT}; background: transparent;")
        row3_box.addWidget(self.stats_lbl)

        lbl_bullet = QLabel("·", objectName="SubLabel")
        lbl_bullet.setStyleSheet("font-size: 11px; color: #CED4DA; background: transparent;")
        row3_box.addWidget(lbl_bullet)

        scope_desc_lbl = QLabel("선택된 저장 위치 내부의 파일 구조가 안전하게 재배치됩니다.", objectName="SubLabel")
        scope_desc_lbl.setStyleSheet("font-size: 11px; color: #6C757D; background: transparent;")
        row3_box.addWidget(scope_desc_lbl)

        row3_box.addStretch()
        tc_layout.addLayout(row3_box)

        layout.addWidget(target_card)

        # 2. 재구성 방식 선택 (라디오 + setEnabled 제어 및 폴더 선택 버튼 너비 확보)
        mode_card = QFrame(objectName="Card")
        mode_card.setStyleSheet(card_qss)
        mc_layout = QVBoxLayout(mode_card)
        mc_layout.setContentsMargins(12, 8, 12, 8)
        mc_layout.setSpacing(4)

        lbl_m1 = QLabel("⚙️ 재구성 방식", objectName="SubLabel")
        lbl_m1.setStyleSheet("font-weight: bold; font-size: 11px; color: #495057; background: transparent;")
        mc_layout.addWidget(lbl_m1)

        self.radio_inplace = QRadioButton("현재 폴더 내에서 제자리 재구성 (추천, 동일 디스크 초고속 이동)")
        self.radio_inplace.setChecked(True)
        self.radio_inplace.toggled.connect(self._on_mode_toggled)

        self.radio_custom = QRadioButton("지정 폴더로 이동하여 재구성")
        self.radio_custom.toggled.connect(self._on_mode_toggled)

        self.btn_group = QButtonGroup(self)
        self.btn_group.addButton(self.radio_inplace)
        self.btn_group.addButton(self.radio_custom)

        mc_layout.addWidget(self.radio_inplace)
        mc_layout.addSpacing(2)
        mc_layout.addWidget(self.radio_custom)

        # 다른 폴더 선택 행 (사라지지 않고 항상 배치, 제자리 재구성 시에는 disabled)
        self.custom_path_frame = QWidget()
        self.custom_path_frame.setStyleSheet("background: transparent;")
        cp_layout = QHBoxLayout(self.custom_path_frame)
        cp_layout.setContentsMargins(22, 2, 0, 0)
        cp_layout.setSpacing(6)

        self.custom_path_edit = QLineEdit()
        self.custom_path_edit.setFixedHeight(28)
        self.custom_path_edit.setPlaceholderText("이동할 대상 폴더 경로를 선택하세요...")
        self.custom_path_edit.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 3px 8px;
                background-color: #FFFFFF;
                font-size: 12px;
            }}
            QLineEdit:disabled {{
                background-color: #F8F9FA;
                color: #ADB5BD;
                border-color: #E9ECEF;
            }}
        """)
        self.btn_browse = QPushButton("폴더 선택")
        self.btn_browse.setObjectName("SecondaryBtn")
        self.btn_browse.setFixedHeight(28)
        self.btn_browse.setFixedWidth(86)
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setStyleSheet("""
            QPushButton#SecondaryBtn {
                background-color: #FFFFFF;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                color: #212529;
            }
            QPushButton#SecondaryBtn:disabled {
                background-color: #F8F9FA;
                color: #ADB5BD;
                border-color: #E9ECEF;
            }
        """)
        self.btn_browse.clicked.connect(self._browse_custom_dir)

        cp_layout.addWidget(self.custom_path_edit, 1)
        cp_layout.addWidget(self.btn_browse)
        self.custom_path_frame.setEnabled(False)
        mc_layout.addWidget(self.custom_path_frame)

        layout.addWidget(mode_card)

        # 3. 새로운 폴더 구조 선택 콤보박스
        strat_card = QFrame(objectName="Card")
        strat_card.setStyleSheet(card_qss)
        sc_layout = QVBoxLayout(strat_card)
        sc_layout.setContentsMargins(12, 8, 12, 8)
        sc_layout.setSpacing(6)

        lbl_s1 = QLabel("📁 변경할 폴더 구조 선택", objectName="SubLabel")
        lbl_s1.setStyleSheet("font-weight: bold; font-size: 11px; color: #495057; background: transparent;")
        sc_layout.addWidget(lbl_s1)

        self.combo_strategy = QComboBox()
        self.combo_strategy.setFixedHeight(28)
        for strat, label in STRATEGY_OPTIONS:
            self.combo_strategy.addItem(label, strat)
        self.combo_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        sc_layout.addWidget(self.combo_strategy)

        # 3-1. 위치 세부 설정 패널 (위치 기반 선택 시 동적 노출)
        self.geo_sub_card = QFrame()
        self.geo_sub_card.setStyleSheet(f"""
            QFrame {{
                background-color: #F8F9FA;
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QRadioButton {{
                background-color: transparent;
                background: transparent;
                spacing: 6px;
                font-size: 12px;
            }}
            QCheckBox {{
                background-color: transparent;
                background: transparent;
                spacing: 6px;
                font-size: 12px;
            }}
            QLabel {{
                background-color: transparent;
                background: transparent;
            }}
        """)
        geo_layout = QVBoxLayout(self.geo_sub_card)
        geo_layout.setContentsMargins(6, 4, 6, 4)
        geo_layout.setSpacing(4)

        lbl_geo_depth = QLabel("📍 위치 계층 깊이 선택", objectName="SubLabel")
        lbl_geo_depth.setStyleSheet("font-weight: bold; font-size: 11px; color: #495057; background: transparent;")
        geo_layout.addWidget(lbl_geo_depth)

        # 4가지 계층 라디오 버튼 (2행 2열 그리드로 정돈하여 글자 잘림 완전 방지)
        depth_grid = QGridLayout()
        depth_grid.setHorizontalSpacing(12)
        depth_grid.setVerticalSpacing(4)

        self.radio_geo_3tier = QRadioButton("3단계 (국가 > 시·도 > 시·군·구)")
        self.radio_geo_3tier.setChecked(True)
        self.radio_geo_3tier.toggled.connect(self._update_preview)

        self.radio_geo_state = QRadioButton("2단계 광역 (국가 > 시·도)")
        self.radio_geo_state.toggled.connect(self._update_preview)

        self.radio_geo_city = QRadioButton("2단계 도시 (국가 > 시·군·구)")
        self.radio_geo_city.toggled.connect(self._update_preview)

        self.radio_geo_country = QRadioButton("1단계 (국가별 단독)")
        self.radio_geo_country.toggled.connect(self._update_preview)

        self.geo_btn_group = QButtonGroup(self)
        self.geo_btn_group.addButton(self.radio_geo_3tier)
        self.geo_btn_group.addButton(self.radio_geo_state)
        self.geo_btn_group.addButton(self.radio_geo_city)
        self.geo_btn_group.addButton(self.radio_geo_country)

        depth_grid.addWidget(self.radio_geo_3tier, 0, 0)
        depth_grid.addWidget(self.radio_geo_state, 0, 1)
        depth_grid.addWidget(self.radio_geo_city, 1, 0)
        depth_grid.addWidget(self.radio_geo_country, 1, 1)
        geo_layout.addLayout(depth_grid)

        # 하위 년/월 체크박스
        self.chk_geo_ym = QCheckBox("⏱️ 하위에 '년/월(YYYY/MM)' 서브폴더 생성 (예: .../2023/07/)")
        self.chk_geo_ym.setChecked(True)
        self.chk_geo_ym.toggled.connect(self._update_preview)
        geo_layout.addWidget(self.chk_geo_ym)

        self.geo_sub_card.setVisible(False)
        sc_layout.addWidget(self.geo_sub_card)

        # 실시간 미리보기
        self.preview_lbl = QLabel()
        self.preview_lbl.setStyleSheet(f"""
            background-color: #F8F9FA;
            border: 1px dashed {Colors.BORDER};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 11px;
            color: {Colors.TEXT_PRIMARY};
            font-family: Menlo, Monaco, monospace;
        """)
        sc_layout.addWidget(self.preview_lbl)

        layout.addWidget(strat_card)
        layout.addStretch(1)

        scroll.setWidget(content_w)
        main_vbox.addWidget(scroll, 1)

        # ── 하단 고정 액션 버튼 바 ─────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 4, 0, 0)
        btn_layout.setSpacing(8)
        btn_layout.addStretch()

        self.btn_cancel_step1 = QPushButton("취소")
        self.btn_cancel_step1.setObjectName("SecondaryBtn")
        self.btn_cancel_step1.setFixedHeight(32)
        self.btn_cancel_step1.setMinimumWidth(80)
        self.btn_cancel_step1.setCursor(Qt.PointingHandCursor)
        self.btn_cancel_step1.clicked.connect(self.reject)

        self.btn_start = QPushButton("🔄 재구성 시작")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setFixedHeight(32)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_reorganize)

        btn_layout.addWidget(self.btn_cancel_step1)
        btn_layout.addWidget(self.btn_start)
        main_vbox.addLayout(btn_layout)

        return main_w

    # ─────────────────────────────────────────────────────────────
    # Step 2: 진행 중 화면
    # ─────────────────────────────────────────────────────────────
    def _create_step2_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 20, 10, 10)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignCenter)

        # 프로그레스 서클 애니메이션
        self.spinner = ProgressCircle(size=52, color=Colors.ACCENT)
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)

        # 메인 진행 텍스트
        self.step2_title = QLabel("미디어 파일의 폴더 구조를 재배치하고 있습니다...")
        self.step2_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(self.step2_title, alignment=Qt.AlignCenter)

        self.step2_current_file = QLabel("준비 중...")
        self.step2_current_file.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(self.step2_current_file, alignment=Qt.AlignCenter)

        # 프로그레스 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(540)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignCenter)

        # 속도 및 잔여 시간 (ETA)
        self.step2_speed_lbl = QLabel("속도 및 남은 시간 계산 중...")
        self.step2_speed_lbl.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(self.step2_speed_lbl, alignment=Qt.AlignCenter)

        # 절전 방지 활성화 뱃지
        self.wake_lock_badge = QLabel("☕ 시스템 절전 모드 진입 방지가 활성화되어 있습니다.")
        self.wake_lock_badge.setStyleSheet(f"font-size: 11px; color: #2B8A3E; font-weight: 500;")
        layout.addWidget(self.wake_lock_badge, alignment=Qt.AlignCenter)

        # 주황색 주의 배너 카드
        warn_card = QFrame(objectName="WarningBanner")
        warn_card.setFixedWidth(540)
        wc_layout = QHBoxLayout(warn_card)
        wc_layout.setSpacing(10)

        warn_icon = QLabel("⚠️")
        warn_icon.setStyleSheet("font-size: 20px;")
        wc_layout.addWidget(warn_icon)

        warn_text = QLabel(
            "<b>파일 이동 및 데이터베이스 업데이트가 진행 중입니다.</b><br>"
            "파일 손상 및 꼬임을 방지하기 위해 <b>작업을 강제 종료하거나 PC 전원을 끄지 마세요.</b>"
        )
        warn_text.setStyleSheet("font-size: 12px; color: #7A5300; line-height: 140%;")
        warn_text.setWordWrap(True)
        wc_layout.addWidget(warn_text, 1)

        layout.addWidget(warn_card, alignment=Qt.AlignCenter)
        layout.addStretch()

        return w

    # ─────────────────────────────────────────────────────────────
    # Step 3: 완료 및 확인 화면
    # ─────────────────────────────────────────────────────────────
    def _create_step3_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. 상단 완료 타이틀 바 (컴팩트 정렬)
        header_box = QHBoxLayout()
        header_box.setAlignment(Qt.AlignCenter)
        header_box.setSpacing(8)

        done_icon = QLabel("🎉")
        done_icon.setStyleSheet("font-size: 26px; background: transparent;")
        header_box.addWidget(done_icon)

        self.step3_title = QLabel("폴더 구조 재구성이 완료되었습니다!")
        self.step3_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {Colors.TEXT_PRIMARY}; background: transparent;")
        header_box.addWidget(self.step3_title)
        layout.addLayout(header_box)

        # 2. 작업 요약 카드 (배경과 구분되는 흰색 카드 영역 + 정합 격자 표 레이아웃)
        summary_card = QFrame(objectName="SummaryCard")
        summary_card.setStyleSheet("""
            QFrame#SummaryCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 10px;
            }
        """)
        sc_layout = QVBoxLayout(summary_card)
        sc_layout.setContentsMargins(14, 10, 14, 10)
        sc_layout.setSpacing(8)

        lbl_summary_hdr = QLabel("📋 작업 요약")
        lbl_summary_hdr.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057; background: transparent;")
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
        grid_layout.setSpacing(1)  # 셀 사이 1px 테두리 구분선 효과

        def _make_key_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("""
                background-color: #F8F9FA;
                color: #495057;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 12px;
                border: none;
            """)
            lbl.setFixedWidth(120)
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            return lbl

        def _make_val_lbl() -> QLabel:
            lbl = QLabel("-")
            lbl.setStyleSheet("""
                background-color: #FFFFFF;
                color: #212529;
                font-size: 12px;
                padding: 5px 12px;
                border: none;
            """)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return lbl

        # 0행: 적용된 전략
        grid_layout.addWidget(_make_key_lbl("적용된 전략"), 0, 0)
        self.res_strat_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_strat_lbl, 0, 1)

        # 1행: 총 처리 결과
        grid_layout.addWidget(_make_key_lbl("총 처리 결과"), 1, 0)
        self.res_result_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_result_lbl, 1, 1)

        # 2행: 폴더 변경 내역
        grid_layout.addWidget(_make_key_lbl("폴더 변경 내역"), 2, 0)
        self.res_folders_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_folders_lbl, 2, 1)

        # 3행: 소요 시간
        grid_layout.addWidget(_make_key_lbl("소요 시간"), 3, 0)
        self.res_time_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_time_lbl, 3, 1)

        # 4행: 최종 저장 위치
        grid_layout.addWidget(_make_key_lbl("최종 저장 위치"), 4, 0)
        self.res_path_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_path_lbl, 4, 1)

        sc_layout.addWidget(grid_frame)
        layout.addWidget(summary_card)

        # 3. 정리 및 실패 상세 내역 카드 (상단 타이틀 좌측 정렬, 하단 컨텐츠 영역 분리)
        detail_card = QFrame(objectName="DetailCard")
        detail_card.setStyleSheet("""
            QFrame#DetailCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 10px;
            }
            QLabel {
                background-color: transparent;
                background: transparent;
            }
        """)
        dc_layout = QVBoxLayout(detail_card)
        dc_layout.setContentsMargins(14, 12, 14, 12)
        dc_layout.setSpacing(8)

        # 3-Top. 타이틀 (카드 상단 맨 위 좌측 정렬)
        self.detail_title_lbl = QLabel("📋 정리 및 실패 내역 (0건)")
        self.detail_title_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        dc_layout.addWidget(self.detail_title_lbl, 0, Qt.AlignTop | Qt.AlignLeft)

        # 3-Content. 하단 컨텐츠 영역 (QStackedWidget으로 묶어서 전체 남은 공간 활용)
        self.detail_stack = QStackedWidget()

        # 페이지 0: 모두 성공 시 노출할 배너
        self.detail_empty_widget = QFrame()
        self.detail_empty_widget.setStyleSheet("""
            QFrame {
                background-color: #E6F4EA;
                border: 1px solid #CEEAD6;
                border-radius: 8px;
            }
        """)
        dew_layout = QVBoxLayout(self.detail_empty_widget)
        dew_layout.setContentsMargins(16, 24, 16, 24)
        dew_layout.setAlignment(Qt.AlignCenter)
        dew_layout.setSpacing(6)

        lbl_all_ok_icon = QLabel("✨")
        lbl_all_ok_icon.setStyleSheet("font-size: 24px; background: transparent; border: none;")
        lbl_all_ok_icon.setAlignment(Qt.AlignCenter)

        lbl_all_ok_title = QLabel("모든 파일이 오류 없이 성공적으로 재구성되었습니다.")
        lbl_all_ok_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #137333; background: transparent; border: none;")
        lbl_all_ok_title.setAlignment(Qt.AlignCenter)

        lbl_all_ok_sub = QLabel("디스크 부재나 이동 충돌 없이 모든 파일의 위치와 DB 메타데이터가 정상 반영되었습니다.")
        lbl_all_ok_sub.setStyleSheet("font-size: 11px; color: #2E7D32; background: transparent; border: none;")
        lbl_all_ok_sub.setAlignment(Qt.AlignCenter)

        dew_layout.addWidget(lbl_all_ok_icon)
        dew_layout.addWidget(lbl_all_ok_title)
        dew_layout.addWidget(lbl_all_ok_sub)

        self.detail_stack.addWidget(self.detail_empty_widget)

        # 페이지 1: 정리/실패 항목이 있을 때 채워질 상세 테이블 (남은 공간 전액 활용)
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(3)
        self.detail_table.setHorizontalHeaderLabels(["파일명", "기존 상대 경로", "처리 결과 및 사유"])
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.verticalHeader().setDefaultSectionSize(26)
        self.detail_table.setShowGrid(True)
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.setStyleSheet("""
            QTableWidget {
                background-color: #FFFFFF;
                alternate-background-color: #F8F9FA;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
                font-size: 11px;
                color: #212529;
            }
            QHeaderView::section {
                background-color: #F1F3F6;
                color: #495057;
                font-size: 11px;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #CED4DA;
                padding: 4px 6px;
            }
        """)

        h_header = self.detail_table.horizontalHeader()
        h_header.setSectionResizeMode(0, QHeaderView.Interactive)
        h_header.setSectionResizeMode(1, QHeaderView.Stretch)
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.detail_table.setColumnWidth(0, 180)
        self.detail_table.setColumnWidth(2, 230)

        self.detail_stack.addWidget(self.detail_table)
        dc_layout.addWidget(self.detail_stack, 1)

        layout.addWidget(detail_card, 1)

        # 4. 하단 액션 버튼 바 (고정 높이)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.setAlignment(Qt.AlignCenter)

        self.btn_open_finder = QPushButton("📂 Finder에서 결과 확인")
        self.btn_open_finder.setObjectName("SecondaryBtn")
        self.btn_open_finder.setFixedHeight(32)
        self.btn_open_finder.setMinimumWidth(160)
        self.btn_open_finder.setCursor(Qt.PointingHandCursor)
        self.btn_open_finder.clicked.connect(self._open_in_file_manager)

        self.btn_finish = QPushButton("✓ 완료 (라이브러리 새로고침)")
        self.btn_finish.setObjectName("PrimaryBtn")
        self.btn_finish.setFixedHeight(32)
        self.btn_finish.setMinimumWidth(160)
        self.btn_finish.setCursor(Qt.PointingHandCursor)
        self.btn_finish.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_open_finder)
        btn_layout.addWidget(self.btn_finish)
        layout.addLayout(btn_layout)

        return w

    # ─────────────────────────────────────────────────────────────
    # 데이터 로드 및 상호작용
    # ─────────────────────────────────────────────────────────────
    def _get_root_file_count(self, root_path: str) -> int:
        """지정된 루트 디렉토리 하위의 미디어 파일 수 조회 (MediaRepository 사용)"""
        try:
            return self.repo.get_root_media_count(root_path)
        except Exception:
            return 0

    def _populate_target_root_combo(self):
        """등록된 저장 위치 목록을 콤보박스에 바인딩하고 초기 위치를 선택"""
        self.target_root_combo.blockSignals(True)
        self.target_root_combo.clear()

        if not self._output_roots:
            self.target_root_combo.addItem(t("dialog.rename.empty_target", "저장 위치 없음 (미디어 파일이 등록되지 않음)"), "")
            self.target_root_combo.setEnabled(False)
            self.target_root_combo.blockSignals(False)
            return

        selected_idx = 0
        cur_str = str(self.current_base_dir.resolve()) if self.current_base_dir else ""

        for idx, r in enumerate(self._output_roots):
            short_name = Path(r).name or r
            count = self._get_root_file_count(r)
            self.target_root_combo.addItem(f"📁 {short_name}  ({t('common.total', '총')} {count:,}{t('common.files', '개 파일')})", r)
            self.target_root_combo.setItemData(idx, f"경로: {r}\n파일 수: {count:,}개", Qt.ToolTipRole)
            try:
                if cur_str and (cur_str == str(Path(r).resolve()) or cur_str.startswith(str(Path(r).resolve()))):
                    selected_idx = idx
            except Exception:
                pass

        self.target_root_combo.setCurrentIndex(selected_idx)
        sel_root = self.target_root_combo.currentData()
        if sel_root:
            self.current_base_dir = Path(sel_root)
        self.target_root_combo.blockSignals(False)
        self.target_root_combo.currentIndexChanged.connect(self._on_target_root_changed)

    def _on_target_root_changed(self, idx: int):
        """다이얼로그 내부에서 대상 저장 위치 변경 시 즉시 미디어 재로드 및 미리보기 동기화"""
        root_path = self.target_root_combo.currentData()
        if not root_path:
            return
        self.current_base_dir = Path(root_path)
        self._load_data()

    def _load_data(self):
        """대상 디렉토리의 파일들을 백그라운드 준비/조회"""
        self._items = self.service.load_target_items(self.current_base_dir)
        total = len(self._items)

        photos = sum(1 for it in self._items if it.media_type == "photo")
        videos = sum(1 for it in self._items if it.media_type == "video")

        if hasattr(self, "source_path_lbl"):
            self.source_path_lbl.setText(str(self.current_base_dir) if self.current_base_dir else "-")
            self.source_path_lbl.setToolTip(str(self.current_base_dir) if self.current_base_dir else "")

        self.stats_lbl.setText(
            f"총 <b>{total:,}개</b> 미디어 (사진 {photos:,}개, 동영상 {videos:,}개)"
        )

        if total == 0:
            self.btn_start.setEnabled(False)
            self.btn_start.setText("대상 파일 없음")
        else:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("🔄 재구성 시작")

        self._update_preview()

    def _on_mode_toggled(self):
        is_custom = self.radio_custom.isChecked()
        self.custom_path_frame.setEnabled(is_custom)
        self._update_preview()

    def _browse_custom_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "이동할 대상 디렉토리 선택", str(self.current_base_dir)
        )
        if chosen:
            self.custom_path_edit.setText(chosen)
            self._update_preview()

    def _get_target_base_dir(self) -> Path:
        if self.radio_inplace.isChecked():
            return self.current_base_dir
        path_str = self.custom_path_edit.text().strip()
        if path_str:
            return Path(path_str)
        return self.current_base_dir

    def _on_strategy_changed(self):
        """전략 변경 시 위치 세부 카드 노출 여부 결정 및 미리보기 갱신"""
        val = self.combo_strategy.currentData()
        self.geo_sub_card.setVisible(val == GEO_CUSTOM_KEY)
        self._update_preview()

    def _get_effective_strategy(self) -> FolderStrategy:
        """현재 선택된 콤보박스 및 위치 세부 옵션을 조합한 최종 FolderStrategy 계산"""
        val = self.combo_strategy.currentData()
        if val == GEO_CUSTOM_KEY:
            include_ym = self.chk_geo_ym.isChecked()
            if self.radio_geo_3tier.isChecked():
                return FolderStrategy.GEO_COUNTRY_STATE_CITY if include_ym else FolderStrategy.GEO_COUNTRY_STATE_CITY_ONLY
            elif self.radio_geo_state.isChecked():
                return FolderStrategy.GEO_COUNTRY_STATE if include_ym else FolderStrategy.GEO_COUNTRY_STATE_ONLY
            elif self.radio_geo_city.isChecked():
                return FolderStrategy.GEO_COUNTRY_CITY if include_ym else FolderStrategy.GEO_COUNTRY_CITY_ONLY
            else:
                return FolderStrategy.GEO_COUNTRY if include_ym else FolderStrategy.GEO_COUNTRY_ONLY
        return val

    def _update_preview(self):
        """선택된 전략 기반 샘플 파일 경로 미리보기 텍스트 갱신"""
        strat: FolderStrategy = self._get_effective_strategy()
        target_base = self._get_target_base_dir()

        if not self._items:
            self.preview_lbl.setText("미리보기할 미디어 파일이 없습니다.")
            return

        # 위치 전략인 경우 위치 정보가 있는 샘플을 우선적으로 탐색하여 명확한 경로 예시 표시
        sample = self._items[0]
        if "geo" in str(strat).lower():
            for it in self._items:
                if it.country_name and it.country_name not in ("위치 정보 없음", "위치정보없음", "Unknown_Location"):
                    sample = it
                    break

        new_target_dir = self.service.calculate_target_dir(target_base, sample, strat)
        new_path = new_target_dir / sample.file_name

        try:
            rel_curr = sample.current_path.relative_to(self.current_base_dir)
        except Exception:
            rel_curr = sample.current_path.name

        try:
            rel_new = new_path.relative_to(target_base)
        except Exception:
            rel_new = new_path.name

        self.preview_lbl.setText(
            f"<b>[미리보기]</b><br>"
            f"• 변경 전: {rel_curr}<br>"
            f"• <b>변경 후: <font color='{Colors.ACCENT}'>{rel_new}</font></b>"
        )

    # ─────────────────────────────────────────────────────────────
    # 실행 파이프라인
    # ─────────────────────────────────────────────────────────────
    def _start_reorganize(self):
        target_base = self._get_target_base_dir()
        if not self.radio_inplace.isChecked() and not target_base.exists():
            QMessageBox.warning(self, "경로 오류", "지정한 대상 디렉토리가 존재하지 않습니다.")
            return

        strat: FolderStrategy = self._get_effective_strategy()

        # Step 2 화면으로 전환
        self._is_running = True
        self.header_title.setText("미디어 폴더 구조 재구성 진행 중...")
        self.header_desc.setText("시스템 전원 절전 방지 및 고속 재배치가 진행되고 있습니다.")
        self.stack.setCurrentIndex(1)
        self.spinner.start()

        # 워커 생성 및 시작
        self._worker = ReorganizeWorker(
            source_dir=self.current_base_dir,
            target_dir=target_base,
            strategy=strat,
            db_manager=self.db_manager,
            items=self._items,
        )
        self._worker.signals.progress.connect(self._on_worker_progress)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.signals.error.connect(self._on_worker_error)

        QThreadPool.globalInstance().start(self._worker)

    def _on_worker_progress(self, cur: int, tot: int, fname: str, spd: float, eta: float):
        pct = int((cur / tot) * 100) if tot > 0 else 0
        self.progress_bar.setValue(pct)
        self.step2_current_file.setText(f"처리 중: {fname} ({cur:,} / {tot:,} 개, {pct}%)")

        if spd > 0:
            if eta < 60:
                eta_str = f"약 {int(eta)}초 남음"
            else:
                eta_str = f"약 {int(eta // 60)}분 {int(eta % 60)}초 남음"
            self.step2_speed_lbl.setText(
                f"⏱️ 처리 속도: <b>{spd:,.0f}개/초</b> · 예상 잔여 시간: <b>{eta_str}</b>"
            )
        else:
            self.step2_speed_lbl.setText("⏱️ 처리 속도 및 예상 시간 계산 중...")

    def _on_worker_finished(self, result: ReorganizeResult):
        self._is_running = False
        self.spinner.stop()
        self._last_result = result

        # Step 3 화면으로 전환
        self.header_title.setText("폴더 구조 재구성 완료")
        self.header_desc.setText("모든 파일이 새로운 폴더 구조로 안전하게 배치되었습니다.")
        self.stack.setCurrentIndex(2)

        strat_name = self.combo_strategy.currentText()
        cleaned_cnt = result.cleaned_missing_count
        failed_cnt = result.failed_count

        detail_status_lines = []
        if cleaned_cnt > 0:
            detail_status_lines.append(f"<font color='#0072DE'>• <b>존재하지 않는 파일 자동 정리:</b> {cleaned_cnt:,}개 (DB 정리 완료)</font>")
        if failed_cnt > 0:
            detail_status_lines.append(f"<font color='#D93025'>• <b>파일 이동 실패:</b> {failed_cnt:,}개</font>")
        if not detail_status_lines:
            detail_status_lines.append("<font color='#137333'>• <b>모든 파일 정상 완료</b> (누락 및 실패 없음)</font>")

        speed_str = f"약 {result.total_count / result.elapsed_seconds:,.0f}개/초" if (result.elapsed_seconds > 0 and result.total_count > 0) else "-"

        # 2. 작업 요약 표 바인딩
        self.res_strat_lbl.setText(f"<b>{strat_name}</b>")

        res_txt_lines = [f"전체 <b>{result.total_count:,}개</b> 중 <b>{result.success_count:,}개</b> 성공"]
        if cleaned_cnt > 0:
            res_txt_lines.append(f"<font color='#0072DE'>• <b>존재하지 않는 파일 자동 정리:</b> {cleaned_cnt:,}개 (DB 정리 완료)</font>")
        if failed_cnt > 0:
            res_txt_lines.append(f"<font color='#D93025'>• <b>파일 이동 실패:</b> {failed_cnt:,}개</font>")
        if cleaned_cnt == 0 and failed_cnt == 0:
            res_txt_lines.append("<font color='#137333'>• <b>모든 파일 정상 완료</b> (누락 및 실패 없음)</font>")
        self.res_result_lbl.setText("<br>".join(res_txt_lines))

        self.res_folders_lbl.setText(f"새 폴더 <b>{result.new_folders_created:,}개</b> 생성 / 기존 빈 폴더 <b>{result.empty_folders_removed:,}개</b> 정리 완료")
        self.res_time_lbl.setText(f"<b>{result.elapsed_seconds:.2f}초</b> ({speed_str})")
        display_target = result.target_dir or str(self._get_target_base_dir())
        self.res_path_lbl.setText(display_target)
        self.res_path_lbl.setToolTip(display_target)

        # 3. 상세 내역 테이블 바인딩
        failed_items = result.failed_details or []
        total_issues = len(failed_items)

        if total_issues == 0:
            self.detail_stack.setCurrentIndex(0)
            self.detail_title_lbl.setText("📋 정리 및 실패 내역 (0건)")
        else:
            self.detail_stack.setCurrentIndex(1)
            self.detail_title_lbl.setText(f"📋 정리 및 실패 내역 (총 {total_issues:,}건)")

            self.detail_table.setRowCount(total_issues)
            for row_idx, item in enumerate(failed_items):
                # 1. 파일명
                f_item = QTableWidgetItem(item.file_name)
                f_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                font = QFont()
                font.setBold(True)
                f_item.setFont(font)
                self.detail_table.setItem(row_idx, 0, f_item)

                # 2. 상대 경로
                p_item = QTableWidgetItem(item.relative_path)
                p_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                p_item.setToolTip(item.relative_path)
                self.detail_table.setItem(row_idx, 1, p_item)

                # 3. 처리 결과 및 사유
                r_item = QTableWidgetItem(item.reason)
                r_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if item.status == "CLEANED":
                    r_item.setForeground(QColor("#0072DE"))
                else:
                    r_item.setForeground(QColor("#D93025"))
                self.detail_table.setItem(row_idx, 2, r_item)

    def _on_worker_error(self, err_msg: str):
        self._is_running = False
        self.spinner.stop()
        QMessageBox.critical(self, "재구성 오류", f"작업 중 오류가 발생했습니다:\n{err_msg}")
        self.reject()

    def _open_in_file_manager(self):
        """결과물이 저장된 디렉토리를 Finder 또는 파일 탐색기에서 열기"""
        path_str = self.res_path_lbl.text().strip() if hasattr(self, "res_path_lbl") else ""
        if path_str:
            p = Path(path_str)
            if p.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))
                return

        target_dir = self._get_target_base_dir()
        if target_dir and target_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_dir.resolve())))

    def closeEvent(self, event):
        """작업 진행 중 창 닫기 원천 차단"""
        if self._is_running:
            QMessageBox.warning(
                self,
                "작업 진행 중",
                "현재 파일 이동 및 데이터베이스 업데이트가 진행 중입니다.\n"
                "데이터 무결성을 보호하기 위해 작업이 완료될 때까지 창을 닫을 수 없습니다."
            )
            event.ignore()
        else:
            event.accept()
