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

# ────────── 색상 상수 ──────────

class Colors:
    """라이트 모드 색상 토큰."""

    # 배경
    BG_APP       = "#F0F2F5"   # 앱 전체 배경
    BG_SIDEBAR   = "#FFFFFF"   # 사이드바 배경
    BG_CARD      = "#FFFFFF"   # 카드/패널 배경
    BG_TOPBAR    = "#FFFFFF"   # 상단 바 배경
    BG_INPUT     = "#FFFFFF"   # 입력 필드 배경

    # 액센트
    ACCENT       = "#1A73E8"   # 주요 액센트 (Google Blue)
    ACCENT_HOVER = "#1557B0"   # 호버 상태
    ACCENT_LIGHT = "#E8F0FE"   # 액센트 연한 배경 (활성 메뉴)

    # 텍스트
    TEXT_PRIMARY   = "#202124"   # 본문 텍스트
    TEXT_SECONDARY = "#5F6368"   # 설명, 힌트
    TEXT_ACCENT    = "#1A73E8"   # 강조 텍스트 (링크 등)
    TEXT_ON_ACCENT = "#FFFFFF"   # 액센트 배경 위 텍스트

    # 상태
    SUCCESS = "#34A853"   # 성공 (Google Green)
    WARNING = "#FBBC04"   # 경고 (Google Yellow)
    ERROR   = "#EA4335"   # 오류 (Google Red)
    INFO    = "#1A73E8"   # 정보

    # 구분선 / 테두리
    BORDER        = "#E8EAED"   # 기본 테두리
    BORDER_FOCUS  = "#1A73E8"   # 포커스 시 테두리
    DIVIDER       = "#E0E0E0"   # 구분선

    # 호버 / 눌림
    HOVER         = "#F1F3F4"   # 일반 호버
    PRESSED       = "#E8EAED"   # 눌렸을 때


import sys

# ────────── 폰트 ──────────

class Fonts:
    # OS별 네이티브 시스템 한글/영문 폰트 우선순위 스택
    if sys.platform == "darwin":
        FAMILY = '-apple-system, "Apple SD Gothic Neo", "Helvetica Neue", sans-serif'
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

/* ── 사이드바 ── */
#Sidebar {{
    background-color: {Colors.BG_SIDEBAR};
    border-right: 1px solid {Colors.BORDER};
}}

/* ── 사이드바 앱 타이틀 ── */
#SidebarTitle {{
    color: {Colors.TEXT_PRIMARY};
    font-size: {Fonts.SIZE_H1}px;
    font-weight: bold;
    padding-left: 4px;
}}
#SidebarLogo {{
    font-size: 22px;
}}

/* ── 사이드바 햄버거 버튼 ── */
#HamburgerButton {{
    background-color: transparent;
    border: none;
    font-size: 20px;
    color: {Colors.TEXT_SECONDARY};
    padding: 6px;
    border-radius: 6px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}
#HamburgerButton:hover {{
    background-color: {Colors.HOVER};
    color: {Colors.TEXT_PRIMARY};
}}
#HamburgerButton:pressed {{
    background-color: {Colors.PRESSED};
}}

/* ── 사이드바 내비게이션 버튼 (일반) ── */
#NavButton {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 14px;
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: 500;
    margin: 1px 8px;
}}
#NavButton:hover {{
    background-color: {Colors.HOVER};
    color: {Colors.TEXT_PRIMARY};
}}
#NavButton:checked {{
    background-color: {Colors.ACCENT_LIGHT};
    color: {Colors.ACCENT};
    font-weight: bold;
}}

/* ── 사이드바 구분선 ── */
#SidebarDivider {{
    background-color: {Colors.DIVIDER};
    max-height: 1px;
    margin: 6px 16px;
}}

/* ── 상단 바 ── */
#TopBar {{
    background-color: {Colors.BG_TOPBAR};
    border-bottom: 1px solid {Colors.BORDER};
}}
#TopBarHamburger {{
    background-color: transparent;
    border: none;
    font-size: 20px;
    color: {Colors.TEXT_SECONDARY};
    padding: 6px;
    border-radius: 6px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}
#TopBarHamburger:hover {{
    background-color: {Colors.HOVER};
}}
#PageTitle {{
    font-size: {Fonts.SIZE_H1}px;
    font-weight: bold;
    color: {Colors.TEXT_PRIMARY};
}}

/* ── 콘텐츠 영역 ── */
#ContentArea {{
    background-color: {Colors.BG_APP};
}}

/* ── 카드 ── */
#Card {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 12px;
    padding: 20px;
}}

/* ── 통계 카드 (대시보드) ── */
#StatCard {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 12px;
    padding: 20px 24px;
}}
#StatCardValue {{
    font-size: 28px;
    font-weight: bold;
    color: {Colors.TEXT_PRIMARY};
}}
#StatCardLabel {{
    font-size: {Fonts.SIZE_SMALL}px;
    color: {Colors.TEXT_SECONDARY};
}}
#StatCardIcon {{
    font-size: 28px;
}}

/* ── 섹션 타이틀 ── */
#SectionTitle {{
    font-size: {Fonts.SIZE_H2}px;
    font-weight: bold;
    color: {Colors.TEXT_PRIMARY};
    padding-bottom: 4px;
}}

/* ── Primary 버튼 ── */
#PrimaryButton {{
    background-color: {Colors.ACCENT};
    color: {Colors.TEXT_ON_ACCENT};
    border: none;
    border-radius: 8px;
    padding: 10px 24px;
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: bold;
    min-height: 40px;
}}
#PrimaryButton:hover {{
    background-color: {Colors.ACCENT_HOVER};
}}
#PrimaryButton:pressed {{
    background-color: #0D47A1;
}}
#PrimaryButton:disabled {{
    background-color: {Colors.BORDER};
    color: {Colors.TEXT_SECONDARY};
}}

/* ── Secondary 버튼 ── */
#SecondaryButton {{
    background-color: transparent;
    color: {Colors.ACCENT};
    border: 1px solid {Colors.ACCENT};
    border-radius: 8px;
    padding: 10px 24px;
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: bold;
    min-height: 40px;
}}
#SecondaryButton:hover {{
    background-color: {Colors.ACCENT_LIGHT};
}}
#SecondaryButton:disabled {{
    border-color: {Colors.BORDER};
    color: {Colors.TEXT_SECONDARY};
}}

/* ── 위험 버튼 (취소/중단) ── */
#DangerButton {{
    background-color: transparent;
    color: {Colors.ERROR};
    border: 1px solid {Colors.ERROR};
    border-radius: 8px;
    padding: 10px 24px;
    font-size: {Fonts.SIZE_BODY}px;
    font-weight: bold;
    min-height: 40px;
}}
#DangerButton:hover {{
    background-color: #FFEBEE;
}}

/* ── 입력 필드 ── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {Colors.TEXT_PRIMARY};
    selection-background-color: {Colors.ACCENT_LIGHT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {Colors.ACCENT};
}}

/* ── 콤보박스 ── */
QComboBox {{
    background-color: {Colors.BG_INPUT};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {Colors.TEXT_PRIMARY};
    min-height: 36px;
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

/* ── 라디오 버튼 ── */
QRadioButton {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid {Colors.BORDER};
    background-color: {Colors.BG_INPUT};
}}
QRadioButton::indicator:checked {{
    border-color: {Colors.ACCENT};
    background-color: {Colors.ACCENT};
}}

/* ── 체크박스 ── */
QCheckBox {{
    color: {Colors.TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {Colors.BORDER};
    background-color: {Colors.BG_INPUT};
}}
QCheckBox::indicator:checked {{
    border-color: {Colors.ACCENT};
    background-color: {Colors.ACCENT};
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

/* ── 테이블 ── */
QTableWidget {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    gridline-color: {Colors.BORDER};
    selection-background-color: {Colors.ACCENT_LIGHT};
    selection-color: {Colors.TEXT_PRIMARY};
}}
QTableWidget::item {{
    padding: 8px;
}}
QHeaderView::section {{
    background-color: {Colors.BG_APP};
    border: none;
    border-bottom: 1px solid {Colors.BORDER};
    padding: 10px 8px;
    font-weight: bold;
    color: {Colors.TEXT_SECONDARY};
    font-size: {Fonts.SIZE_SMALL}px;
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
    font-family: 'Courier New', monospace;
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
