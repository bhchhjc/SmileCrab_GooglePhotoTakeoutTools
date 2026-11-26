"""
components/media_edit_dialog.py
────────────────────────────────────────────────────────────────
개별 미디어 메타데이터 통합 편집 다이얼로그 (One UI 9.5 스타일)

지원 편집 항목:
  1. 촬영 일시 (커스텀 One UI QCalendarWidget DatePicker + 카드형 TimePicker)
  2. GPS 위치 (위도/경도/고도 + 실시간 GeoResolver 역지오코딩 미리보기)
  3. 설명/캡션 및 촬영 기기 (제조사/모델명)

원본 복원:
  - DB original_snapshot 스냅샷 기반 원본 메타데이터 + 파일 EXIF/OS 시간 일괄 복원
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.core.i18n import t
from src.data.database import DatabaseManager
from src.services.metadata_edit_service import (
    EditMetadataRequest,
    MetadataEditService,
    parse_taken_at,
)
from src.ui.theme import Colors


class ZeroPadSpinBox(QSpinBox):
    """2자리 0패딩(00~59) 표시용 커스텀 스핀박스"""

    def textFromValue(self, value: int) -> str:
        return f"{value:02d}"


class MediaEditDialog(QDialog):
    """개별 미디어 메타데이터 통합 편집 다이얼로그 (One UI 9.5)"""

    def __init__(
        self,
        media_item: Dict[str, Any],
        db_manager: Optional[DatabaseManager] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._media_item = dict(media_item)
        self._db = db_manager or DatabaseManager()
        self._service = MetadataEditService(self._db)
        self._updated_item: Optional[Dict[str, Any]] = None

        self._setup_window()
        self._setup_ui()
        self._load_item_values(self._media_item)

    @property
    def updated_item(self) -> Optional[Dict[str, Any]]:
        """저장 또는 초기화 완료 후 갱신된 미디어 데이터 반환"""
        return self._updated_item

    def _setup_window(self):
        self.setWindowTitle(t("dialog.edit_meta.window_title", "미디어 메타데이터 수정"))
        self.setModal(True)
        self.resize(580, 670)
        self.setMinimumSize(520, 600)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Colors.BG_APP};
            }}
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        # ── 1. 상단 파일 요약 카드 ───────────────────────────────
        header_card = QFrame()
        header_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 14px;
            }}
        """)
        hc_layout = QVBoxLayout(header_card)
        hc_layout.setContentsMargins(14, 12, 14, 12)
        hc_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._lbl_filename = QLabel()
        self._lbl_filename.setStyleSheet(
            f"font-size: 14px; font-weight: 800; color: {Colors.TEXT_PRIMARY}; border: none;"
        )
        top_row.addWidget(self._lbl_filename, stretch=1)

        self._edited_badge = QLabel(t("dialog.edit_meta.badge_edited", "✏️ 사용자 수정됨"))
        self._edited_badge.setStyleSheet(f"""
            background-color: {Colors.ACCENT_LIGHT};
            color: {Colors.ACCENT};
            border: 1px solid #B8D6FB;
            border-radius: 10px;
            padding: 2px 10px;
            font-size: 11px;
            font-weight: bold;
        """)
        self._edited_badge.setVisible(False)
        top_row.addWidget(self._edited_badge)
        hc_layout.addLayout(top_row)

        self._lbl_preview_dt = QLabel()
        self._lbl_preview_dt.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {Colors.ACCENT}; border: none;"
        )
        hc_layout.addWidget(self._lbl_preview_dt)

        self._lbl_path = QLabel()
        self._lbl_path.setStyleSheet(
            f"font-size: 11px; color: {Colors.TEXT_SECONDARY}; border: none;"
        )
        self._lbl_path.setWordWrap(True)
        hc_layout.addWidget(self._lbl_path)

        main_layout.addWidget(header_card)

        # ── 2. One UI 9.5 통합 편집 탭 위젯 ────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 14px;
                padding: 12px;
                margin-top: 6px;
            }}
            QTabBar::tab {{
                background-color: #E9ECEF;
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-radius: 10px;
                padding: 7px 16px;
                margin-right: 6px;
                font-size: 12px;
                font-weight: 600;
            }}
            QTabBar::tab:hover {{
                background-color: #DEE2E6;
                color: {Colors.TEXT_PRIMARY};
            }}
            QTabBar::tab:selected {{
                background-color: {Colors.ACCENT};
                color: #FFFFFF;
                font-weight: bold;
            }}
        """)

        self._tabs.addTab(self._create_datetime_tab(), f"📅 {t('dialog.edit_meta.tab_datetime', '촬영 일시')}")
        self._tabs.addTab(self._create_gps_tab(), f"📍 {t('dialog.edit_meta.tab_gps', 'GPS 위치')}")
        self._tabs.addTab(self._create_details_tab(), f"📝 {t('dialog.edit_meta.tab_details', '설명 / 기기')}")
        main_layout.addWidget(self._tabs, stretch=1)

        # ── 3. 하단 액션 바 ─────────────────────────────────────
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self._reset_btn = QPushButton(f"↺ {t('dialog.edit_meta.btn_reset_original', '원본으로 초기화')}")
        self._reset_btn.setObjectName("SecondaryButton")
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        btn_bar.addWidget(self._reset_btn)

        btn_bar.addStretch()

        self._cancel_btn = QPushButton(t("common.cancel", "취소"))
        self._cancel_btn.setObjectName("SecondaryButton")
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.setFixedWidth(84)
        self._cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(self._cancel_btn)

        self._save_btn = QPushButton(f"💾 {t('dialog.edit_meta.btn_save', '저장 및 적용')}")
        self._save_btn.setObjectName("PrimaryButton")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setFixedWidth(130)
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_bar.addWidget(self._save_btn)

        main_layout.addLayout(btn_bar)

    # ─────────────────────────────────────────────────────────────
    # 탭 1: 촬영 일시 (One UI DatePicker + TimePicker)
    # ─────────────────────────────────────────────────────────────
    def _create_datetime_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # 1) 커스텀 One UI 스타일 인라인 캘린더
        self._calendar = QCalendarWidget()
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self._calendar.setGridVisible(False)
        self._calendar.setMinimumHeight(250)
        self._calendar.setStyleSheet(f"""
            QCalendarWidget QWidget {{
                background-color: {Colors.BG_CARD};
                alternate-background-color: #FAFBFD;
            }}
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background-color: {Colors.BG_CARD};
                border-bottom: 1px solid {Colors.DIVIDER};
                padding: 4px 8px;
            }}
            QCalendarWidget QToolButton {{
                color: {Colors.TEXT_PRIMARY};
                background-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 13px;
                font-weight: 700;
            }}
            QCalendarWidget QToolButton:hover {{
                background-color: {Colors.ACCENT_LIGHT};
                color: {Colors.ACCENT};
            }}
            QCalendarWidget QMenu {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
            }}
            QCalendarWidget QSpinBox {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 2px 6px;
                font-weight: bold;
            }}
            QCalendarWidget QAbstractItemView:enabled {{
                color: {Colors.TEXT_PRIMARY};
                background-color: {Colors.BG_CARD};
                selection-background-color: {Colors.ACCENT};
                selection-color: #FFFFFF;
                border-radius: 8px;
                outline: 0;
                font-size: 12px;
                font-weight: 600;
            }}
            QCalendarWidget QAbstractItemView:disabled {{
                color: #ADB5BD;
            }}
        """)

        # 토요일(파랑) / 일요일(빨강) 요일 색상 지정
        sat_fmt = QTextCharFormat()
        sat_fmt.setForeground(QColor(Colors.ACCENT))
        sun_fmt = QTextCharFormat()
        sun_fmt.setForeground(QColor(Colors.ERROR))
        self._calendar.setWeekdayTextFormat(Qt.Saturday, sat_fmt)
        self._calendar.setWeekdayTextFormat(Qt.Sunday, sun_fmt)
        self._calendar.selectionChanged.connect(self._update_datetime_preview)

        cal_frame = QFrame()
        cal_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 12px;
                padding: 4px;
            }}
        """)
        cal_box = QVBoxLayout(cal_frame)
        cal_box.setContentsMargins(4, 4, 4, 4)
        cal_box.addWidget(self._calendar)
        layout.addWidget(cal_frame)

        # 2) 카드형 TimePicker (시 / 분 / 초)
        time_card = QFrame()
        time_card.setStyleSheet(f"""
            QFrame {{
                background-color: #F8F9FA;
                border: 1px solid {Colors.BORDER};
                border-radius: 12px;
            }}
        """)
        tc_layout = QVBoxLayout(time_card)
        tc_layout.setContentsMargins(14, 10, 14, 10)
        tc_layout.setSpacing(8)

        time_hdr = QLabel(f"⏰ {t('dialog.edit_meta.label_time', '촬영 시각 (시 : 분 : 초)')}")
        time_hdr.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Colors.TEXT_PRIMARY}; border: none;")
        tc_layout.addWidget(time_hdr)

        spin_row = QHBoxLayout()
        spin_row.setSpacing(8)

        _spin_style = f"""
            QSpinBox {{
                background-color: #FFFFFF;
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
                padding: 6px 8px;
                font-size: 16px;
                font-weight: 800;
                color: {Colors.TEXT_PRIMARY};
                min-height: 32px;
            }}
            QSpinBox:focus {{
                border-color: {Colors.ACCENT};
            }}
        """

        self._hour_spin = ZeroPadSpinBox()
        self._hour_spin.setRange(0, 23)
        self._hour_spin.setWrapping(True)
        self._hour_spin.setAlignment(Qt.AlignCenter)
        self._hour_spin.setStyleSheet(_spin_style)
        self._hour_spin.valueChanged.connect(self._update_datetime_preview)

        self._min_spin = ZeroPadSpinBox()
        self._min_spin.setRange(0, 59)
        self._min_spin.setWrapping(True)
        self._min_spin.setAlignment(Qt.AlignCenter)
        self._min_spin.setStyleSheet(_spin_style)
        self._min_spin.valueChanged.connect(self._update_datetime_preview)

        self._sec_spin = ZeroPadSpinBox()
        self._sec_spin.setRange(0, 59)
        self._sec_spin.setWrapping(True)
        self._sec_spin.setAlignment(Qt.AlignCenter)
        self._sec_spin.setStyleSheet(_spin_style)
        self._sec_spin.valueChanged.connect(self._update_datetime_preview)

        colon1 = QLabel(":")
        colon1.setStyleSheet("font-size: 18px; font-weight: bold; color: #495057; border: none;")
        colon2 = QLabel(":")
        colon2.setStyleSheet("font-size: 18px; font-weight: bold; color: #495057; border: none;")

        spin_row.addWidget(self._hour_spin, stretch=1)
        spin_row.addWidget(colon1)
        spin_row.addWidget(self._min_spin, stretch=1)
        spin_row.addWidget(colon2)
        spin_row.addWidget(self._sec_spin, stretch=1)
        tc_layout.addLayout(spin_row)

        # 빠른 시각 프리셋 칩
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        _chip_style = f"""
            QPushButton {{
                background-color: #FFFFFF;
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_LIGHT};
                color: {Colors.ACCENT};
                border-color: {Colors.ACCENT};
            }}
        """
        for label, h, m, s in [("00:00:00", 0, 0, 0), ("12:00:00", 12, 0, 0), ("18:00:00", 18, 0, 0)]:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_chip_style)
            btn.clicked.connect(lambda _=False, hh=h, mm=m, ss=s: self._set_time_values(hh, mm, ss))
            preset_row.addWidget(btn)

        now_btn = QPushButton(t("dialog.edit_meta.btn_now", "현재 날짜/시각"))
        now_btn.setCursor(Qt.PointingHandCursor)
        now_btn.setStyleSheet(_chip_style)
        now_btn.clicked.connect(self._set_now_datetime)
        preset_row.addWidget(now_btn)
        preset_row.addStretch()

        tc_layout.addLayout(preset_row)
        layout.addWidget(time_card)
        return w

    # ─────────────────────────────────────────────────────────────
    # 탭 2: GPS 위치 정보
    # ─────────────────────────────────────────────────────────────
    def _create_gps_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        desc = QLabel(
            t(
                "dialog.edit_meta.gps_desc",
                "위도와 경도를 입력하면 오프라인 도시 색인을 통해 국가/주·도/도시가 자동으로 계산됩니다.",
            )
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(desc)

        form_card = QFrame()
        form_card.setStyleSheet(f"""
            QFrame {{
                background-color: #F8F9FA;
                border: 1px solid {Colors.BORDER};
                border-radius: 12px;
            }}
        """)
        form = QFormLayout(form_card)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        _dbl_style = f"""
            QDoubleSpinBox {{
                background-color: #FFFFFF;
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 13px;
                font-weight: 600;
                min-height: 26px;
            }}
            QDoubleSpinBox:focus {{
                border-color: {Colors.ACCENT};
            }}
        """

        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90.0, 90.0)
        self._lat_spin.setDecimals(6)
        self._lat_spin.setSingleStep(0.001)
        self._lat_spin.setStyleSheet(_dbl_style)
        self._lat_spin.valueChanged.connect(self._update_geo_preview)

        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180.0, 180.0)
        self._lon_spin.setDecimals(6)
        self._lon_spin.setSingleStep(0.001)
        self._lon_spin.setStyleSheet(_dbl_style)
        self._lon_spin.valueChanged.connect(self._update_geo_preview)

        self._alt_spin = QDoubleSpinBox()
        self._alt_spin.setRange(-1000.0, 10000.0)
        self._alt_spin.setDecimals(1)
        self._alt_spin.setSuffix(" m")
        self._alt_spin.setStyleSheet(_dbl_style)

        form.addRow(QLabel(f"🧭 {t('dialog.edit_meta.label_lat', '위도 (Latitude)')}"), self._lat_spin)
        form.addRow(QLabel(f"🧭 {t('dialog.edit_meta.label_lon', '경도 (Longitude)')}"), self._lon_spin)
        form.addRow(QLabel(f"⛰️ {t('dialog.edit_meta.label_alt', '고도 (Altitude)')}"), self._alt_spin)

        layout.addWidget(form_card)

        # 실시간 역지오코딩 미리보기 카드
        geo_preview_card = QFrame()
        geo_preview_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.ACCENT_LIGHT};
                border: 1px solid #B8D6FB;
                border-radius: 12px;
            }}
        """)
        gp_layout = QVBoxLayout(geo_preview_card)
        gp_layout.setContentsMargins(14, 10, 14, 10)
        gp_layout.setSpacing(4)

        gp_title = QLabel(f"🌍 {t('dialog.edit_meta.geo_preview_title', '역지오코딩 예상 위치')}")
        gp_title.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {Colors.ACCENT}; border: none;")
        self._lbl_geo_preview = QLabel("-")
        self._lbl_geo_preview.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {Colors.TEXT_PRIMARY}; border: none;"
        )
        self._lbl_geo_preview.setWordWrap(True)
        gp_layout.addWidget(gp_title)
        gp_layout.addWidget(self._lbl_geo_preview)
        layout.addWidget(geo_preview_card)

        clear_row = QHBoxLayout()
        clear_gps_btn = QPushButton(f"🗑 {t('dialog.edit_meta.btn_clear_gps', '위치 정보 지우기 (0.0, 0.0)')}")
        clear_gps_btn.setObjectName("SecondaryButton")
        clear_gps_btn.setCursor(Qt.PointingHandCursor)
        clear_gps_btn.clicked.connect(self._clear_gps_values)
        clear_row.addWidget(clear_gps_btn)
        clear_row.addStretch()
        layout.addLayout(clear_row)

        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────
    # 탭 3: 설명/캡션 및 촬영 기기
    # ─────────────────────────────────────────────────────────────
    def _create_details_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        lbl_desc = QLabel(f"💬 {t('dialog.edit_meta.label_description', '설명 / 캡션')}")
        lbl_desc.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(lbl_desc)

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText(
            t("dialog.edit_meta.desc_placeholder", "사진에 대한 설명이나 메모를 입력하세요...")
        )
        self._desc_edit.setFixedHeight(120)
        layout.addWidget(self._desc_edit)

        cam_card = QFrame()
        cam_card.setStyleSheet(f"""
            QFrame {{
                background-color: #F8F9FA;
                border: 1px solid {Colors.BORDER};
                border-radius: 12px;
            }}
        """)
        cam_form = QFormLayout(cam_card)
        cam_form.setContentsMargins(14, 14, 14, 14)
        cam_form.setSpacing(10)

        self._make_edit = QLineEdit()
        self._make_edit.setPlaceholderText("예: Samsung, Apple, Sony")
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("예: SM-S908N, iPhone 15 Pro")

        cam_form.addRow(QLabel(f"🏭 {t('dialog.edit_meta.label_make', '제조사 (Make)')}"), self._make_edit)
        cam_form.addRow(QLabel(f"📷 {t('dialog.edit_meta.label_model', '모델명 (Model)')}"), self._model_edit)
        layout.addWidget(cam_card)

        note_lbl = QLabel(
            t(
                "dialog.edit_meta.jpeg_note",
                "※ JPEG(.jpg/.jpeg) 파일은 EXIF 태그와 OS 파일 날짜가 함께 갱신되며, 그 외 포맷은 DB 및 OS 파일 날짜가 갱신됩니다.",
            )
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(note_lbl)

        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────
    # 데이터 바인딩 & 이벤트 핸들러
    # ─────────────────────────────────────────────────────────────
    def _load_item_values(self, item: Dict[str, Any]):
        fname = item.get("file_name") or Path(item.get("file_path") or "-").name
        mtype = item.get("media_type")
        icon = "📷" if mtype == "photo" else "🎬"
        self._lbl_filename.setText(f"{icon} {fname}")
        self._lbl_path.setText(item.get("file_path") or "-")

        is_edited = bool(item.get("is_user_edited"))
        has_snapshot = bool(item.get("original_snapshot"))
        self._edited_badge.setVisible(is_edited)

        if has_snapshot and is_edited:
            self._reset_btn.setText(f"↺ {t('dialog.edit_meta.btn_reset_original', '원본으로 초기화')}")
            self._reset_btn.setToolTip(
                t("dialog.edit_meta.tip_reset_original", "수정 전 원본 메타데이터 스냅샷으로 되돌립니다.")
            )
        else:
            self._reset_btn.setText(f"↺ {t('dialog.edit_meta.btn_reset_form', '입력 되돌리기')}")
            self._reset_btn.setToolTip(
                t("dialog.edit_meta.tip_reset_form", "현재 입력 중인 값을 처음 상태로 되돌립니다.")
            )

        dt = parse_taken_at(item.get("taken_at")) or datetime.now().replace(microsecond=0)
        self._calendar.setSelectedDate(QDate(dt.year, dt.month, dt.day))
        self._set_time_values(dt.hour, dt.minute, dt.second)

        self._lat_spin.setValue(float(item.get("latitude") or 0.0))
        self._lon_spin.setValue(float(item.get("longitude") or 0.0))
        self._alt_spin.setValue(float(item.get("altitude") or 0.0))
        self._update_geo_preview()

        self._desc_edit.setPlainText(item.get("description") or "")
        self._make_edit.setText(item.get("camera_make") or "")
        self._model_edit.setText(item.get("camera_model") or "")
        self._update_datetime_preview()

    def _set_time_values(self, hour: int, minute: int, second: int):
        self._hour_spin.setValue(hour)
        self._min_spin.setValue(minute)
        self._sec_spin.setValue(second)
        self._update_datetime_preview()

    def _set_now_datetime(self):
        now = datetime.now().replace(microsecond=0)
        self._calendar.setSelectedDate(QDate(now.year, now.month, now.day))
        self._set_time_values(now.hour, now.minute, now.second)

    def _current_selected_datetime(self) -> datetime:
        qd = self._calendar.selectedDate()
        return datetime(
            qd.year(),
            qd.month(),
            qd.day(),
            self._hour_spin.value(),
            self._min_spin.value(),
            self._sec_spin.value(),
        )

    def _update_datetime_preview(self):
        dt = self._current_selected_datetime()
        self._lbl_preview_dt.setText(
            f"📅 {t('dialog.edit_meta.preview_taken_at', '적용 예정 촬영 일시')}: {dt.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _update_geo_preview(self):
        lat = self._lat_spin.value()
        lon = self._lon_spin.value()
        if lat == 0.0 and lon == 0.0:
            self._lbl_geo_preview.setText(t("dialog.edit_meta.geo_empty", "위치 정보 없음 (0.0000, 0.0000)"))
            return
        info = GeoResolver().resolve(lat, lon, GeoLanguage.KOREAN)
        parts = [p for p in (info.country_name, info.state_name, info.city_name) if p]
        self._lbl_geo_preview.setText(" > ".join(parts) if parts else f"[{lat:.4f}, {lon:.4f}]")

    def _clear_gps_values(self):
        self._lat_spin.setValue(0.0)
        self._lon_spin.setValue(0.0)
        self._alt_spin.setValue(0.0)
        self._update_geo_preview()

    def _on_save_clicked(self):
        req = EditMetadataRequest(
            taken_at=self._current_selected_datetime(),
            latitude=self._lat_spin.value(),
            longitude=self._lon_spin.value(),
            altitude=self._alt_spin.value(),
            description=self._desc_edit.toPlainText(),
            camera_make=self._make_edit.text(),
            camera_model=self._model_edit.text(),
        )
        result = self._service.apply_edit(self._media_item, req, GeoLanguage.KOREAN)
        if not result.success or not result.updated_item:
            QMessageBox.warning(
                self,
                t("common.error", "오류"),
                result.message or t("dialog.edit_meta.save_failed", "메타데이터 저장에 실패했습니다."),
            )
            return

        self._updated_item = result.updated_item
        self.accept()

    def _on_reset_clicked(self):
        is_edited = bool(self._media_item.get("is_user_edited"))
        has_snapshot = bool(self._media_item.get("original_snapshot"))
        if not (is_edited and has_snapshot):
            self._load_item_values(self._media_item)
            return

        ans = QMessageBox.question(
            self,
            t("dialog.edit_meta.reset_confirm_title", "원본 메타데이터로 초기화"),
            t(
                "dialog.edit_meta.reset_confirm_msg",
                "사용자가 수정한 내용을 모두 취소하고 최초 원본 스냅샷으로 되돌리시겠습니까?",
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return

        result = self._service.restore_original(self._media_item)
        if not result.success or not result.updated_item:
            QMessageBox.warning(
                self,
                t("common.error", "오류"),
                result.message or t("dialog.edit_meta.reset_failed", "원본 복원에 실패했습니다."),
            )
            return

        self._updated_item = result.updated_item
        self.accept()
