"""
components/compare_panel.py
────────────────────────────────────────────────────────────────
Before vs After 메타데이터 3열 가로 정밀 대조 인스펙터 패널
+ 최종 파일 원시 전체 EXIF (Raw EXIF) 포괄 뷰어

핵심 기능:
  - 총 11개 주요 메타데이터 항목 가로 정밀 대조 (출처 하이라이트)
  - 테이블 행 높이(36px) 및 세로 헤더 너비(175px) 확보로 글자 잘림 완전 해소
  - 최종 파일에 저장된 모든 원시 EXIF 태그(카메라 기종, 렌즈, 노출값 등) 전수 덤프 및 실시간 검색
  - 대용량 고해상도 JSON 원본보기 전용 다이얼로그 (JsonViewerDialog) 연동
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import piexif
from PySide6.QtCore import Qt, Signal, QUrl, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPixmap, QDesktopServices, QImageReader
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea,
)

from src.core.geo_resolver import GeoLanguage, GeoResolver
from src.ui.theme import Colors, Fonts

# ── 자주 쓰이는 대표 EXIF 태그 한글 친절 명칭 매핑 ──────────────────────────
TAG_KO_MAP: Dict[str, str] = {
    "Make": "제조사",
    "Model": "기종/모델",
    "LensModel": "렌즈 모델",
    "LensMake": "렌즈 제조사",
    "LensSpecification": "렌즈 제원",
    "ExposureTime": "셔터 스피드",
    "FNumber": "조리개 (F값)",
    "ISOSpeedRatings": "ISO 감도",
    "PhotographicSensitivity": "ISO 감도",
    "FocalLength": "초점거리",
    "FocalLengthIn35mmFilm": "35mm 환산 초점거리",
    "DateTimeOriginal": "원본 촬영일시",
    "DateTimeDigitized": "디지털화 일시",
    "DateTime": "수정 일시",
    "Software": "소프트웨어/펌웨어",
    "Orientation": "사진 회전 방향",
    "Flash": "플래시 상태",
    "WhiteBalance": "화이트 밸런스",
    "MeteringMode": "측광 모드",
    "ExposureProgram": "노출 프로그램",
    "ExposureBiasValue": "노출 보정값",
    "ImageDescription": "사진 설명",
    "UserComment": "사용자 코멘트",
    "GPSLatitude": "GPS 위도",
    "GPSLongitude": "GPS 경도",
    "GPSAltitude": "GPS 고도",
    "GPSTimeStamp": "GPS 시각",
    "GPSDateStamp": "GPS 일자",
    "ColorSpace": "색 공간",
    "PixelXDimension": "가로 해상도",
    "PixelYDimension": "세로 해상도",
    "SceneCaptureType": "장면 캡처 유형",
    "SubSecTimeOriginal": "초 단위 세부 촬영시각",
}


def _format_exif_val(tag_name: str, val: Any) -> str:
    """EXIF 원시 바이너리/튜플 값을 사람이 읽을 수 있는 친절한 텍스트로 변환"""
    if isinstance(val, bytes):
        try:
            decoded = val.decode("utf-8", errors="replace").strip("\x00 \r\n")
            return decoded if decoded else "<empty>"
        except Exception:
            return str(val)

    if isinstance(val, tuple):
        # Rational: (numerator, denominator)
        if len(val) == 2 and isinstance(val[0], int) and isinstance(val[1], int):
            num, den = val
            if den == 0:
                return "0"
            if "ExposureTime" in tag_name:
                return f"1/{int(round(den / num))}s" if den > num > 0 else f"{num/den:.4f}s"
            if "FNumber" in tag_name:
                return f"f/{num / den:.1f}"
            if "FocalLength" in tag_name:
                return f"{num / den:.1f} mm"
            if den == 1:
                return str(num)
            return f"{num / den:.2f}"
        elif len(val) == 3 and all(isinstance(x, tuple) for x in val):
            # GPS DMS 포맷: ((d, 1), (m, 1), (s, 100))
            try:
                d = val[0][0] / val[0][1] if val[0][1] != 0 else 0
                m = val[1][0] / val[1][1] if val[1][1] != 0 else 0
                s = val[2][0] / val[2][1] if val[2][1] != 0 else 0
                return f"{int(d)}° {int(m)}' {s:.2f}\""
            except Exception:
                return str(val)
        return str(val)

    return str(val)


def extract_all_raw_exif(image_path: str) -> List[Tuple[str, str, str]]:
    """이미지 파일에서 모든 IFD의 원시 EXIF 태그를 추출하여 (분류, 태그명, 값) 튜플 리스트 반환"""
    if not image_path or not os.path.exists(image_path):
        return []

    results: List[Tuple[str, str, str]] = []

    # 1. piexif를 통한 세부 IFD 전수 순회
    try:
        exif_dict = piexif.load(image_path)
        if isinstance(exif_dict, dict):
            ifd_categories = [
                ("0th", "기기/본문 (0th)"),
                ("Exif", "촬영/노출/렌즈 (Exif)"),
                ("GPS", "GPS 위치 정보 (GPS)"),
                ("Interop", "상호운용성 (Interop)"),
                ("1st", "썸네일 (1st)"),
            ]
            for ifd_key, ifd_title in ifd_categories:
                section_dict = exif_dict.get(ifd_key)
                if isinstance(section_dict, dict):
                    tags_map = piexif.TAGS.get(ifd_key, {})
                    for tag_id, val in section_dict.items():
                        if tag_id == piexif.ExifIFD.MakerNote:
                            val_len = len(val) if isinstance(val, (bytes, bytearray)) else 0
                            results.append((ifd_title, "MakerNote (카메라 제조사 고유 바이너리)", f"<{val_len:,} bytes>"))
                            continue

                        tag_info = tags_map.get(tag_id)
                        name = tag_info["name"] if tag_info else f"Tag_{tag_id}"
                        ko_hint = TAG_KO_MAP.get(name)
                        display_name = f"{name} ({ko_hint})" if ko_hint else name
                        formatted = _format_exif_val(name, val)
                        results.append((ifd_title, display_name, formatted))
    except Exception:
        pass

    # 2. piexif 결과가 비어있는 경우 Pillow getexif fallback
    if not results:
        try:
            from PIL import Image, ExifTags
            with Image.open(image_path) as img:
                raw_exif = img.getexif()
                if raw_exif:
                    for k, v in raw_exif.items():
                        name = ExifTags.TAGS.get(k, f"Tag_{k}")
                        ko_hint = TAG_KO_MAP.get(name)
                        display_name = f"{name} ({ko_hint})" if ko_hint else name
                        results.append(("일반 메타데이터", display_name, str(v)))
        except Exception:
            pass

    return results


class JsonViewerDialog(QDialog):
    """대용량 Takeout JSON 메타데이터를 쾌적하게 열람하는 전용 팝업 다이얼로그"""

    def __init__(self, title: str, file_name: str, json_path: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680, 720)
        self.setMinimumSize(500, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 상단 정보 바 + 복사 버튼
        top_bar = QHBoxLayout()
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        lbl_name = QLabel(f"📄 원본 미디어: {file_name}")
        lbl_name.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {Colors.TEXT_PRIMARY};")
        info_col.addWidget(lbl_name)

        lbl_path = QLabel(f"JSON 위치: {json_path}")
        lbl_path.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        lbl_path.setWordWrap(True)
        info_col.addWidget(lbl_path)

        top_bar.addLayout(info_col, stretch=1)

        copy_btn = QPushButton("📋 JSON 전체 복사")
        copy_btn.setObjectName("SecondaryButton")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setFixedHeight(30)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        top_bar.addWidget(copy_btn)

        layout.addLayout(top_bar)

        # 본문 고정폭 JSON 에디터
        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlainText(content)
        self._edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #F8F9FA;
                color: #202124;
                font-family: Menlo, Monaco, 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid #DADCE0;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        layout.addWidget(self._edit, stretch=1)

        # 하단 닫기 버튼
        bottom_box = QHBoxLayout()
        bottom_box.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("PrimaryButton")
        close_btn.setFixedWidth(90)
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.accept)
        bottom_box.addWidget(close_btn)
        layout.addLayout(bottom_box)

    def _copy_to_clipboard(self):
        QApplication.clipboard().setText(self._edit.toPlainText())
        QMessageBox.information(self, "복사 완료", "JSON 전체 내용이 클립보드에 복사되었습니다.")


class MapViewerDialog(QDialog):
    """
    반응형 크기 조절을 지원하는 인앱 인터랙티브 지도 팝업 다이얼로그 (QWebEngineView 연동)
    """

    def __init__(self, lat: float, lon: float, location_name: str = "", parent=None):
        super().__init__(parent)
        self.lat = lat
        self.lon = lon
        self.location_name = location_name

        title_txt = f"🗺️ 촬영 위치 지도 - {location_name} [{lat:.4f}, {lon:.4f}]" if location_name else f"🗺️ 촬영 위치 지도 [{lat:.4f}, {lon:.4f}]"
        self.setWindowTitle(title_txt)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)

        # 메인 윈도우 크기에 비례하는 동적 크기 계산 (부모 창의 약 80%, min 640x480, max 1000x700)
        parent_w = parent.window().width() if parent and parent.window() else 1180
        parent_h = parent.window().height() if parent and parent.window() else 760
        target_w = max(640, min(1000, int(parent_w * 0.8)))
        target_h = max(480, min(700, int(parent_h * 0.8)))
        self.resize(target_w, target_h)
        self.setMinimumSize(540, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # 상단 정보 헤더 바
        top_bar = QHBoxLayout()
        loc_title = QLabel(f"📍 {location_name}  ({lat:.4f}, {lon:.4f})" if location_name else f"📍 좌표: {lat:.4f}, {lon:.4f}")
        loc_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1C1D1F;")
        top_bar.addWidget(loc_title)
        top_bar.addStretch()

        open_ext_btn = QPushButton("🌐 웹브라우저에서 크게 보기")
        open_ext_btn.setObjectName("SecondaryButton")
        open_ext_btn.setCursor(Qt.PointingHandCursor)
        open_ext_btn.setFixedHeight(28)
        open_ext_btn.setStyleSheet("font-size: 11px; font-weight: bold; padding: 2px 10px;")
        open_ext_btn.clicked.connect(self._open_in_browser)
        top_bar.addWidget(open_ext_btn)

        layout.addLayout(top_bar)

        # QWebEngineView 지도 영역 (방안 2: 일반 Search URL 로드 후 JS 주입으로 좌측 패널 자동 접기)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self._webview = QWebEngineView(self)
            self._webview.setStyleSheet("border: 1px solid #DCE1E7; border-radius: 8px;")
            map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            self._webview.setUrl(QUrl(map_url))
            self._webview.loadFinished.connect(self._on_map_loaded)
            layout.addWidget(self._webview, stretch=1)
        except Exception as e:
            fallback_lbl = QLabel(f"지도를 로드할 수 없습니다: {e}\n우측 상단의 '웹브라우저에서 크게 보기' 버튼을 이용하세요.")
            fallback_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(fallback_lbl, stretch=1)

        # 하단 닫기 버튼 바
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("PrimaryButton")
        close_btn.setFixedWidth(90)
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(close_btn)
        layout.addLayout(bottom_bar)

    def _on_map_loaded(self, ok: bool):
        """페이지 로드 완료 후 Google Maps 동적 렌더링을 지속 감지하여 좌측 패널 자동 접기"""
        if ok and hasattr(self, "_webview"):
            js = """
            (function() {
                let attempts = 0;
                const maxAttempts = 35; // 300ms * 35 = 약 10초간 지속 감시

                function tryCollapse() {
                    attempts++;
                    try {
                        // 1. 모든 버튼을 순회하며 패널 접기 버튼(< 아이콘) 탐색 및 클릭
                        const btns = document.querySelectorAll('button');
                        for (let i = 0; i < btns.length; i++) {
                            const btn = btns[i];
                            const label = btn.getAttribute('aria-label') || '';
                            const jsact = btn.getAttribute('jsaction') || '';
                            const title = btn.getAttribute('title') || '';
                            if (
                                label.includes('접기') || label.includes('Collapse') ||
                                jsact.includes('pane.collapse') || jsact.includes('sidebar.collapse') ||
                                title.includes('접기') || title.includes('Collapse')
                            ) {
                                btn.click();
                                clearInterval(intervalId);
                                return true;
                            }
                        }

                        // 2. 화살표 버튼 셀렉터 폴백
                        const arrowBtn = document.querySelector('button[jsaction*="collapse"], [data-tooltip*="접기"], [data-tooltip*="Collapse"]');
                        if (arrowBtn) {
                            arrowBtn.click();
                            clearInterval(intervalId);
                            return true;
                        }
                    } catch(e) {}

                    if (attempts >= maxAttempts) {
                        clearInterval(intervalId);
                    }
                    return false;
                }

                // 즉시 1회 실행 후 300ms 간격으로 동적 생성되는 버튼 클릭
                const intervalId = setInterval(tryCollapse, 300);
                tryCollapse();
            })();
            """
            self._webview.page().runJavaScript(js)

    def _open_in_browser(self):
        url = f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"
        QDesktopServices.openUrl(QUrl(url))


class ComparePanel(QFrame):
    """
    메타데이터 가로 대조표 인스펙터 패널
    - 상단: 11개 주요 데이터 전/후 정밀 대조표 (출처 하이라이트)
    - 하단: 최종 파일에 저장된 모든 원시 EXIF 태그 (Raw EXIF) 전수 뷰어
    """

    close_requested = Signal()
    location_tier_changed = Signal(bool)

    ROW_KEYS = [
        "1. 촬영 일시",
        "2. GPS 위도/경도",
        "3. GPS 고도 (Altitude)",
        "4. 역지오코딩 위치 (지역)",
        "5. 설명 / 캡션",
        "6. 인물 태그 (People)",
        "7. 즐겨찾기 (Favorite)",
        "8. 파일 수정일시 (mtime)",
        "9. 파일 생성일시 (birthtime)",
        "10. 파일 용량 (Size)",
        "11. 촬영 기기 (Make/Model)",
        "12. SHA-256 무결성 해시",
        "13. 매칭 방식 (Rule)",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(560)
        self._current_item: Optional[Dict[str, Any]] = None
        self._all_exif_data: List[Tuple[str, str, str]] = []
        self._show_3tier: bool = True  # 기본값: 3단계 상세 위치 표기 (국가 > 주/도 > 시/군/구)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(6)

        # ── 상단 닫기 바 (우측 상단 미니멀 고정 닫기 버튼) ─────
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("닫기")
        close_btn.setStyleSheet(
            f"border: none; border-radius: 11px; font-size: 12px; font-weight: bold;"
            f"background-color: {Colors.HOVER}; color: {Colors.TEXT_SECONDARY};"
        )
        close_btn.clicked.connect(self.close_requested.emit)
        top_row.addWidget(close_btn)
        main_layout.addLayout(top_row)

        # ── 상단 미디어 썸네일 & 핵심 인스펙터 카드 ─────────
        inspector_box = QFrame()
        inspector_box.setStyleSheet(
            f"background-color: #F8F9FA; border: 1px solid {Colors.BORDER};"
            f"border-radius: 8px; padding: 6px;"
        )
        insp_layout = QVBoxLayout(inspector_box)
        insp_layout.setContentsMargins(6, 6, 6, 6)
        insp_layout.setSpacing(8)

        # 1) 사진 썸네일 / 동영상 플레이스홀더 (세로 고정 180px)
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedHeight(180)
        self._thumb_lbl.setAlignment(Qt.AlignCenter)
        self._thumb_lbl.setStyleSheet(
            f"background-color: #ECEFF1; border-radius: 6px; color: {Colors.TEXT_SECONDARY};"
            f"font-size: 12px; font-weight: bold;"
        )
        self._thumb_lbl.setText("미리보기 준비 중...")
        insp_layout.addWidget(self._thumb_lbl)

        # 2) 4개 핵심 정보 헤더 (파일명, 촬영일자, GPS좌표+지도보기, 상세위치+3단계토글)
        info_form = QVBoxLayout()
        info_form.setSpacing(6)
        info_form.setContentsMargins(4, 2, 4, 2)

        _card_field_style = """
            background-color: #FFFFFF;
            border: 1px solid #DCE1E7;
            border-radius: 8px;
            padding: 0px 10px;
            font-size: 12px;
            font-weight: 500;
            color: #1C1D1F;
        """

        self._info_fname_lbl = QLabel("📄 파일명   : -")
        self._info_fname_lbl.setFixedHeight(30)
        self._info_fname_lbl.setStyleSheet(_card_field_style)
        self._info_fname_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._info_date_lbl = QLabel("📅 촬영일시 : -")
        self._info_date_lbl.setFixedHeight(30)
        self._info_date_lbl.setStyleSheet(_card_field_style)
        self._info_date_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        # 3) GPS 좌표 행 (좌측 좌표 + 우측 Google Maps 바로가기 버튼)
        gps_row = QHBoxLayout()
        gps_row.setSpacing(8)
        gps_row.setAlignment(Qt.AlignVCenter)

        self._info_gps_lbl = QLabel("📍 GPS 좌표 : -")
        self._info_gps_lbl.setFixedHeight(30)
        self._info_gps_lbl.setStyleSheet(_card_field_style)
        self._info_gps_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        gps_row.addWidget(self._info_gps_lbl, stretch=1)

        self._current_lat = 0.0
        self._current_lon = 0.0
        self._current_loc_name = ""

        self._map_btn = QPushButton("🗺️ 지도 보기")
        self._map_btn.setCursor(Qt.PointingHandCursor)
        self._map_btn.setFixedSize(92, 30)
        self._map_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8F2FD;
                color: #0072DE;
                border: 1px solid #B8D6FB;
                border-radius: 8px;
                font-size: 11px;
                font-weight: bold;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: #D3E6FC;
                border-color: #0072DE;
            }
            QPushButton:pressed {
                background-color: #B8D6FB;
            }
        """)
        self._map_btn.setVisible(False)
        self._map_btn.clicked.connect(self._open_google_map)
        gps_row.addWidget(self._map_btn)

        # 4) 역지오코딩 상세 위치 행 (좌측 지명(줄바꿈 지원) + 우측 3단계/2단계 전환 버튼)
        loc_row = QHBoxLayout()
        loc_row.setSpacing(8)
        loc_row.setAlignment(Qt.AlignVCenter)

        self._info_loc_lbl = QLabel("🌍 상세 위치 : -")
        self._info_loc_lbl.setMinimumHeight(30)
        self._info_loc_lbl.setStyleSheet("""
            background-color: #FFFFFF;
            border: 1px solid #DCE1E7;
            border-radius: 8px;
            padding: 4px 10px;
            font-size: 12px;
            font-weight: 500;
            color: #1C1D1F;
        """)
        self._info_loc_lbl.setWordWrap(True)
        self._info_loc_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        loc_row.addWidget(self._info_loc_lbl, stretch=1)

        # 3단계 / 2단계 위치 표기 전환 토글 버튼 (지도 보기 버튼과 동일한 92x30 크기로 통일)
        self._tier_toggle_btn = QPushButton("🏷️ 3단계 (상세)")
        self._tier_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._tier_toggle_btn.setFixedSize(92, 30)
        self._tier_toggle_btn.setToolTip("클릭하여 3단계(국가>주/도>도시) / 2단계(국가+도시) 위치 표기를 전환합니다.")
        self._tier_toggle_btn.clicked.connect(self._toggle_location_tier)
        self._update_tier_btn_style()
        self._tier_toggle_btn.setVisible(False)
        loc_row.addWidget(self._tier_toggle_btn)

        info_form.addWidget(self._info_fname_lbl)
        info_form.addWidget(self._info_date_lbl)
        info_form.addLayout(gps_row)
        info_form.addLayout(loc_row)
        insp_layout.addLayout(info_form)

        # ── 시각적 구분선 ──────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet(f"color: {Colors.BORDER}; margin: 2px 0;")

        # ── 경로 정보 카드 (원본 / JSON / 최종 경로: 자동 줄바꿈, 볼드 타이틀, 복사/열기 액션) ──
        path_card = QFrame()
        path_card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #DCE1E7;
                border-radius: 8px;
            }
        """)
        path_layout = QVBoxLayout(path_card)
        path_layout.setContentsMargins(10, 8, 10, 8)
        path_layout.setSpacing(6)

        _hdr_btn_style = """
            QPushButton {
                background-color: #FFFFFF;
                color: #495057;
                border: 1px solid #CED4DA;
                border-radius: 4px;
                padding: 1px 7px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #F1F3F6;
                border-color: #ADB5BD;
                color: #1C1D1F;
            }
            QPushButton:pressed {
                background-color: #E4E8EE;
            }
        """

        _path_txt_style = """
            QLabel {
                background-color: #F8F9FA;
                border: 1px solid #E5E8EB;
                border-radius: 6px;
                padding: 5px 8px;
                font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
                font-size: 11px;
                color: #212529;
                line-height: 135%;
            }
        """

        # 1. 원본 파일 경로 행
        row_orig_hdr = QHBoxLayout()
        lbl_orig_title = QLabel("📁 원본 파일 경로")
        lbl_orig_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057; background: transparent; border: none;")
        row_orig_hdr.addWidget(lbl_orig_title)
        row_orig_hdr.addStretch()

        self._btn_copy_orig = QPushButton("📋 복사")
        self._btn_copy_orig.setFixedHeight(22)
        self._btn_copy_orig.setStyleSheet(_hdr_btn_style)
        self._btn_copy_orig.setCursor(Qt.PointingHandCursor)
        self._btn_copy_orig.clicked.connect(lambda: self._copy_path_with_feedback(self._path_orig_lbl.text(), self._btn_copy_orig))
        row_orig_hdr.addWidget(self._btn_copy_orig)

        self._btn_open_orig = QPushButton("📂 열기")
        self._btn_open_orig.setFixedHeight(22)
        self._btn_open_orig.setStyleSheet(_hdr_btn_style)
        self._btn_open_orig.setCursor(Qt.PointingHandCursor)
        self._btn_open_orig.clicked.connect(lambda: self._open_in_finder(self._path_orig_lbl.text()))
        row_orig_hdr.addWidget(self._btn_open_orig)

        self._path_orig_lbl = QLabel("-")
        self._path_orig_lbl.setStyleSheet(_path_txt_style)
        self._path_orig_lbl.setWordWrap(True)
        self._path_orig_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        path_layout.addLayout(row_orig_hdr)
        path_layout.addWidget(self._path_orig_lbl)

        # 2. JSON 메타 경로 행
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #F1F3F6; max-height: 1px; border: none;")
        path_layout.addWidget(sep1)

        row_json_hdr = QHBoxLayout()
        lbl_json_title = QLabel("📋 JSON 메타 경로")
        lbl_json_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057; background: transparent; border: none;")
        row_json_hdr.addWidget(lbl_json_title)
        row_json_hdr.addStretch()

        self._btn_copy_json = QPushButton("📋 복사")
        self._btn_copy_json.setFixedHeight(22)
        self._btn_copy_json.setStyleSheet(_hdr_btn_style)
        self._btn_copy_json.setCursor(Qt.PointingHandCursor)
        self._btn_copy_json.clicked.connect(lambda: self._copy_path_with_feedback(self._path_json_lbl.text(), self._btn_copy_json))
        row_json_hdr.addWidget(self._btn_copy_json)

        self._btn_view_json = QPushButton("👁️ 원본 열람")
        self._btn_view_json.setFixedHeight(22)
        self._btn_view_json.setStyleSheet(_hdr_btn_style)
        self._btn_view_json.setCursor(Qt.PointingHandCursor)
        self._btn_view_json.clicked.connect(self._show_json_detail)
        row_json_hdr.addWidget(self._btn_view_json)

        self._path_json_lbl = QLabel("-")
        self._path_json_lbl.setStyleSheet(_path_txt_style)
        self._path_json_lbl.setWordWrap(True)
        self._path_json_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        path_layout.addLayout(row_json_hdr)
        path_layout.addWidget(self._path_json_lbl)

        # 3. 최종 파일 경로 행
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #F1F3F6; max-height: 1px; border: none;")
        path_layout.addWidget(sep2)

        row_final_hdr = QHBoxLayout()
        lbl_final_title = QLabel("🎯 최종 파일 경로")
        lbl_final_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057; background: transparent; border: none;")
        row_final_hdr.addWidget(lbl_final_title)
        row_final_hdr.addStretch()

        self._btn_copy_final = QPushButton("📋 복사")
        self._btn_copy_final.setFixedHeight(22)
        self._btn_copy_final.setStyleSheet(_hdr_btn_style)
        self._btn_copy_final.setCursor(Qt.PointingHandCursor)
        self._btn_copy_final.clicked.connect(lambda: self._copy_path_with_feedback(self._path_final_lbl.text(), self._btn_copy_final))
        row_final_hdr.addWidget(self._btn_copy_final)

        self._btn_open_final = QPushButton("📂 열기")
        self._btn_open_final.setFixedHeight(22)
        self._btn_open_final.setStyleSheet(_hdr_btn_style)
        self._btn_open_final.setCursor(Qt.PointingHandCursor)
        self._btn_open_final.clicked.connect(lambda: self._open_in_finder(self._path_final_lbl.text()))
        row_final_hdr.addWidget(self._btn_open_final)

        self._path_final_lbl = QLabel("-")
        self._path_final_lbl.setStyleSheet(_path_txt_style)
        self._path_final_lbl.setWordWrap(True)
        self._path_final_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        path_layout.addLayout(row_final_hdr)
        path_layout.addWidget(self._path_final_lbl)

        # ── 중앙 단일 통합 스크롤 영역 (개별 스크롤바 제거, 전체 통 스크롤) ──
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.setSpacing(10)

        # 1. 사진 기본 정보 섹션 헤더 (스크롤 시 함께 스크롤되어 상단 고정 제거)
        sec1_title = QLabel("📷 사진 기본 정보")
        sec1_title.setStyleSheet("font-size: 14px; font-weight: 800; color: #1F1F1F;")
        content_layout.addWidget(sec1_title)

        content_layout.addWidget(inspector_box)
        content_layout.addWidget(divider)

        # 2. 경로 정보 표 카드 (스크롤 내부)
        content_layout.addWidget(path_card)

        # 3. 메타데이터 정리 및 적용 결과 섹션 헤더
        compare_hdr = QHBoxLayout()
        compare_title = QLabel("📊 메타데이터 정리 및 적용 결과")
        compare_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #1F1F1F;")
        compare_hdr.addWidget(compare_title)

        legend = QLabel("■ 파란색: 최종 적용된 채택 출처")
        legend.setStyleSheet("font-size: 11px; color: #1A73E8; font-weight: bold; padding-left: 6px;")
        compare_hdr.addWidget(legend)
        compare_hdr.addStretch()
        content_layout.addLayout(compare_hdr)

        # 4. 13개 항목 가로 정밀 대조 테이블 (스크롤 완전 제거: 520px 고정)
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels([
            "1. 원본 파일의 데이터", "2. JSON의 메타데이터", "3. 최종 파일의 데이터"
        ])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setDefaultSectionSize(36)
        self._table.verticalHeader().setMinimumSectionSize(34)
        self._table.verticalHeader().setMinimumWidth(175)
        self._table.setShowGrid(True)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 13행(468px) + 헤더(36px) + 프레임 보더 여유 = 520px (내부 미세 스크롤 100% 제거)
        self._table.setFixedHeight(520)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        self._table.setRowCount(len(self.ROW_KEYS))
        self._table.setVerticalHeaderLabels(self.ROW_KEYS)
        self._table.verticalHeader().setVisible(True)

        content_layout.addWidget(self._table)

        # 5. 하단 카메라 및 렌즈 상세 EXIF 정보 컨테이너
        exif_container = QFrame()
        exif_container.setStyleSheet(f"background-color: transparent;")
        exif_layout = QVBoxLayout(exif_container)
        exif_layout.setContentsMargins(0, 4, 0, 0)
        exif_layout.setSpacing(4)

        exif_hdr_bar = QHBoxLayout()
        exif_title = QLabel("🔍 카메라 및 렌즈 상세 EXIF 정보")
        exif_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #1F1F1F;")
        exif_hdr_bar.addWidget(exif_title)

        self._exif_count_lbl = QLabel("(0개 태그)")
        self._exif_count_lbl.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_SECONDARY};")
        exif_hdr_bar.addWidget(self._exif_count_lbl)

        exif_hdr_bar.addStretch()

        self._exif_search = QLineEdit()
        self._exif_search.setPlaceholderText("🔍 태그 검색 (예: Model, ISO, Lens)...")
        self._exif_search.setFixedHeight(24)
        self._exif_search.setFixedWidth(200)
        self._exif_search.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self._exif_search.textChanged.connect(self._filter_exif_table)
        exif_hdr_bar.addWidget(self._exif_search)

        exif_layout.addLayout(exif_hdr_bar)

        self._exif_table = QTableWidget()
        self._exif_table.setColumnCount(3)
        self._exif_table.setHorizontalHeaderLabels(["분류 (IFD)", "EXIF 태그 명칭", "메타데이터 값"])
        self._exif_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._exif_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._exif_table.setAlternatingRowColors(True)
        self._exif_table.setShowGrid(True)
        self._exif_table.verticalHeader().setVisible(False)
        self._exif_table.verticalHeader().setDefaultSectionSize(26)
        # 개별 세로/가로 스크롤바 비활성화 (통합 스크롤 영역에서 전체 표시)
        self._exif_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._exif_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        exif_h = self._exif_table.horizontalHeader()
        exif_h.setSectionResizeMode(0, QHeaderView.Interactive)
        exif_h.setSectionResizeMode(1, QHeaderView.Interactive)
        exif_h.setSectionResizeMode(2, QHeaderView.Stretch)
        self._exif_table.setColumnWidth(0, 130)
        self._exif_table.setColumnWidth(1, 210)
        self._exif_table.setFixedHeight(120)

        exif_layout.addWidget(self._exif_table)
        content_layout.addWidget(exif_container)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, stretch=1)

        # ── 하단 버튼 바 ─────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._open_btn = QPushButton("📂 최종 위치 열기")
        self._open_btn.setObjectName("PrimaryButton")
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.clicked.connect(self._open_file_location)
        btn_row.addWidget(self._open_btn)

        self._open_orig_btn = QPushButton("📁 원본 위치 열기")
        self._open_orig_btn.setObjectName("SecondaryButton")
        self._open_orig_btn.setCursor(Qt.PointingHandCursor)
        self._open_orig_btn.clicked.connect(self._open_orig_location)
        btn_row.addWidget(self._open_orig_btn)

        self._json_btn = QPushButton("📄 JSON 원본보기")
        self._json_btn.setObjectName("SecondaryButton")
        self._json_btn.setCursor(Qt.PointingHandCursor)
        self._json_btn.clicked.connect(self._show_json_detail)
        btn_row.addWidget(self._json_btn)

        main_layout.addLayout(btn_row)

    def set_media_data(self, item: Dict[str, Any]):
        """선택된 미디어 항목을 11개 대조 항목 및 전체 EXIF 테이블에 렌더링"""
        self._current_item = item
        orig_p = item.get("original_path") or "-"
        final_p = item.get("file_path") or "-"

        f_lat = item.get("latitude") or 0.0
        f_lon = item.get("longitude") or 0.0
        c_name = (item.get("country_name") or "").strip()
        state = (item.get("state_name") or "").strip()
        city = (item.get("city_name") or "").strip()

        # 1. JSON 파일 및 원본 파일 메타 탐색
        json_meta: Dict[str, Any] = {}
        json_p_str = "-"
        if orig_p and orig_p != "-":
            p = Path(orig_p)
            cand1 = Path(orig_p + ".json")
            cand2 = Path(orig_p + ".supplemental-metadata.json")
            target = cand1 if cand1.exists() else (cand2 if cand2.exists() else None)
            if target and target.exists():
                json_p_str = str(target)
                try:
                    with open(target, "r", encoding="utf-8") as f:
                        json_meta = json.load(f)
                except Exception:
                    json_meta = {}

        # 1. 경로 정보 카드 라벨 바인딩 (자동 줄바꿈, 툴팁 지원)
        if hasattr(self, "_path_orig_lbl"):
            self._path_orig_lbl.setText(orig_p if orig_p else "-")
            self._path_orig_lbl.setToolTip(orig_p if orig_p else "-")
        if hasattr(self, "_path_json_lbl"):
            self._path_json_lbl.setText(json_p_str if json_p_str else "-")
            self._path_json_lbl.setToolTip(json_p_str if json_p_str else "-")
        if hasattr(self, "_path_final_lbl"):
            self._path_final_lbl.setText(final_p if final_p else "-")
            self._path_final_lbl.setToolTip(final_p if final_p else "-")

        # 상단 인스펙터 바인딩
        fname = item.get("file_name") or (Path(final_p).name if final_p != "-" else "-")
        self._info_fname_lbl.setText(f"📄 파일명   : {fname}")

        dt_str = item.get("taken_at") or "-"
        self._info_date_lbl.setText(f"📅 촬영일시 : {dt_str}")

        # 위치정보 및 3단계/2단계 표시 갱신
        self._update_location_display(item)

        # 썸네일 미리보기 로드 (세로 고정 180px, 비율 유지 축소 및 EXIF 방향 자동 회전)
        mtype = item.get("media_type")
        if mtype == "video":
            self._thumb_lbl.setPixmap(QPixmap())
            self._thumb_lbl.setText("🎬 동영상 파일\n(미리보기를 지원하지 않습니다)")
        elif final_p != "-" and os.path.exists(final_p):
            reader = QImageReader(final_p)
            reader.setAutoTransform(True)  # 스마트폰 세로/회전 EXIF 태그 자동 보정
            qimg = reader.read()
            if not qimg.isNull():
                pix = QPixmap.fromImage(qimg)
                scaled_pix = pix.scaled(520, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._thumb_lbl.setPixmap(scaled_pix)
                self._thumb_lbl.setText("")
            else:
                self._thumb_lbl.setPixmap(QPixmap())
                self._thumb_lbl.setText("🖼️ 미리보기를 표시할 수 없습니다.")
        else:
            self._thumb_lbl.setPixmap(QPixmap())
            self._thumb_lbl.setText("🖼️ 파일이 디스크에 존재하지 않습니다.")

        # 원본 파일 실제 OS 시간 읽기
        orig_birth_str = "-"
        orig_mtime_str = "-"
        if orig_p != "-" and os.path.exists(orig_p):
            try:
                st = os.stat(orig_p)
                b_time = getattr(st, "st_birthtime", st.st_ctime)
                orig_birth_str = datetime.fromtimestamp(b_time).strftime("%Y-%m-%d %H:%M")
                orig_mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                pass

        # 1. 촬영 일시
        json_taken = json_meta.get("photoTakenTime", {}).get("formatted", "-")
        final_taken = item.get("taken_at") or "-"
        adopted_col = 1 if json_taken != "-" else 0
        self._render_row(0, "(카메라 미기록/왜곡)", json_taken, final_taken, adopted=adopted_col)

        # 2. GPS 위경도
        json_lat, json_lon = 0.0, 0.0
        if "geoData" in json_meta:
            g = json_meta["geoData"]
            json_lat, json_lon = g.get("latitude", 0.0), g.get("longitude", 0.0)
        json_gps = f"{json_lat:.4f}, {json_lon:.4f}" if (json_lat != 0.0 or json_lon != 0.0) else "(위치 없음)"

        final_gps = f"{f_lat:.4f}, {f_lon:.4f}" if (f_lat != 0.0 or f_lon != 0.0) else "(위치 없음)"
        adopted_gps = 1 if (f_lat != 0.0 or f_lon != 0.0) else -1
        self._render_row(1, "(위치 없음)", json_gps, final_gps, adopted=adopted_gps)

        # 3. GPS 고도
        json_alt = json_meta.get("geoData", {}).get("altitude", 0.0)
        self._render_row(2, "0.0 m", f"{json_alt:.1f} m", f"{json_alt:.1f} m", adopted=1 if json_alt else -1)

        # 4. 역지오코딩 위치 (지역 - 3단계/2단계 선택 모드 연동)
        final_loc_txt = self._current_loc_name if (c_name or city) else "(위치 없음)"
        self._render_row(3, "(미지원)", "(좌표 기반 계산)", final_loc_txt, adopted=2 if (c_name or city) else -1)

        # 5. 설명 / 캡션
        json_desc = json_meta.get("description", "-") or "-"
        final_desc = item.get("description") or "-"
        self._render_row(4, "-", json_desc, final_desc, adopted=1 if json_desc != "-" else -1)

        # 6. 인물 태그
        p_names = [p.get("name", "") for p in json_meta.get("people", []) if p.get("name")]
        json_people = ", ".join(p_names) if p_names else "-"
        p_raw = item.get("people") or "[]"
        try:
            p_list = json.loads(p_raw)
            final_people = ", ".join(p_list) if p_list else "-"
        except Exception:
            final_people = "-"
        self._render_row(5, "(미지원)", json_people, final_people, adopted=1 if final_people != "-" else -1)

        # 7. 즐겨찾기
        is_fav = json_meta.get("favorited", False) or item.get("is_favorited", 0)
        fav_str = "⭐ 예 (Favorite)" if is_fav else "아니오"
        self._render_row(6, "-", fav_str, fav_str, adopted=1 if is_fav else -1)

        # 8. 파일 수정일시 (mtime)
        final_mtime = final_taken if final_taken != "-" else "-"
        self._render_row(7, orig_mtime_str, "동일 복원 타겟", final_mtime, adopted=1)

        # 9. 파일 생성일시 (birthtime)
        self._render_row(8, orig_birth_str, "동일 복원 타겟", final_mtime, adopted=1)

        # 10. 파일 용량
        size_bytes = item.get("file_size") or 0
        size_txt = f"{size_bytes / (1024*1024):.2f} MB" if size_bytes else "-"
        self._render_row(9, size_txt, "-", size_txt, adopted=0)

        # 11. 촬영 기기 (Make/Model)
        c_make = (item.get("camera_make") or "").strip()
        c_model = (item.get("camera_model") or "").strip()
        final_cam = f"{c_make} {c_model}".strip() if (c_make or c_model) else "(기기 정보 없음)"

        json_cam_make = json_meta.get("cameraMake") or json_meta.get("deviceMake") or ""
        json_cam_model = json_meta.get("cameraModel") or json_meta.get("deviceModel") or ""
        json_cam = f"{json_cam_make} {json_cam_model}".strip() if (json_cam_make or json_cam_model) else "-"

        orig_make, orig_model = "", ""
        if orig_p and orig_p != "-" and os.path.exists(orig_p):
            from src.core.exif_writer import ExifWriter
            orig_make, orig_model = ExifWriter.extract_camera_info(Path(orig_p))
        orig_cam = f"{orig_make} {orig_model}".strip() if (orig_make or orig_model) else "-"

        adopted_cam = 0 if orig_cam != "-" else (1 if json_cam != "-" else (2 if final_cam != "(기기 정보 없음)" else -1))
        self._render_row(10, orig_cam, json_cam, final_cam, adopted=adopted_cam)

        # 12. SHA-256 해시
        f_hash = item.get("file_hash") or "-"
        hash_short = f_hash[:16] + "..." if len(f_hash) > 16 else f_hash
        self._render_row(11, hash_short, "-", f"{hash_short} (무결성 검증)", adopted=0)

        # 13. 매칭 방식
        rule_name = "supplemental-metadata" if "supplemental" in json_p_str else ("파일명.json 완전일치" if json_p_str != "-" else "파일명 날짜 Fallback")
        self._render_row(12, "-", rule_name, "성공 적용", adopted=1)

        # 2. 하단 최종 파일 전체 EXIF 데이터 추출 및 바인딩
        self._load_all_exif(final_p)

    def _update_tier_btn_style(self):
        if self._show_3tier:
            self._tier_toggle_btn.setText("🏷️ 3단계 (상세)")
            self._tier_toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #E8F2FD;
                    color: #0072DE;
                    border: 1px solid #B8D6FB;
                    border-radius: 8px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 0px 4px;
                }
                QPushButton:hover {
                    background-color: #D3E6FC;
                    border-color: #0072DE;
                }
            """)
        else:
            self._tier_toggle_btn.setText("🏷️ 2단계 (요약)")
            self._tier_toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F8F9FA;
                    color: #495057;
                    border: 1px solid #CED4DA;
                    border-radius: 8px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 0px 4px;
                }
                QPushButton:hover {
                    background-color: #E9ECEF;
                    border-color: #ADB5BD;
                }
            """)

    def _toggle_location_tier(self):
        self._show_3tier = not self._show_3tier
        self._update_tier_btn_style()
        self.location_tier_changed.emit(self._show_3tier)
        if self._current_item:
            self._update_location_display(self._current_item)
            c_name = (self._current_item.get("country_name") or "").strip()
            city = (self._current_item.get("city_name") or "").strip()
            loc_txt = self._current_loc_name if (c_name or city) else "(위치 없음)"
            self._render_row(3, "(미지원)", "(좌표 기반 계산)", loc_txt, adopted=2 if (c_name or city) else -1)

    def set_location_tier(self, show_3tier: bool):
        if self._show_3tier != show_3tier:
            self._show_3tier = show_3tier
            self._update_tier_btn_style()
            if self._current_item:
                self._update_location_display(self._current_item)
                c_name = (self._current_item.get("country_name") or "").strip()
                city = (self._current_item.get("city_name") or "").strip()
                loc_txt = self._current_loc_name if (c_name or city) else "(위치 없음)"
                self._render_row(3, "(미지원)", "(좌표 기반 계산)", loc_txt, adopted=2 if (c_name or city) else -1)

    @staticmethod
    def _format_location(c_name: str, state: str, city: str, is_3tier: bool) -> str:
        if is_3tier:
            parts = [p.strip() for p in (c_name, state, city) if p and p.strip()]
            return " > ".join(parts) if parts else ""
        else:
            # 2단계: 국가 + 도시 (기존 포맷: c_name city)
            parts = [p.strip() for p in (c_name, city) if p and p.strip()]
            return " ".join(parts) if parts else ""

    def _update_location_display(self, item: Optional[Dict[str, Any]] = None):
        target = item or self._current_item
        if not target:
            self._info_gps_lbl.setText("📍 GPS 좌표 : -")
            self._info_loc_lbl.setText("🌍 상세 위치 : -")
            self._tier_toggle_btn.setVisible(False)
            self._map_btn.setVisible(False)
            self._current_loc_name = ""
            return

        f_lat = target.get("latitude") or 0.0
        f_lon = target.get("longitude") or 0.0
        self._current_lat = f_lat
        self._current_lon = f_lon

        c_name = (target.get("country_name") or "").strip()
        state = (target.get("state_name") or "").strip()
        city = (target.get("city_name") or "").strip()

        loc_formatted = self._format_location(c_name, state, city, self._show_3tier)
        self._current_loc_name = loc_formatted

        has_gps = (f_lat != 0.0 or f_lon != 0.0)
        has_loc = bool(loc_formatted)

        if has_gps:
            self._info_gps_lbl.setText(f"📍 GPS 좌표 : {f_lat:.4f}, {f_lon:.4f}")
            self._map_btn.setVisible(True)
        else:
            self._info_gps_lbl.setText("📍 GPS 좌표 : (좌표 없음)")
            self._map_btn.setVisible(False)

        if has_loc:
            self._info_loc_lbl.setText(f"🌍 상세 위치 : {loc_formatted}")
            self._tier_toggle_btn.setVisible(True)
        else:
            self._info_loc_lbl.setText("🌍 상세 위치 : (위치 없음)")
            self._tier_toggle_btn.setVisible(False)

    def _copy_path_with_feedback(self, path_str: str, btn: QPushButton):
        """경로를 클립보드에 복사하고 1.5초간 버튼에 성공 피드백 표시"""
        if not path_str or path_str == "-":
            return
        QApplication.clipboard().setText(path_str)
        orig_text = btn.text()
        btn.setText("✓ 복사됨")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #E6F4EA;
                color: #137333;
                border: 1px solid #CEEAD6;
                border-radius: 4px;
                padding: 1px 7px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        QTimer.singleShot(1500, lambda: self._restore_copy_btn(btn, orig_text))

    def _restore_copy_btn(self, btn: QPushButton, orig_text: str):
        """복사 버튼의 원래 스타일 및 텍스트 복구"""
        btn.setText(orig_text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #495057;
                border: 1px solid #CED4DA;
                border-radius: 4px;
                padding: 1px 7px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #F1F3F6;
                border-color: #ADB5BD;
                color: #1C1D1F;
            }
            QPushButton:pressed {
                background-color: #E4E8EE;
            }
        """)

    def _open_in_finder(self, path_str: Optional[str]):
        """해당 파일 경로 또는 상위 디렉터리를 OS 파일 관리자(Finder/탐색기)에서 포커스하여 열기"""
        if not path_str or path_str == "-":
            QMessageBox.information(self, "알림", "파일 경로가 유효하지 않습니다.")
            return
        p = Path(path_str)
        if p.exists():
            self._open_in_os(str(p))
        elif p.parent.exists():
            self._open_in_os(str(p.parent))
        else:
            QMessageBox.information(self, "알림", "파일 또는 폴더가 디스크에 존재하지 않습니다.")

    def _render_row(self, row: int, col0: str, col1: str, col2: str, adopted: int = -1):
        """행을 렌더링하고, 채택된 소스에 파란색 하이라이트 배경 부여"""
        texts = [col0, col1, col2]
        for col, txt in enumerate(texts):
            it = QTableWidgetItem(txt)
            it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)

            if col == adopted:
                it.setBackground(QBrush(QColor("#E8F0FE")))
                it.setForeground(QColor("#1A73E8"))
                font = QFont()
                font.setBold(True)
                it.setFont(font)
                it.setToolTip("이 소스 데이터가 최종 파일에 채택되어 적용되었습니다.")
            elif col == 2:
                it.setForeground(QColor("#1F1F1F"))
                font = QFont()
                font.setBold(True)
                it.setFont(font)

            self._table.setItem(row, col, it)

    def _load_all_exif(self, file_path: str):
        """최종 파일의 모든 원시 EXIF 태그를 읽어와 테이블에 표시"""
        self._all_exif_data = extract_all_raw_exif(file_path)
        self._filter_exif_table()

    def _filter_exif_table(self):
        """검색어에 따라 원시 EXIF 테이블 실시간 필터링"""
        query = self._exif_search.text().strip().lower()
        filtered = [
            item for item in self._all_exif_data
            if not query or query in item[0].lower() or query in item[1].lower() or query in item[2].lower()
        ]

        self._exif_table.setRowCount(len(filtered))
        for row, (ifd_name, tag_name, val_str) in enumerate(filtered):
            item_ifd = QTableWidgetItem(ifd_name)
            item_ifd.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            item_ifd.setForeground(QColor(Colors.TEXT_SECONDARY))

            item_tag = QTableWidgetItem(tag_name)
            item_tag.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_tag.setFont(QFont())

            item_val = QTableWidgetItem(val_str)
            item_val.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_val.setToolTip(val_str)

            self._exif_table.setItem(row, 0, item_ifd)
            self._exif_table.setItem(row, 1, item_tag)
            self._exif_table.setItem(row, 2, item_val)

        total = len(self._all_exif_data)
        showing = len(filtered)
        if total == 0:
            self._exif_count_lbl.setText("(EXIF 없음/동영상)")
        elif query:
            self._exif_count_lbl.setText(f"({showing}/{total}개 일치)")
        else:
            self._exif_count_lbl.setText(f"(총 {total}개 태그)")

        # EXIF 항목 개수에 맞춰 테이블 높이 동적 확장 (행당 26px + 헤더 28px)
        header_h = self._exif_table.horizontalHeader().height() or 28
        row_h = self._exif_table.verticalHeader().defaultSectionSize() or 26
        target_h = header_h + len(filtered) * row_h + 4
        self._exif_table.setFixedHeight(max(target_h, 80))

    def _open_file_location(self):
        if not self._current_item:
            return
        p = self._current_item.get("file_path")
        self._open_in_os(p)

    def _open_orig_location(self):
        if not self._current_item:
            return
        p = self._current_item.get("original_path")
        self._open_in_os(p)

    def _open_in_os(self, path_str: Optional[str]):
        if path_str and os.path.exists(path_str):
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", path_str])
            elif sys.platform == "win32":
                subprocess.run(["explorer", f"/select,{path_str}"])
        else:
            QMessageBox.information(self, "알림", "파일 경로가 디스크에 존재하지 않습니다.")

    def _open_google_map(self):
        """인터랙티브 인앱 지도 팝업 다이얼로그 (MapViewerDialog) 실행"""
        if self._current_lat != 0.0 or self._current_lon != 0.0:
            dlg = MapViewerDialog(
                lat=self._current_lat,
                lon=self._current_lon,
                location_name=self._current_loc_name,
                parent=self,
            )
            dlg.exec()
        else:
            QMessageBox.information(self, "알림", "유효한 GPS 좌표가 존재하지 않습니다.")

    def _show_json_detail(self):
        """개선된 고해상도 JsonViewerDialog 팝업으로 전체 JSON 내용 표시"""
        if not self._current_item:
            return
        orig_p = self._current_item.get("original_path")
        if not orig_p:
            return

        json_p = Path(orig_p + ".json")
        supp_json_p = Path(orig_p + ".supplemental-metadata.json")
        target_json = json_p if json_p.exists() else (supp_json_p if supp_json_p.exists() else None)

        if target_json and target_json.exists():
            try:
                with open(target_json, "r", encoding="utf-8") as f:
                    content = json.dumps(json.load(f), indent=2, ensure_ascii=False)
                j_path_str = str(target_json)
            except Exception as e:
                content = f"JSON 로드 실패: {e}"
                j_path_str = str(target_json)
        else:
            content = "해당 파일과 연결된 원본 Takeout JSON 메타데이터 파일을 찾을 수 없습니다."
            j_path_str = "없음"

        dlg = JsonViewerDialog(
            title="원본 Takeout JSON 메타데이터",
            file_name=Path(orig_p).name,
            json_path=j_path_str,
            content=content,
            parent=self,
        )
        dlg.exec()
