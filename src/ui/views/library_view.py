"""
views/library_view.py
────────────────────────────────────────────────────────────────
미디어 라이브러리 뷰

SQLite DB와 연동하여 정리된 미디어를 검색·필터링하는 탐색기 뷰.
더블클릭 또는 버튼으로 Finder(macOS) / 탐색기(Windows) 에서 파일 위치 열기.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QFont

from src.ui.theme import Colors, Fonts
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository


class LibraryView(QWidget):
    """
    미디어 라이브러리 뷰.
    
    SQLite DB에서 미디어 목록을 검색하고, 선택한 파일의
    위치를 Finder/Explorer로 바로 열 수 있다.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # DB 초기화 (싱글턴 패턴으로 연결)
        self._db   = DatabaseManager()
        self._repo: Optional[MediaRepository] = None
        self._setup_ui()

    def set_repository(self, repo: MediaRepository):
        """외부에서 레포지토리를 주입할 때 사용 (ProcessService 완료 후)."""
        self._repo = repo
        self.refresh()

    def refresh(self):
        """DB에서 최신 데이터를 불러와 화면을 갱신한다."""
        self._db.initialize()
        if self._repo is None:
            self._repo = MediaRepository(self._db.conn)
        self.refresh_data()

    # ── UI 초기화 ─────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 24, 32, 24)

        # ── 헤더 행 ───────────────────────────────────────────
        top_layout = QHBoxLayout()
        title_label = QLabel("미디어 라이브러리")
        title_font = QFont()
        title_font.setPointSize(Fonts.SIZE_H1)
        title_font.setBold(True)
        title_label.setFont(title_font)
        top_layout.addWidget(title_label)
        top_layout.addStretch()

        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setFixedWidth(110)
        refresh_btn.clicked.connect(self.refresh)
        top_layout.addWidget(refresh_btn)
        layout.addLayout(top_layout)

        # ── 검색 / 필터 바 ────────────────────────────────────
        filter_card = QFrame()
        filter_card.setObjectName("Card")
        filter_layout = QHBoxLayout(filter_card)
        filter_layout.setContentsMargins(16, 12, 16, 12)
        filter_layout.setSpacing(12)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("검색 (파일명, 인물명, 캡션, 앨범명)...")
        self.search_edit.textChanged.connect(self.refresh_data)
        filter_layout.addWidget(self.search_edit, stretch=3)

        self.type_combo = QComboBox()
        self.type_combo.addItem("전체 미디어", "")
        self.type_combo.addItem("📷 사진만",   "photo")
        self.type_combo.addItem("🎬 동영상만",  "video")
        self.type_combo.currentIndexChanged.connect(self.refresh_data)
        filter_layout.addWidget(self.type_combo, stretch=1)

        self.gps_combo = QComboBox()
        self.gps_combo.addItem("GPS 전체",      None)
        self.gps_combo.addItem("📍 GPS 있음만", True)
        self.gps_combo.addItem("GPS 없음만",    False)
        self.gps_combo.currentIndexChanged.connect(self.refresh_data)
        filter_layout.addWidget(self.gps_combo, stretch=1)

        layout.addWidget(filter_card)

        # ── 미디어 목록 테이블 ────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "파일명", "촬영 일시", "유형", "용량", "GPS 좌표", "인물", "원본 앨범",
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.table)

        # ── 하단 상태 + 액션 바 ───────────────────────────────
        bottom_layout = QHBoxLayout()
        self.count_label = QLabel("검색 결과: 0개 항목")
        self.count_label.setObjectName("SubLabel")
        bottom_layout.addWidget(self.count_label)
        bottom_layout.addStretch()

        open_btn = QPushButton("📂 선택 파일 위치 열기")
        open_btn.setObjectName("SecondaryButton")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setFixedWidth(180)
        open_btn.clicked.connect(self._open_selected_folder)
        bottom_layout.addWidget(open_btn)
        layout.addLayout(bottom_layout)

    # ── 데이터 갱신 ───────────────────────────────────────────

    def refresh_data(self):
        """검색/필터 조건으로 DB를 조회하여 테이블을 갱신한다."""
        if not self._repo:
            return

        kw         = self.search_edit.text().strip() or None
        media_type = self.type_combo.currentData() or None
        has_gps    = self.gps_combo.currentData()

        try:
            results = self._repo.search_media(
                keyword=kw, media_type=media_type, has_gps=has_gps, limit=200
            )
        except Exception:
            results = []

        self.table.setRowCount(len(results))

        for row_idx, item in enumerate(results):
            # 파일명 (UserRole에 전체 경로 저장)
            fname_item = QTableWidgetItem(item.get("file_name", ""))
            fname_item.setData(Qt.UserRole, item.get("file_path", ""))

            # 촬영 일시
            dt_str   = item.get("taken_at") or "-"
            dt_item  = QTableWidgetItem(dt_str)

            # 유형
            type_str  = "📷 사진" if item.get("media_type") == "photo" else "🎬 동영상"
            type_item = QTableWidgetItem(type_str)

            # 용량
            size_mb   = (item.get("file_size") or 0) / (1024 * 1024)
            size_item = QTableWidgetItem(f"{size_mb:.1f} MB")

            # GPS 좌표
            lat = item.get("latitude") or 0.0
            lon = item.get("longitude") or 0.0
            gps_str  = f"{lat:.4f}, {lon:.4f}" if (lat != 0.0 or lon != 0.0) else "-"
            gps_item = QTableWidgetItem(gps_str)

            # 인물
            people_raw = item.get("people") or "[]"
            try:
                people_list = json.loads(people_raw)
                people_str  = ", ".join(people_list) if people_list else "-"
            except Exception:
                people_str = "-"
            people_item = QTableWidgetItem(people_str)

            # 원본 앨범
            album_item = QTableWidgetItem(item.get("album_name") or "-")

            # 테이블에 삽입
            for col, cell in enumerate([
                fname_item, dt_item, type_item, size_item,
                gps_item, people_item, album_item,
            ]):
                self.table.setItem(row_idx, col, cell)

        self.count_label.setText(f"검색 결과: {len(results):,}개 파일")

    # ── 이벤트 핸들러 ─────────────────────────────────────────

    def _open_selected_folder(self):
        """선택된 파일을 Finder(macOS) 또는 탐색기(Windows)에서 연다."""
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        file_path = item.data(Qt.UserRole)
        if file_path and os.path.exists(file_path):
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", file_path])
            elif sys.platform == "win32":
                subprocess.run(["explorer", f"/select,{file_path}"])

    def _on_item_double_clicked(self, _item):
        """더블클릭 → 파일 위치 열기."""
        self._open_selected_folder()
