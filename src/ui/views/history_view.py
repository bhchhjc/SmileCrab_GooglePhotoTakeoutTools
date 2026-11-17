"""
views/history_view.py
────────────────────────────────────────────────────────────────
처리 이력 뷰

SQLite DB의 media_files 테이블에서 작업 이력을 조회하여
날짜별로 그룹화해서 테이블로 표시한다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QScrollArea, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from src.ui.theme import Colors, Fonts
from src.data.database import DatabaseManager


class HistoryView(QWidget):
    """
    처리 이력 뷰.
    
    DB에서 미디어 파일 목록을 날짜(created_at) 기준으로 그룹화하여
    처리 이력 테이블을 표시한다.
    """

    # 테이블 컬럼 정의
    COLUMNS = ["날짜", "앨범/입력 폴더", "처리 파일 수", "미디어 유형", "상태"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = DatabaseManager()
        self._setup_ui()

    def _setup_ui(self):
        """이력 뷰 UI 초기화."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        # ── 헤더 행 (타이틀 + 새로고침 버튼) ───────────────────
        header_row = QHBoxLayout()

        title = QLabel("처리 이력")
        title_font = QFont()
        title_font.setPointSize(Fonts.SIZE_H1)
        title_font.setBold(True)
        title.setFont(title_font)
        header_row.addWidget(title)

        header_row.addStretch()

        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setFixedWidth(110)
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn)

        layout.addLayout(header_row)

        # ── 요약 라벨 ─────────────────────────────────────────
        self._summary_label = QLabel("DB를 조회하는 중...")
        self._summary_label.setObjectName("SubLabel")
        layout.addWidget(self._summary_label)

        # ── 이력 테이블 ───────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)

        # 컬럼 너비 설정
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 120)
        self._table.setColumnWidth(2,  90)
        self._table.setColumnWidth(3, 100)
        self._table.setColumnWidth(4,  80)

        layout.addWidget(self._table, stretch=1)

    # ── 공개 메서드 ──────────────────────────────────────────

    def refresh(self):
        """DB에서 이력 데이터를 새로 불러와 테이블을 갱신한다."""
        self._db.initialize()
        self._load_history()

    # ── 내부 메서드 ──────────────────────────────────────────

    def _load_history(self):
        """DB 이력 조회 및 테이블 렌더링."""
        try:
            jobs = self._db.get_history_summary()
        except Exception as e:
            self._summary_label.setText(f"이력 조회 실패: {e}")
            return

        self._table.setRowCount(0)

        if not jobs:
            self._summary_label.setText("처리 이력이 없습니다. '새 작업' 메뉴에서 Takeout 정리를 시작해보세요.")
            return

        self._summary_label.setText(f"총 {len(jobs)}건의 처리 작업 이력이 있습니다.")

        for row_idx, job in enumerate(jobs):
            self._table.insertRow(row_idx)

            date_str    = str(job.get("date",   ""))[:10]
            album       = job.get("album_name", "(알 수 없음)")
            count       = job.get("count",       0)
            media_types = job.get("media_types", "")
            status      = job.get("status",      "완료")

            # 날짜
            self._set_cell(row_idx, 0, date_str, align=Qt.AlignCenter)

            # 앨범/폴더명
            self._set_cell(row_idx, 1, album)

            # 처리 파일 수
            self._set_cell(row_idx, 2, f"{count:,}개", align=Qt.AlignCenter)

            # 미디어 유형 요약
            self._set_cell(row_idx, 3, media_types, align=Qt.AlignCenter)

            # 상태 (뱃지 느낌으로 색상 적용)
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            if status == "완료":
                status_item.setForeground(QColor(Colors.SUCCESS))
            elif status == "오류":
                status_item.setForeground(QColor(Colors.ERROR))
            self._table.setItem(row_idx, 4, status_item)

    def _set_cell(self, row: int, col: int, text: str, align=Qt.AlignLeft | Qt.AlignVCenter):
        """테이블 셀 항목 생성 헬퍼."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(align)
        self._table.setItem(row, col, item)
