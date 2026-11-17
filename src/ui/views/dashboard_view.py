"""
views/dashboard_view.py
────────────────────────────────────────────────────────────────
대시보드 뷰

표시 내용:
  - 통계 카드: 전체 사진 수 / 절약된 용량 / 마지막 작업 날짜
  - "새 Takeout 정리 시작" Primary 버튼
  - 최근 작업 목록 (DB에서 조회)

Signals:
  start_job_requested: "새 작업 시작" 버튼 클릭 시 방출
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy,
    QGridLayout,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from src.ui.theme import Colors, Fonts
from src.data.database import DatabaseManager


class StatCard(QFrame):
    """
    통계 카드 위젯.
    아이콘, 수치, 라벨로 구성된 단일 통계 카드.
    """

    def __init__(self, icon: str, label: str, value: str = "0", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(6)

        # 아이콘
        icon_label = QLabel(icon)
        icon_label.setObjectName("StatCardIcon")
        layout.addWidget(icon_label)

        # 수치
        self._value_label = QLabel(value)
        self._value_label.setObjectName("StatCardValue")
        font = QFont()
        font.setPointSize(Fonts.SIZE_TITLE + 2)
        font.setBold(True)
        self._value_label.setFont(font)
        layout.addWidget(self._value_label)

        # 라벨
        label_widget = QLabel(label)
        label_widget.setObjectName("StatCardLabel")
        layout.addWidget(label_widget)

    def set_value(self, value: str):
        """수치 텍스트 갱신."""
        self._value_label.setText(value)


class RecentJobRow(QFrame):
    """최근 작업 행 위젯."""

    def __init__(self, date_str: str, album: str, count: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)

        # 날짜
        date_label = QLabel(date_str)
        date_label.setFixedWidth(110)
        date_label.setObjectName("SubLabel")
        layout.addWidget(date_label)

        # 앨범/폴더명
        album_label = QLabel(album)
        album_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(album_label)

        # 처리 파일 수
        count_label = QLabel(f"{count:,}개")
        count_label.setObjectName("SubLabel")
        count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(count_label)


class DashboardView(QWidget):
    """
    대시보드 메인 뷰.
    
    Signals:
        start_job_requested: "새 작업 시작" 버튼 클릭 시 방출 (MainWindow에서 연결)
    """

    start_job_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardView")
        self._db = DatabaseManager()
        self._setup_ui()

    def _setup_ui(self):
        """대시보드 UI 초기화."""
        # 스크롤 가능한 메인 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("DashboardContent")
        scroll.setWidget(content)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 28, 32, 28)
        content_layout.setSpacing(24)

        # ── 환영 메시지 ───────────────────────────────────────
        welcome = QLabel("안녕하세요! 👋")
        welcome_font = QFont()
        welcome_font.setPointSize(Fonts.SIZE_TITLE)
        welcome_font.setBold(True)
        welcome.setFont(welcome_font)
        content_layout.addWidget(welcome)

        sub_welcome = QLabel("Google Takeout 사진 정리 도구입니다. 아래에서 현황을 확인하세요.")
        sub_welcome.setObjectName("SubLabel")
        content_layout.addWidget(sub_welcome)

        # ── 통계 카드 그리드 (3열) ────────────────────────────
        stats_grid = QGridLayout()
        stats_grid.setSpacing(16)

        self._card_total   = StatCard("🖼", "전체 미디어 파일", "0")
        self._card_saved   = StatCard("💾", "중복 제거로 절약", "0 B")
        self._card_last    = StatCard("📅", "마지막 작업",      "-")

        stats_grid.addWidget(self._card_total, 0, 0)
        stats_grid.addWidget(self._card_saved, 0, 1)
        stats_grid.addWidget(self._card_last,  0, 2)

        content_layout.addLayout(stats_grid)

        # ── 새 작업 시작 버튼 ─────────────────────────────────
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self._start_btn = QPushButton("  ➕  새 Takeout 정리 시작")
        self._start_btn.setObjectName("PrimaryButton")
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.setFixedHeight(48)
        self._start_btn.setMinimumWidth(240)
        self._start_btn.clicked.connect(self.start_job_requested.emit)

        btn_layout.addWidget(self._start_btn)
        btn_layout.addStretch()
        content_layout.addWidget(btn_container)

        # ── 최근 작업 섹션 ────────────────────────────────────
        section_title = QLabel("최근 작업")
        section_title.setObjectName("SectionTitle")
        section_font = QFont()
        section_font.setPointSize(Fonts.SIZE_H2)
        section_font.setBold(True)
        section_title.setFont(section_font)
        content_layout.addWidget(section_title)

        # 최근 작업 카드 컨테이너
        self._recent_card = QFrame()
        self._recent_card.setObjectName("Card")
        self._recent_layout = QVBoxLayout(self._recent_card)
        self._recent_layout.setContentsMargins(0, 8, 0, 8)
        self._recent_layout.setSpacing(0)

        self._no_history_label = QLabel("아직 처리된 작업이 없습니다.\n위 버튼을 눌러 첫 번째 Takeout 정리를 시작해보세요! 🚀")
        self._no_history_label.setObjectName("SubLabel")
        self._no_history_label.setAlignment(Qt.AlignCenter)
        self._no_history_label.setContentsMargins(0, 24, 0, 24)
        self._recent_layout.addWidget(self._no_history_label)

        content_layout.addWidget(self._recent_card)
        content_layout.addStretch()

        # 외부 레이아웃 (스크롤 영역 감싸기)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

    # ── 공개 메서드 ──────────────────────────────────────────

    def refresh(self):
        """DB에서 최신 통계/이력 데이터를 불러와 UI를 갱신한다."""
        self._db.initialize()
        self._update_stats()
        self._update_recent_jobs()

    # ── 내부 메서드 ──────────────────────────────────────────

    def _update_stats(self):
        """통계 카드 수치 갱신."""
        try:
            stats = self._db.get_statistics()
            total = stats.get("total_files", 0)
            self._card_total.set_value(f"{total:,}")

            # 절약 용량: 전체 용량 - (중복 제거 후 순수 용량)
            # 현재 DB에 직접 "절약 용량" 필드는 없으므로 total_size 표시
            total_size = stats.get("total_size_bytes", 0)
            self._card_saved.set_value(self._format_bytes(total_size))

            # 마지막 작업 날짜: created_at 기준 최신
            last_date = stats.get("last_updated")
            if last_date:
                self._card_last.set_value(str(last_date)[:10])
            else:
                self._card_last.set_value("-")

        except Exception:
            # DB 미초기화 등 예외 상황: 기본값 유지
            pass

    def _update_recent_jobs(self):
        """최근 작업 목록 갱신 (날짜 기준 그룹)."""
        try:
            # 기존 항목 제거 (no_history_label 포함)
            while self._recent_layout.count():
                item = self._recent_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            jobs = self._db.get_recent_jobs(limit=10)

            if not jobs:
                # 이력 없음
                self._no_history_label = QLabel(
                    "아직 처리된 작업이 없습니다.\n위 버튼을 눌러 첫 번째 Takeout 정리를 시작해보세요! 🚀"
                )
                self._no_history_label.setObjectName("SubLabel")
                self._no_history_label.setAlignment(Qt.AlignCenter)
                self._no_history_label.setContentsMargins(0, 24, 0, 24)
                self._recent_layout.addWidget(self._no_history_label)
                return

            # 헤더 행
            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(12, 4, 12, 4)
            header_layout.setSpacing(16)
            for text, width in [("날짜", 110), ("앨범/폴더", -1), ("처리 수", 60)]:
                lbl = QLabel(text)
                lbl.setObjectName("SubLabel")
                font = QFont()
                font.setBold(True)
                lbl.setFont(font)
                if width > 0:
                    lbl.setFixedWidth(width)
                else:
                    lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                if text == "처리 수":
                    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                header_layout.addWidget(lbl)
            self._recent_layout.addWidget(header)

            # 구분선
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setObjectName("SidebarDivider")
            self._recent_layout.addWidget(sep)

            # 작업 행
            for job in jobs:
                date_str = str(job.get("date", ""))[:10]
                album    = job.get("album", "(알 수 없음)")
                count    = job.get("count", 0)
                row = RecentJobRow(date_str, album, count)
                self._recent_layout.addWidget(row)

        except Exception:
            pass

    @staticmethod
    def _format_bytes(size: int) -> str:
        """바이트를 사람이 읽기 쉬운 단위로 변환."""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
