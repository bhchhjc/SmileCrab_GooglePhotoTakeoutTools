"""
views/library_view.py
────────────────────────────────────────────────────────────────
미디어 라이브러리 뷰 (선명한 폴더 배경 + 컴팩트 툴바 + 가로 대조표)

핵심 기능:
  - 부모 그룹 노드 선명한 소프트 블루 배경(#E8F0FE)과 볼드 블루(#174EA6) 적용으로 시각적 구분 극대화
  - 그룹명 'YYYY년 MM월' 직관적 표기 및 전체 디렉토리 경로 연동
  - 검색 툴바 높이(28px) 및 여백(4px) 초슬림화
  - 마우스 드래그 컬럼 리사이즈 (Interactive) 지원
  - 11개 항목 가로 정밀 대조표 인스펙터 연동
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QUrl, QPoint, QMimeData, QTimer, QThreadPool, QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QFrame, QSplitter, QMessageBox, QMenu, QApplication,
    QStackedWidget, QGridLayout, QDialog,
)
from PySide6.QtGui import QFont, QColor, QBrush, QDesktopServices, QPainter, QPen

from src.ui.theme import Colors, Fonts
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.ui.components.compare_panel import ComparePanel
from src.ui.components.progress_circle import ProgressCircle
from src.ui.components.reorganize_dialog import ReorganizeDialog
from src.ui.components.batch_rename_dialog import BatchRenameDialog
from src.ui.components.geo_relabel_dialog import GeoRelabelDialog
from src.ui.components.treemap_dialog import TreemapDialog
from src.ui.workers import LibraryLoaderWorker, group_media_items, GroupReorderWorker
from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.i18n import i18n, t

logger = logging.getLogger(__name__)


class LibraryView(QWidget):
    """
    미디어 라이브러리 메인 뷰 (비동기 로딩 + 원형 프로그레스 인디케이터 + 초고속 지연 로딩)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._db = DatabaseManager()
        self._repo: Optional[MediaRepository] = None
        self._current_worker: Optional[LibraryLoaderWorker] = None
        self._cached_valid_results: Optional[List[Dict[str, Any]]] = None
        self._all_expanded = False
        self._show_3tier = True  # 기본값: 3단계 위치 표기 (국가 > 주/도 > 시/군/구)

        # 검색창 디바운스 타이머 (250ms)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_data)

        self._setup_ui()
        self.retranslate_ui()
        i18n.language_changed.connect(lambda _: self.retranslate_ui())

    def refresh(self):
        """DB 최신화 및 루트 폴더 목록, 미디어 목록 갱신"""
        self._db.initialize()
        if self._repo is None:
            self._repo = MediaRepository(self._db)

        self._update_root_paths()
        self.refresh_data()

    def _open_reorganize_dialog(self):
        """미디어 폴더 구조 재구성 마법사 다이얼로그를 엽니다."""
        selected_root = self._root_combo.currentData()
        base_dir = Path(selected_root) if selected_root else None

        dialog = ReorganizeDialog(current_base_dir=base_dir, db_manager=self._db, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _open_batch_rename_dialog(self):
        """메타데이터 기반 파일명 일괄 변경 마법사 다이얼로그를 엽니다."""
        selected_root = self._root_combo.currentData()
        base_dir = Path(selected_root) if selected_root else None

        dialog = BatchRenameDialog(
            current_base_dir=base_dir,
            db_manager=self._db,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _open_geo_relabel_dialog(self):
        """미디어 역지오코딩 지역명 언어 일괄 변경 마법사 다이얼로그를 엽니다."""
        selected_root = self._root_combo.currentData()
        base_dir = Path(selected_root) if selected_root else None

        dialog = GeoRelabelDialog(
            current_base_dir=base_dir,
            db_manager=self._db,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _open_treemap_dialog(self):
        """미디어 용량 시각화 트리맵 다이얼로그를 엽니다 (모달)."""
        selected_root = self._root_combo.currentData() or ""
        dialog = TreemapDialog(
            db_manager=self._db,
            repo=self._repo,
            initial_root=selected_root,
            parent=self.window(),
        )
        dialog.exec()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(6)

        # ── 상단 일체형 타이틀 헤더 ──────────────────────────
        top_bar = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {Colors.TEXT_PRIMARY};")
        top_bar.addWidget(self._title_lbl)
        top_bar.addStretch()

        main_layout.addLayout(top_bar)

        # ── 2단 복합 필터 및 정렬 바 ─────────────────────────
        filter_card = QFrame()
        filter_card.setObjectName("Card")
        filter_card.setStyleSheet("""
            QFrame#Card {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
                padding: 4px;
            }
        """)
        filter_main_layout = QVBoxLayout(filter_card)
        filter_main_layout.setContentsMargins(12, 10, 12, 10)
        filter_main_layout.setSpacing(10)

        _lbl_style = "font-size: 11px; font-weight: bold; color: #495057; border: none; background: transparent;"

        # [1단] 분류 및 정렬 체계 행
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        # 1-1. 저장 위치
        col_root = QVBoxLayout()
        col_root.setSpacing(3)
        self._lbl_root = QLabel()
        self._lbl_root.setStyleSheet(_lbl_style)
        self._root_combo = QComboBox()
        self._root_combo.setFixedHeight(28)
        self._root_combo.currentIndexChanged.connect(self.refresh_data)
        col_root.addWidget(self._lbl_root)
        col_root.addWidget(self._root_combo)
        row1.addLayout(col_root, stretch=3)

        # 1-2. 그룹 분류 기준
        col_group = QVBoxLayout()
        col_group.setSpacing(3)
        self._lbl_group = QLabel()
        self._lbl_group.setStyleSheet(_lbl_style)
        self._group_combo = QComboBox()
        self._group_combo.setFixedHeight(28)
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        col_group.addWidget(self._lbl_group)
        col_group.addWidget(self._group_combo)
        row1.addLayout(col_group, stretch=2)

        # 1-3. 그룹 정렬 순서
        col_sort = QVBoxLayout()
        col_sort.setSpacing(3)
        self._lbl_sort = QLabel()
        self._lbl_sort.setStyleSheet(_lbl_style)
        self._group_sort_combo = QComboBox()
        self._group_sort_combo.setFixedHeight(28)
        self._group_sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        col_sort.addWidget(self._lbl_sort)
        col_sort.addWidget(self._group_sort_combo)
        row1.addLayout(col_sort, stretch=2)

        filter_main_layout.addLayout(row1)

        # 중간 구분선
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.HLine)
        sep_line.setStyleSheet("background-color: #F1F3F6; max-height: 1px; border: none;")
        filter_main_layout.addWidget(sep_line)

        # [2단] 필터 및 정밀 검색 행
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        # 2-1. 미디어 유형
        col_type = QVBoxLayout()
        col_type.setSpacing(3)
        self._lbl_type = QLabel()
        self._lbl_type.setStyleSheet(_lbl_style)
        self._type_combo = QComboBox()
        self._type_combo.setFixedHeight(28)
        self._type_combo.currentIndexChanged.connect(self.refresh_data)
        col_type.addWidget(self._lbl_type)
        col_type.addWidget(self._type_combo)
        row2.addLayout(col_type, stretch=2)

        # 2-2. 키워드 검색창
        col_search = QVBoxLayout()
        col_search.setSpacing(3)
        self._lbl_search = QLabel()
        self._lbl_search.setStyleSheet(_lbl_style)
        self._search_edit = QLineEdit()
        self._search_edit.setFixedHeight(28)
        self._search_edit.textChanged.connect(self._search_timer.start)
        col_search.addWidget(self._lbl_search)
        col_search.addWidget(self._search_edit)
        row2.addLayout(col_search, stretch=5)

        # 2-3. 리스트 보기 제어 버튼 그룹 (상세 검색 우측 배치)
        col_actions = QVBoxLayout()
        col_actions.setSpacing(3)
        self._lbl_actions = QLabel()
        self._lbl_actions.setStyleSheet(_lbl_style)
        col_actions.addWidget(self._lbl_actions)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(6)

        self._expand_all_btn = QPushButton()
        self._expand_all_btn.setObjectName("SecondaryButton")
        self._expand_all_btn.setCursor(Qt.PointingHandCursor)
        self._expand_all_btn.setFixedHeight(28)
        self._expand_all_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self._expand_all_btn.clicked.connect(self._toggle_expand_all)
        btn_box.addWidget(self._expand_all_btn)

        self._toggle_panel_btn = QPushButton()
        self._toggle_panel_btn.setObjectName("SecondaryButton")
        self._toggle_panel_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_panel_btn.setFixedHeight(28)
        self._toggle_panel_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self._toggle_panel_btn.clicked.connect(self._toggle_compare_panel)
        btn_box.addWidget(self._toggle_panel_btn)

        self._location_tier_btn = QPushButton()
        self._location_tier_btn.setObjectName("SecondaryButton")
        self._location_tier_btn.setCursor(Qt.PointingHandCursor)
        self._location_tier_btn.setFixedHeight(28)
        self._location_tier_btn.clicked.connect(self._toggle_location_tier_option)
        self._update_location_tier_btn_style()
        btn_box.addWidget(self._location_tier_btn)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self._refresh_btn.clicked.connect(self.refresh)
        btn_box.addWidget(self._refresh_btn)

        self._treemap_btn = QPushButton()
        self._treemap_btn.setObjectName("SecondaryButton")
        self._treemap_btn.setCursor(Qt.PointingHandCursor)
        self._treemap_btn.setFixedHeight(28)
        self._treemap_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self._treemap_btn.clicked.connect(self._open_treemap_dialog)
        btn_box.addWidget(self._treemap_btn)

        col_actions.addLayout(btn_box)
        row2.addLayout(col_actions)

        filter_main_layout.addLayout(row2)

        main_layout.addWidget(filter_card)

        # ── 메인 스플리터 (트리 뷰 + 우측 비교 대조표 패널) ──
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        # 1. 멀티 컬럼 계층 트리 위젯 (마우스 수동 너비 조절 Interactive + 우클릭 메뉴)
        self._tree = QTreeWidget()
        self._tree.setAlternatingRowColors(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)

        header = self._tree.header()
        for i in range(6):
            header.setSectionResizeMode(i, QHeaderView.Interactive)

        self._tree.setColumnWidth(0, 260)
        self._tree.setColumnWidth(1, 135)
        self._tree.setColumnWidth(2, 120)
        self._tree.setColumnWidth(3, 55)
        self._tree.setColumnWidth(4, 70)
        self._tree.setColumnWidth(5, 230)

        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)

        # 2. 로딩 상태 위젯 (Samsung One UI 원형 프로그레스 인디케이터)
        self._loading_widget = QWidget()
        loading_layout = QVBoxLayout(self._loading_widget)
        loading_layout.setAlignment(Qt.AlignCenter)
        loading_layout.setSpacing(14)

        self._progress_circle = ProgressCircle(size=44, color=Colors.ACCENT)
        loading_layout.addWidget(self._progress_circle, alignment=Qt.AlignCenter)

        self._loading_title = QLabel()
        self._loading_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {Colors.TEXT_PRIMARY};")
        loading_layout.addWidget(self._loading_title, alignment=Qt.AlignCenter)

        self._loading_sub = QLabel()
        self._loading_sub.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        loading_layout.addWidget(self._loading_sub, alignment=Qt.AlignCenter)

        # 3. 트리와 로딩 화면을 전환하는 스택 위젯
        self._tree_stack = QStackedWidget()
        self._tree_stack.addWidget(self._tree)           # Index 0: 트리 목록
        self._tree_stack.addWidget(self._loading_widget) # Index 1: 원형 로딩 스피너
        self._splitter.addWidget(self._tree_stack)

        # 4. 우측 Before / After 가로 대조표 패널
        self._compare_panel = ComparePanel()
        self._compare_panel.close_requested.connect(self._close_compare_panel)
        self._compare_panel.location_tier_changed.connect(self._on_panel_location_tier_changed)
        self._compare_panel.setVisible(False)
        self._splitter.addWidget(self._compare_panel)

        self._splitter.setSizes([580, 520])
        main_layout.addWidget(self._splitter, stretch=1)

        # ── 하단 상태 바 ─────────────────────────────────────
        bottom_bar = QHBoxLayout()
        self._count_label = QLabel()
        self._count_label.setObjectName("SubLabel")
        bottom_bar.addWidget(self._count_label)
        bottom_bar.addStretch()

        self._reorganize_btn = QPushButton()
        self._reorganize_btn.setObjectName("SecondaryButton")
        self._reorganize_btn.setCursor(Qt.PointingHandCursor)
        self._reorganize_btn.setFixedHeight(28)
        self._reorganize_btn.setStyleSheet(f"""
            QPushButton#SecondaryButton {{
                font-size: 11px;
                font-weight: bold;
                padding: 2px 12px;
                color: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT};
                background-color: {Colors.ACCENT_LIGHT};
                border-radius: 10px;
            }}
            QPushButton#SecondaryButton:hover {{
                background-color: #D0EBFF;
            }}
        """)
        self._reorganize_btn.clicked.connect(self._open_reorganize_dialog)
        bottom_bar.addWidget(self._reorganize_btn)

        self._rename_btn = QPushButton()
        self._rename_btn.setObjectName("SecondaryButton")
        self._rename_btn.setCursor(Qt.PointingHandCursor)
        self._rename_btn.setFixedHeight(28)
        self._rename_btn.setStyleSheet(f"""
            QPushButton#SecondaryButton {{
                font-size: 11px;
                font-weight: bold;
                padding: 2px 12px;
                color: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT};
                background-color: {Colors.ACCENT_LIGHT};
                border-radius: 10px;
            }}
            QPushButton#SecondaryButton:hover {{
                background-color: #D0EBFF;
            }}
        """)
        self._rename_btn.clicked.connect(self._open_batch_rename_dialog)
        bottom_bar.addWidget(self._rename_btn)

        self._relabel_geo_btn = QPushButton()
        self._relabel_geo_btn.setObjectName("SecondaryButton")
        self._relabel_geo_btn.setCursor(Qt.PointingHandCursor)
        self._relabel_geo_btn.setFixedHeight(28)
        self._relabel_geo_btn.setStyleSheet(f"""
            QPushButton#SecondaryButton {{
                font-size: 11px;
                font-weight: bold;
                padding: 2px 12px;
                color: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT};
                background-color: {Colors.ACCENT_LIGHT};
                border-radius: 10px;
            }}
            QPushButton#SecondaryButton:hover {{
                background-color: #D0EBFF;
            }}
        """)
        self._relabel_geo_btn.clicked.connect(self._open_geo_relabel_dialog)
        bottom_bar.addWidget(self._relabel_geo_btn)

        self._sync_btn = QPushButton()
        self._sync_btn.setObjectName("SecondaryButton")
        self._sync_btn.setCursor(Qt.PointingHandCursor)
        self._sync_btn.setFixedHeight(28)
        self._sync_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self._sync_btn.clicked.connect(self._sync_missing_files)
        bottom_bar.addWidget(self._sync_btn)

        self._open_folder_btn = QPushButton()
        self._open_folder_btn.setObjectName("SecondaryButton")
        self._open_folder_btn.setCursor(Qt.PointingHandCursor)
        self._open_folder_btn.setFixedHeight(28)
        self._open_folder_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self._open_folder_btn.clicked.connect(self._open_selected_file_folder)
        bottom_bar.addWidget(self._open_folder_btn)

        main_layout.addLayout(bottom_bar)

    def retranslate_ui(self):
        """다국어 변경 시 라이브러리 모든 UI 텍스트 실시간 재설정"""
        self._title_lbl.setText(f"🖼 {t('library.title', '미디어 라이브러리')}")
        self._lbl_root.setText(f"📂 {t('library.label_root', '저장 위치')}")
        self._lbl_group.setText(f"📑 {t('library.label_group', '그룹 분류')}")
        self._lbl_sort.setText(f"↕️ {t('library.label_sort', '그룹 정렬')}")
        self._lbl_type.setText(f"🎬 {t('library.label_type', '미디어 유형')}")
        self._lbl_search.setText(f"🔍 {t('library.label_search', '상세 검색')}")
        self._search_edit.setPlaceholderText(t("library.search_placeholder", "파일명, 촬영 국가/도시, 인물, 캡션 검색..."))
        self._lbl_actions.setText(f"📋 {t('library.label_actions', '목록 제어')}")

        # 그룹 분류 콤보박스 텍스트 갱신 (선택 상태 유지)
        cur_group = self._group_combo.currentData() or "date"
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem(f"📅 {t('library.group_date', '연도/월별 그룹')}", "date")
        self._group_combo.addItem(f"🗓 {t('library.group_day', '촬영 일자별 그룹 (일 단위)')}", "day")
        self._group_combo.addItem(f"🌍 {t('library.group_loc_3tier', '위치: 국가 > 시·도 > 시·군·구 (3단계)')}", "location_3tier")
        self._group_combo.addItem(f"🌍 {t('library.group_loc_country_state', '위치: 국가 > 시·도 (2단계 광역)')}", "location_country_state")
        self._group_combo.addItem(f"🌍 {t('library.group_loc_country_city', '위치: 국가 > 시·군·구 (2단계 도시)')}", "location_country_city")
        self._group_combo.addItem(f"🌍 {t('library.group_loc_country', '위치: 국가별 단독 (1단계)')}", "location_country")
        self._group_combo.addItem(f"📷 {t('library.group_camera', '촬영 기기별 그룹 (제조사/모델)')}", "camera")
        self._group_combo.addItem(f"📁 {t('library.group_folder', '출력 폴더별 그룹')}", "folder")
        self._group_combo.addItem(f"🏷 {t('library.group_album', '원본 앨범별 그룹')}", "album")
        g_idx = self._group_combo.findData(cur_group)
        if g_idx >= 0:
            self._group_combo.setCurrentIndex(g_idx)
        self._group_combo.blockSignals(False)

        # 정렬 순서 콤보박스 텍스트 갱신
        cur_sort = self._group_sort_combo.currentData() or "name"
        self._group_sort_combo.blockSignals(True)
        self._group_sort_combo.clear()
        self._group_sort_combo.addItem(t("library.sort_name", "가나다 / 최신순 (기본)"), "name")
        self._group_sort_combo.addItem(t("library.sort_count", "사진 많은 순 (건수순)"), "count")
        s_idx = self._group_sort_combo.findData(cur_sort)
        if s_idx >= 0:
            self._group_sort_combo.setCurrentIndex(s_idx)
        self._group_sort_combo.blockSignals(False)

        # 미디어 유형 콤보박스 텍스트 갱신
        cur_type = self._type_combo.currentData() or ""
        self._type_combo.blockSignals(True)
        self._type_combo.clear()
        self._type_combo.addItem(t("library.filter_all", "전체 유형"), "")
        self._type_combo.addItem(f"📷 {t('library.filter_photo', '사진')}", "photo")
        self._type_combo.addItem(f"🎬 {t('library.filter_video', '동영상')}", "video")
        t_idx = self._type_combo.findData(cur_type)
        if t_idx >= 0:
            self._type_combo.setCurrentIndex(t_idx)
        self._type_combo.blockSignals(False)

        # 버튼들
        self._expand_all_btn.setText(
            f"📁 {t('library.btn_collapse_all', '전체 접기')}" if self._all_expanded
            else f"📂 {t('library.btn_expand_all', '전체 펼치기')}"
        )
        self._toggle_panel_btn.setText(f"📋 {t('library.btn_detail_panel', '상세 정보')}")
        self._refresh_btn.setText(f"🔄 {t('common.refresh', '새로고침')}")
        self._treemap_btn.setText(t("library.btn_treemap", "📊 용량 시각화 (트리맵)"))

        self._update_location_tier_btn_style()

        # 트리 헤더
        self._tree.setHeaderLabels([
            t("library.col_filename_path", "파일명 / 디렉토리 경로"),
            t("library.col_taken_at", "촬영 일시"),
            t("library.col_camera", "촬영 기기"),
            t("library.col_type", "유형"),
            t("library.col_size", "용량"),
            t("library.col_location", "GPS 및 촬영 위치"),
        ])
        for i in range(6):
            self._tree.headerItem().setTextAlignment(i, Qt.AlignCenter)

        # 로딩 라벨
        self._loading_title.setText(t("library.loading_title", "미디어 라이브러리를 불러오는 중입니다..."))
        self._loading_sub.setText(t("library.loading_sub", "대용량 파일 데이터와 디스크 무결성을 안전하게 검증하고 있습니다."))

        # 하단 액션 버튼
        self._reorganize_btn.setText(t("library.btn_reorganize", "📁 폴더 구조 재구성"))
        self._rename_btn.setText(t("library.btn_rename", "🏷️ 파일명 일괄 변경"))
        self._relabel_geo_btn.setText(t("library.btn_relabel_geo", "🌐 지역명 언어 변경"))
        self._sync_btn.setText(t("library.btn_sync", "🧹 DB 동기화 (누락 파일 정리)"))
        self._sync_btn.setToolTip(t("library.tip_sync", "디스크에서 삭제되거나 누락된 파일의 DB 레코드를 정리하여 실제 상태와 동기화합니다."))
        self._open_folder_btn.setText(f"📂 {t('library.btn_open_folder', '선택 파일 위치 열기')}")

        self._update_root_paths()

    def _update_root_paths(self):
        if not self._repo:
            return
        roots = self._repo.get_output_roots()
        cur_data = self._root_combo.currentData()

        self._root_combo.blockSignals(True)
        self._root_combo.clear()
        self._root_combo.addItem(f"📂 {t('library.root_all', '저장 위치: 전체')}", "")
        for r in roots:
            short_name = Path(r).name or r
            self._root_combo.addItem(f"📁 {short_name} ({r})", r)

        idx = self._root_combo.findData(cur_data)
        if idx >= 0:
            self._root_combo.setCurrentIndex(idx)
        self._root_combo.blockSignals(False)

    def _on_group_changed(self):
        """그룹 분류 기준 변경 시: 백그라운드 스레드에서 비동기 재그룹핑"""
        if self._cached_valid_results is not None:
            self._render_groups_from_cache()
        else:
            self.refresh_data()

    def _on_sort_changed(self):
        """그룹 정렬 기준(가나다순 vs 건수순) 변경 시: 백그라운드 스레드에서 비동기 재정렬"""
        if self._cached_valid_results is not None:
            self._render_groups_from_cache()
        else:
            self.refresh_data()

    def _render_groups_from_cache(self):
        """메모리에 캐시된 미디어 데이터를 백그라운드 스레드에서 비동기 재그룹핑 (UI 프리징 100% 방지)"""
        if self._cached_valid_results is None:
            return

        self._progress_circle.start()
        self._tree_stack.setCurrentIndex(1)
        self._count_label.setText(t("library.reorganizing_groups", "⏳ 그룹 및 정렬 기준을 재구성하는 중..."))

        group_by = self._group_combo.currentData() or "date"
        sort_by = self._group_sort_combo.currentData() or "name"

        reorder_worker = GroupReorderWorker(self._cached_valid_results, group_by, sort_by)
        reorder_worker.signals.finished.connect(self._on_reorder_finished)
        QThreadPool.globalInstance().start(reorder_worker)

    def _on_reorder_finished(self, sorted_groups: list, total_files: int):
        self._build_tree_nodes(sorted_groups, total_files)

    def refresh_data(self):
        if not self._repo:
            return

        # 이전 실행 중인 비동기 워커가 있으면 취소
        if self._current_worker:
            self._current_worker.cancel()
            self._current_worker = None

        self._cached_valid_results = None

        kw         = self._search_edit.text().strip() or None
        media_type = self._type_combo.currentData() or None
        has_gps    = None
        root_path  = self._root_combo.currentData() or None
        group_by   = self._group_combo.currentData() or "date"
        sort_by    = self._group_sort_combo.currentData() or "name"

        # UI 즉시 반응 (0ms 프리징 없이 로딩 상태 진입 및 인디케이터 부드러운 회전 보장)
        self._progress_circle.start()
        self._tree_stack.setCurrentIndex(1)
        self._count_label.setText(t("library.loading_data", "⏳ 미디어 라이브러리 데이터를 안전하게 불러오는 중..."))

        worker = LibraryLoaderWorker(
            keyword=kw,
            media_type=media_type,
            has_gps=has_gps,
            root_path=root_path,
            group_by=group_by,
            sort_by=sort_by,
        )
        self._current_worker = worker

        # 람다 클로저를 통해 인스턴스 비교를 안전하게 바인딩
        worker.signals.finished.connect(lambda groups, valid_items, count, w=worker: self._on_load_finished(w, groups, valid_items, count))
        worker.signals.error.connect(lambda err, w=worker: self._on_load_error(w, err))

        QThreadPool.globalInstance().start(worker)

    def _on_load_finished(self, worker: LibraryLoaderWorker, sorted_groups: list, valid_results: list, total_files: int):
        if worker != self._current_worker:
            return
        self._current_worker = None
        self._cached_valid_results = valid_results
        self._build_tree_nodes(sorted_groups, total_files)

    def _build_tree_nodes(self, sorted_groups: list, total_files: int):
        """
        초고속 지연 로딩 (Lazy Loading):
        - 부모 그룹 노드(10~20개)만 0.001초 만에 즉시 생성하여 UI 프리징을 100% 방지합니다.
        - 첫 번째 최신 그룹만 자식을 즉시 생성하여 펼치고, 나머지 그룹은 사용자가 화살표를 누를 때 즉시 자식을 채웁니다.
        """
        self._tree.setUpdatesEnabled(False)
        self._tree.clear()

        group_by = self._group_combo.currentData()
        items_unit = t("common.items", "개")

        for idx, (grp_name, gdata) in enumerate(sorted_groups):
            items = gdata["items"]
            dir_p = gdata["dir_path"]

            # 1. 부모 그룹 노드:
            # '출력 폴더별'일 때만 해당 폴더의 실제 경로(— dir_p)를 표시하고,
            # 기기별/일자별/앨범별 등 여러 폴더에 분산된 그룹은 특정 경로를 붙이지 않음
            if group_by == "folder":
                label_text = f"{grp_name} ({len(items):,}{items_unit})   —   {dir_p}"
                node_dir = dir_p
            else:
                label_text = f"{grp_name} ({len(items):,}{items_unit})"
                node_dir = ""

            parent_node = QTreeWidgetItem(self._tree)
            parent_node.setText(0, label_text)
            parent_node.setData(0, Qt.UserRole + 1, node_dir)
            parent_node.setData(0, Qt.UserRole + 2, items)  # 데이터 리스트 보관
            parent_node.setData(0, Qt.UserRole + 3, False)  # is_loaded = False
            font = QFont()
            font.setBold(True)
            parent_node.setFont(0, font)

            # 부모 행 전체 너비 스팬 (경로 잘림 100% 방지)
            parent_node.setFirstColumnSpanned(True)

            # 선명한 소프트 블루 배경(#E8F0FE)과 딥블루 폰트(#174EA6)로 확실한 구분
            group_bg = QBrush(QColor("#E8F0FE"))
            parent_node.setBackground(0, group_bg)
            parent_node.setForeground(0, QColor("#174EA6"))

            # 지연 로딩용 더미 자식 (화살표 표시 보장)
            dummy = QTreeWidgetItem(parent_node)
            dummy.setText(0, f"  {t('common.loading', '불러오는 중...')}")

            # 첫 번째 그룹의 아이템이 100개 이하일 때만 즉시 펼쳐서 시각 피드백 제공
            if idx == 0 and len(items) <= 100:
                self._populate_group_children(parent_node)
                parent_node.setExpanded(True)

        self._tree.setUpdatesEnabled(True)
        self._tree_stack.setCurrentIndex(0)
        self._progress_circle.stop()
        self._count_label.setText(
            t("library.search_result_count", "검색 결과: 총 {total:,}개 미디어 (그룹: {groups}개)").format(
                total=total_files, groups=len(sorted_groups)
            )
        )

    def _on_item_expanded(self, item: QTreeWidgetItem):
        """사용자가 그룹을 펼칠 때 자식 파일 노드들을 지연 생성 (0.001초 소요)"""
        self._populate_group_children(item)

    def _populate_group_children(self, parent_node: QTreeWidgetItem):
        """특정 부모 노드의 자식 파일 노드들을 동적 생성"""
        is_loaded = parent_node.data(0, Qt.UserRole + 3)
        if is_loaded:
            return

        items = parent_node.data(0, Qt.UserRole + 2)
        if items is None:
            return

        # 더미 노드 제거
        parent_node.takeChildren()

        photo_text = t("common.photos", "사진")
        video_text = t("common.videos", "동영상")

        for idx, it in enumerate(items):
            if idx > 0 and idx % 200 == 0:
                QCoreApplication.processEvents()

            child = QTreeWidgetItem(parent_node)
            fname = it.get("file_name", "")
            mtype = it.get("media_type")
            icon_str = "📷" if mtype == "photo" else "🎬"
            child.setText(0, f"  {icon_str} {fname}")

            dt_str = it.get("taken_at") or "-"
            child.setText(1, dt_str)

            make = (it.get("camera_make") or "").strip()
            model = (it.get("camera_model") or "").strip()
            if make and model:
                cam_str = f"{make} {model}"
            elif make or model:
                cam_str = make or model
            else:
                cam_str = "-"
            child.setText(2, cam_str)

            type_str = photo_text if mtype == "photo" else video_text
            child.setText(3, type_str)
            child.setText(3, type_str)

            size_mb = (it.get("file_size") or 0) / (1024 * 1024)
            child.setText(4, f"{size_mb:.1f} MB")

            lat = it.get("latitude") or 0.0
            lon = it.get("longitude") or 0.0
            has_loc = lat != 0.0 or lon != 0.0
            if has_loc:
                c_name = (it.get("country_name") or "").strip()
                state = (it.get("state_name") or "").strip()
                city = (it.get("city_name") or "").strip()
                if not c_name:
                    info = GeoResolver().resolve(lat, lon, GeoLanguage.KOREAN)
                    c_name = info.country_name
                    state = info.state_name
                    city = info.city_name
                    it["country_name"] = c_name
                    it["state_name"] = state
                    it["city_name"] = city
                if self._show_3tier:
                    parts = [p for p in (c_name, state, city) if p]
                    loc_txt = " > ".join(parts)
                else:
                    parts = [p for p in (c_name, city) if p]
                    loc_txt = " ".join(parts)
                child.setText(5, f"📍 [{lat:.4f}, {lon:.4f}] {loc_txt}".strip())
                child.setForeground(5, QColor(Colors.ACCENT))
            else:
                child.setText(5, "-")

            child.setData(0, Qt.UserRole, it)

        parent_node.setData(0, Qt.UserRole + 3, True)

    def _toggle_expand_all(self):
        """전체 그룹 펼치기 / 접기 토글"""
        self._all_expanded = not self._all_expanded
        self._tree.setUpdatesEnabled(False)
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent_node = root.child(i)
            if self._all_expanded:
                self._populate_group_children(parent_node)
                parent_node.setExpanded(True)
            else:
                parent_node.setExpanded(False)
        self._tree.setUpdatesEnabled(True)
        self._expand_all_btn.setText(
            f"📁 {t('library.btn_collapse_all', '전체 접기')}" if self._all_expanded
            else f"📂 {t('library.btn_expand_all', '전체 펼치기')}"
        )

    def _on_load_error(self, worker: LibraryLoaderWorker, error_msg: str):
        if worker != self._current_worker:
            return
        self._current_worker = None
        self._progress_circle.stop()
        self._tree_stack.setCurrentIndex(0)
        self._count_label.setText(f"❌ {t('library.load_error', '데이터 조회 실패')}: {error_msg}")
        logger.error("라이브러리 데이터 로딩 실패: %s", error_msg)

    def _show_context_menu(self, pos: QPoint):
        """파인더/탐색기 스타일 우클릭 컨텍스트 메뉴"""
        item = self._tree.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                border-radius: 4px;
                font-size: 12px;
                color: #212529;
            }
            QMenu::item:selected {
                background-color: #E8F0FE;
                color: #174EA6;
            }
            QMenu::separator {
                height: 1px;
                background: #ECEFF1;
                margin: 4px 6px;
            }
        """)

        if data:
            # 개별 미디어 파일 노드 우클릭
            f_path = data.get("file_path", "")
            fname = data.get("file_name", t("common.files", "파일"))

            # 1. 파일 위치 열기 (탐색기/Finder에서 선택 상태로 표시)
            default_reveal = f"'{fname}' 위치 열기 (Finder/탐색기)"
            reveal_text = t("library.ctx_open_file_loc", default_reveal).format(fname=fname)
            act_reveal = menu.addAction(f"🔍 {reveal_text}")
            act_reveal.triggered.connect(lambda: self._reveal_file_in_os(f_path))

            menu.addSeparator()

            # 2. 파일 복사 (OS 클립보드에 파일 복사 -> 외부 폴더 붙여넣기 가능)
            act_copy_file = menu.addAction(f"📋 {t('library.ctx_copy_file', '파일 복사 (외부 폴더에 붙여넣기)')}")
            act_copy_file.triggered.connect(lambda: self._copy_file_to_clipboard(f_path))

            # 3. 파일 전체 경로 복사
            act_copy_path = menu.addAction(f"📝 {t('library.ctx_copy_path', '파일 전체 경로 복사')}")
            act_copy_path.triggered.connect(lambda: self._copy_text_to_clipboard(f_path))

        else:
            # 부모 디렉토리/그룹 노드 우클릭
            dir_path = item.data(0, Qt.UserRole + 1)
            if dir_path and os.path.exists(dir_path):
                act_open_dir = menu.addAction(f"📂 {t('library.ctx_open_folder', '폴더 위치 열기 (Finder/탐색기)')}")
                act_open_dir.triggered.connect(lambda: self._open_dir_in_os(dir_path))

                act_copy_dir = menu.addAction(f"📝 {t('library.ctx_copy_folder_path', '폴더 경로 복사')}")
                act_copy_dir.triggered.connect(lambda: self._copy_text_to_clipboard(dir_path))

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _reveal_file_in_os(self, file_path: str):
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, t("common.info", "알림"), t("library.msg_file_not_found", "해당 파일이 디스크에 존재하지 않습니다."))
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", file_path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{file_path}"])

    def _open_dir_in_os(self, dir_path: str):
        if not dir_path or not os.path.exists(dir_path):
            QMessageBox.warning(self, t("common.info", "알림"), t("library.msg_dir_not_found", "해당 디렉토리가 디스크에 존재하지 않습니다."))
            return
        if sys.platform == "darwin":
            subprocess.run(["open", dir_path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", dir_path])

    def _copy_file_to_clipboard(self, file_path: str):
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, t("common.info", "알림"), t("library.msg_file_not_found", "디스크에 존재하지 않는 파일입니다."))
            return

        success = False
        # 1. macOS: AppleScript의 POSIX file을 통해 Finder 클립보드(NSFilenamesPboardType)에 설정 (Cmd+V 붙여넣기 지원)
        if sys.platform == "darwin":
            try:
                escaped_path = file_path.replace('"', '\\"')
                script = f'set the clipboard to (POSIX file "{escaped_path}")'
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
                if res.returncode == 0:
                    success = True
            except Exception as e:
                logger.warning("osascript 클립보드 복사 실패: %s", e)

        # 2. Windows 및 macOS 폴백: Qt 표준 QMimeData setUrls (CF_HDROP 포맷 생성)
        if not success:
            try:
                mime_data = QMimeData()
                mime_data.setUrls([QUrl.fromLocalFile(file_path)])
                mime_data.setText(file_path)
                QApplication.clipboard().setMimeData(mime_data)
                success = True
            except Exception as e:
                logger.warning("Qt 클립보드 복사 실패: %s", e)

        if success:
            fname = Path(file_path).name
            self._count_label.setText(f"📋 '{fname}' {t('library.msg_copied_file', '파일이 클립보드에 복사되었습니다.')}")
        else:
            QMessageBox.warning(self, t("common.error", "오류"), t("library.msg_copy_failed", "클립보드에 파일을 복사하지 못했습니다."))

    def _copy_text_to_clipboard(self, text: str):
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._count_label.setText(f"📝 {t('library.msg_copied_path', '경로가 클립보드에 복사되었습니다')}: {text}")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if data:
            self._compare_panel.set_media_data(data)
            if not self._compare_panel.isVisible():
                self._compare_panel.setVisible(True)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if data:
            f_path = data.get("file_path")
            if f_path and os.path.exists(f_path):
                # 시스템 기본 사진/동영상 뷰어로 미디어 자체 직접 실행
                QDesktopServices.openUrl(QUrl.fromLocalFile(f_path))
                return
        # 폴더/그룹 노드인 경우 펼침/접힘 토글
        item.setExpanded(not item.isExpanded())

    def _open_selected_file_folder(self):
        item = self._tree.currentItem()
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if data:
            f_path = data.get("file_path")
            if f_path and os.path.exists(f_path):
                if sys.platform == "darwin":
                    subprocess.run(["open", "-R", f_path])
                elif sys.platform == "win32":
                    subprocess.run(["explorer", f"/select,{f_path}"])

    def _toggle_compare_panel(self):
        self._compare_panel.setVisible(not self._compare_panel.isVisible())

    def _close_compare_panel(self):
        self._compare_panel.setVisible(False)

    def _toggle_location_tier_option(self):
        """3단계(국가 > 주/도 > 시/군/구) / 2단계(국가 + 시/군/구) 위치 표기 전환"""
        self._show_3tier = not self._show_3tier
        self._update_location_tier_btn_style()
        self._compare_panel.set_location_tier(self._show_3tier)
        self._update_all_tree_location_display()

    def _on_panel_location_tier_changed(self, show_3tier: bool):
        """우측 비교 대조표 패널에서 위치 단계가 변경되었을 때 메인 뷰 동기화"""
        self._show_3tier = show_3tier
        self._update_location_tier_btn_style()
        self._update_all_tree_location_display()

    def _update_location_tier_btn_style(self):
        if self._show_3tier:
            self._location_tier_btn.setText(f"🏷️ {t('library.tier_3_btn', '위치: 3단계 (상세)')}")
            self._location_tier_btn.setToolTip(t("library.tier_3_tip", "클릭 시 2단계(국가+도시) 요약 표기로 전환합니다."))
            self._location_tier_btn.setStyleSheet(f"""
                QPushButton#SecondaryButton {{
                    font-size: 11px;
                    font-weight: 600;
                    padding: 2px 10px;
                    color: {Colors.ACCENT};
                    border: 1px solid {Colors.ACCENT};
                    background-color: #F0F6FE;
                    border-radius: 10px;
                }}
                QPushButton#SecondaryButton:hover {{
                    background-color: #E2EEFD;
                    border-color: {Colors.ACCENT};
                }}
            """)
        else:
            self._location_tier_btn.setText(f"🏷️ {t('library.tier_2_btn', '위치: 2단계 (요약)')}")
            self._location_tier_btn.setToolTip(t("library.tier_2_tip", "클릭 시 3단계(국가>주/도>도시) 상세 표기로 전환합니다."))
            self._location_tier_btn.setStyleSheet("""
                QPushButton#SecondaryButton {
                    font-size: 11px;
                    font-weight: 600;
                    padding: 2px 10px;
                    color: #495057;
                    border: 1px solid #CED4DA;
                    background-color: #FFFFFF;
                    border-radius: 10px;
                }
                QPushButton#SecondaryButton:hover {
                    background-color: #F1F3F5;
                    border-color: #ADB5BD;
                }
            """)

    def _update_all_tree_location_display(self):
        """트리에 로드된 모든 미디어 아이템의 5번 '위치' 컬럼 실시간 일괄 갱신"""
        self._tree.setUpdatesEnabled(False)
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent_node = root.child(i)
            for j in range(parent_node.childCount()):
                child = parent_node.child(j)
                it = child.data(0, Qt.UserRole)
                if isinstance(it, dict):
                    lat = it.get("latitude") or 0.0
                    lon = it.get("longitude") or 0.0
                    if lat != 0.0 or lon != 0.0:
                        c_name = (it.get("country_name") or "").strip()
                        state = (it.get("state_name") or "").strip()
                        city = (it.get("city_name") or "").strip()
                        if self._show_3tier:
                            parts = [p for p in (c_name, state, city) if p]
                            loc_txt = " > ".join(parts)
                        else:
                            parts = [p for p in (c_name, city) if p]
                            loc_txt = " ".join(parts)
                        child.setText(5, f"📍 [{lat:.4f}, {lon:.4f}] {loc_txt}".strip())
        self._tree.setUpdatesEnabled(True)

    def _sync_missing_files(self):
        """디스크에서 삭제/누락된 파일의 DB 레코드를 사용자 확인 후 일괄 정리"""
        if not self._repo:
            return
        ans = QMessageBox.question(
            self,
            t("library.sync_confirm_title", "DB 동기화 확인"),
            t("library.sync_confirm_msg", "실제 디스크 상에 존재하지 않거나 삭제된 파일의 DB 레코드를 정리하시겠습니까?\n\n이 작업은 되돌릴 수 없습니다."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            cleaned = self._repo.clean_missing_files()
            QMessageBox.information(
                self,
                t("library.sync_done_title", "동기화 완료"),
                t("library.sync_done_msg", "디스크에서 누락된 총 {count:,}개의 파일 DB 레코드를 정리했습니다.").format(count=cleaned),
            )
            self._update_root_paths()
            self.refresh_data()
