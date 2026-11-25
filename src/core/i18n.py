"""
core/i18n.py
────────────────────────────────────────────────────────────────
GooglePhotoTakeoutTools 다국어(i18n) 지원 중앙 엔진

지원 언어:
  - ko_KR: 한국어 (Korean)
  - en_US: English (US)
  - ja_JP: 日本語 (Japanese)
  - zh_CN: 简体中文 (Simplified Chinese)
  - zh_TW: 繁體中文 (Traditional Chinese - Taiwan)
  - zh_HK: 繁體中文 (Traditional Chinese - Hong Kong)
"""

from __future__ import annotations

import json
import locale
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QLocale, QObject, Signal

logger = logging.getLogger(__name__)

SUPPORTED_LOCALES: Dict[str, str] = {
    "ko_KR": "한국어",
    "en_US": "English",
    "ja_JP": "日本語",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文 (台灣)",
    "zh_HK": "繁體中文 (香港)",
}

LOCALE_FLAGS: Dict[str, str] = {
    "ko_KR": "🇰🇷",
    "en_US": "🇺🇸",
    "ja_JP": "🇯🇵",
    "zh_CN": "🇨🇳",
    "zh_TW": "🇹🇼",
    "zh_HK": "🇭🇰",
}

DEFAULT_LOCALE = "ko_KR"
FALLBACK_LOCALE = "en_US"


class I18nManager(QObject):
    """
    애플리케이션 전역 다국어 관리자 (싱글톤 패턴)
    JSON 기반 언어 팩 로딩 및 시그널을 통한 UI 실시간 갱신 지원.
    """
    language_changed = Signal(str)

    _instance: Optional["I18nManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None):
        if hasattr(self, "_initialized") and self._initialized:
            return
        super().__init__(parent)
        self._initialized = True

        self._locales_dir = Path(__file__).resolve().parent.parent / "locales"
        self._translations: Dict[str, Dict[str, Any]] = {}
        self._current_locale: str = DEFAULT_LOCALE

        # 초기 번역 로드
        self._load_translations()

    @property
    def current_locale(self) -> str:
        return self._current_locale

    @property
    def supported_locales(self) -> Dict[str, str]:
        return SUPPORTED_LOCALES

    def _load_translations(self) -> None:
        """locales 디렉토리 내 모든 지원 언어 JSON 파일을 메모리에 로드"""
        if not self._locales_dir.exists():
            self._locales_dir.mkdir(parents=True, exist_ok=True)

        for loc_code in SUPPORTED_LOCALES.keys():
            json_file = self._locales_dir / f"{loc_code}.json"
            if json_file.exists():
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        self._translations[loc_code] = json.load(f)
                except Exception as exc:
                    logger.error(f"Failed to load translation file {json_file}: {exc}")
                    self._translations[loc_code] = {}
            else:
                self._translations[loc_code] = {}

    def detect_system_locale(self) -> str:
        """
        OS 시스템 설정 언어를 감지하여 지원 언어 코드 중 가장 적합한 로케일 반환.
        """
        sys_loc = QLocale.system().name()  # 예: 'ko_KR', 'en_US', 'ja_JP', 'zh_CN', 'zh_TW'
        if sys_loc in SUPPORTED_LOCALES:
            return sys_loc

        # 접두사 기준 매핑 시도
        lang_code = sys_loc.split("_")[0].lower()
        if lang_code == "ko":
            return "ko_KR"
        elif lang_code == "ja":
            return "ja_JP"
        elif lang_code == "zh":
            # 중국어 세부 로케일 판별
            if "HK" in sys_loc.upper():
                return "zh_HK"
            elif "TW" in sys_loc.upper():
                return "zh_TW"
            else:
                return "zh_CN"
        elif lang_code == "en":
            return "en_US"

        return DEFAULT_LOCALE

    def set_locale(self, locale_code: str) -> bool:
        """
        현재 언어 변경 및 language_changed 시그널 발송.
        """
        if locale_code not in SUPPORTED_LOCALES:
            logger.warning(f"Unsupported locale: {locale_code}, fallback to {DEFAULT_LOCALE}")
            locale_code = DEFAULT_LOCALE

        if self._current_locale == locale_code:
            return False

        # 해당 언어 팩이 비어있다면 재로드 시도
        if not self._translations.get(locale_code):
            self._load_translations()

        self._current_locale = locale_code
        logger.info(f"Application language changed to: {locale_code} ({SUPPORTED_LOCALES[locale_code]})")
        self.language_changed.emit(locale_code)
        return True

    def get_text(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        키 경로(dot-notation)를 탐색하여 번역 텍스트 반환.
        
        탐색 순서:
          1. 현재 로케일
          2. FALLBACK_LOCALE (en_US)
          3. DEFAULT_LOCALE (ko_KR)
          4. default 값 (제공된 경우)
          5. key 자체
        """
        val = self._lookup(self._current_locale, key)
        if val is None and self._current_locale != FALLBACK_LOCALE:
            val = self._lookup(FALLBACK_LOCALE, key)
        if val is None and self._current_locale != DEFAULT_LOCALE and FALLBACK_LOCALE != DEFAULT_LOCALE:
            val = self._lookup(DEFAULT_LOCALE, key)

        if val is None:
            val = default if default is not None else key

        if kwargs and isinstance(val, str):
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return str(val)

    def _lookup(self, locale_code: str, key: str) -> Optional[str]:
        """점(dot)으로 구분된 키를 JSON 트리 구조에서 탐색"""
        data = self._translations.get(locale_code)
        if not data:
            return None

        # 1. 플랫 키 직접 탐색
        if key in data:
            return data[key]

        # 2. dot 표기법 중첩 탐색
        parts = key.split(".")
        curr: Any = data
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return None
        return curr if isinstance(curr, str) else None


# 전역 싱글톤 인스턴스 및 헬퍼 함수
i18n = I18nManager()


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    """번역 텍스트를 조회하는 단축 헬퍼 함수"""
    return i18n.get_text(key, default=default, **kwargs)


def get_open_file_manager_text() -> str:
    """
    현재 운영체제(macOS / Windows / Linux)에 맞춰
    Finder에서 보기 / 탐색기에서 보기 / 폴더 열기 다국어 텍스트를 반환합니다.
    """
    import sys
    if sys.platform == "darwin":
        return t("common.open_in_finder", "Finder에서 보기")
    elif sys.platform == "win32":
        return t("common.open_in_explorer", "탐색기에서 보기")
    else:
        return t("common.open_in_file_manager", "폴더 열기")
