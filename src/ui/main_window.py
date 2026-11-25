"""
main_window.py
────────────────────────────────────────────────────────────────
메인 윈도우 (Material 3 Navigation Rail + Antigravity 일체형 구조)

레이아웃:
  MainWindow (QMainWindow)
  └── CentralWidget
      └── RootLayout (QHBoxLayout)
          ├── SidebarWidget (M3 Navigation Rail, 76px ↔ 240px)
          └── ContentStack (QStackedWidget)
              ├── [0] DashboardView
              ├── [1] JobView
              ├── [2] HistoryView
              ├── [3] LibraryView
              └── [4] SettingsView
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QCloseEvent, QIcon

from src.core.i18n import i18n, t
from src.data.database import DatabaseManager
from src.ui.theme import MAIN_STYLESHEET
from src.ui.components.sidebar_widget import SidebarWidget
from src.ui.views.dashboard_view import DashboardView
from src.ui.views.job_view import JobView
from src.ui.views.history_view import HistoryView
from src.ui.views.library_view import LibraryView
from src.ui.views.settings_view import SettingsView


class MainWindow(QMainWindow):
    """
    앱 메인 윈도우.
    상단 구분선을 없애고 Navigation Rail이 전체 높이를 담당하는 일체형 윈도우.
    """

    def __init__(self):
        super().__init__()
        # DB에 저장된 언어 복원 또는 시스템 언어 감지
        db = DatabaseManager()
        saved_lang = db.get_setting("app_language")
        if saved_lang:
            i18n.set_locale(saved_lang)
        else:
            detected = i18n.detect_system_locale()
            i18n.set_locale(detected)

        self.setWindowTitle(f"🦀 {t('common.app_title', 'Smile Crab [Google Photo Takeout Tools]')}")
        self.resize(1180, 760)
        self.setMinimumSize(880, 600)

        # 윈도우 창 아이콘 설정
        root_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent.parent
        for icon_name in ("app_icon.png", "app_icon.ico", "app_icon.icns"):
            icon_file = root_dir / "assets" / "icons" / icon_name
            if icon_file.exists():
                self.setWindowIcon(QIcon(str(icon_file)))
                break

        # 전역 스타일시트 적용
        self.setStyleSheet(MAIN_STYLESHEET)

        self._setup_ui()
        self._connect_signals()

        i18n.language_changed.connect(self._retranslate_ui)

        # 초기 페이지: 대시보드
        self._navigate_to(0)

    def _retranslate_ui(self):
        self.setWindowTitle(f"🦀 {t('common.app_title', 'Smile Crab [Google Photo Takeout Tools]')}")

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        # 일체형 수평 레이아웃 (TopBar 제거)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. 좌측 M3 Navigation Rail (전체 높이)
        self._sidebar = SidebarWidget()
        root_layout.addWidget(self._sidebar)

        # 2. 우측 콘텐츠 스택
        self._stack = QStackedWidget()
        self._stack.setObjectName("ContentStack")

        self._dashboard_view = DashboardView()
        self._job_view       = JobView()
        self._history_view   = HistoryView()
        self._library_view   = LibraryView()
        self._settings_view  = SettingsView(on_db_reset=self._on_db_reset)

        self._stack.addWidget(self._dashboard_view)   # index 0
        self._stack.addWidget(self._job_view)         # index 1
        self._stack.addWidget(self._history_view)     # index 2
        self._stack.addWidget(self._library_view)     # index 3
        self._stack.addWidget(self._settings_view)    # index 4

        root_layout.addWidget(self._stack, stretch=1)

        # ── 단축키 바인딩 (macOS Cmd+W / Cmd+Q, Windows Alt+F4 / Ctrl+W) ──
        # Cmd+W (macOS) / Ctrl+W (Windows)
        self._sc_close = QShortcut(QKeySequence("Ctrl+W"), self)
        self._sc_close.activated.connect(self.close)

        # Alt+F4 (Windows 표준 창 닫기)
        self._sc_alt_f4 = QShortcut(QKeySequence("Alt+F4"), self)
        self._sc_alt_f4.activated.connect(self.close)

        # Cmd+Q (macOS 앱 종료) / Ctrl+Q (Windows 앱 종료)
        self._sc_quit = QShortcut(QKeySequence("Ctrl+Q"), self)
        self._sc_quit.activated.connect(self.close)

    def closeEvent(self, event: QCloseEvent):
        """프로그램 종료 시 확인 다이얼로그 노출 (진행 중인 작업 보호)"""
        is_busy = hasattr(self, "_job_view") and getattr(self._job_view, "is_busy", False)

        if is_busy:
            title = t("common.quit_busy_title", "작업 진행 중 종료 확인")
            text = t(
                "common.quit_busy_msg",
                "현재 사진 스캔 또는 정리 작업이 진행 중입니다.\n"
                "지금 프로그램을 종료하면 작업이 즉시 중단되며 일부 파일만 정리될 수 있습니다.\n\n"
                "정말 프로그램을 종료하시겠습니까?"
            )
        else:
            title = t("common.quit_title", "프로그램 종료 확인")
            text = t("common.quit_msg", "GooglePhotoTakeoutTools 프로그램을 종료하시겠습니까?")

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Question if not is_busy else QMessageBox.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)

        yes_btn = msg_box.button(QMessageBox.Yes)
        if yes_btn:
            yes_btn.setText(t("common.quit_btn", "종료"))
        no_btn = msg_box.button(QMessageBox.No)
        if no_btn:
            no_btn.setText(t("common.cancel", "취소"))

        reply = msg_box.exec()
        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()

    def _connect_signals(self):
        # 사이드바 메뉴 선택 → 페이지 전환
        self._sidebar.nav_changed.connect(self._navigate_to)

        # 대시보드 → "새 작업 시작" 버튼 → 새 작업 페이지로 이동
        self._dashboard_view.start_job_requested.connect(
            lambda: self._navigate_to(1)
        )
        # 대시보드 → "전체 이력 보기" 버튼 → 처리 이력 페이지로 이동
        self._dashboard_view.view_history_requested.connect(
            lambda: self._navigate_to(2)
        )

        # 작업 완료 시 → 대시보드 / 이력 / 라이브러리 갱신
        self._job_view.job_completed.connect(self._on_job_completed)

    def _navigate_to(self, page_idx: int):
        self._stack.setCurrentIndex(page_idx)
        self._sidebar.set_active_page(page_idx)

        # 페이지 진입 시 데이터 자동 갱신
        if page_idx == 0:
            self._dashboard_view.refresh()
        elif page_idx == 2:
            self._history_view.refresh()
        elif page_idx == 3:
            self._library_view.refresh()

    def _on_job_completed(self):
        self._dashboard_view.refresh()
        self._history_view.refresh()
        self._library_view.refresh()

    def _on_db_reset(self):
        self._dashboard_view.refresh()
        self._history_view.refresh()
        self._library_view.refresh()
