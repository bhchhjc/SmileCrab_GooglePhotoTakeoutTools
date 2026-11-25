"""
batch_rename_dialog.py
────────────────────────────────────────────────────────────────
메타데이터 기반 파일명 일괄 변경(Batch Rename) 3단계 위자드 다이얼로그

단계:
  Step 1: 대상 확인, 스택형 토큰 빌더(촬영일시, 카메라, 위치, 사용자 지정 문구, 괄호 등), 실시간 라이브 미리보기
  Step 2: 비동기 고속 이름변경 진행 (진행률, 속도/ETA, 절전방지, 안전주의 배너, 창닫기 잠금)
  Step 3: 결과 요약 격자 표 및 상세 내역(존재하지 않는 파일 정리/실패) 테이블, Finder 열기, 완료 자동 갱신
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThreadPool, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLayout, QLayoutItem, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.core.i18n import t
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.services.batch_rename_service import (
    BatchRenameResult, BatchRenameService, BracketStyle,
    RenamePatternConfig, RenameTokenConfig, RenameTokenType,
    get_token_display_name,
)
from src.ui.components.progress_circle import ProgressCircle
from src.ui.theme import Colors, Fonts
from src.ui.workers import BatchRenameWorker


DATE_FORMAT_OPTIONS = [
    ("%Y%m%d-%H%M%S", "YYYYMMDD-HHmmss (20230730-154740)"),
    ("%Y%m%d_%H%M%S", "YYYYMMDD_HHmmss (20230730_154740)"),
    ("%Y%m%d%H%M%S", "YYYYMMDDHHmmss (20230730154740)"),
    ("%Y%m%d", "YYYYMMDD (20230730)"),
    ("%Y-%m-%d", "YYYY-MM-DD (2023-07-30)"),
]

DELIMITER_OPTIONS = [
    ("_", "_ (언더스코어)"),
    ("-", "- (하이픈)"),
    (" ", "  (공백)"),
    ("", "없음 (붙여쓰기)"),
]


class FlowLayout(QLayout):
    """
    아이템들을 가로로 최대한 채우고, 공간이 부족하면 다음 줄로 자동 줄바꿈(Wrap)하는 레이아웃.
    TagView / Chip-Group에 최적화된 표준 Qt 레이아웃.
    """
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            w = item.widget()
            if w and not w.isVisibleTo(w.parentWidget()):
                continue

            space_x = self._spacing
            space_y = self._spacing
            item_size = item.sizeHint()
            item_w = item_size.width()
            item_h = item_size.height()

            next_x = x + item_w + space_x
            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item_w + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_h)

        return y + line_height - rect.y() + margins.bottom()


class BatchRenameDialog(QDialog):
    """메타데이터 기반 파일명 일괄 변경 마법사 다이얼로그"""

    def __init__(
        self,
        current_base_dir: Optional[Path] = None,
        db_manager: Optional[DatabaseManager] = None,
        target_items: Optional[List[Dict[str, Any]]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.db_manager = db_manager or DatabaseManager()
        self.repo = MediaRepository(self.db_manager)
        self.service = BatchRenameService(self.db_manager)

        # 등록된 출력 루트(저장 위치) 목록 조회
        self._output_roots = self.repo.get_output_roots()

        # 초기 대상 디렉토리 결정
        if current_base_dir:
            self.current_base_dir = Path(current_base_dir)
        elif self._output_roots:
            self.current_base_dir = Path(self._output_roots[0])
        else:
            self.current_base_dir = None

        self._items: List[Dict[str, Any]] = target_items or []
        self._tokens: List[RenameTokenConfig] = []
        self._token_row_widgets: List[QWidget] = []
        self._chip_buttons: Dict[RenameTokenType, QPushButton] = {}
        self._token_label_map: Dict[RenameTokenType, str] = {
            RenameTokenType.DATE: f"📅 {get_token_display_name(RenameTokenType.DATE)}",
            RenameTokenType.MAKE: f"📷 {get_token_display_name(RenameTokenType.MAKE)}",
            RenameTokenType.MODEL: f"📱 {get_token_display_name(RenameTokenType.MODEL)}",
            RenameTokenType.COUNTRY: f"🌍 {get_token_display_name(RenameTokenType.COUNTRY)}",
            RenameTokenType.STATE: f"🏙️ {get_token_display_name(RenameTokenType.STATE)}",
            RenameTokenType.CITY: f"📍 {get_token_display_name(RenameTokenType.CITY)}",
            RenameTokenType.ORIGINAL_NAME: f"📄 {get_token_display_name(RenameTokenType.ORIGINAL_NAME)}",
            RenameTokenType.CUSTOM_TEXT: f"✏️ {get_token_display_name(RenameTokenType.CUSTOM_TEXT)}",
            RenameTokenType.SEQUENCE: f"🔢 {get_token_display_name(RenameTokenType.SEQUENCE)}",
        }
        self._is_running = False
        self._worker: Optional[BatchRenameWorker] = None
        self._last_result: Optional[BatchRenameResult] = None

        # 기본 토큰 프리셋 (예: [Make] + Date)
        self._tokens = [
            RenameTokenConfig(RenameTokenType.DATE, bracket_style=BracketStyle.NONE, date_format="%Y%m%d-%H%M%S", next_delimiter="_"),
            RenameTokenConfig(RenameTokenType.ORIGINAL_NAME, bracket_style=BracketStyle.NONE, next_delimiter=""),
        ]

        self._setup_window()
        self._setup_ui()
        self._populate_target_root_combo()
        self._load_data()
        self._update_chip_buttons_state()

    def _setup_window(self):
        self.setWindowTitle(t("dialog.rename.window_title", "미디어 파일명 일괄 변경 마법사"))
        self.setModal(True)
        self.resize(800, 720)
        self.setMinimumSize(760, 600)

        from PySide6.QtGui import QPalette
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
                border-radius: 10px;
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
                font-size: 11px;
                color: #212529;
                min-height: 24px;
            }}
            QLineEdit {{
                border: 1px solid #CED4DA;
                border-radius: 6px;
                padding: 2px 8px;
                background-color: #FFFFFF;
                font-size: 11px;
                color: #212529;
            }}
            QPushButton#ChipBtn {{
                background-color: #FFFFFF;
                color: #0072DE;
                border: 1px solid #B8D6FB;
                border-radius: 12px;
                font-size: 11px;
                font-weight: bold;
                padding: 3px 9px;
            }}
            QPushButton#ChipBtn:hover {{
                background-color: #E8F2FD;
                border-color: #0072DE;
            }}
            QPushButton#PrimaryBtn {{
                background-color: #0072DE;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 16px;
            }}
            QPushButton#PrimaryBtn:hover {{
                background-color: #005BB5;
            }}
            QPushButton#PrimaryBtn:disabled {{
                background-color: #CED4DA;
                color: #6C757D;
            }}
            QPushButton#SecondaryBtn {{
                background-color: #FFFFFF;
                color: #495057;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                font-size: 12px;
                padding: 6px 14px;
            }}
            QPushButton#SecondaryBtn:hover {{
                background-color: #F8F9FA;
                border-color: #ADB5BD;
            }}
            QFrame#WarningBanner {{
                background-color: #FFF9DB;
                border: 1px solid #FFE066;
                border-radius: 10px;
                padding: 12px;
            }}
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(8)

        # 상단 공통 헤더
        header_layout = QHBoxLayout()
        header_icon = QLabel("🏷️")
        header_icon.setStyleSheet("font-size: 24px;")
        header_layout.addWidget(header_icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.header_title = QLabel(t("dialog.rename.header_title", "미디어 파일명 일괄 변경"))
        self.header_title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        self.header_desc = QLabel(t("dialog.rename.header_desc", "사진 및 동영상의 메타데이터(촬영일시, 카메라, 위치 등)를 원하는 조합으로 일괄 변경합니다."))
        self.header_desc.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
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
    # Step 1: 규칙 설정 및 미리보기
    # ─────────────────────────────────────────────────────────────
    def _create_step1_widget(self) -> QWidget:
        main_w = QWidget()
        main_vbox = QVBoxLayout(main_w)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(6)

        # 전체 내용을 감싸는 스크롤 영역 (가로 스크롤 완전 차단)
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.NoFrame)
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content_w = QWidget()
        vbox = QVBoxLayout(content_w)
        vbox.setContentsMargins(0, 0, 4, 0)
        vbox.setSpacing(10)

        # 1. 대상 안내 카드 (방안 A: 수직 계층형 컴팩트 카드)
        target_card = QFrame(objectName="Card")
        tc_layout = QVBoxLayout(target_card)
        tc_layout.setContentsMargins(14, 10, 14, 10)
        tc_layout.setSpacing(6)

        # 1행: 작업 대상 라벨 + 간결한 콤보박스 (폴더명 + 파일 수)
        row1_box = QHBoxLayout()
        row1_box.setSpacing(8)

        lbl_target_hdr = QLabel(t("dialog.rename.target_repo_label", "📁 작업 대상 저장소:"))
        lbl_target_hdr.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        row1_box.addWidget(lbl_target_hdr)

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

        lbl_path_title = QLabel(t("dialog.rename.actual_path_label", "📍 실제 저장 경로:"))
        lbl_path_title.setStyleSheet("font-size: 11px; color: #6C757D;")
        row2_box.addWidget(lbl_path_title)

        self.target_path_lbl = QLabel(str(self.current_base_dir) if self.current_base_dir else "-")
        self.target_path_lbl.setStyleSheet("font-size: 11px; color: #343A40;")
        self.target_path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row2_box.addWidget(self.target_path_lbl, 1)
        tc_layout.addLayout(row2_box)

        # 3행: 미디어 구성 통계 및 안전 안내
        row3_box = QHBoxLayout()
        row3_box.setSpacing(8)

        self.target_stats_lbl = QLabel(t("common.loading", "대상 미디어 분석 중..."))
        self.target_stats_lbl.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Colors.ACCENT};")
        row3_box.addWidget(self.target_stats_lbl)

        lbl_bullet = QLabel("·")
        lbl_bullet.setStyleSheet("font-size: 11px; color: #CED4DA;")
        row3_box.addWidget(lbl_bullet)

        scope_desc_lbl = QLabel(t("dialog.rename.target_scope_desc", "선택된 저장 위치 내부 파일들의 이름만 안전하게 변경됩니다."))
        scope_desc_lbl.setStyleSheet("font-size: 11px; color: #6C757D;")
        row3_box.addWidget(scope_desc_lbl)

        row3_box.addStretch()
        tc_layout.addLayout(row3_box)

        vbox.addWidget(target_card)

        # 2. 토큰 빌더 카드 (클릭으로 추가/제거하는 토글 칩 + 스택 목록)
        builder_card = QFrame(objectName="Card")
        bc_layout = QVBoxLayout(builder_card)
        bc_layout.setContentsMargins(14, 10, 14, 10)
        bc_layout.setSpacing(10)

        # 2-A. 파일 제목에 사용할 항목 선택 (TagView 스타일 자동 줄바꿈 FlowLayout)
        lbl_chips = QLabel(t("dialog.rename.available_tokens", "➕ 파일 제목에 사용할 항목 선택 (클릭하여 켜기/끄기):"))
        lbl_chips.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        bc_layout.addWidget(lbl_chips)

        chips_container = QWidget()
        chips_container.setStyleSheet("background: transparent;")
        flow_layout = FlowLayout(chips_container, margin=0, spacing=6)

        tokens_to_offer = [
            (RenameTokenType.DATE, f"📅 {get_token_display_name(RenameTokenType.DATE)}"),
            (RenameTokenType.MAKE, f"📷 {get_token_display_name(RenameTokenType.MAKE)}"),
            (RenameTokenType.MODEL, f"📱 {get_token_display_name(RenameTokenType.MODEL)}"),
            (RenameTokenType.COUNTRY, f"🌍 {get_token_display_name(RenameTokenType.COUNTRY)}"),
            (RenameTokenType.STATE, f"🏙️ {get_token_display_name(RenameTokenType.STATE)}"),
            (RenameTokenType.CITY, f"📍 {get_token_display_name(RenameTokenType.CITY)}"),
            (RenameTokenType.ORIGINAL_NAME, f"📄 {get_token_display_name(RenameTokenType.ORIGINAL_NAME)}"),
            (RenameTokenType.CUSTOM_TEXT, f"✏️ {get_token_display_name(RenameTokenType.CUSTOM_TEXT)}"),
            (RenameTokenType.SEQUENCE, f"🔢 {get_token_display_name(RenameTokenType.SEQUENCE)}"),
        ]

        self._chip_buttons.clear()
        for tt, label in tokens_to_offer:
            btn = QPushButton(label)
            btn.setObjectName("ChipBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked=False, t_type=tt: self._toggle_token(t_type))
            self._chip_buttons[tt] = btn
            flow_layout.addWidget(btn)

        bc_layout.addWidget(chips_container)

        # 2-B. 현재 조합 스택 영역 (일체형 표 Wrapper)
        lbl_stack = QLabel("📋 파일명 조합 순서 및 세부 설정:")
        lbl_stack.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        bc_layout.addWidget(lbl_stack)

        table_wrapper = QFrame()
        table_wrapper.setStyleSheet("""
            QFrame#TableWrapper {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
            }
        """)
        table_wrapper.setObjectName("TableWrapper")
        tw_layout = QVBoxLayout(table_wrapper)
        tw_layout.setContentsMargins(0, 0, 0, 0)
        tw_layout.setSpacing(0)

        # 테이블 헤더 바 (개별 헤더 테두리 없는 깔끔한 디자인)
        self.stack_header = QFrame()
        self.stack_header.setStyleSheet("""
            QFrame {
                background-color: #F8F9FA;
                border: none;
                border-bottom: 1px solid #E5E8EB;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QLabel {
                font-size: 11px;
                font-weight: bold;
                color: #495057;
                background: transparent;
                border: none;
            }
        """)
        h_layout = QHBoxLayout(self.stack_header)
        h_layout.setContentsMargins(10, 6, 10, 6)
        h_layout.setSpacing(8)

        lbl_h_num = QLabel("#")
        lbl_h_num.setFixedWidth(24)
        lbl_h_num.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(lbl_h_num)

        lbl_h_name = QLabel("항목명")
        lbl_h_name.setFixedWidth(95)
        lbl_h_name.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(lbl_h_name)

        lbl_h_opt = QLabel("세부 설정 (날짜 형식 / 직접 문구)")
        lbl_h_opt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h_layout.addWidget(lbl_h_opt, 1)

        lbl_h_brk = QLabel("괄호")
        lbl_h_brk.setFixedWidth(70)
        lbl_h_brk.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(lbl_h_brk)

        lbl_h_delim = QLabel("다음 연결")
        lbl_h_delim.setFixedWidth(80)
        lbl_h_delim.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(lbl_h_delim)

        lbl_h_actions = QLabel("순서 / 관리")
        lbl_h_actions.setFixedWidth(76)
        lbl_h_actions.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(lbl_h_actions)

        tw_layout.addWidget(self.stack_header)

        # 스택 아이템 컨테이너 (헤더 바로 아래 0 여백 밀착)
        self.stack_container = QWidget()
        self.stack_container.setStyleSheet("background-color: transparent;")
        self.stack_layout = QVBoxLayout(self.stack_container)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.stack_layout.setSpacing(0)
        tw_layout.addWidget(self.stack_container)

        bc_layout.addWidget(table_wrapper)

        # 2-C. 하단 옵션 바 (정보 누락 시 처리)
        bottom_box = QHBoxLayout()
        bottom_box.setSpacing(8)
        bottom_box.setContentsMargins(2, 4, 2, 2)

        lbl_fb = QLabel("정보 누락 시:")
        lbl_fb.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        bottom_box.addWidget(lbl_fb)

        self.combo_fallback = QComboBox()
        self.combo_fallback.setMinimumWidth(240)
        self.combo_fallback.view().setMinimumWidth(260)
        self.combo_fallback.addItem("해당 항목 생략 (구분자 자동 정돈)", "SKIP")
        self.combo_fallback.addItem("대체 텍스트(Unknown) 삽입", "TEXT")
        self.combo_fallback.currentIndexChanged.connect(self._on_pattern_changed)
        bottom_box.addWidget(self.combo_fallback)

        bottom_box.addStretch()
        bc_layout.addLayout(bottom_box)

        vbox.addWidget(builder_card)

        # 3. 실시간 미리보기 카드
        preview_card = QFrame(objectName="Card")
        pc_layout = QVBoxLayout(preview_card)
        pc_layout.setContentsMargins(12, 8, 12, 8)
        pc_layout.setSpacing(6)

        lbl_pv_title = QLabel("🔍 실시간 변환 미리보기 (현재 보유 미디어 기준)")
        lbl_pv_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")
        pc_layout.addWidget(lbl_pv_title)

        self.preview_lbl = QLabel("미리보기 계산 중...")
        self.preview_lbl.setStyleSheet("font-size: 12px; line-height: 140%; color: #212529;")
        self.preview_lbl.setWordWrap(True)
        pc_layout.addWidget(self.preview_lbl)

        vbox.addWidget(preview_card)

        main_scroll.setWidget(content_w)
        main_vbox.addWidget(main_scroll, 1)

        # 4. 하단 버튼 바 (다이얼로그 하단 고정)
        btn_box = QHBoxLayout()
        btn_box.setContentsMargins(0, 4, 0, 0)
        btn_box.setSpacing(10)

        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setObjectName("SecondaryBtn")
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setFixedWidth(90)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        btn_box.addStretch()

        self.btn_start = QPushButton("🔄 일괄 변경 시작")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setFixedHeight(32)
        self.btn_start.setMinimumWidth(140)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_batch_rename)
        btn_box.addWidget(self.btn_start)

        main_vbox.addLayout(btn_box)
        return main_w

    # ─────────────────────────────────────────────────────────────
    # Step 2: 비동기 진행 화면 (폴더구조 재구성과 디자인 통일)
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
        self.step2_title = QLabel("미디어 파일의 파일명을 일괄 변경하고 있습니다...")
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
            "<b>파일명 변경 및 데이터베이스 업데이트가 진행 중입니다.</b><br>"
            "파일 손상 및 꼬임을 방지하기 위해 <b>작업을 강제 종료하거나 PC 전원을 끄지 마세요.</b>"
        )
        warn_text.setStyleSheet("font-size: 12px; color: #7A5300; line-height: 140%;")
        warn_text.setWordWrap(True)
        wc_layout.addWidget(warn_text, 1)

        layout.addWidget(warn_card, alignment=Qt.AlignCenter)
        layout.addStretch()

        return w

    # ─────────────────────────────────────────────────────────────
    # Step 3: 완료 및 확인 화면 (정밀 격자 표 + 유동적 상세 테이블)
    # ─────────────────────────────────────────────────────────────
    def _create_step3_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. 상단 축하 타이틀
        header_box = QHBoxLayout()
        header_box.setAlignment(Qt.AlignCenter)
        header_box.setSpacing(8)

        done_icon = QLabel("🎉")
        done_icon.setStyleSheet("font-size: 26px; background: transparent;")
        header_box.addWidget(done_icon)

        self.step3_title = QLabel("파일명 일괄 변경이 완료되었습니다!")
        self.step3_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {Colors.TEXT_PRIMARY}; background: transparent;")
        header_box.addWidget(self.step3_title)
        layout.addLayout(header_box)

        # 2. 작업 요약 카드 (정밀 격자 표)
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
        grid_layout.setSpacing(1)

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
            lbl.setSizePolicy(QLabel().sizePolicy().horizontalPolicy(), QLabel().sizePolicy().verticalPolicy())
            return lbl

        def _make_val_lbl() -> QLabel:
            lbl = QLabel("-")
            lbl.setStyleSheet("""
                background-color: #FFFFFF;
                color: #212529;
                font-size: 12px;
                padding: 6px 12px;
                border: none;
            """)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return lbl

        grid_layout.addWidget(_make_key_lbl("적용된 규칙"), 0, 0)
        self.res_pattern_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_pattern_lbl, 0, 1)

        grid_layout.addWidget(_make_key_lbl("총 처리 결과"), 1, 0)
        self.res_result_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_result_lbl, 1, 1)

        grid_layout.addWidget(_make_key_lbl("소요 시간"), 2, 0)
        self.res_time_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_time_lbl, 2, 1)

        grid_layout.addWidget(_make_key_lbl("대상 디렉토리"), 3, 0)
        self.res_path_lbl = _make_val_lbl()
        grid_layout.addWidget(self.res_path_lbl, 3, 1)

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

        # 페이지 0: 모두 성공 시 배너
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

        lbl_all_ok_title = QLabel("모든 파일명이 오류 없이 성공적으로 변경되었습니다.")
        lbl_all_ok_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #137333; background: transparent; border: none;")
        lbl_all_ok_title.setAlignment(Qt.AlignCenter)

        lbl_all_ok_sub = QLabel("디스크 부재나 이름 충돌 없이 모든 파일의 이름과 DB 메타데이터가 정상 반영되었습니다.")
        lbl_all_ok_sub.setStyleSheet("font-size: 11px; color: #2E7D32; background: transparent; border: none;")
        lbl_all_ok_sub.setAlignment(Qt.AlignCenter)

        dew_layout.addWidget(lbl_all_ok_icon)
        dew_layout.addWidget(lbl_all_ok_title)
        dew_layout.addWidget(lbl_all_ok_sub)

        self.detail_stack.addWidget(self.detail_empty_widget)

        # 페이지 1: 상세 내역 테이블
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

        # 4. 하단 버튼 바
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
    # 토큰 스택 제어 로직
    # ─────────────────────────────────────────────────────────────
    def _update_chip_buttons_state(self):
        """현재 _tokens 목록에 포함된 토큰의 칩 버튼 스타일 동기화 (순수 라벨 + 색상으로만 선택 여부 구분)"""
        included_types = {t.token_type for t in self._tokens}
        for tt, btn in self._chip_buttons.items():
            label = self._token_label_map.get(tt, tt.value)
            btn.setText(label)
            if tt in included_types:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #0072DE;
                        color: #FFFFFF;
                        border: 1px solid #0072DE;
                        border-radius: 14px;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 3px 11px;
                    }
                    QPushButton:hover {
                        background-color: #005BB5;
                        border-color: #005BB5;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #FFFFFF;
                        color: #495057;
                        border: 1px solid #CED4DA;
                        border-radius: 14px;
                        font-size: 11px;
                        font-weight: 500;
                        padding: 3px 11px;
                    }
                    QPushButton:hover {
                        background-color: #F8F9FA;
                        border-color: #0072DE;
                        color: #0072DE;
                    }
                """)

    def _toggle_token(self, token_type: RenameTokenType):
        """토큰 칩 클릭 시: 포함되어 있으면 제거, 미포함이면 맨 뒤에 추가 (단일 추가 토글)"""
        found_idx = -1
        for idx, t in enumerate(self._tokens):
            if t.token_type == token_type:
                found_idx = idx
                break

        if found_idx >= 0:
            # 이미 있으면 제거
            self._tokens.pop(found_idx)
        else:
            # 없으면 추가 (직전 토큰 구분자 확인)
            if self._tokens:
                last_tok = self._tokens[-1]
                if last_tok.bracket_style == BracketStyle.NONE and not last_tok.next_delimiter:
                    last_tok.next_delimiter = "_"

            custom_init = "새텍스트" if token_type == RenameTokenType.CUSTOM_TEXT else ""
            new_token = RenameTokenConfig(
                token_type=token_type,
                bracket_style=BracketStyle.NONE,
                custom_text=custom_init,
                next_delimiter="",
            )
            self._tokens.append(new_token)

        self._rebuild_token_stack_ui()
        self._update_chip_buttons_state()
        self._on_pattern_changed()

    def _remove_token(self, index: int):
        """특정 인덱스의 토큰 제거"""
        if 0 <= index < len(self._tokens):
            self._tokens.pop(index)
            self._rebuild_token_stack_ui()
            self._update_chip_buttons_state()
            self._on_pattern_changed()

    def _move_token(self, index: int, direction: int):
        """토큰 순서 변경 (direction: -1 위로, +1 아래로)"""
        new_idx = index + direction
        if 0 <= new_idx < len(self._tokens):
            self._tokens[index], self._tokens[new_idx] = self._tokens[new_idx], self._tokens[index]
            self._rebuild_token_stack_ui()
            self._on_pattern_changed()

    def _rebuild_token_stack_ui(self):
        """현재 _tokens 목록을 기반으로 깔끔한 표 형식의 순서 UI를 재생성"""
        # 기존 위젯 정리
        while self.stack_layout.count():
            item = self.stack_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._tokens:
            lbl_empty = QLabel("선택된 항목이 없습니다. 상단에서 파일명에 포함할 항목을 클릭하세요.")
            lbl_empty.setStyleSheet("font-size: 11px; color: #ADB5BD; padding: 14px;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            self.stack_layout.addWidget(lbl_empty)
            return

        total_tokens = len(self._tokens)

        for idx, token in enumerate(self._tokens):
            is_last = (idx == total_tokens - 1)
            row_frame = QFrame()
            row_frame.setFixedHeight(38)
            border_style = "border: none;" if is_last else "border-bottom: 1px solid #ECEFF2;"
            row_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #FFFFFF;
                    {border_style}
                }}
                QFrame:hover {{
                    background-color: #F8F9FA;
                }}
            """)
            r_layout = QHBoxLayout(row_frame)
            r_layout.setContentsMargins(10, 2, 10, 2)
            r_layout.setSpacing(8)

            # 1. 번호 (#)
            lbl_num = QLabel(str(idx + 1))
            lbl_num.setFixedWidth(24)
            lbl_num.setAlignment(Qt.AlignCenter)
            lbl_num.setStyleSheet("font-size: 11px; font-weight: bold; color: #868E96; background: transparent; border: none;")
            r_layout.addWidget(lbl_num)

            # 2. 항목명 뱃지 (가로폭 95px 통일)
            badge_text = self._token_label_map.get(token.token_type, token.token_type.value)
            lbl_name = QLabel(badge_text)
            lbl_name.setFixedWidth(95)
            lbl_name.setAlignment(Qt.AlignCenter)
            lbl_name.setStyleSheet("""
                background-color: #E8F2FD;
                color: #0072DE;
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
                padding: 3px 0px;
                border: 1px solid #D0E4FA;
            """)
            r_layout.addWidget(lbl_name)

            # 3. 세부 설정 (날짜 형식 / 사용자 직접 문구 / 기타 항목은 힌트 안내)
            if token.token_type == RenameTokenType.CUSTOM_TEXT:
                edit_custom = QLineEdit(token.custom_text)
                edit_custom.setPlaceholderText("직접 문구 입력...")
                edit_custom.setFixedHeight(26)
                edit_custom.setStyleSheet("font-size: 11px; padding: 2px 6px;")
                edit_custom.textChanged.connect(lambda txt, t=token: self._update_custom_text(t, txt))
                r_layout.addWidget(edit_custom, 1)
            elif token.token_type == RenameTokenType.DATE:
                combo_date = QComboBox()
                combo_date.setFixedHeight(26)
                combo_date.setStyleSheet("font-size: 11px;")
                for fmt_val, fmt_lbl in DATE_FORMAT_OPTIONS:
                    combo_date.addItem(fmt_lbl, fmt_val)
                cur_idx = 0
                for f_i, (fv, fl) in enumerate(DATE_FORMAT_OPTIONS):
                    if fv == token.date_format:
                        cur_idx = f_i
                        break
                combo_date.setCurrentIndex(cur_idx)
                combo_date.currentIndexChanged.connect(lambda c_idx, t=token, cb=combo_date: self._update_date_format(t, cb.currentData()))
                r_layout.addWidget(combo_date, 1)
            else:
                lbl_hint = QLabel("(메타데이터 값 자동 반영)")
                lbl_hint.setStyleSheet("font-size: 11px; color: #ADB5BD; background: transparent; border: none;")
                r_layout.addWidget(lbl_hint, 1)

            # 4. 괄호 선택 (기호로만 콤팩트 표시, 가로폭 70px, 팝업 85px로 잘림 완전 방지)
            combo_bracket = QComboBox()
            combo_bracket.setFixedWidth(70)
            combo_bracket.setFixedHeight(26)
            combo_bracket.setStyleSheet("font-size: 11px; padding: 2px 4px 2px 6px;")
            combo_bracket.view().setMinimumWidth(85)
            combo_bracket.addItem("없음", BracketStyle.NONE)
            combo_bracket.addItem("[  ]", BracketStyle.SQUARE)
            combo_bracket.addItem("(  )", BracketStyle.ROUND)
            if token.bracket_style == BracketStyle.SQUARE:
                combo_bracket.setCurrentIndex(1)
            elif token.bracket_style == BracketStyle.ROUND:
                combo_bracket.setCurrentIndex(2)
            combo_bracket.currentIndexChanged.connect(lambda c_idx, t=token, cb=combo_bracket: self._update_bracket(t, cb.currentData()))
            r_layout.addWidget(combo_bracket)

            # 5. 다음 연결 구분자 (가로폭 80px로 낭비 축소, 팝업 뷰 110px)
            combo_next_delim = QComboBox()
            combo_next_delim.setFixedWidth(80)
            combo_next_delim.setFixedHeight(26)
            combo_next_delim.setStyleSheet("font-size: 11px; padding: 2px 4px 2px 6px;")
            combo_next_delim.view().setMinimumWidth(110)

            if is_last:
                combo_next_delim.addItem("— (끝)", "")
                combo_next_delim.setEnabled(False)
            else:
                combo_next_delim.addItem("_ (언더)", "_")
                combo_next_delim.addItem("없음", "")
                combo_next_delim.addItem("- (하이픈)", "-")
                combo_next_delim.addItem("공백", " ")
                combo_next_delim.addItem(". (마침표)", ".")

                cur_d = token.next_delimiter if token.next_delimiter is not None else "_"
                target_d_idx = 0
                for d_i, d_val in enumerate(["_", "", "-", " ", "."]):
                    if cur_d == d_val:
                        target_d_idx = d_i
                        break
                combo_next_delim.setCurrentIndex(target_d_idx)
                combo_next_delim.currentIndexChanged.connect(
                    lambda c_idx, t=token, cb=combo_next_delim: self._update_next_delimiter(t, cb.currentData())
                )
            r_layout.addWidget(combo_next_delim)

            # 6. 순서 이동 및 삭제 버튼 (가로폭 76px 영역)
            action_box = QHBoxLayout()
            action_box.setSpacing(3)
            action_box.setContentsMargins(0, 0, 0, 0)

            btn_up = QPushButton("▲")
            btn_up.setFixedSize(22, 22)
            btn_up.setEnabled(idx > 0)
            btn_up.setCursor(Qt.PointingHandCursor)
            btn_up.clicked.connect(lambda checked=False, i=idx: self._move_token(i, -1))
            action_box.addWidget(btn_up)

            btn_down = QPushButton("▼")
            btn_down.setFixedSize(22, 22)
            btn_down.setEnabled(idx < total_tokens - 1)
            btn_down.setCursor(Qt.PointingHandCursor)
            btn_down.clicked.connect(lambda checked=False, i=idx: self._move_token(i, 1))
            action_box.addWidget(btn_down)

            btn_del = QPushButton("✕")
            btn_del.setFixedSize(22, 22)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("color: #D93025; font-weight: bold;")
            btn_del.clicked.connect(lambda checked=False, i=idx: self._remove_token(i))
            action_box.addWidget(btn_del)

            r_layout.addLayout(action_box)
            self.stack_layout.addWidget(row_frame)

    def _update_custom_text(self, token: RenameTokenConfig, text: str):
        token.custom_text = text
        self._on_pattern_changed()

    def _update_date_format(self, token: RenameTokenConfig, fmt: str):
        token.date_format = fmt
        self._on_pattern_changed()

    def _update_bracket(self, token: RenameTokenConfig, bracket: BracketStyle):
        old_bracket = token.bracket_style
        token.bracket_style = bracket
        # 괄호 적용 시 뒤 구분자를 직관적으로 '없음(밀착)'으로 자동 전환
        if bracket != BracketStyle.NONE and old_bracket == BracketStyle.NONE:
            token.next_delimiter = ""
            self._rebuild_token_stack_ui()
        elif bracket == BracketStyle.NONE and old_bracket != BracketStyle.NONE:
            token.next_delimiter = "_"
            self._rebuild_token_stack_ui()
        self._on_pattern_changed()

    def _update_next_delimiter(self, token: RenameTokenConfig, delim: Optional[str]):
        token.next_delimiter = delim
        self._on_pattern_changed()

    def _get_current_pattern(self) -> RenamePatternConfig:
        fb_mode = self.combo_fallback.currentData() if hasattr(self, "combo_fallback") else "SKIP"
        fb_text = "Unknown" if fb_mode == "TEXT" else ""
        return RenamePatternConfig(
            tokens=self._tokens,
            delimiter="_",
            fallback_text=fb_text,
            preserve_extension=True,
            auto_remove_bracket_delimiters=False,
        )

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
        """선택된 저장 위치 디렉토리 기준으로 대상 미디어 목록 로드 및 통계 표시 (MediaRepository 사용)"""
        base_str = str(self.current_base_dir.resolve()) if self.current_base_dir else ""
        if base_str:
            self._items = self.repo.get_media_items_for_rename(base_str)
        else:
            self._items = []

        total = len(self._items)
        photos = sum(1 for it in self._items if it.get("media_type") == "photo")
        videos = sum(1 for it in self._items if it.get("media_type") == "video")

        if hasattr(self, "target_path_lbl"):
            self.target_path_lbl.setText(str(self.current_base_dir) if self.current_base_dir else "-")
            self.target_path_lbl.setToolTip(str(self.current_base_dir) if self.current_base_dir else "")

        self.target_stats_lbl.setText(
            f"{t('common.total', '총')} <b>{total:,}{t('common.items', '개')}</b> {t('common.files', '미디어')} ({t('common.photos', '사진')} {photos:,}{t('common.items', '개')}, {t('common.videos', '동영상')} {videos:,}{t('common.items', '개')})"
        )

        if total == 0:
            self.btn_start.setEnabled(False)
            self.btn_start.setText("대상 파일 없음")
        else:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("🔄 일괄 변경 시작")

        self._rebuild_token_stack_ui()
        self._on_pattern_changed()

    def _on_pattern_changed(self):
        """패턴 변경 시 실시간 미리보기 갱신"""
        pattern = self._get_current_pattern()
        if not self._items:
            self.preview_lbl.setText("미리보기할 미디어 파일이 없습니다.")
            return

        # 샘플 3개 선정 (1: 기기/위치 모두 있는 파일, 2: 정보 누락 파일, 3: 일반 파일)
        samples = self._items[:3]
        lines = []
        for it in samples:
            old_name = it.get("file_name") or Path(it.get("file_path", "")).name
            new_name = self.service.generate_filename(pattern, it, sequence_num=1)
            lines.append(
                f"• 변경 전: <code>{old_name}</code><br>"
                f"• <b>변경 후: <font color='#0072DE'><code>{new_name}</code></font></b><br>"
            )

        self.preview_lbl.setText("".join(lines))

    # ─────────────────────────────────────────────────────────────
    # 실행 파이프라인
    # ─────────────────────────────────────────────────────────────
    def _start_batch_rename(self):
        pattern = self._get_current_pattern()
        if not pattern.tokens:
            QMessageBox.warning(self, "규칙 오류", "하나 이상의 메타데이터 토큰을 추가해 주세요.")
            return

        # Step 2 화면 전환
        self._is_running = True
        self.header_title.setText("파일명 일괄 변경 진행 중...")
        self.header_desc.setText("타임스탬프 무손실 보존 및 안전한 파일명 변경이 진행되고 있습니다.")
        self.stack.setCurrentIndex(1)
        self.spinner.start()

        # 워커 시작
        self._worker = BatchRenameWorker(
            items=self._items,
            pattern=pattern,
            source_dir=self.current_base_dir,
            db_manager=self.db_manager,
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

    def _on_worker_finished(self, result: BatchRenameResult):
        self._is_running = False
        self.spinner.stop()
        self._last_result = result

        # Step 3 화면 전환
        self.header_title.setText("파일명 일괄 변경 완료")
        self.header_desc.setText("모든 파일명이 지정한 규칙에 맞추어 안전하게 변경되었습니다.")
        self.stack.setCurrentIndex(2)

        # 1. 적용된 규칙
        self.res_pattern_lbl.setText(f"<code>{result.pattern_summary}</code>")

        # 2. 총 처리 결과
        cleaned_cnt = result.cleaned_missing_count
        failed_cnt = result.failed_count
        res_txt_lines = [f"전체 <b>{result.total_count:,}개</b> 중 <b>{result.success_count:,}개</b> 성공"]
        if cleaned_cnt > 0:
            res_txt_lines.append(f"<font color='#0072DE'>• <b>존재하지 않는 파일 자동 정리:</b> {cleaned_cnt:,}개 (DB 정리 완료)</font>")
        if failed_cnt > 0:
            res_txt_lines.append(f"<font color='#D93025'>• <b>변경 실패:</b> {failed_cnt:,}개</font>")
        if cleaned_cnt == 0 and failed_cnt == 0:
            res_txt_lines.append("<font color='#137333'>• <b>모든 파일 정상 완료</b> (누락 및 실패 없음)</font>")
        self.res_result_lbl.setText("<br>".join(res_txt_lines))

        # 3. 소요 시간
        speed_str = f"약 {result.total_count / result.elapsed_seconds:,.0f}개/초" if (result.elapsed_seconds > 0 and result.total_count > 0) else "-"
        self.res_time_lbl.setText(f"<b>{result.elapsed_seconds:.2f}초</b> ({speed_str})")

        # 4. 대상 디렉토리
        display_dir = result.source_dir or self.target_path_lbl.text()
        self.res_path_lbl.setText(display_dir)
        self.res_path_lbl.setToolTip(display_dir)

        # 5. 상세 내역 테이블
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
                f_item = QTableWidgetItem(item.file_name)
                f_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                font = QFont()
                font.setBold(True)
                f_item.setFont(font)
                self.detail_table.setItem(row_idx, 0, f_item)

                p_item = QTableWidgetItem(item.relative_path)
                p_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                p_item.setToolTip(item.relative_path)
                self.detail_table.setItem(row_idx, 1, p_item)

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
        QMessageBox.critical(self, "변경 오류", f"파일명 일괄 변경 중 오류가 발생했습니다:\n{err_msg}")
        self.reject()

    def _open_in_file_manager(self):
        """결과물이 저장된 디렉토리를 Finder 또는 파일 탐색기에서 열기"""
        # 1. 결과 요약 라벨에 표시된 실제 대상 디렉토리
        target_path_str = self.res_path_lbl.text().strip() if hasattr(self, "res_path_lbl") else ""
        # 2. Step 1 대상 경로 라벨
        if not target_path_str and hasattr(self, "target_path_lbl"):
            target_path_str = self.target_path_lbl.text().strip()
        # 3. current_base_dir
        if not target_path_str and self.current_base_dir:
            target_path_str = str(self.current_base_dir)

        if target_path_str:
            p = Path(target_path_str)
            if p.is_file():
                p = p.parent
            if p.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))
                return

        # 4. 그래도 없으면 대상 아이템 중 첫 번째 파일의 부모 폴더 열기
        if self._items:
            first_path = self._items[0].get("file_path")
            if first_path:
                p = Path(first_path).parent
                if p.exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    def closeEvent(self, event):
        if self._is_running:
            QMessageBox.warning(
                self,
                "작업 진행 중",
                "현재 파일명 변경 및 데이터베이스 업데이트가 진행 중입니다.\n"
                "데이터 무결성을 보호하기 위해 작업이 완료될 때까지 창을 닫을 수 없습니다."
            )
            event.ignore()
        else:
            event.accept()
