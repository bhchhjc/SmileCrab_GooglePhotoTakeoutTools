# ==============================================================================
# GooglePhotoTakeoutTools - Windows Executable Build Script (PowerShell)
# ==============================================================================
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🚀 GooglePhotoTakeoutTools - Windows 빌드 시작" -ForegroundColor Cyan
Write-Host "=========================================================="

$PyInstaller = Join-Path $ProjectRoot "venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
    Write-Host "❌ 가상환경 내 pyinstaller를 찾을 수 없습니다." -ForegroundColor Red
    Write-Host "다음 명령으로 설치해주세요: .\venv\Scripts\pip.exe install pyinstaller"
    exit 1
}

# 이전 빌드 정리
Write-Host "🧹 이전 빌드 정리 중..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

# 빌드 실행
Write-Host "📦 PyInstaller 빌드 실행 중..." -ForegroundColor Green
& $PyInstaller --clean --noconfirm GooglePhotoTakeoutTools.spec

$ExePath = Join-Path $ProjectRoot "dist\GooglePhotoTakeoutTools\GooglePhotoTakeoutTools.exe"

if (Test-Path $ExePath) {
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "✅ Windows 빌드 성공!" -ForegroundColor Green
    Write-Host "📍 산출물 위치: $ExePath"
    Write-Host "=========================================================="
} else {
    Write-Host "❌ 빌드 실패: 실행 파일이 생성되지 않았습니다." -ForegroundColor Red
    exit 1
}
