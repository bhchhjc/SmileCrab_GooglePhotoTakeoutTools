"""
main_window.py
────────────────────────────────────────────────────────────────
메인 윈도우 (사이드바 네비게이션 구조)

레이아웃:
  MainWindow (QMainWindow)
  └── CentralWidget
      └── RootLayout (QVBoxLayout)
          ├── TopBar (QFrame)   ← 햄버거 버튼 + 페이지 타이틀
          └── BodyLayout (QHBoxLayout)
              ├── SidebarWidget    ← 사이드바 (토글 가능)
              └── ContentArea
                  └── ContentStack (QStackedWidget)
                      ├── [0] DashboardView
                      ├── [1] JobView
                      ├── [2] HistoryView
                      ├── [3] LibraryView
                      └── [4] SettingsView
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFrame, QLabel, QStackedWidget, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from src.ui.theme import MAIN_STYLESHEET, Colors, Fonts
from src.ui.components.sidebar_widget import SidebarWidget
from src.ui.views.dashboard_view import DashboardView
from src.ui.views.job_view import JobView
from src.ui.views.history_view import HistoryView
from src.ui.views.library_view import LibraryView
from src.ui.views.settings_view import SettingsView


# 페이지 인덱스 → 타이틀 매핑
PAGE_TITLES = {
    0: "대시보드",
    1: "새 작업",
    2: "처리 이력",
    3: "미디어 라이브러리",
    4: "설정",
}


class MainWindow(QMainWindow):
    """
    앱 메인 윈도우.
    
    사이드바 + 콘텐츠 영역으로 구성되며,
    사이드바의 메뉴 선택에 따라 ContentStack의 페이지를 전환한다.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("📸 Google Photo Takeout Tools")
        self.resize(1100, 720)
        self.setMinimumSize(800, 560)

        # 전역 스타일시트 적용
        self.setStyleSheet(MAIN_STYLESHEET)

        self._setup_ui()
        self._connect_signals()

        # 초기 페이지: 대시보드
        self._navigate_to(0)

    # ── UI 초기화 ─────────────────────────────────────────────

    def _setup_ui(self):
        """전체 레이아웃 구성."""
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 상단 TopBar ───────────────────────────────────────
        self._top_bar = self._build_top_bar()
        root_layout.addWidget(self._top_bar)

        # ── 바디 (사이드바 + 콘텐츠) ─────────────────────────
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # 사이드바
        self._sidebar = SidebarWidget()
        body_layout.addWidget(self._sidebar)

        # 콘텐츠 영역
        content_area = QWidget()
        content_area.setObjectName("ContentArea")
        content_area_layout = QVBoxLayout(content_area)
        content_area_layout.setContentsMargins(0, 0, 0, 0)
        content_area_layout.setSpacing(0)

        # 콘텐츠 스택
        self._stack = QStackedWidget()
        self._stack.setObjectName("ContentStack")

        # 뷰 인스턴스 생성 및 등록
        self._dashboard_view = DashboardView()
        self._job_view       = JobView()
        self._history_view   = HistoryView()
        self._library_view   = LibraryView()
        self._settings_view  = SettingsView()

        self._stack.addWidget(self._dashboard_view)   # index 0
        self._stack.addWidget(self._job_view)         # index 1
        self._stack.addWidget(self._history_view)     # index 2
        self._stack.addWidget(self._library_view)     # index 3
        self._stack.addWidget(self._settings_view)    # index 4

        content_area_layout.addWidget(self._stack)
        body_layout.addWidget(content_area, stretch=1)

        root_layout.addWidget(body, stretch=1)

    def _build_top_bar(self) -> QFrame:
        """상단 TopBar 위젯 생성."""
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 16, 0)
        layout.setSpacing(12)

        # 햄버거(토글) 버튼
        self._hamburger_btn = QPushButton("☰")
        self._hamburger_btn.setObjectName("TopBarHamburger")
        self._hamburger_btn.setCursor(Qt.PointingHandCursor)
        self._hamburger_btn.setToolTip("사이드바 열기/닫기")
        layout.addWidget(self._hamburger_btn)

        # 페이지 타이틀 라벨
        self._page_title = QLabel("대시보드")
        self._page_title.setObjectName("PageTitle")
        font = QFont()
        font.setPointSize(Fonts.SIZE_H1)
        font.setBold(True)
        self._page_title.setFont(font)
        layout.addWidget(self._page_title)

        layout.addStretch()

        return bar

    # ── 시그널 연결 ───────────────────────────────────────────

    def _connect_signals(self):
        """각 컴포넌트 시그널 연결."""
        # 햄버거 버튼 → 사이드바 토글
        self._hamburger_btn.clicked.connect(self._sidebar.toggle)

        # 사이드바 메뉴 선택 → 페이지 전환
        self._sidebar.nav_changed.connect(self._navigate_to)

        # 대시보드 → "새 작업 시작" 버튼 → 새 작업 페이지로 이동
        self._dashboard_view.start_job_requested.connect(
            lambda: self._navigate_to(1)
        )

        # 작업 완료 시 → 대시보드 갱신 + 이력 갱신
        self._job_view.job_completed.connect(self._on_job_completed)

    # ── 내비게이션 ────────────────────────────────────────────

    def _navigate_to(self, page_idx: int):
        """
        지정된 페이지 인덱스로 콘텐츠 스택 전환.
        
        Args:
            page_idx: 0=대시보드, 1=새작업, 2=처리이력, 3=미디어, 4=설정
        """
        # 콘텐츠 스택 전환
        self._stack.setCurrentIndex(page_idx)

        # 상단 타이틀 갱신
        self._page_title.setText(PAGE_TITLES.get(page_idx, ""))

        # 사이드바 버튼 상태 동기화 (외부에서 navigate_to 호출 시)
        self._sidebar.set_active_page(page_idx)

        # 페이지 진입 시 필요한 데이터 갱신
        if page_idx == 0:
            self._dashboard_view.refresh()
        elif page_idx == 2:
            self._history_view.refresh()
        elif page_idx == 3:
            self._library_view.refresh()

    # ── 이벤트 핸들러 ─────────────────────────────────────────

    def _on_job_completed(self):
        """작업 완료 시 대시보드/이력 뷰 데이터 갱신."""
        self._dashboard_view.refresh()
        self._history_view.refresh()
