# 생기부 파서 설계 스펙 (개발 AI 프롬프트용)

이 문서는 생기부 파서 서비스를 구현하는 개발 AI(Claude Code 등)에게 그대로 전달하는 설계 스펙입니다. `docs/PARSER_SPEC.md`로 저장하고, 파서 관련 작업 시작 전 이 문서를 먼저 읽게 하세요.

## 전제

- 입력은 이미지가 아닌 **텍스트 PDF** (OCR 불필요)
- LLM 모듈은 **DeepSeek** (`deepseek-chat`, 임시 선택 — 추후 교체 가능하도록 서비스 레이어는 모델에 종속되지 않게 추상화할 것)
- **신뢰도(confidence) 산출 로직 불필요**
- **LLM 호출 실패 시 재시도 로직 불필요** — 단, 블록 단위 예외 처리(아래 참고)는 필요

## 전체 원칙: Rule-based / LLM 하이브리드

| 영역 | 방식 | 이유 |
|---|---|---|
| 출결, 성적, 수상, 봉사, 독서 | Rule-based (정규식 + 표 파서) | 포맷 고정, 빠르고 정밀하며 비용 없음 |
| 세특, 창체(자율/동아리/진로), 행특 | LLM (DeepSeek, 비동기 병렬) | 자유 서술형 텍스트, 문맥 이해 필요 |

---

## 1. Rule-based 추출

### 1.1 텍스트 & 표 분리
- PyMuPDF로 전체 원문 텍스트 추출
- pdfplumber로 표 영역 구조화 추출 (`extract_tables()`)

### 1.2 섹션 분리
생기부는 `1. 인적사항` ~ `10. 행동특성 및 종합의견` 순서의 고정 번호 체계를 가짐. 정규식으로 헤더를 찾아 원문을 섹션 단위로 분할한다.

```python
SECTION_PATTERN = re.compile(
    r"^\d+\.\s*(인적사항|학적사항|출결상황|수상경력|자격증.*|"
    r"진로희망사항|창의적체험활동상황|동아리활동|봉사활동실적|"
    r"교과학습발달상황|독서활동상황|행동특성 및 종합의견)"
)
```

### 1.3 성적 파싱
- 패턴: `단위수 + 원점수/과목평균(표준편차) + 성취도(수강자수) + 석차등급`
- 학년 매핑: `[1학년]`, `[2학년]` 헤더의 텍스트 오프셋을 기록해두고, 각 성적 패턴이 어느 학년 헤더 다음에 위치하는지로 학년을 결정
- **학기 매핑 (수정)**: 인접 패턴 간 문자 간격으로 학기를 추정하지 않는다. 원문에 명시된 `1학기`, `2학기` 라벨을 앵커로 잡고, 그 라벨 다음에 오는 성적 패턴들을 해당 학기로 매핑한다. 학년과 동일한 방식(라벨 오프셋 기반)을 적용할 것.
- `achievement_grade`, `student_count`는 `r"([A-E])\((\d+)\)"`로 분리 저장 (합쳐서 저장하지 않음)

### 1.4 수상 / 봉사 / 독서
- pdfplumber 표 추출 결과를 `학년 | 항목 | 내용` 형태로 정제 후 딕셔너리 변환
- 병합 셀로 인한 빈 행은 이전 행의 학년/과목 값을 상태 변수로 유지하며 보정

### 1.5 출결
- **수정**: 학년 숫자 뒤 일수 숫자들을 위치 순서로만 추출하지 않는다. `결석일수`, `지각`, `조퇴`, `결과` 등 **라벨 텍스트를 앵커로 삼고 해당 라벨 주변의 숫자를 매칭**하는 방식으로 구현한다. 학교별 서식 차이(열 추가/순서 변경)에 안전하도록.

---

## 2. LLM 추출 (DeepSeek)

### 2.1 전처리 — 블록 슬라이싱
- 세특: `과목명 :` 패턴으로 분할하되, **1.3에서 이미 규칙 기반으로 추출한 정식 과목명 리스트를 화이트리스트로 사용**하여 분할 지점을 매칭한다. `국어:`, `국어 :`, `국어Ⅰ:`, `한국사(1학기):` 등 표기 변형을 정규식 하나로 처리하려 하지 말 것 — 성적 섹션 파싱 결과를 세특 분할기에 전달하는 구조로 구현.
- 창체/행특: `[1학년]`, `1학기` 등 학년/학기 헤더 패턴으로 분할
- 각 블록에 학년/학기/과목 메타데이터 태깅

### 2.2 노이즈 정제
- 생기부 하단 반복 삽입되는 발급 정보(학교명, 날짜, 이름 등)를 LLM 호출 전 정규식으로 제거

### 2.3 영역별 LLM 호출
- 세특: "이 텍스트에서 교과 역량 평가와 구체적 탐구 활동/프로젝트를 각각 별개 객체로 분리하여 추출하라"
- 창체: "활동 내용을 자율/동아리/진로/봉사로 분류하고, 단순 참여보다 주도적 경험을 중심으로 추출하라"
- 행특: "담임교사 관찰 내용에서 인성, 학업태도, 종합평가를 긍정 역량 중심으로 각각 분리 추출하라"
- 모든 프롬프트는 JSON 배열 강제 출력 (`response_format: json_object`), 마크다운/부가설명 없이 순수 JSON만 반환하도록 지시
- 프롬프트에 few-shot 예시 최소 1개 포함 (활동 세분화 판단 정확도를 위해 필수)

### 2.4 병렬 처리
- `asyncio.Semaphore`로 동시성 제어
- **수정**: 초기값을 100이 아닌 **10~20**으로 설정. DeepSeek API의 실제 계정 티어별 rate limit을 확인 후 점진적으로 상향 조정할 것.

### 2.5 블록 단위 예외 처리 (재시도 아님 — 필수 구현)
재시도 로직은 없지만, 한 블록의 실패가 전체 배치를 중단시켜서는 안 된다. 각 블록 호출은 다음과 같이 감싼다.

```python
async def parse_block(block: TextBlock) -> list[Activity] | None:
    try:
        raw = await call_deepseek(block)
        return [Activity.model_validate(item) for item in json.loads(raw)]
    except Exception as e:
        logger.warning(f"block parse failed: block_id={block.id}, error={e}")
        return None  # 이 블록만 결과에서 누락, 나머지는 계속 진행
```
- JSON 파싱 실패, 스키마 검증 실패, API 에러 모두 이 방식으로 처리
- 실패한 블록은 최종 응답의 `errors` 배열에 `block_id`와 사유를 기록 (신뢰도 점수는 계산하지 않되, 실패 자체는 로그와 응답에 남길 것)

---

## 3. 최종 병합

Rule-based 결과(출결/성적/수상/봉사/독서)와 LLM 결과(활동 타임라인)를 `SeteukAnalysisResult` 스키마로 병합하여 반환한다. `parsing_confidence` 필드는 이번 구현 범위에서 제외한다.

---

## 4. 출력 JSON 형식

파서의 최종 반환 형식은 아래와 같다. `academic_performance`의 `achievement_grade`/`student_count`는 분리 저장하고(`AAA(236)` 형태로 합치지 않음), `awards`/`volunteer_records`의 `date`는 ISO 8601로 정규화하되 원문은 `raw_date`에 보존한다. `parsing_confidence`, 재시도 관련 필드는 포함하지 않는다.

```json
{
  "attendance": [
    {
      "grade": 2,
      "total_days": 190,
      "absence": 1,
      "note": "질병 결석 1일"
    }
  ],
  "academic_performance": [
    {
      "grade": 2,
      "semester": 1,
      "category": "수학",
      "subject": "수학Ⅰ",
      "units": 4,
      "achievement_grade": "A",
      "student_count": 236,
      "raw_score": 96,
      "subject_average": 78.4,
      "std_deviation": 12.1,
      "rank": ""
    }
  ],
  "reading_activities": [
    {
      "grade": 2,
      "semester": 1,
      "subject": "생명과학",
      "title": "이기적 유전자",
      "author": "리처드 도킨스"
    }
  ],
  "awards": [
    {
      "name": "수학 경시대회",
      "rank": "금상(1위)",
      "date": "2023-05-20",
      "raw_date": "2023.05.20"
    }
  ],
  "volunteer_records": [
    {
      "grade": 2,
      "date": "2023-07-15",
      "raw_date": "2023.07.15",
      "place": "지역아동센터",
      "content": "학습 멘토링",
      "hours": 8
    }
  ],
  "activities": [
    {
      "grade": 2,
      "semester": 1,
      "activity_category": "과목세부특기사항",
      "subject": "수학Ⅰ",
      "activity_name": "감염병 확산과 지수함수 모델",
      "activity_type": "report",
      "role": "",
      "description": "감염병 확산 초기 단계를 지수함수로 모델링하고, 실제 데이터와 비교하여 한계를 분석함",
      "keywords": ["수학적 모델링", "감염병", "지수함수"],
      "source_block": "(원문 텍스트 블록)"
    },
    {
      "grade": 2,
      "semester": 1,
      "activity_category": "과목세부특기사항",
      "subject": "수학Ⅰ",
      "activity_name": "학급 발표",
      "activity_type": "presentation",
      "role": "",
      "description": "탐구보고서 내용을 급우들에게 발표하며 원리를 설명함",
      "keywords": ["발표", "의사소통"],
      "source_block": "(원문 텍스트 블록)"
    },
    {
      "grade": 2,
      "semester": 2,
      "activity_category": "동아리활동",
      "subject": "",
      "activity_name": "생명과학 동아리 부장",
      "activity_type": "project",
      "role": "부장",
      "description": "동아리 부장으로서 학기 프로젝트를 기획하고 실험 데이터를 수집함",
      "keywords": ["리더십", "데이터 수집"],
      "source_block": "(원문 텍스트 블록)"
    }
  ],
  "errors": [
    {
      "block_id": "activities_2-2_동아리활동_03",
      "reason": "JSONDecodeError: LLM 응답이 유효한 JSON 배열이 아님"
    }
  ]
}
```

- `errors`는 문자열 배열이 아니라 `{ "block_id": string, "reason": string }` 객체 배열로 구성한다 — 어떤 블록이 왜 실패했는지 추적 가능하게 하기 위함 (2.5절 블록 단위 예외 처리와 연결).
- `activities` 배열은 세특 한 문단에서 여러 개별 활동이 분리되어 나올 수 있으므로, 원본 문단 수보다 배열 길이가 많을 수 있다.
