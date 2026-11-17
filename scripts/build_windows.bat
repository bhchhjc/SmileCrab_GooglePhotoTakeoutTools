@echo off
REM ==============================================================================
REM GooglePhotoTakeoutTools - Windows Executable Build Script (Batch)
REM ==============================================================================

echo ==========================================================
echo [INFO] GooglePhotoTakeoutTools - Windows 빌드 시작
echo ==========================================================

REM 프로젝트 루트 이동
cd /d "%~dp0\.."

REM 가상환경 내 pyinstaller 경로 확인
set PYINSTALLER=venv\Scripts\pyinstaller.exe

if not exist "%PYINSTALLER%" (
    echo [ERROR] 가상환경 내 pyinstaller를 찾을 수 없습니다.
    echo [INFO] venv\Scripts\pip.exe install pyinstaller 명령으로 설치해주세요.
    exit /b 1
)

REM 이전 빌드 정리
echo [INFO] 이전 빌드 캐시 및 산출물 정리...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 빌드 실행
echo [INFO] PyInstaller 빌드 실행 중...
"%PYINSTALLER%" --clean --noconfirm GooglePhotoTakeoutTools.spec

if exist "dist\GooglePhotoTakeoutTools\GooglePhotoTakeoutTools.exe" (
    echo ==========================================================
    echo [SUCCESS] Windows 빌드 성공!
    echo [OUTPUT] dist\GooglePhotoTakeoutTools\GooglePhotoTakeoutTools.exe
    echo ==========================================================
) else (
    echo [ERROR] 빌드 실패: 실행 파일이 생성되지 않았습니다.
    exit /b 1
)
