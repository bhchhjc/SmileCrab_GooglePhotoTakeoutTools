"""
GooglePhotoTakeoutTools - Main Application Entry Point
GUI 애플리케이션 초기화 및 실행 진입점
"""

import os
import signal
import sys
from pathlib import Path

# 사용자가 어떤 경로에서 실행하더라도 프로젝트 루트를 sys.path에 자동 등록
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Windows 환경: 작업 표시줄(Taskbar)에서 파이썬 기본 아이콘 대신 전용 앱 아이콘으로 분리 표시되도록 설정
if sys.platform.startswith("win"):
    import ctypes
    try:
        app_user_model_id = "littleplanet.googlephototakeouttools.smilecrab.v1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_user_model_id)
    except Exception:
        pass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.theme import MAIN_STYLESHEET


def main() -> int:
    # 터미널 Ctrl+C (SIGINT) 입력 시 UI 종료 확인 다이얼로그 없이 그 즉시 강제 종료
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # High DPI 디스플레이(레티나, 4K 등) 대응
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("GooglePhotoTakeoutTools")
    app.setOrganizationName("LittlePlanet")

    # 앱 아이콘 설정 (Windows 작업표시줄, macOS Dock, Linux 창 아이콘)
    icon_candidates = [
        PROJECT_ROOT / "assets" / "icons" / "app_icon.png",
        PROJECT_ROOT / "assets" / "icons" / "app_icon.ico",
        PROJECT_ROOT / "assets" / "icons" / "app_icon.icns",
    ]
    for icon_path in icon_candidates:
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    # 라이트 모드 테마 적용
    app.setStyleSheet(MAIN_STYLESHEET)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
