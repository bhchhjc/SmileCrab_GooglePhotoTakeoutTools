#!/usr/bin/env bash
# ==============================================================================
# GooglePhotoTakeoutTools - macOS App Bundle Build Script
# ==============================================================================
set -e

# 프로젝트 루트 경로 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

echo "=========================================================="
echo "🚀 GooglePhotoTakeoutTools - macOS 빌드 시작"
echo "=========================================================="

# 가상환경 확인
VENV_PYTHON="${PROJECT_ROOT}/venv/bin/python"
VENV_PYINSTALLER="${PROJECT_ROOT}/venv/bin/pyinstaller"

if [ ! -f "${VENV_PYINSTALLER}" ]; then
    echo "❌ PyInstaller가 가상환경에 설치되어 있지 않습니다."
    echo "다음 명령으로 설치해주세요: ./venv/bin/pip install pyinstaller"
    exit 1
fi

# 이전 빌드 아티팩트 정리
echo "🧹 이전 빌드 캐시 및 산출물 정리..."
rm -rf "${PROJECT_ROOT}/build"
rm -rf "${PROJECT_ROOT}/dist"

# PyInstaller 빌드 실행
echo "📦 PyInstaller로 .app 번들 생성 중..."
"${VENV_PYINSTALLER}" --clean --noconfirm "${PROJECT_ROOT}/GooglePhotoTakeoutTools.spec"

APP_PATH="${PROJECT_ROOT}/dist/GooglePhotoTakeoutTools.app"

if [ -d "${APP_PATH}" ]; then
    echo ""
    echo "=========================================================="
    echo "✅ macOS 빌드 성공!"
    echo "📍 산출물 위치: ${APP_PATH}"
    echo "💡 실행 방법: open '${APP_PATH}'"
    echo "=========================================================="
else
    echo "❌ 빌드 실패: 산출물 .app 디렉토리를 찾을 수 없습니다."
    exit 1
fi
