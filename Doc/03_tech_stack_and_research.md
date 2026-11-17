# 03. 프로젝트 기술 스택 및 조사/분석 자료

본 문서는 GooglePhotoTakeoutTools 프로젝트에서 채택한 기술 스택과 사전 조사/분석된 기술적 타당성 검토 내용을 정리합니다.

---

## 1. 확정 기술 스택 개요

| 레이어 | 기술 | 선정 사유 |
| :--- | :--- | :--- |
| **언어** | Python 3.10+ | 이미지/동영상 메타데이터 처리 생태계 최상위, 크로스플랫폼 지원 |
| **GUI 프레임워크** | PySide6 (Qt for Python) | macOS/Windows 네이티브 룩앤필, 풍부한 위젯, 멀티스레딩(QThreadPool) 지원 |
| **데이터베이스** | SQLite3 (FTS5 포함) | 서버리스 무설치 로컬 DB, 수십만 장 미디어 초고속 인덱싱/검색 |
| **이미지/EXIF** | Pillow, piexif | 순수 파이썬/C 바인딩 기반 고속 EXIF 주입 및 썸네일 생성 |
| **동영상 메타** | mutagen / ExifTool | MP4/MOV 컨테이너 타임스탬프 및 위치 정보 주입 |
| **빌드/패키징** | PyInstaller | 단일 실행파일(Windows .exe / macOS .app/.dmg) 생성 |

---

## 2. 크로스플랫폼 기술 스택 비교 분석 결과

Python 외에 성능 최적화 대안(Tauri/Rust, Wails/Go, Flutter)과 비교 검토를 진행하였습니다.

* **결론 및 선택 근거**:
  - Rust(Tauri) 및 Go(Wails)가 메모리 점유율과 초기 구동 속도에서 강점이 있으나, **Google Takeout 특유의 변칙적인 미디어 포맷(HEIC, QuickTime Atom, 모션포토 등)**을 다루는 메타데이터 라이브러리 생태계는 Python이 압도적임.
  - Python(PySide6) 기반에서 비동기 스레드 풀(`QThreadPool`)을 도입하여 UI 프리징을 차단하고, SQLite로 인덱싱을 최적화함으로써 **충분히 빠르고 안정적인 사용자 경험**을 제공하기로 확정함.

---

## 3. 핵심 엔지니어링 고려사항

1. **비동기 UI 처리**: 메인 스레드 분리(QRunnable/QThreadPool)로 수만 건 배치 작업 시 응답 없음 방지.
2. **저장공간 사전 점검 (Pre-flight check)**: 복사(Copy) 모드 선택 시 원본 크기와 대상 드라이브 여유 공간 비교.
3. **OS 차이 대응**:
   - macOS 한글 NFD 자소 분리를 `unicodedata.normalize('NFC')`로 일괄 정규화.
   - OS별 파일 생성일(`birthtime`) 갱신 API 연동.
   - Windows 260자 경로 제한(MAX_PATH) 방어.
4. **상태 추적 및 트랜잭션**: SQLite 상태 플래그를 통한 작업 중단 시 이어하기(Resume) 지원.
