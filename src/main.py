"""
GooglePhotoTakeoutTools - Main Application Entry Point
GUI 애플리케이션 초기화 및 실행 진입점
"""

import sys
from pathlib import Path

# 사용자가 어떤 경로에서 실행하더라도 프로젝트 루트를 sys.path에 자동 등록
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.theme import MAIN_STYLESHEET


def main() -> int:
    # High DPI 디스플레이(레티나, 4K 등) 대응
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("GooglePhotoTakeoutTools")
    app.setOrganizationName("LittlePlanet")

    # 라이트 모드 테마 적용
    app.setStyleSheet(MAIN_STYLESHEET)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
