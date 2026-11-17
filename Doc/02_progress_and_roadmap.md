# 02. 프로젝트 진행 상황 및 로드맵 (Checklist)

본 문서는 GooglePhotoTakeoutTools 프로젝트의 전체 마일스톤과 각 단계별 세부 작업 진행 현황을 To-Do 체크리스트 형태로 관리합니다.

---

## 📌 프로젝트 마일스톤 개요

```mermaid
flowchart LR
    M0["Phase 0\n기획 & 환경설정"] --> M1["Phase 1\n코어 엔진 개발"]
    M1 --> M2["Phase 2\n로컬 DB 연동"]
    M2 --> M3["Phase 3\nPySide6 GUI"]
    M3 --> M4["Phase 4\n검증 & 패키징"]
```

---

## 📋 세부 단계별 체크리스트

### Phase 0: 프로젝트 기획 및 기본 문서화 (완료)
- [x] 프로젝트 역할(PM / 직원) 및 기본 운영 규칙 확립
- [x] 기술 스택 확정 (Python + PySide6 + SQLite)
- [x] `/Doc` 표준 문서 체계 구축
  - [x] 개발 환경 및 빌드 가이드 (`01_environment_and_build.md`)
  - [x] 진행 상황 및 로드맵 (`02_progress_and_roadmap.md`)
  - [x] 기술 스택 및 조사 자료 (`03_tech_stack_and_research.md`)
  - [x] UI/UX 조사 및 설계안 (`04_ui_ux_research.md`)
  - [x] Takeout 데이터 구조 분석서 (`05_takeout_data_analysis.md`)
  - [x] 아키텍처 및 디자인 패턴 설계서 (`00_project_architecture.md`)
  - [x] 오픈소스(gpth, immich-go) 벤치마크 및 메타데이터 심층 분석서 (`06_opensource_benchmark_analysis.md`)
- [x] Git 저장소 초기화 (`git init`) 및 `.gitignore`에 `Sample/` 경로 완벽 제외
- [x] 프로젝트 디렉토리 뼈대 생성 (`src/`, `tests/`, `requirements.txt`)
- [x] Initial commit 생성 (`a94a683`)

---

### Phase 1: 코어 엔진 개발 (Takeout 메타데이터 파서 & 매칭 엔진 - 진행 중)
- [x] 도메인 모델 설계 (`src/core/models.py`)
  - [x] `MediaMetadata`, `MediaFile`, `GeoLocation`, `MatchResult` 정의
- [x] 크로스플랫폼 유틸리티 (`src/core/utils.py`)
  - [x] macOS NFD 한글 자소 분리 방지 (`unicodedata.normalize('NFC')`)
  - [x] 파일명 날짜 정규식 파서 (Fallback 대응)
- [x] JSON 메타데이터 파서 모듈 (`src/core/parser.py`)
  - [x] `photoTakenTime`, `creationTime`, `geoData`, `description`, `people` 안전 추출
- [x] 다단계 휴리스틱 파일 매칭 엔진 (`src/core/matcher.py`)
  - [x] 디렉토리 사전 인덱싱 (`DirectoryMetadataIndex`)을 통한 고속 매칭
  - [x] 1단계: 완전 일치 (`.json`, `.supplemental-metadata.json`)
  - [x] 2단계: 중복 번호 `(1)` 불일치 정규식 매칭
  - [x] 3단계: 한국어 수정본(`-수정됨`) 및 영문(`-edited`) 원본 역추적
  - [x] 4단계: 역방향 제목 조회 (`title` Reverse Lookup)
  - [x] 5단계: 46~51자 파일명 잘림 접두사 매칭
  - [x] 6단계: 파일명 날짜 Fallback
- [x] 단위 테스트 작성 및 통과 (`tests/test_parser.py`, `tests/test_matcher.py` - 7/7 OK)
- [x] 실제 사용자 샘플 데이터(201개 파일) 대상 검증 수행 (`samples/verify_sample_matching.py`)
  - [x] **매칭 성공률: 100.00% (201/201 파일 매칭 완료)**
- [ ] 메타데이터 주입기 (`src/core/exif_writer.py`, `video_writer.py`)
- [ ] OS별 파일 시스템 날짜(`mtime`, `birthtime`) 동기화 (`src/core/os_sync.py`)
- [ ] 규칙 기반 파일 정리기 (`src/services/process_service.py`)

---

### Phase 2: 로컬 데이터베이스 구축 (SQLite)
- [ ] SQLite 스키마 정의 (`media_files`, `metadata`, `fts`)
- [ ] 작업 이력 및 중단/재개(Resume) 상태 트랜잭션 관리
- [ ] 파일 해시(SHA256) 기반 중복 검출 및 인덱싱
- [ ] 키워드/날짜/카메라 기종 고속 검색 쿼리 작성

---

### Phase 3: PySide6 GUI 인터페이스 구현
- [ ] 메인 윈도우 프레임 및 다크/라이트 테마 구성
- [ ] 백그라운드 비동기 워커(`QThreadPool`, `QRunnable`) 및 취소/일시정지 기능
- [ ] Step 1: 폴더 선택 및 디스크 여유 공간 점검(Pre-flight check) 뷰
- [ ] Step 2: 드라이런(Dry-run) 분석 통계 및 차트 뷰
- [ ] Step 3: 정리 옵션(폴더 규칙, 모드 등) 설정 패널
- [ ] Step 4: 실시간 진행률(Progress bar) 및 로그 뷰어
- [ ] Step 5: 로컬 미디어 라이브러리 및 검색 그리드 뷰

---

### Phase 4: 테스트, 최적화 및 크로스플랫폼 패키징
- [ ] 샘플 파일(20~30개) 대상 통합 테스트 수행
- [ ] macOS (.app / .dmg) 빌드 검증
- [ ] Windows (.exe) 빌드 검증
- [ ] 최종 사용자 매뉴얼 작성
