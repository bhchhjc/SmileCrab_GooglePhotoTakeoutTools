"""
views/history_view.py
────────────────────────────────────────────────────────────────
처리 이력 뷰 (Task Session 단위 작업 이력 관리)

개념:
  1회 실행된 일련의 정리 작업을 단일 Task 항목으로 묶어,
  입력 경로, 출력 경로, 처리 파일 수, 총 용량, 완료 상태를 일목요연하게 표시합니다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from src.core.i18n import get_open_file_manager_text, i18n, t
from src.ui.theme import Colors, Fonts
from src.data.database import DatabaseManager


STRATEGY_DISPLAY_MAP = {
    "year_month": "년/월",
    "year_year_month": "년/년-월",
    "year_only": "년도별",
    "year_month_day": "년/월/일",
    "camera_year_month": "촬영기기/년/월",
    "year_month_camera": "년/월/촬영기기",
    "type_year_month": "미디어유형/년/월",
    "geo_country_city": "국가/도시/년/월",
    "geo_country": "국가/년/월",
    "album_name": "원본 앨범명",
}


class HistoryTableWidget(QTableWidget):
    """
    Finder / 탐색기 스타일의 스마트 반응형 테이블 위젯.
    
    1. 모든 열이 QHeaderView.Interactive 모드로 마우스 드래그를 통해 자유롭게 너비 조절 가능.
    2. 창 크기 변경(리사이즈, 최대화) 시 긴 텍스트 경로를 갖는 '작업 경로(1번 열)'가 남은 공간을
       자동으로 흡수하여 테이블이 항상 뷰포트 전체(100%)를 빈틈없이 가득 채움 (macOS Finder / Windows Explorer 방식).
    3. 다른 열(일시, 구성, 상태 등)의 너비를 마우스로 조절할 때도 경로 열이 연동되어 전체 너비를 가득 찬 상태로 유지.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_adjusting = False
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_section_resized)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_column_widths()

    def showEvent(self, event):
        super().showEvent(event)
        self.adjust_column_widths()

    def adjust_column_widths(self):
        if self._is_adjusting or self.columnCount() < 8:
            return
        viewport_w = self.viewport().width()
        if viewport_w <= 0:
            return
        self._is_adjusting = True
        try:
            # 2번 열(작업 경로 및 전략)을 제외한 나머지 열들의 너비 합산
            other_w = sum(self.columnWidth(i) for i in range(self.columnCount()) if i != 2)
            remaining_w = viewport_w - other_w
            # 최소 240px 이상 확보
            if remaining_w >= 240:
                self.setColumnWidth(2, remaining_w)
        finally:
            self._is_adjusting = False

    def _on_section_resized(self, logicalIndex: int, oldSize: int, newSize: int):
        if self._is_adjusting:
            return
        # 사용자가 2번 열(경로) 외의 다른 열을 조절한 경우, 2번 열이 차이를 흡수하여 전체 창 채움(100%) 유지
        if logicalIndex != 2:
            self.adjust_column_widths()


class HistoryView(QWidget):
    """
    작업(Task) 단위 처리 이력 뷰
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = DatabaseManager()
        self._setup_ui()
        self.retranslate_ui()
        i18n.language_changed.connect(lambda _: self.retranslate_ui())

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        # ── 헤더 행 ───────────────────────────────────────────
        header_row = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {Colors.TEXT_PRIMARY}; border: none;")
        header_row.addWidget(self._title_lbl)
        header_row.addStretch()

        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("SecondaryButton")
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(self._refresh_btn)

        layout.addLayout(header_row)

        # 요약 설명
        self._summary_label = QLabel()
        self._summary_label.setObjectName("SubLabel")
        self._summary_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self._summary_label)

        # ── 작업 이력 테이블 (Finder/탐색기 스타일 전체 채움 + Interactive 리사이즈) ──
        self._table = HistoryTableWidget()
        self._table.setColumnCount(8)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(48)  # 위아래 2단 경로 배치를 위해 48px로 설정
        self._table.setShowGrid(False)

        # 기본 컬럼 초기 너비 설정
        self._table.setColumnWidth(0, 130)  # 0: 작업 일시
        self._table.setColumnWidth(1, 105)  # 1: 작업 유형
        self._table.setColumnWidth(2, 290)  # 2: 작업 경로 및 전략 (adjust_column_widths로 자동 확장)
        self._table.setColumnWidth(3, 85)   # 3: 처리 파일 수
        self._table.setColumnWidth(4, 145)  # 4: 미디어 구성
        self._table.setColumnWidth(5, 85)   # 5: 총 용량
        self._table.setColumnWidth(6, 90)   # 6: 상태 (✅ 성공 / ❌ 실패 / ⏹ 중단)
        self._table.setColumnWidth(7, 145)  # 7: 액션 버튼 (Finder/탐색기 보기)

        layout.addWidget(self._table, stretch=1)

    def retranslate_ui(self):
        """다국어 변경 시 이력 뷰 전체 UI 재설정"""
        self._title_lbl.setText(f"⏱ {t('history.title', '작업 세션 이력')}")
        self._refresh_btn.setText(f"🔄 {t('common.refresh', '새로고침')}")

        self._table.setHorizontalHeaderLabels([
            t("history.col_date", "작업 일시"),
            t("history.col_type", "작업 유형"),
            t("history.col_path_strategy", "작업 경로 및 전략"),
            t("history.col_count", "처리 파일 수"),
            t("history.col_media", "미디어 구성"),
            t("history.col_size", "총 용량"),
            t("history.col_status", "상태"),
            t("history.col_action", "액션"),
        ])
        self.refresh()

    def refresh(self):
        """DB에서 최신 작업 세션 이력을 로드하여 갱신"""
        self._db.initialize()
        self._load_history()

    def _create_path_cell(self, src_dir: str, dest_dir: str, is_reorganize: bool = False, strategy_str: str = "") -> QWidget:
        """작업 유형에 따라 입력/출력 경로 및 재구성 전략을 위아래 2단으로 렌더링하는 컴팩트 셀 위젯"""
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignVCenter)

        if not is_reorganize:
            # 일반 Takeout 사진 정리
            src_lbl = QLabel(f"📥 {t('history.label_source', '원본')}: {src_dir}")
            src_lbl.setStyleSheet("font-size: 11px; color: #495057; font-weight: 500; border: none; background: transparent;")
            layout.addWidget(src_lbl)

            dest_lbl = QLabel(f"📤 {t('history.label_target', '저장')}: {dest_dir}")
            dest_lbl.setStyleSheet("font-size: 11px; color: #0072DE; font-weight: 600; border: none; background: transparent;")
            layout.addWidget(dest_lbl)

            widget.setToolTip(f"📦 {t('dashboard.type_organize', '사진 정리')}\n\n📥 {src_dir}\n📤 {dest_dir}")
        else:
            # 폴더 구조 재구성
            strat_display = strategy_str if strategy_str else t("history.custom_strategy", "선택 전략")
            if src_dir == dest_dir:
                dest_lbl = QLabel(f"📂 {t('history.label_target', '대상')}: {src_dir}")
                dest_lbl.setStyleSheet("font-size: 11px; color: #212529; font-weight: 600; border: none; background: transparent;")
                layout.addWidget(dest_lbl)

                strat_lbl = QLabel(f"🏷 {t('history.label_strategy', '전략')}: {strat_display}")
                strat_lbl.setStyleSheet("font-size: 11px; color: #7950F2; font-weight: 600; border: none; background: transparent;")
                layout.addWidget(strat_lbl)

                widget.setToolTip(f"🔄 {t('dashboard.type_reorganize', '폴더 재구성')}\n\n📂 {src_dir}\n🏷 {strat_display}")
            else:
                src_lbl = QLabel(f"📥 {t('history.label_source', '출발')}: {src_dir}")
                src_lbl.setStyleSheet("font-size: 11px; color: #495057; font-weight: 500; border: none; background: transparent;")
                layout.addWidget(src_lbl)

                dest_lbl = QLabel(f"📤 {t('history.label_target', '도착')}: {dest_dir} ({strat_display})")
                dest_lbl.setStyleSheet("font-size: 11px; color: #7950F2; font-weight: 600; border: none; background: transparent;")
                layout.addWidget(dest_lbl)

                widget.setToolTip(f"🔄 {t('dashboard.type_reorganize', '폴더 재구성')}\n\n📥 {src_dir}\n📤 {dest_dir}\n🏷 {strat_display}")

        return widget

    def _load_history(self):
        try:
            sessions = self._db.get_history_summary()
        except Exception as e:
            self._summary_label.setText(f"{t('common.failure', '조회 실패')}: {e}")
            return

        self._table.setRowCount(0)

        if not sessions:
            self._summary_label.setText(t("history.empty_history", "실행된 작업 이력이 없습니다. '새 작업' 메뉴에서 사진 정리를 실행해보세요."))
            return

        self._summary_label.setText(t("history.summary_count", "총 {count}회의 작업 이력이 기록되어 있습니다.", count=len(sessions)))

        for row_idx, job in enumerate(sessions):
            self._table.insertRow(row_idx)

            time_str   = job.get("session_time", "-")
            src_dir    = job.get("source_dir", "-")
            dest_dir   = job.get("target_dir", "-")
            count      = job.get("count", 0)
            media_info = job.get("media_types", "-")
            
            size_b     = job.get("total_size") or 0
            size_str   = f"{size_b / (1024*1024):.1f} MB" if size_b else "-"
            status_raw = str(job.get("status", "COMPLETED"))
            status_upper = status_raw.upper()

            is_reorganize = "REORGANIZED" in status_upper
            strategy_str = ""
            if is_reorganize and "(" in status_raw and ")" in status_raw:
                try:
                    raw_strat = status_raw.split("(", 1)[1].split(")", 1)[0].strip()
                    # 다국어 전략 사전 조회
                    strat_key = f"strategies.{raw_strat.upper()}"
                    translated_strat = t(strat_key, "")
                    if translated_strat:
                        strategy_str = translated_strat
                    else:
                        strategy_str = STRATEGY_DISPLAY_MAP.get(raw_strat.lower(), raw_strat)
                except Exception:
                    strategy_str = ""

            # 0번 컬럼: 작업 일시
            self._set_cell(row_idx, 0, time_str, align=Qt.AlignCenter)

            # 1번 컬럼: 작업 유형 캡슐 뱃지
            type_container = QWidget()
            type_layout = QHBoxLayout(type_container)
            type_layout.setContentsMargins(0, 0, 0, 0)
            type_layout.setAlignment(Qt.AlignCenter)

            if is_reorganize:
                type_lbl = QLabel(t("dashboard.type_reorganize", "🔄 폴더 재구성"))
                type_lbl.setStyleSheet(
                    "background-color: #F3F0FF; color: #7950F2; border-radius: 8px; "
                    "font-weight: bold; font-size: 11px; padding: 3px 8px; border: none;"
                )
            else:
                type_lbl = QLabel(t("dashboard.type_organize", "📦 사진 정리"))
                type_lbl.setStyleSheet(
                    "background-color: #E8F2FD; color: #0072DE; border-radius: 8px; "
                    "font-weight: bold; font-size: 11px; padding: 3px 8px; border: none;"
                )
            type_lbl.setAlignment(Qt.AlignCenter)
            type_layout.addWidget(type_lbl)
            self._table.setCellWidget(row_idx, 1, type_container)

            # 2번 컬럼: 작업 경로 및 전략 위아래 2단 배치 위젯
            path_widget = self._create_path_cell(src_dir, dest_dir, is_reorganize, strategy_str)
            self._table.setCellWidget(row_idx, 2, path_widget)

            # 3번 컬럼: 파일 수 (상세 툴팁 포함)
            total   = job.get("total_files") or count
            skipped = job.get("skipped_duplicate") or 0
            failed  = job.get("failed_count") or 0

            count_item = QTableWidgetItem(f"{count:,}{t('common.items', '개')}")
            count_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            tooltip_lines = [f"✅ {t('common.success', '완료')}: {count:,}{t('common.items', '개')}"]
            if total and total != count:
                tooltip_lines.append(f"📁 {t('common.total', '총 대상')}: {total:,}{t('common.items', '개')}")
            if skipped:
                tooltip_lines.append(f"⏭️ {t('job.cnt_skipped', '중복 스킵')}: {skipped:,}{t('common.items', '개')}")
            if failed:
                tooltip_lines.append(f"⚠️ {t('common.failure', '실패')}: {failed:,}{t('common.items', '개')}")
            count_item.setToolTip("\n".join(tooltip_lines))
            self._table.setItem(row_idx, 3, count_item)

            # 4번 컬럼: 미디어 구성
            display_media_info = media_info
            if media_info and media_info != "-":
                import re
                p_m = re.search(r"(?:사진|Photos?)\s*(\d+)", media_info)
                v_m = re.search(r"(?:동영상|Videos?)\s*(\d+)", media_info)
                parts = []
                if p_m:
                    parts.append(f"{t('common.photos', '사진')} {int(p_m.group(1)):,}{t('common.items', '개')}")
                if v_m:
                    parts.append(f"{t('common.videos', '동영상')} {int(v_m.group(1)):,}{t('common.items', '개')}")
                if parts:
                    display_media_info = ", ".join(parts)
            self._set_cell(row_idx, 4, display_media_info, align=Qt.AlignCenter)

            # 5번 컬럼: 총 용량
            self._set_cell(row_idx, 5, size_str, align=Qt.AlignCenter)

            # 6번 컬럼: 상태 캡슐 뱃지 (✅ 성공, ❌ 실패, ⏹ 중단)
            badge_container = QWidget()
            badge_layout = QHBoxLayout(badge_container)
            badge_layout.setContentsMargins(0, 0, 0, 0)
            badge_layout.setAlignment(Qt.AlignCenter)

            if "CANCEL" in status_upper or "STOP" in status_upper:
                badge_text = f"⏹ {t('common.cancel', '중단')}"
                badge_style = "background-color: #FFF9DB; color: #F08C00; border-radius: 8px; font-weight: bold; font-size: 11px; padding: 3px 10px; border: none;"
            elif "FAILED" in status_upper or (count == 0 and total > 0):
                badge_text = f"❌ {t('common.failure', '실패')}"
                badge_style = "background-color: #FFF5F5; color: #FA5252; border-radius: 8px; font-weight: bold; font-size: 11px; padding: 3px 10px; border: none;"
            else:
                badge_text = f"✅ {t('common.success', '성공')}"
                badge_style = "background-color: #E6FCF5; color: #0CA678; border-radius: 8px; font-weight: bold; font-size: 11px; padding: 3px 10px; border: none;"

            status_lbl = QLabel(badge_text)
            status_lbl.setAlignment(Qt.AlignCenter)
            status_lbl.setStyleSheet(badge_style)
            badge_layout.addWidget(status_lbl)
            self._table.setCellWidget(row_idx, 6, badge_container)

            # 7번 컬럼: 폴더 열기 액션 버튼 또는 삭제 뱃지
            cell_widget = QWidget()
            cell_layout = QHBoxLayout(cell_widget)
            cell_layout.setContentsMargins(6, 4, 6, 4)
            cell_layout.setAlignment(Qt.AlignCenter)

            dest_exists = bool(dest_dir and dest_dir != "-" and os.path.exists(dest_dir))
            if dest_exists:
                open_btn = QPushButton(f"📁 {get_open_file_manager_text()}")
                open_btn.setObjectName("SecondaryButton")
                open_btn.setCursor(Qt.PointingHandCursor)
                open_btn.setFixedHeight(26)
                open_btn.setStyleSheet("""
                    QPushButton#SecondaryButton {
                        min-height: 24px;
                        max-height: 26px;
                        font-size: 11px;
                        padding: 2px 8px;
                        border: 1px solid #0072DE;
                        border-radius: 8px;
                        color: #0072DE;
                        background: transparent;
                    }
                    QPushButton#SecondaryButton:hover {
                        background-color: #E8F3FF;
                    }
                """)
                open_btn.clicked.connect(lambda checked=False, p=dest_dir: self._open_dir(p))
                cell_layout.addWidget(open_btn)
            else:
                missing_badge = QLabel(f"⚠️ {t('history.folder_deleted', '폴더 삭제됨')}")
                missing_badge.setFixedHeight(24)
                missing_badge.setStyleSheet(
                    "font-size: 11px; color: #FA5252; font-weight: bold; background-color: #FFF5F5;"
                    "border-radius: 8px; padding: 2px 8px; border: none;"
                )
                missing_badge.setAlignment(Qt.AlignCenter)
                missing_badge.setToolTip(f"{dest_dir}")
                cell_layout.addWidget(missing_badge)

            self._table.setCellWidget(row_idx, 7, cell_widget)

    def _set_cell(self, row: int, col: int, text: str, align=Qt.AlignLeft | Qt.AlignVCenter):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align)
        self._table.setItem(row, col, item)

    def _open_dir(self, dir_path: str):
        if not dir_path or dir_path == "-" or not os.path.exists(dir_path):
            QMessageBox.warning(
                self,
                t("common.notice", "알림"),
                f"해당 결과 폴더가 디스크에 존재하지 않습니다.\n폴더가 삭제되었거나 이동되었을 수 있습니다.\n\n경로: {dir_path}"
            )
            return
        if sys.platform == "darwin":
            subprocess.run(["open", dir_path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", os.path.normpath(dir_path)])
        else:
            subprocess.run(["xdg-open", dir_path])
