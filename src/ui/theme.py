"""
theme.py
────────────────────────────────────────────────────────────────
앱 전체 라이트 모드 디자인 시스템

색상 팔레트 (Material Design Light 계열 + Google 색상):
  - 배경 : #F0F2F5  (밝은 회색)
  - 사이드바 : #FFFFFF (흰색)
  - 카드/패널 : #FFFFFF
  - 액센트 : #1A73E8  (Google Blue)
  - 텍스트 주요 : #202124
  - 텍스트 보조 : #5F6368
  - 구분선 : #E8EAED
  - 활성 메뉴 배경 : #E8F0FE
  - 활성 메뉴 텍스트/아이콘 : #1A73E8
"""

import sys
from pathlib import Path

_ASSETS_ICONS_DIR = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent.parent) / "assets" / "icons"
ICON_RADIO_UNCHECKED = str(_ASSETS_ICONS_DIR / "radio_unchecked.svg").replace("\\", "/")
ICON_RADIO_CHECKED = str(_ASSETS_ICONS_DIR / "radio_checked.svg").replace("\\", "/")
ICON_RADIO_DISABLED = str(_ASSETS_ICONS_DIR / "radio_disabled.svg").replace("\\", "/")
ICON_CHECKBOX_UNCHECKED = str(_ASSETS_ICONS_DIR / "checkbox_unchecked.svg").replace("\\", "/")
ICON_CHECKBOX_CHECKED = str(_ASSETS_ICONS_DIR / "checkbox_checked.svg").replace("\\", "/")
ICON_CHECKBOX_DISABLED = str(_ASSETS_ICONS_DIR / "checkbox_disabled.svg").replace("\\", "/")


# ────────── 색상 상수 ──────────

class Colors:
    """라이트 모드 색상 토큰 (Samsung One UI 9.5 테마)."""

    # 배경
    BG_APP       = "#F4F6F9"   # 앱 전체 배경 (부드러운 블루그레이 미색)
    BG_SIDEBAR   = "#FFFFFF"   # 사이드바 배경
    BG_CARD      = "#FFFFFF"   # 카드/패널 배경
    BG_TOPBAR    = "#FFFFFF"   # 상단 바 배경
    BG_INPUT     = "#FFFFFF"   # 입력 필드 배경

    # 액센트 (Samsung One UI Signature Cobalt Blue)
    ACCENT       = "#0072DE"   # 주요 액센트 (One UI Blue)
    ACCENT_HOVER = "#005EB8"   # 호버 상태
    ACCENT_LIGHT = "#E8F2FD"   # 액센트 연한 배경 (활성 선택)

    # 텍스트
    TEXT_PRIMARY   = "#1C1D1F"   # 본문 텍스트 (차분한 다크)
    TEXT_SECONDARY = "#6C757D"   # 설명, 힌트
    TEXT_ACCENT    = "#0072DE"   # 강조 텍스트 (링크 등)
    TEXT_ON_ACCENT = "#FFFFFF"   # 액센트 배경 위 텍스트

    # 상태
    SUCCESS = "#12B886"   # 성공 (One UI Soft Green)
    WARNING = "#F59F00"   # 경고
    ERROR   = "#E03131"   # 오류 (One UI Red)
    INFO    = "#0072DE"   # 정보

    # One UI 인디케이터
    M3_SURFACE         = "#F8F9FA"   # Rail 배경
    M3_INDICATOR       = "#E1EDFB"   # One UI 소프트 블루 알약 배경
    M3_ON_INDICATOR    = "#0050A0"   # 알약 내부 활성 텍스트/아이콘 (Deep Blue)
    M3_HOVER           = "#ECEFF4"   # 호버 배경

    # 구분선 / 테두리
    BORDER        = "#E5E8EB"   # 기본 테두리
    BORDER_FOCUS  = "#0072DE"   # 포커스 시 테두리
    DIVIDER       = "#ECEFF1"   # 구분선

    # 호버 / 눌림
    HOVER         = "#F1F3F6"   # 일반 호버
    PRESSED       = "#E4E8EE"   # 눌렸을 때


import sys

# ────────── 폰트 ──────────

class Fonts:
    # OS별 네이티브 시스템 한글/영문 폰트 우선순위 스택
    if sys.platform == "darwin":
        FAMILY = '"Apple SD Gothic Neo", "Helvetica Neue", "Arial", sans-serif'
    elif sys.platform == "win32":
        FAMILY = '"Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    else:
        FAMILY = '"Noto Sans CJK KR", "Noto Sans KR", sans-serif'

    SIZE_TITLE  = 20
    SIZE_H1     = 16
    SIZE_H2     = 14
    SIZE_BODY   = 13
    SIZE_SMALL  = 11


# ────────── 메인 QSS 스타일시트 ──────────

MAIN_STYLESHEET = f"""
/* ── 전역 기본값 ── */
QWidget {{
    font-family: {Fonts.FAMILY};
    font-size: {Fonts.SIZE_BODY}px;
    color: {Colors.TEXT_PRIMARY};
    background-color: transparent;
}}

QLabel {{
    border: none;
    background-color: transparent;
}}

QMainWindow {{
    background-color: {Colors.BG_APP};
}}

/* ── 스크롤바 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {Colors.BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.TEXT_SECONDARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {Colors.BORDER};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {Colors.TEXT_SECONDARY};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Material 3 Navigation Rail ── */
#NavRail {{
    background-color: {Colors.M3_SURFACE};
    border-right: 1px solid {Colors.BORDER};
}}

#RailToggleBtn {{
    background-color: transparent;
    border: none;
    border-radius: 18px;
    font-size: 20px;
    color: {Colors.TEXT_SECONDARY};
    padding: 0px;
    margin: 0px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}
#RailToggleBtn:hover {{
    background-color: {Colors.M3_HOVER};
    color: {Colors.TEXT_PRIMARY};
}}

/* M3 컴팩트 레일 아이템 (76px 모드) */
#CompactRailItem {{
    background-color: transparent;
    border: none;
    border-radius: 16px;
    padding: 0px;
    margin: 3px 6px;
}}
#CompactRailItem:hover {{
    background-color: rgba(0, 0, 0, 0.04);
}}

/* M3 확장 드로어 아이템 (240px 모드) */
#ExpandedRailItem {{
    background-color: transparent;
    border: none;
    border-radius: 24px;
    padding: 0px;
    margin: 3px 12px;
}}
#ExpandedRailItem:hover {{
    background-color: rgba(0, 0, 0, 0.04);
}}
#ExpandedRailItem:checked {{
    background-color: #D3E3FD;
}}

/* ── 사이드바 구분선 ── */
#SidebarDivider {{
    background-color: {Colors.DIVIDER};
    max-height: 1px;
    margin: 8px 16px;
}}

/* ── 페이지 상단 통합 헤더 (Antigravity 스타일 일체형) ── */
#PageHeaderContainer {{
    background-color: transparent;
    padding: 20px 32px 4px 32px;
}}
#PageHeaderTitle {{
    font-size: 22px;
    font-weight: 800;
    color: {Colors.TEXT_PRIMARY};
}}
#PageHeaderSubtitle {{
    font-size: 12px;
    color: {Colors.TEXT_SECONDARY};
    padding-top: 2px;
}}

/* ── 콘텐츠 영역 ── */
#ContentArea {{
    background-color: {Colors.BG_APP};
}}

/* ── 카드 (One UI 9.5 Focus Block) ── */
#Card {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 16px;
    padding: 14px 18px;
}}

/* ── 통계 카드 (대시보드) ── */
#StatCard {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 14px;
    padding: 12px 16px;
}}
#StatCardValue {{
    font-size: 22px;
    font-weight: bold;
    color: {Colors.TEXT_PRIMARY};
}}
#StatCardLabel {{
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: 600;
    color: {Colors.TEXT_PRIMARY};
}}
#StatCardDesc {{
    font-size: 11px;
    color: {Colors.TEXT_SECONDARY};
    padding-top: 2px;
}}
#StatCardIcon {{
    font-size: 24px;
}}

/* ── One UI 9.5 마스터-디테일 서브 내비게이션 ── */
#OneUISubNav {{
    background-color: #FAFBFD;
    border-right: 1px solid {Colors.BORDER};
}}
#OneUINavItem {{
    background-color: transparent;
    border: none;
    border-radius: 12px;
    text-align: left;
    padding: 9px 14px;
    font-size: 13px;
    font-weight: 600;
    color: #495057;
    margin: 2px 6px;
}}
#OneUINavItem:hover {{
    background-color: #EEF2F6;
    color: {Colors.TEXT_PRIMARY};
}}
#OneUINavItem:checked {{
    background-color: {Colors.ACCENT_LIGHT};
    color: {Colors.ACCENT};
    font-weight: bold;
}}

/* ── 섹션 타이틀 ── */
#SectionTitle {{
    font-size: {Fonts.SIZE_H2}px;
    font-weight: bold;
    color: {Colors.TEXT_PRIMARY};
    padding-bottom: 4px;
}}

/* ── Primary 버튼 (One UI 9.5) ── */
#PrimaryButton {{
    background-color: {Colors.ACCENT};
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 5px 16px;
    font-size: 12px;
    font-weight: bold;
    min-height: 30px;
}}
#PrimaryButton:hover {{
    background-color: {Colors.ACCENT_HOVER};
}}
#PrimaryButton:pressed {{
    background-color: #004B99;
}}
#PrimaryButton:disabled {{
    background-color: #E9ECEF;
    color: #ADB5BD;
}}

/* ── Secondary 버튼 (One UI 9.5) ── */
#SecondaryButton {{
    background-color: transparent;
    color: {Colors.ACCENT};
    border: 1px solid {Colors.ACCENT};
    border-radius: 10px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
    min-height: 28px;
}}
#SecondaryButton:hover {{
    background-color: {Colors.ACCENT_LIGHT};
}}
#SecondaryButton:disabled {{
    border-color: #E9ECEF;
    color: #ADB5BD;
}}

/* ── 위험 버튼 (취소/중단) ── */
#DangerButton {{
    background-color: transparent;
    color: {Colors.ERROR};
    border: 1px solid {Colors.ERROR};
    border-radius: 10px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: bold;
    min-height: 28px;
}}
#DangerButton:hover {{
    background-color: #FFF5F5;
}}

/* ── 다이얼로그 및 메시지 박스 (One UI 9.5) ── */
QMessageBox, QDialog {{
    background-color: #FFFFFF;
}}
QMessageBox QLabel {{
    color: {Colors.TEXT_PRIMARY};
    font-size: 13px;
}}
QMessageBox QPushButton {{
    background-color: #F1F3F5;
    color: #212529;
    border: 1px solid #CED4DA;
    border-radius: 8px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 600;
    min-width: 64px;
    min-height: 26px;
}}
QMessageBox QPushButton:hover {{
    background-color: #E9ECEF;
}}
QMessageBox QPushButton:default {{
    background-color: {Colors.ACCENT};
    color: #FFFFFF;
    border: none;
}}
QMessageBox QPushButton:default:hover {{
    background-color: {Colors.ACCENT_HOVER};
}}

/* ── 한 줄 입력 필드 (One UI 9.5) ── */
QLineEdit {{
    background-color: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 4px 10px;
    color: {Colors.TEXT_PRIMARY};
    min-height: 24px;
    max-height: 36px;
    selection-background-color: {Colors.ACCENT_LIGHT};
}}
QLineEdit:focus {{
    border-color: {Colors.ACCENT};
}}

/* ── 여러 줄 텍스트 및 콘솔 영역 ── */
QTextEdit, QPlainTextEdit {{
    background-color: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    color: {Colors.TEXT_PRIMARY};
    selection-background-color: {Colors.ACCENT_LIGHT};
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {Colors.ACCENT};
}}

/* ── 콤보박스 ── */
QComboBox {{
    background-color: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 4px 10px;
    color: {Colors.TEXT_PRIMARY};
    min-height: 24px;
    max-height: 32px;
}}
QComboBox:focus {{
    border-color: {Colors.ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    selection-background-color: {Colors.ACCENT_LIGHT};
    selection-color: {Colors.ACCENT};
    padding: 4px;
}}

/* ── 라디오 버튼 (Material 3 스타일) ── */
QRadioButton {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
    font-size: 13px;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: none;
    background: transparent;
    image: url({ICON_RADIO_UNCHECKED});
}}
QRadioButton::indicator:checked {{
    image: url({ICON_RADIO_CHECKED});
}}
QRadioButton::indicator:disabled {{
    image: url({ICON_RADIO_DISABLED});
}}

/* ── 체크박스 (Material 3 스타일) ── */
QCheckBox {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
    font-size: 13px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: none;
    background: transparent;
    image: url({ICON_CHECKBOX_UNCHECKED});
}}
QCheckBox::indicator:checked {{
    image: url({ICON_CHECKBOX_CHECKED});
}}
QCheckBox::indicator:disabled {{
    image: url({ICON_CHECKBOX_DISABLED});
}}

/* ── 프로그레스바 ── */
QProgressBar {{
    background-color: {Colors.BORDER};
    border: none;
    border-radius: 6px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {Colors.ACCENT};
    border-radius: 6px;
}}

/* ── 테이블 및 트리 뷰 (One UI 9.0 스타일) ── */
QTableWidget, QTreeWidget {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 12px;
    gridline-color: {Colors.BORDER};
    selection-background-color: {Colors.ACCENT_LIGHT};
    selection-color: {Colors.ACCENT};
}}
QTableWidget::item {{
    padding: 6px 8px;
}}
QTreeWidget::item {{
    height: 28px;
    padding: 0px 4px;
    border-bottom: 1px solid #F8F9FA;
}}
QTreeWidget::item:hover {{
    background-color: #EEF2F6;
}}
QTreeWidget::item:selected {{
    background-color: {Colors.ACCENT_LIGHT};
    color: {Colors.ACCENT};
    font-weight: bold;
}}
QHeaderView::section {{
    background-color: {Colors.BG_APP};
    border: none;
    border-right: 1px solid {Colors.BORDER};
    border-bottom: 1px solid {Colors.BORDER};
    padding: 8px 6px;
    font-weight: bold;
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.SIZE_SMALL}px;
}}
QHeaderView::section:hover {{
    background-color: #E8EAED;
}}
QHeaderView::section:horizontal {{
    border-right: 1px solid {Colors.BORDER};
    border-bottom: 1px solid {Colors.BORDER};
    text-align: center;
}}
QHeaderView::section:vertical {{
    border-right: 1px solid {Colors.BORDER};
    border-bottom: 1px solid {Colors.BORDER};
    text-align: left;
    padding-left: 8px;
    padding-right: 8px;
}}

/* ── 스크롤바 (One UI 9.5 슬림 스크롤바) ── */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #CED4DA;
    min-height: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: #ADB5BD;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
    height: 0px;
}}
QScrollBar:horizontal {{
    border: none;
    background: transparent;
    height: 6px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #CED4DA;
    min-width: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #ADB5BD;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none;
    background: none;
    width: 0px;
}}

/* ── 라벨 (보조 텍스트) ── */
#SubLabel {{
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.SIZE_SMALL}px;
}}

/* ── 구분선 (Horizontal Frame) ── */
QFrame[frameShape="4"] {{
    color: {Colors.DIVIDER};
}}

/* ── 로그 콘솔 ── */
#LogConsole {{
    background-color: #F8F9FA;
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    font-family: Menlo, Monaco, "Courier New", monospace;
    font-size: {Fonts.SIZE_SMALL}px;
    color: {Colors.TEXT_PRIMARY};
    padding: 8px;
}}

/* ── 상태 뱃지 ── */
#BadgeSuccess {{
    background-color: #E6F4EA;
    color: {Colors.SUCCESS};
    border-radius: 10px;
    padding: 2px 10px;
    font-size: {Fonts.SIZE_SMALL}px;
    font-weight: bold;
}}
#BadgeError {{
    background-color: #FCE8E6;
    color: {Colors.ERROR};
    border-radius: 10px;
    padding: 2px 10px;
    font-size: {Fonts.SIZE_SMALL}px;
    font-weight: bold;
}}
#BadgeWarning {{
    background-color: #FEF7E0;
    color: #E37400;
    border-radius: 10px;
    padding: 2px 10px;
    font-size: {Fonts.SIZE_SMALL}px;
    font-weight: bold;
}}
"""
