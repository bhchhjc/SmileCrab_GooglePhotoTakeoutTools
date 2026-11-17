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
from PySide6.QtGui import QFont, QColor

from src.ui.theme import Colors, Fonts
from src.ui.workers import ScanWorker, ProcessWorker
from src.services.process_service import FolderStrategy, ProcessMode


# ── 서브스텝 인덱스 상수 ─────────────────────────────────────
STEP_SETUP    = 0
STEP_PREVIEW  = 1
STEP_PROGRESS = 2
STEP_DONE     = 3


class StepIndicator(QWidget):
    """
    상단 서브스텝 인디케이터 바.
    현재 단계를 시각적으로 표시 (동그라미 + 라벨 + 연결선).
    """

    STEPS = ["폴더 선택", "미리보기", "처리 중", "완료"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._circles: list[QLabel] = []
        self._labels: list[QLabel] = []

        for i, step in enumerate(self.STEPS):
            # 동그라미 번호
            circle = QLabel(str(i + 1))
            circle.setFixedSize(28, 28)
            circle.setAlignment(Qt.AlignCenter)
            self._circles.append(circle)
            layout.addWidget(circle)

            # 텍스트
            lbl = QLabel(step)
            lbl.setObjectName("SubLabel")
            self._labels.append(lbl)
            layout.addWidget(lbl)

            # 연결선 (마지막 항목 제외)
            if i < len(self.STEPS) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                layout.addWidget(line, stretch=1)

        self._update_style()

    def set_step(self, step: int):
        self._current = step
        self._update_style()

    def _update_style(self):
        for i, (circle, label) in enumerate(zip(self._circles, self._labels)):
            if i < self._current:
                # 완료된 스텝
                circle.setStyleSheet(
                    f"background-color: {Colors.SUCCESS}; color: white;"
                    f"border-radius: 14px; font-weight: bold;"
                )
                label.setStyleSheet(f"color: {Colors.SUCCESS}; font-weight: bold;")
            elif i == self._current:
                # 현재 스텝
                circle.setStyleSheet(
                    f"background-color: {Colors.ACCENT}; color: white;"
                    f"border-radius: 14px; font-weight: bold;"
                )
                label.setStyleSheet(f"color: {Colors.ACCENT}; font-weight: bold;")
            else:
                # 미래 스텝
                circle.setStyleSheet(
                    f"background-color: {Colors.BORDER}; color: {Colors.TEXT_SECONDARY};"
                    f"border-radius: 14px;"
                )
                label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")


class FolderPicker(QWidget):
    """폴더 선택 위젯 (경로 표시 + 찾아보기 버튼)."""

    def __init__(self, label: str, placeholder: str = "폴더를 선택하세요...", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(label)
        font = QFont()
        font.setBold(True)
        lbl.setFont(font)
        layout.addWidget(lbl)

        row = QHBoxLayout()
        self._path_label = QLabel(placeholder)
        self._path_label.setObjectName("SubLabel")
        self._path_label.setWordWrap(True)
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self._path_label, stretch=1)

        browse_btn = QPushButton("폴더 선택")
        browse_btn.setObjectName("SecondaryButton")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(browse_btn)

        layout.addLayout(row)

        self._path: str = ""

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if path:
            self._path = path
            self._path_label.setText(path)
            self._path_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")

    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str):
        self._path = path
        self._path_label.setText(path)


class SetupStep(QWidget):
    """STEP 0: 폴더 선택 + 옵션 설정."""

    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        # 입력 폴더
        input_card = QFrame()
        input_card.setObjectName("Card")
        input_layout = QVBoxLayout(input_card)
        input_layout.setSpacing(12)

        input_title = QLabel("📂 입력 폴더 (Google Takeout 압축 해제 경로)")
        input_title.setObjectName("SectionTitle")
        input_layout.addWidget(input_title)

        self.input_picker = FolderPicker(
            "Takeout 폴더",
            "Google Takeout 압축 해제 폴더를 선택하세요."
        )
        input_layout.addWidget(self.input_picker)
        layout.addWidget(input_card)

        # 출력 폴더
        output_card = QFrame()
        output_card.setObjectName("Card")
        output_layout = QVBoxLayout(output_card)
        output_layout.setSpacing(12)

        output_title = QLabel("📁 출력 폴더 (정리된 사진을 저장할 경로)")
        output_title.setObjectName("SectionTitle")
        output_layout.addWidget(output_title)

        self.output_picker = FolderPicker(
            "출력 폴더",
            "사진이 정리될 출력 폴더를 선택하세요."
        )
        output_layout.addWidget(self.output_picker)
        layout.addWidget(output_card)

        # 옵션
        options_card = QFrame()
        options_card.setObjectName("Card")
        options_layout = QVBoxLayout(options_card)
        options_layout.setSpacing(16)

        options_title = QLabel("⚙ 처리 옵션")
        options_title.setObjectName("SectionTitle")
        options_layout.addWidget(options_title)

        grid = QGridLayout()
        grid.setSpacing(12)

        # 폴더 구조
        grid.addWidget(QLabel("폴더 구조"), 0, 0)
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems([
            "YYYY/MM  (연도/월)",
            "YYYY     (연도만)",
            "앨범명    (원본 앨범 구조 유지)",
        ])
        grid.addWidget(self.strategy_combo, 0, 1)

        # 처리 모드
        grid.addWidget(QLabel("처리 방식"), 1, 0)
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(16)
        self.mode_group = QButtonGroup(self)
        self.radio_copy = QRadioButton("복사 (원본 보존)")
        self.radio_move = QRadioButton("이동 (원본 삭제)")
        self.radio_copy.setChecked(True)
        self.mode_group.addButton(self.radio_copy, 0)
        self.mode_group.addButton(self.radio_move, 1)
        mode_layout.addWidget(self.radio_copy)
        mode_layout.addWidget(self.radio_move)
        mode_layout.addStretch()
        grid.addWidget(mode_widget, 1, 1)

        options_layout.addLayout(grid)
        layout.addWidget(options_card)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        scroll.setWidget(content)

    @property
    def folder_strategy(self) -> FolderStrategy:
        idx = self.strategy_combo.currentIndex()
        return [FolderStrategy.YEAR_MONTH, FolderStrategy.YEAR_ONLY, FolderStrategy.ALBUM][idx]

    @property
    def process_mode(self) -> ProcessMode:
        return ProcessMode.COPY if self.radio_copy.isChecked() else ProcessMode.MOVE


class PreviewStep(QWidget):
    """STEP 1: 스캔 결과 미리보기."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        title = QLabel("🔍 스캔 결과 미리보기")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        # 통계 그리드
        stats_card = QFrame()
        stats_card.setObjectName("Card")
        stats_layout = QGridLayout(stats_card)
        stats_layout.setSpacing(16)

        self._stat_labels: dict[str, QLabel] = {}
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

            cell = QFrame()
            cell_layout = QVBoxLayout(cell)
            cell_layout.addWidget(lbl)
            cell_layout.addWidget(val)
            stats_layout.addWidget(cell, row, col)

        layout.addWidget(stats_card)

        # 메시지
        self._msg_label = QLabel("위 버튼을 눌러 먼저 폴더를 스캔하세요.")
        self._msg_label.setObjectName("SubLabel")
        self._msg_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._msg_label)
        layout.addStretch()

    def update_stats(self, stats: dict):
        """스캔 결과로 통계 갱신."""
        for key, val_label in self._stat_labels.items():
            val = stats.get(key, 0)
            val_label.setText(f"{val:,}")
        self._msg_label.setText("✅ 스캔 완료! 아래 '처리 시작' 버튼을 누르세요.")


class ProgressStep(QWidget):
    """STEP 2: 실시간 진행 상황."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        # 진행 상태 메시지
        self._status_label = QLabel("처리 준비 중...")
        self._status_label.setObjectName("SectionTitle")
        layout.addWidget(self._status_label)

        # 프로그레스바
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(14)
        layout.addWidget(self._progress_bar)

        self._pct_label = QLabel("0 %")
        self._pct_label.setObjectName("SubLabel")
        self._pct_label.setAlignment(Qt.AlignRight)
        layout.addWidget(self._pct_label)

        # 로그 콘솔
        log_title = QLabel("처리 로그")
        log_title.setObjectName("SectionTitle")
        layout.addWidget(log_title)

        self._log_console = QPlainTextEdit()
        self._log_console.setObjectName("LogConsole")
        self._log_console.setReadOnly(True)
        layout.addWidget(self._log_console, stretch=1)

    def reset(self):
        self._progress_bar.setValue(0)
        self._pct_label.setText("0 %")
        self._status_label.setText("처리 준비 중...")
        self._log_console.clear()

    def update_progress(self, current: int, total: int, message: str):
        pct = int(current / total * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._pct_label.setText(f"{current:,} / {total:,}  ({pct} %)")
        self._status_label.setText(message)
        self._log_console.appendPlainText(f"[{pct:3d}%] {message}")
        # 최신 로그로 스크롤
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

        self._title = QLabel("처리 완료!")
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

    def set_result(self, processed: int, skipped: int, errors: int, output_path: str):
        self._summary.setText(
            f"처리 완료: {processed:,}개   |   건너뜀: {skipped:,}개   |   오류: {errors:,}개\n\n"
            f"출력 경로: {output_path}"
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

        self._setup_ui()

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
        header_layout.setContentsMargins(32, 16, 32, 16)
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

        outer.addWidget(self._sub_stack, stretch=1)

        # ── 하단 버튼 바 ─────────────────────────────────────
        btn_bar = QFrame()
        btn_bar.setObjectName("Card")
        btn_bar.setStyleSheet(
            f"QFrame#Card {{ border-radius: 0; border-left: none; border-right: none;"
            f"border-bottom: none; border-top: 1px solid {Colors.BORDER}; }}"
        )
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(32, 12, 32, 12)
        btn_layout.setSpacing(12)

        self._back_btn = QPushButton("← 이전")
        self._back_btn.setObjectName("SecondaryButton")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setFixedWidth(110)
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._on_back)

        btn_layout.addWidget(self._back_btn)
        btn_layout.addStretch()

        self._stop_btn = QPushButton("중단")
        self._stop_btn.setObjectName("DangerButton")
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._on_stop)
        btn_layout.addWidget(self._stop_btn)

        self._next_btn = QPushButton("스캔 시작  →")
        self._next_btn.setObjectName("PrimaryButton")
        self._next_btn.setCursor(Qt.PointingHandCursor)
        self._next_btn.setFixedWidth(140)
        self._next_btn.clicked.connect(self._on_next)
        btn_layout.addWidget(self._next_btn)

        outer.addWidget(btn_bar)

    # ── 스텝 전환 ─────────────────────────────────────────────

    def _go_to_step(self, step: int):
        self._sub_stack.setCurrentIndex(step)
        self._step_indicator.set_step(step)
        self._back_btn.setEnabled(step > 0 and step < STEP_PROGRESS)
        self._stop_btn.setVisible(step == STEP_PROGRESS)

        # 버튼 텍스트 / 가시성 조정
        if step == STEP_SETUP:
            self._next_btn.setText("스캔 시작  →")
            self._next_btn.setVisible(True)
        elif step == STEP_PREVIEW:
            self._next_btn.setText("처리 시작  →")
            self._next_btn.setVisible(True)
        elif step == STEP_PROGRESS:
            self._next_btn.setVisible(False)
        elif step == STEP_DONE:
            self._next_btn.setText("새 작업 시작")
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
        self._progress_step.reset()
        self._go_to_step(STEP_SETUP)

    # ── 스캔 (ScanWorker) ─────────────────────────────────────

    def _start_scan(self):
        """입력값 검증 후 스캔 워커 실행."""
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
        self._next_btn.setText("스캔 중...")

        worker = ScanWorker(input_path, output_path)
        worker.signals.finished.connect(self._on_scan_done)
        worker.signals.error.connect(self._on_error)
        self._thread_pool.start(worker)

    def _on_scan_done(self, stats: dict):
        self._scan_stats = stats
        self._preview_step.update_stats(stats)
        self._next_btn.setEnabled(True)
        self._go_to_step(STEP_PREVIEW)

    # ── 처리 (ProcessWorker) ─────────────────────────────────

    def _start_process(self):
        """처리 워커 실행."""
        input_path  = self._setup_step.input_picker.path
        output_path = self._setup_step.output_picker.path
        strategy    = self._setup_step.folder_strategy
        mode        = self._setup_step.process_mode

        self._should_stop = False
        self._go_to_step(STEP_PROGRESS)
        self._progress_step.reset()

        worker = ProcessWorker(
            input_path  = input_path,
            output_path = output_path,
            strategy    = strategy,
            mode        = mode,
            should_stop_fn = lambda: self._should_stop,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_process_done)
        worker.signals.error.connect(self._on_error)
        self._thread_pool.start(worker)

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
