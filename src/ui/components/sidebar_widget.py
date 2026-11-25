"""
components/sidebar_widget.py
────────────────────────────────────────────────────────────────
Material Design 3 (M3) Navigation Rail 컴포넌트

사양:
  - Collapsed (기본): 폭 76px (20px 큰 아이콘 + 11px 하단 라벨)
  - Expanded (확장): 폭 240px (아이콘 + 우측 라벨)
  - M3 Active Indicator Pill (타원형 알약 배경 #D3E3FD) 적용
  - 상단 햄버거 버튼(☰) 정중앙 배치 및 호버 영역 완벽 정렬
"""

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QButtonGroup, QWidget, QSizePolicy,
)
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, Signal,
)
from PySide6.QtGui import QFont

from src.core.i18n import i18n, t
from src.ui.theme import Colors, Fonts

RAIL_COLLAPSED_WIDTH = 76
RAIL_EXPANDED_WIDTH  = 240
ANIM_DURATION        = 200  # ms


class M3RailItem(QPushButton):
    """
    Material Design 3 Navigation Rail 버튼.
    - 컴팩트 모드(76px): 56x32px 알약(Pill) 인디케이터 안에 24px 대형 아이콘 + 하단 11px 라벨
    - 확장 모드(240px): 48px 가로 행에 20px 아이콘 + 13px 라벨
    """

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self._icon_str = icon
        self._label_str = label
        self._is_expanded = False

        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setText("")  # 텍스트는 내부 커스텀 라벨로만 렌더링

        # 내부 메인 레이아웃
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # 1. 컴팩트 모드 위젯 (76px)
        self._compact_widget = QWidget()
        self._compact_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        c_box = QVBoxLayout(self._compact_widget)
        c_box.setContentsMargins(0, 4, 0, 4)
        c_box.setSpacing(3)
        c_box.setAlignment(Qt.AlignCenter)

        # M3 타원형 알약 (Active Indicator Pill: 56x32)
        self._pill = QFrame()
        self._pill.setFixedSize(56, 32)
        pill_layout = QHBoxLayout(self._pill)
        pill_layout.setContentsMargins(0, 0, 0, 0)
        pill_layout.setAlignment(Qt.AlignCenter)

        self._c_icon = QLabel(icon)
        self._c_icon.setAlignment(Qt.AlignCenter)
        self._c_icon.setStyleSheet("font-size: 22px; background: transparent;")
        pill_layout.addWidget(self._c_icon)
        c_box.addWidget(self._pill, 0, Qt.AlignCenter)

        self._c_label = QLabel(label)
        self._c_label.setAlignment(Qt.AlignCenter)
        self._c_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #444746; background: transparent;")
        c_box.addWidget(self._c_label, 0, Qt.AlignCenter)

        self._layout.addWidget(self._compact_widget)

        # 2. 확장 모드 위젯 (240px)
        self._expanded_widget = QWidget()
        self._expanded_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        e_box = QHBoxLayout(self._expanded_widget)
        e_box.setContentsMargins(20, 0, 16, 0)
        e_box.setSpacing(14)
        e_box.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._e_icon = QLabel(icon)
        self._e_icon.setStyleSheet("font-size: 20px; background: transparent;")
        e_box.addWidget(self._e_icon)

        self._e_label = QLabel(label)
        self._e_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #1F1F1F; background: transparent;")
        e_box.addWidget(self._e_label)

        self._layout.addWidget(self._expanded_widget)
        self._expanded_widget.setVisible(False)

        self.toggled.connect(self._sync_state)
        self.update_mode(is_expanded=False)

    def update_mode(self, is_expanded: bool):
        self._is_expanded = is_expanded
        if is_expanded:
            self.setObjectName("ExpandedRailItem")
            self.setFixedHeight(48)
            self._compact_widget.setVisible(False)
            self._expanded_widget.setVisible(True)
        else:
            self.setObjectName("CompactRailItem")
            self.setFixedHeight(64)
            self._compact_widget.setVisible(True)
            self._expanded_widget.setVisible(False)

        self._sync_state(self.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)

    def set_label(self, label: str):
        self._label_str = label
        self._c_label.setText(label)
        self._e_label.setText(label)

    def _sync_state(self, checked: bool):
        if checked:
            self._pill.setStyleSheet("background-color: #D3E3FD; border-radius: 16px;")
            self._c_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #041E49; background: transparent;")
            self._e_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #041E49; background: transparent;")
        else:
            self._pill.setStyleSheet("background-color: transparent; border-radius: 16px;")
            self._c_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #444746; background: transparent;")
            self._e_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #444746; background: transparent;")


class SidebarWidget(QFrame):
    """
    Material Design 3 Navigation Rail
    """

    nav_changed = Signal(int)

    NAV_ITEMS = [
        ("🏠", "홈",       0),
        ("➕", "새 작업",   1),
        ("⏱", "처리 이력", 2),
        ("🖼", "라이브러리", 3),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setFixedWidth(RAIL_COLLAPSED_WIDTH)
        self._is_expanded = False

        self._buttons: dict[int, M3RailItem] = {}
        self._setup_ui()
        self._setup_animation()
        self.retranslate_ui()
        i18n.language_changed.connect(lambda _: self.retranslate_ui())

    def retranslate_ui(self):
        """다국어 변경 시 사이드바 텍스트 갱신"""
        labels = {
            0: t("sidebar.dashboard", "홈"),
            1: t("sidebar.job", "새 작업"),
            2: t("sidebar.history", "처리 이력"),
            3: t("sidebar.library", "라이브러리"),
            4: t("sidebar.settings", "설정"),
        }
        for idx, lbl in labels.items():
            if idx in self._buttons:
                self._buttons[idx].set_label(lbl)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 16)
        layout.setSpacing(6)

        # ── 상단 햄버거 토글 버튼 (좌측 20px 제자리 고정) ───────
        self._top_container = QWidget()
        self._top_container.setFixedHeight(44)
        top_layout = QHBoxLayout(self._top_container)
        top_layout.setContentsMargins(20, 0, 16, 0)
        top_layout.setSpacing(12)

        self._toggle_btn = QPushButton("☰")
        self._toggle_btn.setObjectName("RailToggleBtn")
        self._toggle_btn.setFixedSize(36, 36)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setToolTip("메뉴 확장 / 축소")
        self._toggle_btn.clicked.connect(self.toggle)
        top_layout.addWidget(self._toggle_btn)

        self._app_title = QLabel("Smile Crab")
        self._app_title.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {Colors.TEXT_PRIMARY};")
        self._app_title.setVisible(False)
        top_layout.addWidget(self._app_title)
        top_layout.addStretch()

        layout.addWidget(self._top_container)
        layout.addSpacing(4)

        # ── 내비게이션 버튼 그룹 ──────────────────────────────
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for icon, label, page_idx in self.NAV_ITEMS:
            btn = M3RailItem(icon, label)
            self._btn_group.addButton(btn, page_idx)
            self._buttons[page_idx] = btn
            layout.addWidget(btn)

        # 기본 선택: 홈
        self._buttons[0].setChecked(True)
        self._btn_group.idClicked.connect(self.nav_changed.emit)

        layout.addStretch()

        # ── 하단 설정 버튼 ────────────────────────────────────
        divider = QFrame()
        divider.setObjectName("SidebarDivider")
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        settings_btn = M3RailItem("⚙", "설정")
        self._btn_group.addButton(settings_btn, 4)
        self._buttons[4] = settings_btn
        layout.addWidget(settings_btn)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(ANIM_DURATION)
        self._anim.setEasingCurve(QEasingCurve.InOutQuart)
        self._anim.valueChanged.connect(self._on_anim_value_changed)
        self._anim.finished.connect(self._on_anim_finished)

    def toggle(self):
        self._anim.stop()
        if self._is_expanded:
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(RAIL_COLLAPSED_WIDTH)
            self._app_title.setVisible(False)
            for btn in self._buttons.values():
                btn.update_mode(is_expanded=False)
        else:
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(RAIL_EXPANDED_WIDTH)
            for btn in self._buttons.values():
                btn.update_mode(is_expanded=True)

        self._is_expanded = not self._is_expanded
        self._anim.start()

    def _on_anim_value_changed(self, value):
        self.setFixedWidth(value)

    def _on_anim_finished(self):
        if self._is_expanded:
            self.setFixedWidth(RAIL_EXPANDED_WIDTH)
            self._app_title.setVisible(True)
        else:
            self.setFixedWidth(RAIL_COLLAPSED_WIDTH)
            self._app_title.setVisible(False)

    def set_active_page(self, page_idx: int):
        if page_idx in self._buttons:
            self._buttons[page_idx].setChecked(True)
