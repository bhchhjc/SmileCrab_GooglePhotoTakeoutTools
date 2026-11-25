"""
GooglePhotoTakeoutTools - Power Management
작업 진행 중 OS 시스템 절전 모드 진입 방지 (Sleep Prevention / Wake Lock) 모듈
"""

import logging
import os
import platform
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class SleepInhibitor:
    """
    운영체제(macOS / Windows)별 절전 모드 방지 컨텍스트 매니저.
    
    대용량 파일 처리 및 디스크 I/O 작업 중 시스템이 Sleep 상태로 진입하는 것을 방지하며,
    작업 완료 또는 비정상 종료(Crash, SIGKILL) 시 OS 커널 레벨에서 자동으로 절전 방지를 회수합니다.
    
    사용 예:
        with SleepInhibitor("대용량 파일 재구성"):
            # 파일 작업 수행
    """

    def __init__(self, reason: str = "Media Processing in Progress"):
        self.reason = reason
        self.system = platform.system()
        self._caffeinate_proc: Optional[subprocess.Popen] = None
        self._is_active = False

    @property
    def is_active(self) -> bool:
        """절전 방지가 현재 활성화되어 있는지 여부"""
        return self._is_active

    def start(self) -> bool:
        """절전 방지 시작"""
        if self._is_active:
            return True

        try:
            if self.system == "Darwin":  # macOS
                # -d: Create an assertion to prevent the display from sleeping.
                # -i: Create an assertion to prevent the system from idle sleeping.
                # -m: Create an assertion to prevent the disk from idling.
                # -w <pid>: Wait for the process with the specified pid to exit.
                # 우리 앱의 PID를 감시하게 하여 앱 강제종료/크래시 시 macOS 커널이 caffeinate를 자동 종료함.
                pid = os.getpid()
                self._caffeinate_proc = subprocess.Popen(
                    ["caffeinate", "-dim", "-w", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._is_active = True
                logger.info("macOS caffeinate 절전 방지 활성화 (PID: %d)", pid)
                return True

            elif self.system == "Windows":
                import ctypes

                # Execution State Flags
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_AWAYMODE_REQUIRED = 0x00000040

                result = ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
                )
                if result != 0:
                    self._is_active = True
                    logger.info("Windows SetThreadExecutionState 절전 방지 활성화")
                    return True
                else:
                    logger.warning("Windows SetThreadExecutionState 호출 실패")
                    return False

            else:
                # Linux 또는 기타 OS: 치명적이지 않으므로 No-op
                logger.debug("절전 방지 미지원 OS: %s (No-op)", self.system)
                self._is_active = True
                return True

        except Exception as e:
            logger.warning("절전 방지 활성화 중 예외 발생: %s", e)
            self._is_active = False
            return False

    def stop(self) -> None:
        """절전 방지 해제 및 OS 기본 전원 모드로 복구"""
        if not self._is_active:
            return

        try:
            if self.system == "Darwin":
                if self._caffeinate_proc and self._caffeinate_proc.poll() is None:
                    self._caffeinate_proc.terminate()
                    try:
                        self._caffeinate_proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        self._caffeinate_proc.kill()
                self._caffeinate_proc = None
                logger.info("macOS caffeinate 절전 방지 해제 완료")

            elif self.system == "Windows":
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                logger.info("Windows 절전 방지 해제 (ES_CONTINUOUS)")

        except Exception as e:
            logger.warning("절전 방지 해제 중 예외 발생: %s", e)
        finally:
            self._is_active = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
