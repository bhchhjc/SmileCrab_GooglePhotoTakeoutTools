"""
views/settings_view.py
────────────────────────────────────────────────────────────────
설정 뷰

사용자 설정을 관리한다:
  - 기본 처리 모드 (복사 / 이동)
  - 기본 폴더 구조 전략
  - 앱 버전 정보

설정 값은 현재 메모리 내 상태로 관리 (추후 JSON 파일 영속화 확장 가능).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QRadioButton, QButtonGroup, QPushButton,
    QFrame, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.ui.theme import Colors, Fonts

# 앱 버전 (추후 별도 version.py로 분리 가능)
APP_VERSION = "0.3.0-alpha"


class SettingRow(QWidget):
    """
    단일 설정 항목 행.
    좌측: 라벨 + 설명, 우측: 컨트롤 위젯
    """

    def __init__(self, label: str, description: str, control: QWidget, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(16)

        # 좌측: 라벨 + 설명
        left = QVBoxLayout()
        left.setSpacing(2)

        label_widget = QLabel(label)
        label_font = QFont()
        label_font.setBold(True)
        label_widget.setFont(label_font)
        left.addWidget(label_widget)

        desc_widget = QLabel(description)
        desc_widget.setObjectName("SubLabel")
        desc_widget.setWordWrap(True)
        left.addWidget(desc_widget)

        left_container = QWidget()
        left_container.setLayout(left)
        left_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout.addWidget(left_container, stretch=1)
        layout.addWidget(control)


class SettingsView(QWidget):
    """설정 메인 뷰."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # 스크롤 가능한 메인 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(24)

        # ── 페이지 타이틀 ─────────────────────────────────────
        title = QLabel("설정")
        title_font = QFont()
        title_font.setPointSize(Fonts.SIZE_H1)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # ── 처리 기본값 카드 ──────────────────────────────────
        processing_card = self._build_section_card(
            "⚙  처리 기본값",
            [
                self._build_folder_strategy_row(),
                self._build_process_mode_row(),
            ]
        )
        layout.addWidget(processing_card)

        # ── 앱 정보 카드 ──────────────────────────────────────
        about_card = self._build_about_card()
        layout.addWidget(about_card)

        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)

    # ── 카드 빌더 ────────────────────────────────────────────

    def _build_section_card(self, title: str, rows: list[QWidget]) -> QFrame:
        """섹션 카드 (제목 + 행 목록)."""
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(0)

        # 카드 제목
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(Fonts.SIZE_H2)
        title_font.setBold(True)
        title_label.setFont(title_font)
        card_layout.addWidget(title_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("SidebarDivider")
        sep.setContentsMargins(0, 8, 0, 0)
        card_layout.addWidget(sep)

        for i, row in enumerate(rows):
            card_layout.addWidget(row)
            if i < len(rows) - 1:
                # 항목 간 구분선
                item_sep = QFrame()
                item_sep.setFrameShape(QFrame.HLine)
                item_sep.setObjectName("SidebarDivider")
                card_layout.addWidget(item_sep)

        return card

    def _build_folder_strategy_row(self) -> SettingRow:
        """폴더 구조 전략 설정 행."""
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems([
            "YYYY/MM  (연도/월)",
            "YYYY     (연도만)",
            "앨범명    (원본 구조 유지)",
        ])
        self._strategy_combo.setFixedWidth(200)
        return SettingRow(
            "기본 폴더 구조",
            "정리된 사진을 어떤 폴더 구조로 저장할지 기본값을 설정합니다.\n새 작업 시 이 값이 기본으로 선택됩니다.",
            self._strategy_combo,
        )

    def _build_process_mode_row(self) -> SettingRow:
        """처리 모드 설정 행."""
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(16)

        self._mode_group = QButtonGroup(self)
        self._radio_copy = QRadioButton("복사 (원본 보존)")
        self._radio_move = QRadioButton("이동 (원본 삭제)")
        self._radio_copy.setChecked(True)
        self._mode_group.addButton(self._radio_copy, 0)
        self._mode_group.addButton(self._radio_move, 1)

        mode_layout.addWidget(self._radio_copy)
        mode_layout.addWidget(self._radio_move)

        return SettingRow(
            "기본 처리 방식",
            "파일을 복사할지 이동할지 기본값을 설정합니다.\n이동 모드는 원본 Takeout 폴더에서 파일이 삭제됩니다.",
            mode_widget,
        )

    def _build_about_card(self) -> QFrame:
        """앱 정보 카드."""
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(8)

        # 카드 제목
        title_label = QLabel("ℹ  앱 정보")
        title_font = QFont()
        title_font.setPointSize(Fonts.SIZE_H2)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("SidebarDivider")
        layout.addWidget(sep)

        # 버전
        layout.addSpacing(4)
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("버전"))
        ver_val = QLabel(APP_VERSION)
        ver_val.setObjectName("SubLabel")
        ver_row.addWidget(ver_val)
        ver_row.addStretch()
        layout.addLayout(ver_row)

        # 기술 스택
        tech_row = QHBoxLayout()
        tech_row.addWidget(QLabel("기술 스택"))
        tech_val = QLabel("Python 3.9  •  PySide6  •  SQLite  •  piexif  •  Pillow")
        tech_val.setObjectName("SubLabel")
        tech_val.setWordWrap(True)
        tech_row.addWidget(tech_val, stretch=1)
        layout.addLayout(tech_row)

        # GitHub 링크 (텍스트만 표시)
        repo_row = QHBoxLayout()
        repo_row.addWidget(QLabel("리포지토리"))
        repo_val = QLabel("GooglePhotoTakeoutTools")
        repo_val.setObjectName("SubLabel")
        repo_row.addWidget(repo_val)
        repo_row.addStretch()
        layout.addLayout(repo_row)

        return card
