"""
GooglePhotoTakeoutTools - OS Date Synchronizer
운영체제(macOS / Windows)별 파일 생성일(birthtime) 및 수정일(mtime) 동기화 모듈
"""

import logging
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class OsDateSync:
    """
    크로스플랫폼 파일 시스템 타임스탬프 동기화 엔진.
    Finder(macOS)와 파일 탐색기(Windows)에서 실제 촬영 날짜로 정렬되도록
    파일의 생성일(birthtime/creation time) 및 수정일(mtime)을 갱신합니다.
    """

    @classmethod
    def sync_file_time(cls, file_path: Path, target_dt: datetime) -> bool:
        """
        파일의 mtime, atime, birthtime(OS 지원 시)을 target_dt로 동기화합니다.
        """
        if not file_path.exists():
            logger.warning("동기화 실패: 파일이 존재하지 않습니다 [%s]", file_path)
            return False

        timestamp = target_dt.timestamp()

        # 1. 공통: 수정일(mtime) 및 접근일(atime) 갱신
        try:
            os.utime(file_path, (timestamp, timestamp))
        except OSError as e:
            logger.error("os.utime 실패 [%s]: %s", file_path, e)
            return False

        # 2. OS별 생성일(birthtime/creation time) 갱신
        current_os = platform.system()
        if current_os == "Darwin":  # macOS
            cls._sync_macos_creation_time(file_path, target_dt)
        elif current_os == "Windows":
            cls._sync_windows_creation_time(file_path, target_dt)

        return True

    @staticmethod
    def _sync_macos_creation_time(file_path: Path, target_dt: datetime) -> None:
        """
        macOS의 SetFile CLI를 사용하여 파일 생성일(creation date)을 갱신합니다.
        형식: SetFile -d "MM/DD/YYYY HH:MM:SS" file_path
        """
        date_str = target_dt.strftime("%m/%d/%Y %H:%M:%S")
        try:
            subprocess.run(
                ["SetFile", "-d", date_str, "-m", date_str, str(file_path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            # SetFile 명령어가 없는 환경(Xcode CLI tools 미설치 등)의 경우
            # os.utime()으로 mtime이 이미 설정되었으므로 치명적이지 않음
            pass

    @staticmethod
    def _sync_windows_creation_time(file_path: Path, target_dt: datetime) -> None:
        """
        Windows의 Win32 kernel32.SetFileTime API를 사용하여
        파일 생성일(CreationTime), 접근일(LastAccessTime), 수정일(LastWriteTime)을 갱신합니다.
        """
        try:
            import ctypes
            from ctypes import wintypes

            # FILETIME 구조체: 1601년 1월 1일 기준 100나노초 단위
            # Unix epoch(1970)과의 차이는 11644473600초
            unix_time = target_dt.timestamp()
            filetime_int = int((unix_time + 11644473600) * 10000000)

            low_part = filetime_int & 0xFFFFFFFF
            high_part = filetime_int >> 32
            ft = wintypes.FILETIME(low_part, high_part)

            # 파일 핸들 열기 (GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE)
            handle = ctypes.windll.kernel32.CreateFileW(
                str(file_path),
                0x40000000,  # GENERIC_WRITE
                0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
                None,
                3,  # OPEN_EXISTING
                0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
                None,
            )

            if handle != -1:
                try:
                    # SetFileTime(hFile, lpCreationTime, lpLastAccessTime, lpLastWriteTime)
                    ctypes.windll.kernel32.SetFileTime(handle, ctypes.byref(ft), ctypes.byref(ft), ctypes.byref(ft))
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception as e:
            logger.debug("Windows SetFileTime 실패 [%s]: %s", file_path, e)
