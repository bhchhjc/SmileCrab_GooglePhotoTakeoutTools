# 01. 개발 환경 구성 및 빌드 가이드 (Windows / macOS)

본 문서는 Windows 및 macOS 환경에서 **GooglePhotoTakeoutTools** 프로젝트의 개발 환경을 구축하고, 의존성을 관리하며, 최종 실행 파일로 패키징(빌드)하는 표준 절차를 안내합니다.

---

## 1. 사전 요구사항 (Prerequisites)

* **Python**: 3.10 이상 권장 (3.11/3.12 호환)
* **Git**: 형상 관리 (모든 명령어는 PM 사전 승인 하에 실행)
* **OS**:
  - macOS: Monterey (12.0) 이상 (Apple Silicon / Intel 모두 지원)
  - Windows: Windows 10 / 11 (64-bit)

---

## 2. 개발 환경 설정 (가상환경)

프로젝트 격리 및 일관된 패키지 버전 관리를 위해 표준 `venv`를 사용합니다.

### 2.1. macOS 환경
```bash
# 1. 가상환경 생성
python3 -m venv venv

# 2. 가상환경 활성화
source venv/bin/activate

# 3. pip 업그레이드 및 필수 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.2. Windows 환경 (PowerShell)
```powershell
# 1. 가상환경 생성
python -m venv venv

# 2. 가상환경 활성화 (스크립트 실행 권한 필요시: Set-ExecutionPolicy Unrestricted -Scope Process)
.\venv\Scripts\Activate.ps1

# 3. pip 업그레이드 및 필수 패키지 설치
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. 핵심 의존성 목록 (`requirements.txt` 계획)

```text
# GUI 프레임워크
PySide6>=6.6.0

# 이미지 및 미디어 메타데이터 처리
Pillow>=10.0.0
piexif>=1.1.3
mutagen>=1.47.0

# 시스템 및 파일 제어
pywin32>=306; sys_platform == 'win32'

# 패키징 및 테스트
pytest>=7.4.0
pyinstaller>=6.3.0
```

---

## 4. 실행 및 테스트

```bash
# 개발 모드 실행
python -m src.main

# 단위 테스트 실행
pytest tests/
```

---

## 5. 배포용 단일 실행 파일 빌드 가이드 (PyInstaller)

### 5.1. macOS (.app 및 .dmg 번들)
```bash
pyinstaller \
  --noconsole \
  --onedir \
  --name "GooglePhotoTakeoutTools" \
  --windowed \
  --clean \
  src/main.py
```

### 5.2. Windows (.exe 실행 파일)
```powershell
pyinstaller `
  --noconsole `
  --onefile `
  --name "GooglePhotoTakeoutTools" `
  --clean `
  src/main.py
```
