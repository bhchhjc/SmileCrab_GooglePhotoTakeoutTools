"""
components/sidebar_widget.py
────────────────────────────────────────────────────────────────
사이드바 위젯 컴포넌트

구조:
  SidebarWidget (QFrame)
  ├── 헤더 영역: 앱 로고 + 타이틀
  ├── 네비게이션 버튼 그룹 (QButtonGroup)
  │   ├── NavButton: 대시보드
  │   ├── NavButton: 새 작업
  │   ├── NavButton: 처리 이력
  │   └── NavButton: 미디어 라이브러리
  ├── Spacer (유연한 여백)
  └── 하단 고정: 설정

토글 방식: ChatGPT 스타일
  - 완전히 숨김(0px) ↔ 완전히 표시(SIDEBAR_WIDTH px)
  - QPropertyAnimation으로 smooth 전환
"""

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QButtonGroup, QWidget, QSizePolicy,
)
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, Signal, QSize,
)
from PySide6.QtGui import QFont

from src.ui.theme import Colors, Fonts

# 사이드바 너비 상수
SIDEBAR_WIDTH = 240   # 완전히 표시될 때의 너비 (px)
ANIM_DURATION = 220   # 애니메이션 지속 시간 (ms)


class NavButton(QPushButton):
    """
    사이드바 내비게이션 버튼.
    - 아이콘(이모지) + 텍스트 라벨
    - 체크 상태(checked)로 현재 활성 메뉴 표시
    """

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(44)

        # 아이콘 + 텍스트를 하나의 문자열로 구성
        self.setText(f"  {icon}   {label}")
        font = QFont()
        font.setPointSize(Fonts.SIZE_BODY)
        self.setFont(font)


class SidebarWidget(QFrame):
    """
    ChatGPT 스타일 사이드바.
    
    Signals:
        nav_changed(int): 네비게이션 메뉴 선택 시 페이지 인덱스 방출
            0 = 대시보드
            1 = 새 작업
            2 = 처리 이력
            3 = 미디어 라이브러리
            4 = 설정
    """

    nav_changed = Signal(int)

    # 메뉴 정의: (아이콘, 라벨, 페이지 인덱스)
    NAV_ITEMS = [
        ("🏠", "대시보드",       0),
        ("➕", "새 작업",        1),
        ("⏱", "처리 이력",      2),
        ("🖼", "미디어 라이브러리", 3),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")

        # 초기 너비 = SIDEBAR_WIDTH (표시 상태로 시작)
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._is_visible = True

        self._setup_ui()
        self._setup_animation()

    def _setup_ui(self):
        """사이드바 UI 초기화."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 헤더 (로고 + 앱 타이틀) ──────────────────────────
        header = QWidget()
        header.setFixedHeight(60)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(10)

        logo_label = QLabel("📸")
        logo_label.setObjectName("SidebarLogo")
        logo_label.setFixedWidth(28)

        title_label = QLabel("Photo Tools")
        title_label.setObjectName("SidebarTitle")

        header_layout.addWidget(logo_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        layout.addWidget(header)

        # 헤더 아래 구분선
        divider = QFrame()
        divider.setObjectName("SidebarDivider")
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        # ── 네비게이션 버튼 그룹 ──────────────────────────────
        layout.addSpacing(8)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._buttons: dict[int, NavButton] = {}

        for icon, label, page_idx in self.NAV_ITEMS:
            btn = NavButton(icon, label)
            self._button_group.addButton(btn, page_idx)
            self._buttons[page_idx] = btn
            layout.addWidget(btn)

        # 첫 번째 항목(대시보드) 기본 선택
        self._buttons[0].setChecked(True)

        # 버튼 클릭 시 시그널 방출
        self._button_group.idClicked.connect(self.nav_changed.emit)

        # ── 유연한 Spacer ─────────────────────────────────────
        layout.addStretch()

        # ── 구분선 ───────────────────────────────────────────
        bottom_divider = QFrame()
        bottom_divider.setObjectName("SidebarDivider")
        bottom_divider.setFrameShape(QFrame.HLine)
        bottom_divider.setFixedHeight(1)
        layout.addWidget(bottom_divider)

        # ── 설정 버튼 (하단 고정) ─────────────────────────────
        layout.addSpacing(4)
        settings_btn = NavButton("⚙", "설정")
        self._button_group.addButton(settings_btn, 4)
        self._buttons[4] = settings_btn
        layout.addWidget(settings_btn)
        layout.addSpacing(8)

    def _setup_animation(self):
        """사이드바 슬라이드 애니메이션 초기화."""
        self._anim = QPropertyAnimation(self, b"maximumWidth")
        self._anim.setDuration(ANIM_DURATION)
        self._anim.setEasingCurve(QEasingCurve.InOutQuart)

    # ── 공개 메서드 ──────────────────────────────────────────

    def toggle(self):
        """사이드바 표시/숨김 토글."""
        if self._is_visible:
            self._hide_sidebar()
        else:
            self._show_sidebar()

    def set_active_page(self, page_idx: int):
        """
        외부에서 활성 페이지를 설정할 때 사용.
        (예: 대시보드에서 '새 작업 시작' 버튼 클릭 시)
        """
        if page_idx in self._buttons:
            self._buttons[page_idx].setChecked(True)

    # ── 내부 메서드 ──────────────────────────────────────────

    def _show_sidebar(self):
        """사이드바 표시 애니메이션 실행."""
        self._is_visible = True
        self.setMaximumWidth(0)  # 시작 지점 초기화
        self._anim.stop()
        self._anim.setStartValue(0)
        self._anim.setEndValue(SIDEBAR_WIDTH)
        # 애니메이션 종료 후 고정 너비 설정
        self._anim.finished.connect(self._on_show_finished)
        self._anim.start()

    def _hide_sidebar(self):
        """사이드바 숨김 애니메이션 실행."""
        self._is_visible = False
        # 먼저 finished 시그널 연결 해제 (중복 방지)
        try:
            self._anim.finished.disconnect()
        except RuntimeError:
            pass
        self._anim.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(0)
        self._anim.start()

    def _on_show_finished(self):
        """사이드바 표시 완료 후 최대 너비 고정."""
        try:
            self._anim.finished.disconnect(self._on_show_finished)
        except RuntimeError:
            pass
        self.setMaximumWidth(SIDEBAR_WIDTH)
        self.setFixedWidth(SIDEBAR_WIDTH)
