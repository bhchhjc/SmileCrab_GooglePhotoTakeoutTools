"""
views/job_view.py
────────────────────────────────────────────────────────────────
새 작업 뷰 — 단일 뷰 내 서브스텝 방식

내부 서브스텝 (QStackedWidget):
  STEP_SETUP    (0): Takeout 폴더 선택 + 출력 폴더 + 옵션 설정
  STEP_PREVIEW  (1): 스캔 결과 미리보기 + 최종 옵션 확인
  STEP_PROGRESS (2): 실시간 진행 상황 + 로그
  STEP_DONE     (3): 완료 요약

Signals:
  job_completed: 작업 완료 시 방출 → MainWindow에서 대시보드/이력 갱신
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QFileDialog, QComboBox, QRadioButton, QButtonGroup,
    QProgressBar, QPlainTextEdit, QScrollArea, QGridLayout,
    QSizePolicy, QSpacerItem, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QThreadPool
from PySide6.QtGui import (
    QFont, QColor, QDragEnterEvent, QDragMoveEvent,
    QDragLeaveEvent, QDropEvent,
)

from src.ui.theme import Colors, Fonts
from src.ui.workers import ScanWorker, ProcessWorker
from src.core.geo_resolver import GeoLanguage
from src.core.i18n import i18n, t
from src.data.database import DatabaseManager
from src.services.process_service import FolderStrategy, ProcessMode, get_strategy_display_name


# ── 서브스텝 인덱스 상수 ─────────────────────────────────────
STEP_SETUP    = 0
STEP_PREVIEW  = 1
STEP_PROGRESS = 2
STEP_DONE     = 3


class StepIndicator(QWidget):
    """
    상단 서브스텝 인디케이터 바.
    현재 단계를 시각적으로 표시 (상단 동그라미 번호 + 연결선 / 하단 가운데 정렬 라벨).
    """

    STEPS = ["폴더 선택", "미리보기", "처리 중", "완료"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        grid = QGridLayout(self)
        grid.setContentsMargins(16, 8, 16, 8)
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)

        self._circles: list[QLabel] = []
        self._labels: list[QLabel] = []
        self._lines: list[QFrame] = []

        for i, step in enumerate(self.STEPS):
            col_idx = i * 2

            # 1. 상단 동그라미 번호 (가운데 정렬)
            circle = QLabel(str(i + 1))
            circle.setFixedSize(28, 28)
            circle.setAlignment(Qt.AlignCenter)
            self._circles.append(circle)
            grid.addWidget(circle, 0, col_idx, Qt.AlignCenter)

            # 2. 하단 텍스트 라벨 (가운데 정렬)
            lbl = QLabel(step)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("SubLabel")
            self._labels.append(lbl)
            grid.addWidget(lbl, 1, col_idx, Qt.AlignCenter)

            # 3. 연결선 (마지막 스텝 제외)
            if i < len(self.STEPS) - 1:
                line = QFrame()
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self._lines.append(line)
                grid.addWidget(line, 0, col_idx + 1, Qt.AlignVCenter)
                grid.setColumnStretch(col_idx + 1, 1)

        self._update_style()

    def set_step(self, step: int):
        self._current = step
        self._update_style()

    def retranslate_ui(self):
        """서브스텝 라벨 다국어 갱신"""
        steps = [
            t("job.step_select", "폴더 선택"),
            t("job.step_preview", "미리보기"),
            t("job.step_processing", "처리 중"),
            t("job.step_done", "완료"),
        ]
        for lbl, name in zip(self._labels, steps):
            lbl.setText(name)

    def _update_style(self):
        for i, (circle, label) in enumerate(zip(self._circles, self._labels)):
            if i < self._current:
                # 완료된 스텝
                circle.setStyleSheet(
                    f"background-color: {Colors.SUCCESS}; color: white;"
                    f"border-radius: 14px; font-weight: bold; font-size: 12px;"
                )
                label.setStyleSheet(f"color: {Colors.SUCCESS}; font-weight: bold; font-size: 11px;")
            elif i == self._current:
                # 현재 스텝
                circle.setStyleSheet(
                    f"background-color: {Colors.ACCENT}; color: white;"
                    f"border-radius: 14px; font-weight: bold; font-size: 12px;"
                )
                label.setStyleSheet(f"color: {Colors.ACCENT}; font-weight: bold; font-size: 11px;")
            else:
                # 미래 스텝
                circle.setStyleSheet(
                    f"background-color: {Colors.BORDER}; color: {Colors.TEXT_SECONDARY};"
                    f"border-radius: 14px; font-size: 12px;"
                )
                label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")

        # 연결선 색상 동적 갱신
        for i, line in enumerate(self._lines):
            if i < self._current:
                line.setStyleSheet(f"background-color: {Colors.SUCCESS}; border: none;")
            else:
                line.setStyleSheet(f"background-color: {Colors.BORDER}; border: none;")


class FolderPicker(QFrame):
    """
    드래그 앤 드롭을 지원하는 One UI 스타일 폴더 선택 컴포넌트.
    Finder(Mac) 및 파일 탐색기(Win)에서 폴더를 드래그하여 드롭하면 경로가 자동 설정됩니다.
    """

    path_changed = Signal(str)

    def __init__(self, label: str, placeholder: str = "폴더를 선택하거나 이곳으로 끌어다 놓으세요...", parent=None):
        super().__init__(parent)
        self.setObjectName("FolderPickerZone")
        self.setAcceptDrops(True)
        self._path: str = ""
        self._placeholder = placeholder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # 1. 헤더: 라벨 + 드롭 안내 힌트
        hdr_layout = QHBoxLayout()
        hdr_layout.setSpacing(8)

        self._lbl = QLabel(label)
        self._lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1C1D1F; border: none; background: transparent;")
        hdr_layout.addWidget(self._lbl)

        self._hint_lbl = QLabel("(💡 Finder 또는 파일 탐색기에서 폴더를 끌어다 놓으세요)")
        self._hint_lbl.setStyleSheet("font-size: 11px; color: #868E96; border: none; background: transparent;")
        hdr_layout.addWidget(self._hint_lbl)
        hdr_layout.addStretch()

        layout.addLayout(hdr_layout)

        # 2. 경로 표시줄 + 찾아보기 버튼
        row = QHBoxLayout()
        row.setSpacing(10)

        self._path_label = QLabel(placeholder)
        self._path_label.setObjectName("SubLabel")
        self._path_label.setStyleSheet(
            "font-size: 12px; color: #868E96; background-color: #FFFFFF; "
            "border: 1px solid #E5E8EB; border-radius: 8px; padding: 6px 10px;"
        )
        self._path_label.setWordWrap(True)
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self._path_label, stretch=1)

        self._browse_btn = QPushButton("📂 폴더 선택")
        self._browse_btn.setObjectName("SecondaryButton")
        self._browse_btn.setCursor(Qt.PointingHandCursor)
        self._browse_btn.setFixedHeight(32)
        self._browse_btn.setFixedWidth(120)
        self._browse_btn.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: 600; border-radius: 8px; } "
        )
        self._browse_btn.clicked.connect(self._on_browse)
        row.addWidget(self._browse_btn)

        layout.addLayout(row)

        self._set_drag_active(False)

    def set_labels(self, label: str, placeholder: str, hint: str, browse_btn_text: str):
        self._lbl.setText(label)
        self._placeholder = placeholder
        if not self._path:
            self._path_label.setText(placeholder)
        self._hint_lbl.setText(hint)
        self._browse_btn.setText(browse_btn_text)

    def _set_drag_active(self, active: bool):
        if active:
            self.setStyleSheet("""
                QFrame#FolderPickerZone {
                    background-color: #E8F2FD;
                    border: 2px dashed #0072DE;
                    border-radius: 12px;
                }
            """)
            self._hint_lbl.setText("✨ 여기에 폴더를 놓으세요!")
            self._hint_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #0072DE; border: none; background: transparent;")
        else:
            self.setStyleSheet("""
                QFrame#FolderPickerZone {
                    background-color: #FAFBFD;
                    border: 1px dashed #CED4DA;
                    border-radius: 12px;
                }
                QFrame#FolderPickerZone:hover {
                    border-color: #0072DE;
                    background-color: #F8F9FA;
                }
            """)
            self._hint_lbl.setText("(💡 Finder 또는 파일 탐색기에서 폴더를 끌어다 놓으세요)")
            self._hint_lbl.setStyleSheet("font-size: 11px; color: #868E96; border: none; background: transparent;")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return

        for url in urls:
            local_path = url.toLocalFile()
            if not local_path:
                continue

            p = Path(local_path)
            if p.is_dir():
                self.set_path(str(p))
                event.acceptProposedAction()
                return
            elif p.is_file():
                self.set_path(str(p.parent))
                event.acceptProposedAction()
                return

        event.ignore()

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(self, t("common.select_folder", "폴더 선택"), self._path or "")
        if path:
            self.set_path(path)

    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str):
        self._path = path
        if path:
            self._path_label.setText(path)
            self._path_label.setStyleSheet(
                "font-size: 12px; font-weight: 600; color: #1C1D1F; background-color: #FFFFFF; "
                "border: 1px solid #0072DE; border-radius: 8px; padding: 6px 10px;"
            )
            self.path_changed.emit(path)
        else:
            self._path_label.setText(self._placeholder)
            self._path_label.setStyleSheet(
                "font-size: 12px; color: #868E96; background-color: #FFFFFF; "
                "border: 1px solid #E5E8EB; border-radius: 8px; padding: 6px 10px;"
            )
            self.path_changed.emit("")


class SetupStep(QWidget):
    """STEP 0: 폴더 선택 + 옵션 설정."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 입력 폴더
        input_card = QFrame()
        input_card.setObjectName("Card")
        input_layout = QVBoxLayout(input_card)
        input_layout.setSpacing(12)

        self.input_title = QLabel()
        self.input_title.setObjectName("SectionTitle")
        input_layout.addWidget(self.input_title)

        self.input_picker = FolderPicker("", "")
        input_layout.addWidget(self.input_picker)
        layout.addWidget(input_card)

        # 출력 폴더
        output_card = QFrame()
        output_card.setObjectName("Card")
        output_layout = QVBoxLayout(output_card)
        output_layout.setSpacing(12)

        self.output_title = QLabel()
        self.output_title.setObjectName("SectionTitle")
        output_layout.addWidget(self.output_title)

        self.output_picker = FolderPicker("", "")
        output_layout.addWidget(self.output_picker)
        layout.addWidget(output_card)

        # 옵션
        options_card = QFrame()
        options_card.setObjectName("Card")
        options_layout = QVBoxLayout(options_card)
        options_layout.setSpacing(16)

        self.options_title = QLabel()
        self.options_title.setObjectName("SectionTitle")
        options_layout.addWidget(self.options_title)

        grid = QGridLayout()
        grid.setSpacing(12)

        # 1. 폴더 구조 (10종 프리셋)
        self.strategy_lbl = QLabel()
        grid.addWidget(self.strategy_lbl, 0, 0)
        self.strategy_combo = QComboBox()
        self._populate_strategies()
        grid.addWidget(self.strategy_combo, 0, 1)

        # 2. 위치 표기 언어 (DB 설정값 동기화 및 상시 선택 가능)
        self.geo_lang_lbl = QLabel()
        grid.addWidget(self.geo_lang_lbl, 1, 0)
        self.geo_lang_combo = QComboBox()
        self._populate_geo_languages()

        # DB에 저장된 기본 역지오코딩 언어 복원
        saved_geo = DatabaseManager().get_setting("geo_language")
        if saved_geo:
            g_idx = self.geo_lang_combo.findData(saved_geo)
            if g_idx >= 0:
                self.geo_lang_combo.setCurrentIndex(g_idx)

        self.geo_lang_combo.setEnabled(True)  # 폴더 전략과 상관없이 상시 활성화!
        grid.addWidget(self.geo_lang_combo, 1, 1)

        # 3. 생성 경로 실시간 미리보기
        self.preview_path_title_lbl = QLabel()
        grid.addWidget(self.preview_path_title_lbl, 2, 0)
        self.preview_path_lbl = QLabel("📁 2023/05/IMG_20230515_120000.jpg")
        self.preview_path_lbl.setFixedHeight(34)
        self.preview_path_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.preview_path_lbl.setStyleSheet("""
            font-size: 11px;
            font-family: monospace;
            font-weight: bold;
            color: #0072DE;
            background-color: #F8F9FA;
            border: 1px solid #DCE1E7;
            border-radius: 8px;
            padding: 0px 12px;
        """)
        grid.addWidget(self.preview_path_lbl, 2, 1)

        # 시그널 연결
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.geo_lang_combo.currentIndexChanged.connect(self._update_preview_path)

        # 4. 처리 모드
        self.mode_lbl = QLabel()
        grid.addWidget(self.mode_lbl, 3, 0)
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(16)
        self.mode_group = QButtonGroup(self)
        self.radio_copy = QRadioButton()
        self.radio_move = QRadioButton()
        self.radio_copy.setChecked(True)
        self.mode_group.addButton(self.radio_copy, 0)
        self.mode_group.addButton(self.radio_move, 1)
        mode_layout.addWidget(self.radio_copy)
        mode_layout.addWidget(self.radio_move)
        mode_layout.addStretch()
        grid.addWidget(mode_widget, 3, 1)

        options_layout.addLayout(grid)
        layout.addWidget(options_card)
        layout.addStretch()

        # 스캔 진행 상황 카드 (스크롤 밖 하단 고정 영역: 어떤 해상도에서도 가려지지 않고 즉시 노출)
        self.scan_card = QFrame()
        self.scan_card.setObjectName("OneUIScanCard")
        self.scan_card.setStyleSheet("""
            QFrame#OneUIScanCard {
                background-color: #FFFFFF;
                border: 2px solid #0072DE;
                border-radius: 16px;
                margin: 0px 20px 10px 20px;
            }
        """)
        s_layout = QVBoxLayout(self.scan_card)
        s_layout.setContentsMargins(18, 14, 18, 14)
        s_layout.setSpacing(8)

        # 헤더: 타이틀 + 취소 버튼
        s_hdr = QHBoxLayout()
        self.scan_title_lbl = QLabel(t("job.scan_title", "🔍 미디어 파일 사전 스캔 및 분석 중..."))
        self.scan_title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #0072DE; border: none; background: transparent;")
        s_hdr.addWidget(self.scan_title_lbl)
        s_hdr.addStretch()

        self.scan_cancel_btn = QPushButton(f"✕ {t('common.cancel', '취소')}")
        self.scan_cancel_btn.setCursor(Qt.PointingHandCursor)
        self.scan_cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF5F5;
                color: #FA5252;
                border: 1px solid #FFC9C9;
                border-radius: 8px;
                font-size: 11px;
                font-weight: bold;
                padding: 3px 10px;
            }
            QPushButton:hover {
                background-color: #FFE3E3;
            }
        """)
        s_hdr.addWidget(self.scan_cancel_btn)
        s_layout.addLayout(s_hdr)

        # 진행 요약 라벨
        self.scan_summary_lbl = QLabel(t("common.loading", "분석 준비 중..."))
        self.scan_summary_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1C1D1F; border: none; background: transparent;")
        s_layout.addWidget(self.scan_summary_lbl)

        # 프로그레스바
        self.scan_bar = QProgressBar()
        self.scan_bar.setFixedHeight(8)
        self.scan_bar.setTextVisible(False)
        self.scan_bar.setRange(0, 100)
        self.scan_bar.setValue(0)
        self.scan_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E9ECEF;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #0072DE;
                border-radius: 4px;
            }
        """)
        s_layout.addWidget(self.scan_bar)

        # 상세 상태 (현재 처리 파일)
        self.scan_detail_lbl = QLabel("")
        self.scan_detail_lbl.setStyleSheet("font-size: 11px; color: #6C757D; border: none; background: transparent;")
        s_layout.addWidget(self.scan_detail_lbl)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.addWidget(self._scroll, stretch=1)
        outer.addWidget(self.scan_card)
        self.scan_card.hide()

        self._scroll.setWidget(content)
        self.retranslate_ui()

    def _populate_strategies(self):
        curr = self.strategy_combo.currentData()
        self.strategy_combo.blockSignals(True)
        self.strategy_combo.clear()
        strats = [
            FolderStrategy.YEAR_MONTH,
            FolderStrategy.YEAR_YEAR_MONTH,
            FolderStrategy.YEAR_ONLY,
            FolderStrategy.YEAR_MONTH_DAY,
            FolderStrategy.CAMERA_YEAR_MONTH,
            FolderStrategy.YEAR_MONTH_CAMERA,
            FolderStrategy.TYPE_YEAR_MONTH,
            FolderStrategy.GEO_COUNTRY_CITY,
            FolderStrategy.GEO_COUNTRY,
            FolderStrategy.ALBUM_NAME,
        ]
        for s in strats:
            self.strategy_combo.addItem(get_strategy_display_name(s), s)
        if curr:
            idx = self.strategy_combo.findData(curr)
            if idx >= 0:
                self.strategy_combo.setCurrentIndex(idx)
        self.strategy_combo.blockSignals(False)

    def _populate_geo_languages(self):
        curr = self.geo_lang_combo.currentData() if hasattr(self, "geo_lang_combo") else None
        self.geo_lang_combo.blockSignals(True)
        self.geo_lang_combo.clear()
        self.geo_lang_combo.addItem(t("geo_languages.SYSTEM", "💻 시스템 언어 (자동 감지)"), GeoLanguage.SYSTEM)
        self.geo_lang_combo.addItem(t("geo_languages.KOREAN", "🇰🇷 한국어 (대한민국 / 서울)"), GeoLanguage.KOREAN)
        self.geo_lang_combo.addItem(t("geo_languages.ENGLISH", "🇺🇸 영어 (South Korea / Seoul)"), GeoLanguage.ENGLISH)
        if curr:
            idx = self.geo_lang_combo.findData(curr)
            if idx >= 0:
                self.geo_lang_combo.setCurrentIndex(idx)
        self.geo_lang_combo.blockSignals(False)

    def retranslate_ui(self):
        self.input_title.setText(f"📂 {t('job.source_group', '입력 폴더 (Google Takeout 압축 해제 경로)')}")
        self.input_picker.set_labels(
            t("job.source_input_label", "Takeout 폴더 경로"),
            t("job.source_placeholder", "Google Takeout 압축 해제 폴더를 선택하거나 끌어다 놓으세요."),
            t("job.drop_hint", "(💡 Finder 또는 파일 탐색기에서 폴더를 끌어다 놓으세요)"),
            f"📂 {t('common.select_folder', '폴더 선택')}",
        )
        self.output_title.setText(f"📁 {t('job.target_group', '출력 폴더 (정리된 사진을 저장할 경로)')}")
        self.output_picker.set_labels(
            t("job.target_input_label", "저장 대상 폴더 경로"),
            t("job.target_placeholder", "사진이 정리될 출력 폴더를 선택하거나 끌어다 놓으세요."),
            t("job.drop_hint", "(💡 Finder 또는 파일 탐색기에서 폴더를 끌어다 놓으세요)"),
            f"📂 {t('common.select_folder', '폴더 선택')}",
        )
        self.options_title.setText(f"⚙ {t('job.strategy_group', '처리 옵션')}")
        self.strategy_lbl.setText(t("job.strategy_label", "폴더 구조"))
        self._populate_strategies()

        self.geo_lang_lbl.setText(t("job.geo_lang_label", "위치 표기 언어"))
        self._populate_geo_languages()
        self._update_geo_lang_tooltip()
        self.preview_path_title_lbl.setText(t("job.preview_path_label", "생성 경로 예시"))
        self.mode_lbl.setText(t("job.mode_label", "처리 방식"))
        self.radio_copy.setText(t("job.mode_copy", "복사 (원본 보존)"))
        self.radio_move.setText(t("job.mode_move", "이동 (원본 삭제)"))

        self.scan_title_lbl.setText(t("job.scan_title", "🔍 미디어 파일 사전 스캔 및 분석 중..."))
        self.scan_cancel_btn.setText(f"✕ {t('common.cancel', '취소')}")

    def show_scan_progress(self, visible: bool):
        self.scan_card.setVisible(visible)
        if visible:
            self.scan_bar.setRange(0, 0)  # 초기에는 무한 탐색 애니메이션
            self.scan_summary_lbl.setText("📁 폴더 순회 및 파일 탐색 중...")
            self.scan_detail_lbl.setText("Google Takeout 폴더의 미디어 파일 목록을 수집하고 있습니다...")

    def update_scan_progress(self, current: int, total: int, message: str):
        if total > 0:
            pct = int((current / total) * 100)
            self.scan_bar.setRange(0, 100)
            self.scan_bar.setValue(pct)
            self.scan_summary_lbl.setText(
                f"📊 분석 진행률: {pct}%  ({current:,} / {total:,}개 미디어 분석 완료)"
            )
        else:
            self.scan_bar.setRange(0, 0)
            self.scan_summary_lbl.setText(message)

        self.scan_detail_lbl.setText(message)

    def _on_strategy_changed(self):
        """폴더 전략 변경 시: 툴팁 및 미리보기 갱신"""
        self._update_geo_lang_tooltip()
        self._update_preview_path()

    def _update_geo_lang_tooltip(self):
        strat = self.folder_strategy
        is_geo = strat in (FolderStrategy.GEO_COUNTRY_CITY, FolderStrategy.GEO_COUNTRY)
        if is_geo:
            tip = t("job.geo_lang_tip_folder", "선택한 언어가 디스크 폴더 생성 및 DB 지명 색인 모두에 적용됩니다.")
        else:
            tip = t("job.geo_lang_tip_db", "디스크는 선택한 폴더 구조로 정리되며, 지정한 지명 언어는 DB 색인 및 추후 폴더/파일명 재구성에 적용됩니다.")
        self.geo_lang_combo.setToolTip(tip)
        self.geo_lang_lbl.setToolTip(tip)

    def _update_preview_path(self):
        """선택된 전략과 언어에 따라 실시간 생성 경로 예시를 업데이트"""
        strat = self.folder_strategy
        lang = self.geo_language

        is_ko = lang in (GeoLanguage.KOREAN, GeoLanguage.SYSTEM)

        if strat == FolderStrategy.YEAR_MONTH:
            path_str = "📁 2023/05/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.YEAR_YEAR_MONTH:
            path_str = "📁 2023/2023-05/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.YEAR_ONLY:
            path_str = "📁 2023/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.YEAR_MONTH_DAY:
            path_str = "📁 2023/05/15/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.CAMERA_YEAR_MONTH:
            path_str = "📁 Samsung Galaxy S23/2023/05/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.YEAR_MONTH_CAMERA:
            path_str = "📁 2023/05/Samsung Galaxy S23/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.TYPE_YEAR_MONTH:
            path_str = "📁 사진/2023/05/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.GEO_COUNTRY_CITY:
            if is_ko:
                path_str = "📁 대한민국/서울/2023/05/IMG_20230515_120000.jpg"
            else:
                path_str = "📁 South Korea/Seoul/2023/05/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.GEO_COUNTRY:
            if is_ko:
                path_str = "📁 대한민국/2023/05/IMG_20230515_120000.jpg"
            else:
                path_str = "📁 South Korea/2023/05/IMG_20230515_120000.jpg"
        elif strat == FolderStrategy.ALBUM_NAME:
            path_str = "📁 제주도 가족여행 2023/IMG_20230515_120000.jpg"
        else:
            path_str = "📁 2023/05/IMG_20230515_120000.jpg"

        self.preview_path_lbl.setText(path_str)

    @property
    def folder_strategy(self) -> FolderStrategy:
        return self.strategy_combo.currentData() or FolderStrategy.YEAR_MONTH

    @property
    def geo_language(self) -> GeoLanguage:
        return self.geo_lang_combo.currentData() or GeoLanguage.KOREAN

    @property
    def process_mode(self) -> ProcessMode:
        return ProcessMode.COPY if self.radio_copy.isChecked() else ProcessMode.MOVE


class PreviewStep(QWidget):
    """STEP 1: 스캔 결과 미리보기."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        layout.addWidget(self.title)

        # 통계 그리드
        stats_card = QFrame()
        stats_card.setObjectName("Card")
        stats_layout = QGridLayout(stats_card)
        stats_layout.setSpacing(16)

        self._stat_labels: dict[str, QLabel] = {}
        self._stat_title_labels: dict[str, QLabel] = {}
        stats = [
            ("total_files",   "📄 총 파일 수",         "0"),
            ("media_files",   "🖼 미디어 파일",          "0"),
            ("json_files",    "📋 JSON 메타데이터 파일",  "0"),
            ("matched",       "✅ 메타데이터 매칭",        "0"),
            ("unmatched",     "❓ 매칭 실패",             "0"),
            ("duplicates",    "♻ 중복 파일",             "0"),
        ]
        for i, (key, label, default) in enumerate(stats):
            row, col = divmod(i, 2)
            lbl = QLabel(label)
            val = QLabel(default)
            val.setObjectName("StatCardValue")
            font = QFont()
            font.setPointSize(Fonts.SIZE_H1)
            font.setBold(True)
            val.setFont(font)
            self._stat_labels[key] = val
            self._stat_title_labels[key] = lbl

            cell = QFrame()
            cell_layout = QVBoxLayout(cell)
            cell_layout.addWidget(lbl)
            cell_layout.addWidget(val)
            stats_layout.addWidget(cell, row, col)

        layout.addWidget(stats_card)

        # 메시지
        self._msg_label = QLabel()
        self._msg_label.setObjectName("SubLabel")
        self._msg_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._msg_label)
        layout.addStretch()

        self.retranslate_ui()

    def retranslate_ui(self):
        self.title.setText(f"🔍 {t('job.preview_title', '스캔 결과 미리보기')}")
        lbl_maps = {
            "total_files": f"📄 {t('job.stat_total_files', '총 파일 수')}",
            "media_files": f"🖼 {t('job.stat_media_files', '미디어 파일')}",
            "json_files": f"📋 {t('job.stat_json_files', 'JSON 메타데이터 파일')}",
            "matched": f"✅ {t('job.stat_matched', '메타데이터 매칭')}",
            "unmatched": f"❓ {t('job.stat_unmatched', '매칭 실패')}",
            "duplicates": f"♻ {t('job.stat_duplicates', '중복 파일')}",
        }
        for k, lbl in self._stat_title_labels.items():
            if k in lbl_maps:
                lbl.setText(lbl_maps[k])
        if not hasattr(self, "_is_scanned") or not self._is_scanned:
            self._msg_label.setText(t("job.preview_msg_initial", "위 버튼을 눌러 먼저 폴더를 스캔하세요."))
        else:
            self._msg_label.setText(t("job.preview_msg_done", "✅ 스캔 완료! 아래 '처리 시작' 버튼을 누르세요."))

    def update_stats(self, stats: dict):
        """스캔 결과로 통계 갱신."""
        self._is_scanned = True
        for key, val_label in self._stat_labels.items():
            val = stats.get(key, 0)
            val_label.setText(f"{val:,}")
        self._msg_label.setText(t("job.preview_msg_done", "✅ 스캔 완료! 아래 '처리 시작' 버튼을 누르세요."))


class ProgressStep(QWidget):
    """STEP 2: 실시간 진행 상황 및 로그 콘솔 (One UI 9.0 레이아웃)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ── 1. 상단 프로그레스 및 지표 고정 카드 ──────────────────
        progress_card = QFrame()
        progress_card.setObjectName("OneUIProgressCard")
        progress_card.setStyleSheet("""
            QFrame#OneUIProgressCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 16px;
            }
        """)
        p_layout = QVBoxLayout(progress_card)
        p_layout.setContentsMargins(18, 14, 18, 14)
        p_layout.setSpacing(10)

        # 1행: 타이틀 + 진행률 알약 캡슐 뱃지
        hdr_box = QHBoxLayout()
        self.title_lbl = QLabel(t("job.progress_title", "⏳ 미디어 파일 정리 및 메타데이터 주입 중..."))
        self.title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #1C1D1F; border: none; background: transparent;")
        hdr_box.addWidget(self.title_lbl)
        hdr_box.addStretch()

        self._pct_badge = QLabel("0% (0 / 0)")
        self._pct_badge.setStyleSheet(
            "background-color: #E8F2FD; color: #0072DE; border-radius: 12px; "
            "font-size: 12px; font-weight: bold; padding: 4px 12px; border: none;"
        )
        hdr_box.addWidget(self._pct_badge)
        p_layout.addLayout(hdr_box)

        # 2행: One UI 슬림 블루 프로그레스바
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(10)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E9ECEF;
                border-radius: 5px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #0072DE;
                border-radius: 5px;
            }
        """)
        p_layout.addWidget(self._progress_bar)

        # 3행: 실시간 통계 카운트 뱃지 행 (완료 / 건너뜀 / 오류)
        stats_box = QHBoxLayout()
        stats_box.setSpacing(8)

        self._cnt_processed = QLabel(f"✅ {t('job.cnt_processed', '처리 완료')}: 0{t('common.items', '개')}")
        self._cnt_processed.setStyleSheet(
            "background-color: #E6FCF5; color: #0CA678; font-weight: bold; "
            "font-size: 11px; padding: 3px 10px; border-radius: 8px; border: none;"
        )
        stats_box.addWidget(self._cnt_processed)

        self._cnt_skipped = QLabel(f"⏭️ {t('job.cnt_skipped', '건너뜀 (중복)')}: 0{t('common.items', '개')}")
        self._cnt_skipped.setStyleSheet(
            "background-color: #FFF9DB; color: #F59F00; font-weight: bold; "
            "font-size: 11px; padding: 3px 10px; border-radius: 8px; border: none;"
        )
        stats_box.addWidget(self._cnt_skipped)

        self._cnt_errors = QLabel(f"❌ {t('job.cnt_errors', '오류')}: 0{t('common.items', '개')}")
        self._cnt_errors.setStyleSheet(
            "background-color: #FFF5F5; color: #FA5252; font-weight: bold; "
            "font-size: 11px; padding: 3px 10px; border-radius: 8px; border: none;"
        )
        stats_box.addWidget(self._cnt_errors)
        stats_box.addStretch()

        p_layout.addLayout(stats_box)

        # 4행: 현재 처리 파일 상태 안내
        self._status_label = QLabel(t("common.loading", "작업 준비 중..."))
        self._status_label.setStyleSheet("font-size: 11px; color: #495057; border: none; background: transparent;")
        self._status_label.setWordWrap(True)
        p_layout.addWidget(self._status_label)

        layout.addWidget(progress_card)

        # ── 2. 하단 처리 로그 확장 카드 (화면 전체 확장 stretch=1) ──
        log_card = QFrame()
        log_card.setObjectName("OneUILogCard")
        log_card.setStyleSheet("""
            QFrame#OneUILogCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 16px;
            }
        """)
        l_layout = QVBoxLayout(log_card)
        l_layout.setContentsMargins(18, 14, 18, 14)
        l_layout.setSpacing(10)

        log_hdr = QHBoxLayout()
        self.log_title = QLabel(f"📋 {t('job.log_title', '실시간 처리 로그')}")
        self.log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #1C1D1F; border: none; background: transparent;")
        log_hdr.addWidget(self.log_title)
        log_hdr.addStretch()

        self.clear_btn = QPushButton(t("job.clear_logs", "로그 지우기"))
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #868E96;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                font-size: 11px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: #F1F3F6;
                color: #495057;
            }
        """)
        self.clear_btn.clicked.connect(self._clear_logs)
        log_hdr.addWidget(self.clear_btn)
        l_layout.addLayout(log_hdr)

        self._log_console = QPlainTextEdit()
        self._log_console.setObjectName("LogConsole")
        self._log_console.setReadOnly(True)
        self._log_console.setMaximumBlockCount(3000)
        self._log_console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._log_console.setStyleSheet("""
            QPlainTextEdit {
                background-color: #F8F9FA;
                color: #212529;
                border: 1px solid #E5E8EB;
                border-radius: 10px;
                font-family: Menlo, Monaco, "Courier New", monospace;
                font-size: 11px;
                padding: 10px;
                line-height: 1.4;
            }
        """)
        l_layout.addWidget(self._log_console, stretch=1)

        layout.addWidget(log_card, stretch=1)

    def retranslate_ui(self):
        self.title_lbl.setText(t("job.progress_title", "⏳ 미디어 파일 정리 및 메타데이터 주입 중..."))
        self.log_title.setText(f"📋 {t('job.log_title', '실시간 처리 로그')}")
        self.clear_btn.setText(t("job.clear_logs", "로그 지우기"))

    def _clear_logs(self):
        self._log_console.clear()

    def reset(self):
        self._progress_bar.setValue(0)
        self._pct_badge.setText("0% (0 / 0)")
        self._status_label.setText(t("common.loading", "처리 준비 중..."))
        self._cnt_processed.setText(f"✅ {t('job.cnt_processed', '처리 완료')}: 0{t('common.items', '개')}")
        self._cnt_skipped.setText(f"⏭️ {t('job.cnt_skipped', '건너뜀 (중복)')}: 0{t('common.items', '개')}")
        self._cnt_errors.setText(f"❌ {t('job.cnt_errors', '오류')}: 0{t('common.items', '개')}")
        self._log_console.clear()

    def update_progress(self, current: int, total: int, message: str, stats: Optional[dict] = None):
        pct = int(current / total * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._pct_badge.setText(f"{pct}% ({current:,} / {total:,})")
        self._status_label.setText(message)

        if stats:
            p = stats.get("processed", 0)
            s = stats.get("skipped", 0)
            e = stats.get("errors", 0)
            self._cnt_processed.setText(f"✅ {t('job.cnt_processed', '처리 완료')}: {p:,}{t('common.items', '개')}")
            self._cnt_skipped.setText(f"⏭️ {t('job.cnt_skipped', '건너뜀 (중복)')}: {s:,}{t('common.items', '개')}")
            self._cnt_errors.setText(f"❌ {t('job.cnt_errors', '오류')}: {e:,}{t('common.items', '개')}")

        self._log_console.appendPlainText(f"[{pct:3d}%] {message}")
        self._log_console.verticalScrollBar().setValue(
            self._log_console.verticalScrollBar().maximum()
        )


class DoneStep(QWidget):
    """STEP 3: 완료 요약."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 40, 32, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("🎉")
        icon.setStyleSheet("font-size: 64px;")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        self._title = QLabel(t("job.done_title", "처리 완료!"))
        title_font = QFont()
        title_font.setPointSize(Fonts.SIZE_TITLE)
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        self._summary = QLabel("")
        self._summary.setObjectName("SubLabel")
        self._summary.setAlignment(Qt.AlignCenter)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._last_result_data = None

    def retranslate_ui(self):
        self._title.setText(t("job.done_title", "처리 완료!"))
        if self._last_result_data:
            p, s, e, out = self._last_result_data
            self.set_result(p, s, e, out)

    def set_result(self, processed: int, skipped: int, errors: int, output_path: str):
        self._last_result_data = (processed, skipped, errors, output_path)
        self._summary.setText(
            f"{t('job.cnt_processed', '처리 완료')}: {processed:,}{t('common.items', '개')}   |   "
            f"{t('job.cnt_skipped', '건너뜀')}: {skipped:,}{t('common.items', '개')}   |   "
            f"{t('job.cnt_errors', '오류')}: {errors:,}{t('common.items', '개')}\n\n"
            f"{t('job.target_group', '출력 경로')}: {output_path}"
        )


# ── 메인 JobView ─────────────────────────────────────────────

class JobView(QWidget):
    """
    새 작업 뷰 (서브스텝 방식).
    
    Signals:
        job_completed: 처리 완료 시 방출
    """

    job_completed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread_pool = QThreadPool.globalInstance()
        self._scan_stats: dict = {}
        self._should_stop = False
        self._current_scan_worker: Optional[ScanWorker] = None

        self._setup_ui()
        self.retranslate_ui()
        i18n.language_changed.connect(lambda _: self.retranslate_ui())

    @property
    def is_busy(self) -> bool:
        """스캔 중이거나 정리 파이프라인 처리 중인지 여부"""
        return self._current_scan_worker is not None or self._sub_stack.currentIndex() == STEP_PROGRESS

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 헤더 (스텝 인디케이터 + 현재 단계 설명) ─────────
        header_card = QFrame()
        header_card.setObjectName("Card")
        header_card.setStyleSheet(
            f"QFrame#Card {{ border-radius: 0; border-left: none; border-right: none;"
            f"border-top: none; border-bottom: 1px solid {Colors.BORDER}; }}"
        )
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(20, 12, 20, 12)
        header_layout.setSpacing(8)

        self._step_indicator = StepIndicator()
        header_layout.addWidget(self._step_indicator)

        outer.addWidget(header_card)

        # ── 콘텐츠 스택 (서브스텝) ───────────────────────────
        self._sub_stack = QStackedWidget()
        # 각 서브스텝 뷰
        self._setup_step    = SetupStep()
        self._preview_step  = PreviewStep()
        self._progress_step = ProgressStep()
        self._done_step     = DoneStep()

        self._sub_stack.addWidget(self._setup_step)    # 0
        self._sub_stack.addWidget(self._preview_step)  # 1
        self._sub_stack.addWidget(self._progress_step) # 2
        self._sub_stack.addWidget(self._done_step)     # 3

        # 스캔 취소 버튼 연결
        self._setup_step.scan_cancel_btn.clicked.connect(self._cancel_scan)

        outer.addWidget(self._sub_stack, stretch=1)

        # ── 하단 버튼 바 ─────────────────────────────────────
        btn_bar = QFrame()
        btn_bar.setObjectName("Card")
        btn_bar.setStyleSheet(
            f"QFrame#Card {{ border-radius: 0; border-left: none; border-right: none;"
            f"border-bottom: none; border-top: 1px solid {Colors.BORDER}; }}"
        )
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(20, 10, 20, 10)
        btn_layout.setSpacing(12)

        self._back_btn = QPushButton()
        self._back_btn.setObjectName("SecondaryButton")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setFixedWidth(110)
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._on_back)

        btn_layout.addWidget(self._back_btn)
        btn_layout.addStretch()

        self._stop_btn = QPushButton()
        self._stop_btn.setObjectName("DangerButton")
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_layout.addWidget(self._stop_btn)

        self._next_btn = QPushButton()
        self._next_btn.setObjectName("PrimaryButton")
        self._next_btn.setCursor(Qt.PointingHandCursor)
        self._next_btn.setFixedWidth(140)
        self._next_btn.clicked.connect(self._on_next)
        btn_layout.addWidget(self._next_btn)

        outer.addWidget(btn_bar)

    def retranslate_ui(self):
        """언어 변경 시 JobView 및 모든 서브스텝 UI 재설정"""
        self._step_indicator.retranslate_ui()
        self._setup_step.retranslate_ui()
        self._preview_step.retranslate_ui()
        self._progress_step.retranslate_ui()
        self._done_step.retranslate_ui()

        self._back_btn.setText(f"← {t('common.prev', '이전')}")
        self._stop_btn.setText(t("common.cancel", "중단"))

        step = self._sub_stack.currentIndex()
        if step == STEP_SETUP:
            self._next_btn.setText(f"{t('job.btn_start_scan', '스캔 시작')}  ➔")
        elif step == STEP_PREVIEW:
            self._next_btn.setText(f"{t('job.btn_start_process', '처리 시작')}  ➔")
        elif step == STEP_DONE:
            self._next_btn.setText(t("dashboard.action_new_job", "새 작업 시작"))

    # ── 스텝 전환 ─────────────────────────────────────────────

    def _go_to_step(self, step: int):
        self._sub_stack.setCurrentIndex(step)
        self._step_indicator.set_step(step)
        self._back_btn.setEnabled(step > 0 and step < STEP_PROGRESS)
        self._stop_btn.setVisible(step == STEP_PROGRESS)

        # 버튼 텍스트 / 가시성 조정
        if step == STEP_SETUP:
            self._next_btn.setText(f"{t('job.btn_start_scan', '스캔 시작')}  ➔")
            self._next_btn.setVisible(True)
        elif step == STEP_PREVIEW:
            self._next_btn.setText(f"{t('job.btn_start_process', '처리 시작')}  ➔")
            self._next_btn.setVisible(True)
        elif step == STEP_PROGRESS:
            self._next_btn.setVisible(False)
        elif step == STEP_DONE:
            self._next_btn.setText(t("dashboard.action_new_job", "새 작업 시작"))
            self._next_btn.setVisible(True)
            self._back_btn.setEnabled(False)

    def _on_back(self):
        current = self._sub_stack.currentIndex()
        if current > STEP_SETUP:
            self._go_to_step(current - 1)

    def _on_next(self):
        current = self._sub_stack.currentIndex()
        if current == STEP_SETUP:
            self._start_scan()
        elif current == STEP_PREVIEW:
            self._start_process()
        elif current == STEP_DONE:
            self._reset()

    def _on_stop(self):
        self._should_stop = True

    def _reset(self):
        """새 작업을 위해 초기 상태로 리셋."""
        self._should_stop = False
        self._scan_stats = {}
        self._setup_step.show_scan_progress(False)
        self._progress_step.reset()
        self._go_to_step(STEP_SETUP)

    # ── 스캔 (ScanWorker) ─────────────────────────────────────

    def _start_scan(self):
        """입력값 검증 후 스캔 워커 실행 및 실시간 프로그레스 패널 활성화."""
        input_path  = self._setup_step.input_picker.path
        output_path = self._setup_step.output_picker.path

        if not input_path:
            self._show_error("입력 폴더를 선택해 주세요.")
            return
        if not output_path:
            self._show_error("출력 폴더를 선택해 주세요.")
            return
        if not Path(input_path).exists():
            self._show_error("입력 폴더가 존재하지 않습니다.")
            return

        self._next_btn.setEnabled(False)
        self._next_btn.setText("스캔 분석 중...")
        self._setup_step.show_scan_progress(True)

        self._current_scan_worker = ScanWorker(input_path, output_path)
        self._current_scan_worker.signals.progress.connect(self._on_scan_progress)
        self._current_scan_worker.signals.finished.connect(self._on_scan_done)
        self._current_scan_worker.signals.error.connect(self._on_scan_error)
        self._thread_pool.start(self._current_scan_worker)

    def _on_scan_progress(self, current: int, total: int, message: str):
        """스캔 워커로부터 전달받은 진행률 및 메시지를 프로그레스 카드에 실시간 반영."""
        self._setup_step.update_scan_progress(current, total, message)

    def _cancel_scan(self):
        """사용자가 스캔 취소 버튼을 클릭한 경우."""
        if self._current_scan_worker:
            self._current_scan_worker.cancel()
            self._current_scan_worker = None
        self._setup_step.show_scan_progress(False)
        self._next_btn.setEnabled(True)
        self._next_btn.setText("스캔 시작  →")

    def _on_scan_done(self, stats: dict):
        self._current_scan_worker = None
        self._setup_step.show_scan_progress(False)
        self._scan_stats = stats
        self._preview_step.update_stats(stats)
        self._next_btn.setEnabled(True)
        self._next_btn.setText("처리 시작  →")
        self._go_to_step(STEP_PREVIEW)

    def _on_scan_error(self, err_msg: str):
        self._current_scan_worker = None
        self._setup_step.show_scan_progress(False)
        self._next_btn.setEnabled(True)
        self._next_btn.setText("스캔 시작  →")
        self._show_error(f"스캔 중 오류가 발생했습니다: {err_msg}")

    # ── 처리 (ProcessWorker) ─────────────────────────────────

    def _start_process(self):
        """처리 워커 실행."""
        input_path  = self._setup_step.input_picker.path
        output_path = self._setup_step.output_picker.path
        strategy    = self._setup_step.folder_strategy
        mode        = self._setup_step.process_mode
        geo_lang    = self._setup_step.geo_language

        self._should_stop = False
        self._go_to_step(STEP_PROGRESS)
        self._progress_step.reset()

        worker = ProcessWorker(
            input_path  = input_path,
            output_path = output_path,
            strategy    = strategy,
            mode        = mode,
            should_stop_fn = lambda: self._should_stop,
            geo_language = geo_lang,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.stats_progress.connect(self._on_stats_progress)
        worker.signals.finished.connect(self._on_process_done)
        worker.signals.error.connect(self._on_error)
        self._thread_pool.start(worker)

    def _on_stats_progress(self, current: int, total: int, message: str, stats: dict):
        self._progress_step.update_progress(current, total, message, stats)

    def _on_progress(self, current: int, total: int, message: str):
        self._progress_step.update_progress(current, total, message)

    def _on_process_done(self, result: dict):
        self._done_step.set_result(
            processed   = result.get("processed", 0),
            skipped     = result.get("skipped", 0),
            errors      = result.get("errors", 0),
            output_path = self._setup_step.output_picker.path,
        )
        self._go_to_step(STEP_DONE)
        self.job_completed.emit()

    def _on_error(self, error_msg: str):
        self._next_btn.setEnabled(True)
        self._show_error(error_msg)

    @staticmethod
    def _show_error(message: str):
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("오류")
        msg.setText(message)
        msg.exec()
