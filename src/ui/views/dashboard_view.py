"""
views/dashboard_view.py
────────────────────────────────────────────────────────────────
대시보드 뷰

표시 내용:
  - 핵심 통계 카드 (4열):
      1) 총 관리 미디어 (사진/동영상 구성)
      2) 라이브러리 보관 용량 (디스크 총 보관량)
      3) 중복 방지 / 절약 (해시 검사 기반 중복 스킵 수)
      4) 최근 작업 일시 (실행 일시 및 완료 횟수)
  - "새 Takeout 정리 시작" Primary 액션 버튼
  - 최근 작업 세션 (job_history 기반 최근 5건 정밀 요약 및 Finder 열기 액션)

Signals:
  start_job_requested: "새 작업 시작" 버튼 클릭 시 방출
  view_history_requested: "전체 이력 보기" 버튼 클릭 시 방출 (처리 이력 탭 전환)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy,
    QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

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


class StatCard(QFrame):
    """
    통계 카드 위젯.
    아이콘, 라벨, 수치, 보조 설명으로 구성된 단일 통계 카드.
    """

    def __init__(self, icon: str, label: str, value: str = "0", description: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        # 상단 아이콘 + 타이틀 라벨 행
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        icon_label = QLabel(icon)
        icon_label.setObjectName("StatCardIcon")
        top_row.addWidget(icon_label)

        self._label_widget = QLabel(label)
        self._label_widget.setObjectName("StatCardLabel")
        top_row.addWidget(self._label_widget)
        top_row.addStretch()
        layout.addLayout(top_row)

        # 수치
        self._value_label = QLabel(value)
        self._value_label.setObjectName("StatCardValue")
        layout.addWidget(self._value_label)

        # 보조 설명 라벨
        self._desc_lbl = None
        if description:
            self._desc_lbl = QLabel(description)
            self._desc_lbl.setObjectName("StatCardDesc")
            self._desc_lbl.setWordWrap(True)
            layout.addWidget(self._desc_lbl)

    def set_label(self, label: str):
        """카드 제목 라벨 갱신."""
        self._label_widget.setText(label)

    def label(self) -> str:
        """카드 제목 라벨 반환."""
        return self._label_widget.text()

    def set_value(self, value: str):
        """수치 텍스트 갱신."""
        self._value_label.setText(value)

    def set_description(self, description: str):
        """보조 설명 텍스트 갱신."""
        if self._desc_lbl:
            self._desc_lbl.setText(description)
        else:
            self._desc_lbl = QLabel(description)
            self._desc_lbl.setObjectName("StatCardDesc")
            self._desc_lbl.setWordWrap(True)
            self.layout().addWidget(self._desc_lbl)


class DashboardView(QWidget):
    """
    대시보드 메인 뷰.
    
    Signals:
        start_job_requested: "새 작업 시작" 버튼 클릭 시 방출 (MainWindow에서 연결)
        view_history_requested: "전체 이력 보기" 버튼 클릭 시 방출
    """

    start_job_requested = Signal()
    view_history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardView")
        self._db = DatabaseManager()
        self._setup_ui()
        self.retranslate_ui()
        i18n.language_changed.connect(lambda _: self.retranslate_ui())

    def _setup_ui(self):
        """대시보드 UI 초기화."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("DashboardContent")
        scroll.setWidget(content)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(18)

        # ── 환영 메시지 ───────────────────────────────────────
        self._welcome_lbl = QLabel()
        welcome_font = QFont()
        welcome_font.setPointSize(Fonts.SIZE_TITLE)
        welcome_font.setBold(True)
        self._welcome_lbl.setFont(welcome_font)
        content_layout.addWidget(self._welcome_lbl)

        self._sub_welcome_lbl = QLabel()
        self._sub_welcome_lbl.setObjectName("SubLabel")
        content_layout.addWidget(self._sub_welcome_lbl)

        # ── 4열 핵심 통계 카드 그리드 ─────────────────────────
        stats_grid = QGridLayout()
        stats_grid.setSpacing(14)

        self._card_total = StatCard("🖼", "", "0개", "")
        self._card_size  = StatCard("💾", "", "0 B", "")
        self._card_dup   = StatCard("🛡️", "", "0개", "")
        self._card_last  = StatCard("⏱️", "", "-", "")

        stats_grid.addWidget(self._card_total, 0, 0)
        stats_grid.addWidget(self._card_size,  0, 1)
        stats_grid.addWidget(self._card_dup,   0, 2)
        stats_grid.addWidget(self._card_last,  0, 3)

        content_layout.addLayout(stats_grid)

        # ── 새 작업 시작 버튼 ─────────────────────────────────
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self._start_btn = QPushButton()
        self._start_btn.setObjectName("PrimaryButton")
        self._start_btn.setCursor(Qt.PointingHandCursor)
        self._start_btn.setFixedHeight(46)
        self._start_btn.setMinimumWidth(230)
        self._start_btn.clicked.connect(self.start_job_requested.emit)

        btn_layout.addWidget(self._start_btn)
        btn_layout.addStretch()
        content_layout.addWidget(btn_container)

        # ── 최근 작업 섹션 헤더 (타이틀 + 전체 이력 보기 버튼) ──
        sec_header = QHBoxLayout()
        self._section_title = QLabel()
        self._section_title.setObjectName("SectionTitle")
        section_font = QFont()
        section_font.setPointSize(Fonts.SIZE_H2)
        section_font.setBold(True)
        self._section_title.setFont(section_font)
        sec_header.addWidget(self._section_title)
        sec_header.addStretch()

        self._view_all_btn = QPushButton()
        self._view_all_btn.setObjectName("SecondaryButton")
        self._view_all_btn.setCursor(Qt.PointingHandCursor)
        self._view_all_btn.setFixedHeight(28)
        self._view_all_btn.setStyleSheet("""
            QPushButton#SecondaryButton {
                font-size: 11px;
                padding: 2px 12px;
                border: 1px solid #0072DE;
                color: #0072DE;
                border-radius: 6px;
                background: transparent;
            }
            QPushButton#SecondaryButton:hover {
                background-color: #E8F3FF;
            }
        """)
        self._view_all_btn.clicked.connect(self.view_history_requested.emit)
        sec_header.addWidget(self._view_all_btn)
        content_layout.addLayout(sec_header)

        # ── 최근 작업 세션 테이블 ─────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(48)
        self._table.setShowGrid(False)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
            }
            QHeaderView::section {
                background-color: #F8F9FA;
                padding: 6px;
                font-weight: bold;
                font-size: 11px;
                color: #495057;
                border: none;
                border-bottom: 1px solid #E5E8EB;
            }
        """)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)

        self._table.setColumnWidth(0, 110)
        self._table.setColumnWidth(1, 130)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 90)
        self._table.setColumnWidth(5, 145)

        content_layout.addWidget(self._table)

        # 빈 상태 라벨
        self._no_history_label = QLabel()
        self._no_history_label.setObjectName("SubLabel")
        self._no_history_label.setAlignment(Qt.AlignCenter)
        self._no_history_label.setContentsMargins(0, 32, 0, 32)
        content_layout.addWidget(self._no_history_label)

        content_layout.addStretch()

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

    def retranslate_ui(self):
        """다국어 변경 시 대시보드 모든 UI 텍스트 실시간 재설정"""
        self._welcome_lbl.setText(f"{t('dashboard.title', '미디어 통합 대시보드')} 👋")
        self._sub_welcome_lbl.setText(t("dashboard.subtitle", "Google Takeout으로 백업된 미디어 파일의 정리 현황과 통계를 한눈에 확인합니다."))

        self._card_total.set_label(t("dashboard.card_total_files", "총 관리 미디어"))
        self._card_size.set_label(t("dashboard.card_total_size", "라이브러리 보관 용량"))
        self._card_dup.set_label(t("dashboard.card_skipped", "중복 건너뜀 (절약)"))
        self._card_last.set_label(t("dashboard.card_last_run", "최근 작업 일시"))

        self._start_btn.setText(f"  +  {t('dashboard.action_new_job', '새 정리 작업 시작')}")
        self._section_title.setText(t("dashboard.recent_sessions_title", "⏱ 최근 작업 세션 (최근 5건)"))
        self._view_all_btn.setText(t("dashboard.view_all_history", "전체 이력 보기 ➔"))

        self._table.setHorizontalHeaderLabels([
            t("dashboard.col_type", "작업 유형"),
            t("dashboard.col_date", "작업 일시"),
            t("dashboard.col_path_strategy", "작업 경로 및 전략"),
            t("dashboard.col_scale", "처리 규모"),
            t("dashboard.col_status", "상태"),
            t("dashboard.col_action", "액션"),
        ])

        self._no_history_label.setText(t("dashboard.recent_jobs_empty", "아직 실행된 작업 이력이 없습니다.\n위 버튼을 눌러 첫 번째 사진 정리를 시작해보세요! 🚀"))

        self.refresh()

    # ── 공개 메서드 ──────────────────────────────────────────

    def refresh(self):
        """DB에서 최신 통계/이력 데이터를 불러와 UI를 갱신한다."""
        self._db.initialize()
        self._update_stats()
        self._update_recent_jobs()

    # ── 내부 메서드 ──────────────────────────────────────────

    def _update_stats(self):
        """통계 카드 수치 및 동적 보조설명 갱신."""
        try:
            stats = self._db.get_statistics()
            total = stats.get("total_files", 0)
            p_cnt = stats.get("photo_count", 0)
            v_cnt = stats.get("video_count", 0)

            u_item = t('common.items', '개')
            sep = "" if u_item in ("개", "件", "個", "个") else " "

            self._card_total.set_value(f"{total:,}{sep}{u_item}")
            if total > 0:
                self._card_total.set_description(f"{t('common.photos', '사진')} {p_cnt:,}{sep}{u_item} · {t('common.videos', '동영상')} {v_cnt:,}{sep}{u_item}")
            else:
                self._card_total.set_description(t("dashboard.card_total_desc", "정리 및 복원 완료된 총 미디어 수"))

            total_size = stats.get("total_size_bytes", 0)
            self._card_size.set_value(self._format_bytes(total_size))
            self._card_size.set_description(t("dashboard.card_size_desc", "정리 보관된 총 디스크 용량"))

            skipped_cnt = stats.get("skipped_duplicate", 0)
            self._card_dup.set_value(f"{skipped_cnt:,}{sep}{u_item}")
            saved_sz = stats.get("saved_size_bytes", 0)
            if saved_sz > 0:
                self._card_dup.set_description(t("dashboard.card_dup_desc", "절약된 보관 용량: {size}").format(size=self._format_bytes(saved_sz)))
            else:
                self._card_dup.set_description(t("dashboard.card_dup_desc", "해시 검사 기반 중복 방지").replace(": {size}", ""))

            last_dt = stats.get("last_updated")
            job_cnt = stats.get("job_count", 0)
            if last_dt:
                dt_str = str(last_dt)[:16]
                self._card_last.set_value(dt_str)
                self._card_last.set_description(t("dashboard.jobs_done", "총 {count}회 완료").format(count=job_cnt))
            else:
                self._card_last.set_value("-")
                self._card_last.set_description(t("dashboard.no_history_desc", "실행된 작업 이력 없음"))

        except Exception:
            pass

    def _create_path_cell(self, src_dir: str, dest_dir: str, is_reorganize: bool, strategy_str: str) -> QWidget:
        """작업 유형에 따라 경로 및 전략을 요약 렌더링"""
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignVCenter)

        s_name = Path(src_dir).name if src_dir and src_dir != "-" else "-"
        d_name = Path(dest_dir).name if dest_dir and dest_dir != "-" else "-"

        if not is_reorganize:
            line = QLabel(f"📥 {s_name}  ➔  📤 {d_name}")
            line.setStyleSheet("font-size: 11px; color: #212529; font-weight: 500; border: none; background: transparent;")
            layout.addWidget(line)
            widget.setToolTip(f"📦 Google Photo 사진 정리\n\n📥 원본: {src_dir}\n📤 저장: {dest_dir}")
        else:
            strat_display = strategy_str if strategy_str else "선택 전략"
            if src_dir == dest_dir:
                line = QLabel(f"📂 {d_name}  (🏷 {strat_display})")
                line.setStyleSheet("font-size: 11px; color: #7950F2; font-weight: 600; border: none; background: transparent;")
                layout.addWidget(line)
                widget.setToolTip(f"🔄 미디어 폴더 구조 재구성 (제자리)\n\n📂 대상: {src_dir}\n🏷 전략: {strat_display}")
            else:
                line = QLabel(f"📥 {s_name}  ➔  📤 {d_name}  ({strat_display})")
                line.setStyleSheet("font-size: 11px; color: #7950F2; font-weight: 600; border: none; background: transparent;")
                layout.addWidget(line)
                widget.setToolTip(f"🔄 미디어 폴더 구조 재구성\n\n📥 출발: {src_dir}\n📤 도착: {dest_dir}\n🏷 전략: {strat_display}")

        return widget

    def _update_recent_jobs(self):
        """실제 작업 세션(최근 5건) 목록 갱신."""
        try:
            sessions = self._db.get_history_summary()
        except Exception:
            sessions = []

        if not sessions:
            self._table.setVisible(False)
            self._no_history_label.setVisible(True)
            return

        recent_sessions = sessions[:5]
        self._no_history_label.setVisible(False)
        self._table.setVisible(True)
        self._table.setRowCount(len(recent_sessions))
        # 헤더(약 36px) + 각 행(48px) + 테두리 여유를 두어 스크롤바 없이 완전히 펼쳐지도록 높이 지정
        needed_height = 40 + len(recent_sessions) * 48
        self._table.setFixedHeight(needed_height)

        for row_idx, job in enumerate(recent_sessions):
            time_str   = job.get("session_time", "-")
            src_dir    = job.get("source_dir", "-")
            dest_dir   = job.get("target_dir", "-")
            count      = job.get("count", 0)
            size_b     = job.get("total_size") or 0
            size_str   = f"{size_b / (1024*1024):.1f} MB" if size_b else "-"
            status_raw = str(job.get("status", "COMPLETED"))
            status_upper = status_raw.upper()

            is_reorganize = "REORGANIZED" in status_upper
            strategy_str = ""
            if is_reorganize and "(" in status_raw and ")" in status_raw:
                try:
                    raw_strat = status_raw.split("(", 1)[1].split(")", 1)[0].strip()
                    strategy_str = STRATEGY_DISPLAY_MAP.get(raw_strat.lower(), raw_strat)
                except Exception:
                    strategy_str = ""

            # 0번 컬럼: 작업 유형 뱃지
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
            self._table.setCellWidget(row_idx, 0, type_container)

            # 1번 컬럼: 작업 일시
            item_time = QTableWidgetItem(time_str)
            item_time.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row_idx, 1, item_time)

            # 2번 컬럼: 작업 경로 및 전략 요약
            path_widget = self._create_path_cell(src_dir, dest_dir, is_reorganize, strategy_str)
            self._table.setCellWidget(row_idx, 2, path_widget)

            # 3번 컬럼: 처리 규모 (건수 + 용량)
            scale_item = QTableWidgetItem(f"{count:,}{t('common.items', '개')} ({size_str})")
            scale_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row_idx, 3, scale_item)

            # 4번 컬럼: 상태 뱃지
            badge_container = QWidget()
            badge_layout = QHBoxLayout(badge_container)
            badge_layout.setContentsMargins(0, 0, 0, 0)
            badge_layout.setAlignment(Qt.AlignCenter)

            if "CANCEL" in status_upper or "STOP" in status_upper:
                badge_text = f"⏹ {t('common.cancel', '중단')}"
                badge_style = "background-color: #FFF9DB; color: #F08C00; border-radius: 8px; font-weight: bold; font-size: 11px; padding: 3px 10px; border: none;"
            elif "FAILED" in status_upper:
                badge_text = f"❌ {t('common.failure', '실패')}"
                badge_style = "background-color: #FFF5F5; color: #FA5252; border-radius: 8px; font-weight: bold; font-size: 11px; padding: 3px 10px; border: none;"
            else:
                badge_text = f"✅ {t('common.success', '성공')}"
                badge_style = "background-color: #E6FCF5; color: #0CA678; border-radius: 8px; font-weight: bold; font-size: 11px; padding: 3px 10px; border: none;"

            status_lbl = QLabel(badge_text)
            status_lbl.setAlignment(Qt.AlignCenter)
            status_lbl.setStyleSheet(badge_style)
            badge_layout.addWidget(status_lbl)
            self._table.setCellWidget(row_idx, 4, badge_container)

            # 5번 컬럼: 액션 버튼
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
                missing_badge = QLabel(f"⚠️ {t('history.folder_deleted', '삭제됨')}")
                missing_badge.setFixedHeight(24)
                missing_badge.setStyleSheet(
                    "font-size: 11px; color: #FA5252; font-weight: bold; background-color: #FFF5F5;"
                    "border-radius: 8px; padding: 2px 8px; border: none;"
                )
                missing_badge.setAlignment(Qt.AlignCenter)
                missing_badge.setToolTip(f"결과 저장 폴더가 삭제되었거나 이동되었습니다:\n{dest_dir}")
                cell_layout.addWidget(missing_badge)

            self._table.setCellWidget(row_idx, 5, cell_widget)

    def _open_dir(self, dir_path: str):
        if not dir_path or dir_path == "-" or not os.path.exists(dir_path):
            QMessageBox.warning(
                self,
                t("common.notice", "알림"),
                f"해당 결과 폴더가 디스크에 존재하지 않습니다.\n\n경로: {dir_path}"
            )
            return
        if sys.platform == "darwin":
            subprocess.run(["open", dir_path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", os.path.normpath(dir_path)])
        else:
            subprocess.run(["xdg-open", dir_path])

    @staticmethod
    def _format_bytes(size: int) -> str:
        """바이트를 사람이 읽기 쉬운 단위로 변환."""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
