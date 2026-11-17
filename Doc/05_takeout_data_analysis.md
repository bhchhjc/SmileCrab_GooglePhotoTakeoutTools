# 05. Google Takeout Photos 데이터 구조 분석 자료

본 문서는 Google Takeout으로 다운로드한 Google 포토 압축 해제 데이터의 폴더 구조, 메타데이터 JSON 스키마, 파일명 변칙 패턴을 상세히 분석한 자료입니다.

---

## 1. Google Takeout 압축 해제 디렉토리 구조

Takeout 압축을 해제하면 전형적으로 다음과 같은 디렉토리 형태를 띱니다:

```text
Takeout/
└── Google 포토/
    ├── Photos from 2023/                 # 연도별 자동 생성 폴더
    │   ├── IMG_20230515_120000.jpg
    │   ├── IMG_20230515_120000.jpg.json  # 메타데이터
    │   ├── VID_20230515_130000.mp4
    │   └── VID_20230515_130000.mp4.json
    ├── 제주도 여행 2023/                 # 사용자 생성 앨범 폴더 (중복 다운로드 발생)
    │   ├── IMG_20230515_120000.jpg
    │   └── IMG_20230515_120000.jpg.json
    └── metadata.json                     # 폴더 자체의 메타데이터
```

> [!WARNING]
> 사용자가 생성한 앨범에 속한 사진은 `Photos from YYYY` 폴더와 `앨범 폴더`에 **이중으로 다운로드**되어 파일 중복이 발생합니다. 해시(SHA256) 검사를 통해 동일 미디어를 단일화해야 합니다.

---

## 2. Takeout 메타데이터 JSON 표준 스키마 분석

각 미디어 파일 옆에 생성되는 `.json` 파일의 핵심 필드 구조입니다:

```json
{
  "title": "IMG_20230515_123045.jpg",
  "description": "제주도 성산일출봉 정상",
  "imageViews": "0",
  "creationTime": {
    "timestamp": "1684132800",
    "formatted": "2023년 5월 15일 오전 6:40:00 UTC"
  },
  "photoTakenTime": {
    "timestamp": "1684121445",
    "formatted": "2023년 5월 15일 오전 3:30:45 UTC"
  },
  "geoData": {
    "latitude": 33.4580,
    "longitude": 126.9425,
    "altitude": 182.0,
    "latitudeSpan": 0.0,
    "longitudeSpan": 0.0
  },
  "geoDataExif": {
    "latitude": 33.4580,
    "longitude": 126.9425,
    "altitude": 182.0,
    "latitudeSpan": 0.0,
    "longitudeSpan": 0.0
  },
  "favorited": false,
  "googlePhotosOrigin": {
    "mobileUpload": {
      "deviceType": "ANDROID_PHONE"
    }
  }
}
```

### 핵심 필드 추출 우선순위
1. **`photoTakenTime.timestamp`**: 실제 촬영 일시 (Unix Epoch). 파일 시스템 날짜 및 EXIF `DateTimeOriginal`의 제1 기준.
2. **`geoData` vs `geoDataExif`**: 사용자가 웹/앱에서 위치를 보정한 경우 `geoData`에 최신 좌표가 저장됨.
3. **`description`**: 사진 설명(캡션). 미디어의 IPTC/XMP 코멘트에 주입.
4. **`title`**: 원본 파일명. 긴 파일명 잘림 매칭 시 역방향 조회의 핵심 키.

---

## 3. 대표적인 파일명 변칙 패턴 및 매칭 알고리즘

Google Takeout은 파일명 길이 및 중복 규칙에 따라 예측 불가능한 네이밍을 만듭니다:

| 변칙 유형 | 미디어 파일명 | 생성되는 JSON 파일명 | 처리 알고리즘 |
| :--- | :--- | :--- | :--- |
| **정상 매칭** | `photo.jpg` | `photo.jpg.json` | 1차: `filename + ".json"` 단순 검색 |
| **긴 파일명 잘림** | `very_long_name_sample.jpeg` | `very_long_name_sample.j.json` | 2차: JSON 내 `"title"` 필드를 읽어 매칭 (Reverse Lookup) |
| **중복 번호 불일치** | `photo(1).jpg` | `photo.jpg(1).json` | 3차: 정규식 `r"(.*)\((\d+)\)\.(.*)"` 치환 매칭 |
| **보정/편집본** | `photo-edited.jpg` | `photo.jpg.json` 또는 `photo-edited.jpg.json` | 4차: `-edited` 접미사 제거 후 원본 JSON 참조 여부 확인 |
| **특수문자 및 자소분리** | `한글사진_#1.jpg` | `한글사진_#1.jpg.json` | 5차: 유니코드 NFC 정규화 후 매칭 |

---

## 4. 검증용 샘플 파일 선정 가이드 (총 20~30개 권장)

실제 대용량 처리 전, 아래 7가지 케이스를 검증할 수 있도록 샘플 폴더를 구성합니다:
1. 표준 JPG 사진 + JSON (2~3개)
2. 최신 HEIC 사진 + JSON (2~3개)
3. MP4 / MOV 동영상 + JSON (2~3개)
4. 긴 파일명으로 JSON 이름이 잘린 파일 (2~3개)
5. 중복 번호 `(1)` 표기가 엇갈린 파일 (2~3개)
6. 보정본(`-edited`) 파일 (2~3개)
7. 위치/캡션 데이터가 있는 파일 vs 없는 파일 (2~3개)
