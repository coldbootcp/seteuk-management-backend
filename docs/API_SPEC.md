# 세특연구소 백엔드 API 명세서 (v3)

이 문서는 **실제 구현과 일치하는 명세**다. 코드가 바뀌면 여기도 함께 고친다.
엔드포인트를 추가하기 전에 이 문서와 어긋나지 않는지 먼저 확인할 것.

## 0. 서비스가 하는 일

고등학생이 3년에 걸친 세특 활동을 **기록하고, 그 유기적 연결을 관리하고, 다음 단계를
계획하는** 플랫폼의 백엔드다. 두 축이 있다.

1. **현재를 기록한다** — 생기부 업로드 또는 온보딩 질문으로 출발해, 이후 활동·성적·
   수행평가·독서가 생길 때마다 각 탭이나 챗봇으로 쌓는다. 진단이 현재 상태를 서사로
   정리하고 강점/약점을 짚는다.
2. **미래를 계획한다** — 생기부의 핵심은 활동이 학년이 오를수록 고도화되는 것이다.
   AI가 학기별 로드맵과 후속 탐구를 제안하고, 계획은 완료되면 실제 기록으로 승격되며
   그 계보(`parent_activity_id`)가 남는다.

이 "계획 → 실행 → 기록 → 다음 계획" 루프와 활동 계보가 범용 LLM과의 차별점이다.

## 1. 개발 로드맵 진행 상황

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 기반 구축 — FastAPI, Docker, Alembic, JWT, 카카오 로그인, CI | 완료 |
| 1 | 생기부 파서 (규칙기반 + LLM 하이브리드) | 완료 |
| 2 | 기능1 — 진단 (3단계 LLM 파이프라인) | 완료 |
| 3 | AI 챗봇 (SSE 스트리밍, '수정' 모드 도구 호출) | 완료 |
| 4 | 탭 관리 (6개 리소스 CRUD + 계획/로드맵) | 완료 |
| 5 | 기능2 — 후속 탐구 추천 | 완료 |
| 6 | 모니터링 — structlog, Sentry, rate limiting, 좀비 job 정리 | 완료 |

결제/구독은 범위 밖이다. 임의로 구현하지 말 것.

---

## 2. 데이터 모델

### 2.1 두 트랙 원칙

데이터는 성격에 따라 나뉜다.

- **생기부발 공식 기록** — 학년-학기 단위, `source_upload_id`가 채워짐.
- **사용자 직접 입력** — 같은 테이블이지만 `source_upload_id`가 null.
- **주관적 답변(`student_interests`)** — 진로 희망, 관심 키워드, 제약 조건처럼 시간에
  따라 바뀌는 것. 필드별 이력 로그이며, 같은 `field_key`를 7일 이내 다시 쓰면
  `answered_at`을 유지한 채 값만 덮어쓴다(같은 주의 수정은 새 선언이 아니다).
- **이력이 필요 없는 사실** — `users.name` / `current_grade` / `current_semester`.

생기부를 다시 업로드하면 `source_upload_id`가 채워진 행만 지우고 교체한다.
직접 입력한 행은 그대로 남는다.

### 2.2 테이블

| 테이블 | 주요 필드 | 비고 |
|---|---|---|
| `users` | id, email, password_hash, kakao_id, name, current_grade, current_semester | |
| `refresh_tokens` | id(=jti), user_id, expires_at, revoked_at | 로그아웃으로 개별 토큰 무효화 |
| `seteuk_uploads` | id, user_id, status, parsing_confidence, raw_result, failure_reason | PDF 원본은 저장하지 않음 |
| `attendance` | id, user_id, source_upload_id, grade, total_days, absence, note | |
| `academic_performance` | …, grade, semester, category, subject, units, achievement_grade, student_count, raw_score, subject_average, std_deviation, rank | |
| `reading_activities` | …, grade, semester, subject, title, author | |
| `awards` | …, name, rank, date, raw_date | date는 ISO 8601, 원문은 raw_date |
| `volunteer_records` | …, grade, date, raw_date, place, content, hours | |
| `activities` | …, **parent_activity_id**, grade, semester, activity_category, subject, activity_name, activity_type, role, description, keywords, source_block, parsing_confidence | 활동 계보의 기록 쪽 절반 |
| `plan_items` | id, user_id, item_type, title, description, subject, target_grade, target_semester, due_date, status, origin, source_activity_id, source_recommendation_id, completed_activity_id, completed_reading_id, keywords | 미래 계획 / 로드맵 |
| `student_interests` | id, user_id, field_key, value(JSONB), answered_at, updated_at | 챗봇의 장기 메모리 |
| `diagnoses` | id, user_id, status, failure_reason, grades_trend, semester_reviews, career_thread, activity_inventory, knowledge_graph_links, strengths, weaknesses, opportunities, threats, headline_comment | 서로 독립적으로 계산되는 섹션들 — §3.4 참고 |
| `recommendations` | id, user_id, source_activity_id, desired_activity_type, options(JSONB) | 기능2 |
| `conversations` | id, user_id, title, created_at, updated_at | |
| `messages` | id, conversation_id, role, content, mode, applied_actions(JSONB) | |
| `usage_events` | id, user_id, action, created_at | 사용량 한도 카운터 |

### 2.3 enum

- `activity_category`: `과목세부특기사항 | 자율활동 | 동아리활동 | 진로활동 |
  행동특성및종합의견` (생기부 파서가 채움) + `수행평가 | 교외활동 | 기타`
  (학생이 직접 기록)
- `activity_type`: `report | presentation | experiment | project | reading_linked | other`
- `plan_items.item_type`: `activity | reading | assessment | grade | volunteer | award | other`
- `plan_items.status`: `planned | in_progress | done | dropped`
- `plan_items.origin`: `user | ai_roadmap | recommendation | chatbot`
- 챗봇 `mode`: `normal | edit`

### 2.4 활동 계보

3년간의 고도화를 추적하는 뼈대다.

```
activities.parent_activity_id  →  activities.id      (이미 한 활동 사이의 연결)
plan_items.source_activity_id  →  activities.id      (아직 안 한 계획이 매달린 지점)
plan_items.completed_activity_id → activities.id     (계획이 승격되며 생긴 기록)
```

계획을 완료 처리하면 `source_activity_id`가 새 활동의 `parent_activity_id`로 복사되어
사슬이 이어진다. `GET /activities/{id}/lineage`가 사슬 전체(과거 활동 + 미래 계획)를
한 번에 돌려준다.

---

## 3. API

Base URL: `/api/v1`
인증: `Authorization: Bearer {access_token}` (auth 엔드포인트 제외 전 구간 필수)

### 3.1 인증

**POST /auth/signup** → 201 `{ user_id, access_token, refresh_token }`
```json
{ "email": "student@example.com", "password": "string" }
```

**POST /auth/login** → 200 `{ access_token, refresh_token }`

**POST /auth/social/kakao** → 200 `{ access_token, refresh_token, is_new_user }`
```json
{ "kakao_access_token": "string" }
```
클라이언트가 카카오 SDK로 받은 access token을 보내면 서버가 카카오 API로 검증한다.
이미 같은 이메일로 가입된 계정이 있으면 새 계정을 만들지 않고 연결한다. 이메일 제공에
동의하지 않은 사용자도 가입된다.

**POST /auth/refresh** → 200 `{ access_token }`
```json
{ "refresh_token": "string" }
```

**POST /auth/logout** → 204
```json
{ "refresh_token": "string" }
```
해당 refresh 토큰만 무효화한다(다른 기기 세션은 유지). 이미 무효화된 토큰으로 다시
호출해도 204다.

### 3.2 생기부 파서

**POST /seteuk/uploads** (multipart/form-data, `file`) → 201 `{ upload_id, status }`
파싱이 끝나면 결과가 6개 도메인 테이블에 자동 반영된다. 별도 확인/적용 단계는 없다.
**업로드한 PDF 원본은 계정에 보관된다**(통합 결정 P-1 — 예전 방침을 뒤집었다).
학생이 나중에 자기가 올린 파일을 다시 확인할 수 있어야 하기 때문이다. 원본은
진단·챗봇 컨텍스트에 절대 싣지 않으며, `GET /seteuk/uploads/{id}/file`로 내려받는다.

파싱된 기록 중 사용자가 선언한 현재 학년-학기(`users.current_grade`/
`current_semester`)보다 **이후 시점의 기록은 저장하지 않는다**(온보딩 전이라
현재 학년-학기가 없으면 이 검사를 하지 않는다). 문서 자체가 잘못됐거나(다른
버전, 다른 사람 것) 프로필을 갱신하지 않은 채 더 최신 생기부를 다시 올린
경우, 아직 일어나지 않았어야 할 시점의 데이터가 진단·로드맵의 "현재 위치"
판단을 어긋나게 만들기 때문이다. 같은 학년의 학년 단위 기록(자율활동 등,
학기 구분이 없는 것)은 그 학년이 진행 중이면 허용한다. `awards`는
grade/semester가 없고 날짜만 있어 이 검사 대상이 아니다. 걸러진 게 있으면
`errors`에 `block_id: "future_grade_filter"`로 몇 건이 왜 빠졌는지 남는다.

**GET /seteuk/uploads/{upload_id}** → 200 `{ status, parsing_confidence }`
`status`: `processing | done | failed`

**GET /seteuk/uploads/{upload_id}/result** → 200
```json
{
  "attendance": [...], "academic_performance": [...], "reading_activities": [...],
  "awards": [...], "volunteer_records": [...], "activities": [...], "errors": []
}
```

### 3.3 프로필

**POST /profile** → 200 (온보딩 필수 입력)
```json
{
  "name": "홍길동", "grade": 2, "semester": 1,
  "career_goal": { "goal": "AI 연구원", "note": "string 또는 null" },
  "target_department": "컴퓨터공학과",
  "interest_keywords": ["머신러닝"],
  "career_specificity": { "level": "specific", "known_concepts": [], "curious_topics": [] },
  "preferred_output_types": ["report"],
  "activity_channels": ["동아리"],
  "roadmap_constraints": "string 또는 null",
  "self_assessed_strengths": "string",
  "self_assessed_weaknesses": "string"
}
```

**GET /profile/me** → 200 — `users` + `student_interests` 최신값 병합.

### 3.4 진단 (기능1)

**GET /diagnosis/pre-questions** → 200 `{ questions: [...] }`
최초 진단 전에만 동작한다(재진단이면 빈 배열). 생기부와 현재 답변의 갭을 보고 최대
5개 질문을 만든다.

**POST /diagnosis/pre-questions/answers** → 204
```json
{ "answers": [{ "key": "string", "prompt": "string", "answer": "string 또는 null" }] }
```
답변을 대화처럼 취급해 LLM 추출을 거친 뒤, durable하다고 판단된 것만
`student_interests`에 반영한다.

**POST /diagnosis** → 201 `{ diagnosis_id, status }` — 비동기 job.

**GET /diagnosis/{id}**, **GET /diagnosis/latest** → 200
```json
{
  "diagnosis_id": "uuid", "status": "done",
  "grades_trend": {
    "overall": [{ "grade": 2, "semester": 1, "average_rank": 2.27,
                  "subject_count": 11, "excluded_count": 5 }]
  },
  "semester_reviews": [{ "grade": 2, "semester": 1,
                         "grades_review": "…", "reading_review": "…",
                         "activities_review": "…" }],
  "career_thread": [{ "title": "버스 배차 최적화", "summary": "…",
                      "entries": [{ "grade": 1, "semester": "1 또는 null",
                                    "type": "completed", "theme": "…",
                                    "source": "…", "connection": "…" }] }],
  "activity_inventory": [{ "activity_id": "uuid", "grade": 2, "semester": 1,
                           "competency": "전공관련교과역량", "depth_level": "심화탐구",
                           "headline": "베벨기어 설계 및 발표" }],
  "knowledge_graph_links": [{ "from_activity_id": "uuid", "to_activity_id": "uuid",
                              "link_type": "vertical",
                              "relation_label": "지수함수 모델의 실측 데이터 검증" }],
  "strengths": ["…"], "weaknesses": ["…"], "opportunities": ["…"], "threats": ["…"],
  "headline_comment": "…"
}
```

진단은 생기부 입력만으로는 알 수 없는, 분석이 있어야 드러나는 내용을 저장하는
단계다. 이 응답은 그 저장된 내용을 보여줄 뿐이며, 서로 독립적으로 계산된
섹션들로 구성된다 — 하나의 LLM 호출로 전부를 종합하면 근거 없이 추상적으로
흐르기 쉽기 때문에, 각 섹션은 좁은 범위의 실제 데이터만 입력받아 그것을 읽기
좋은 형태로 옮기는 역할만 한다("LLM은 번역기, 저자가 아니다").

- **`grades_trend`** — LLM을 거치지 않는 순수 데이터. **학기별 평균 석차등급
  한 줄**이다(1에 가까울수록 좋으므로 세로축은 뒤집어 그린다). 과목별 개별 선은
  그리지 않는다 — 성적에서 읽어야 하는 것은 학기별 흐름이지 과목 하나하나의
  등락이 아니기 때문이다.

  석차등급이 없는 과목(진로선택·전문교과·P과목)은 **평균에서 뺀다.** 성취도
  A/B/C를 등급으로 환산하면 없는 숫자를 지어내는 것이기 때문이다. 실제 생기부
  샘플에서 이런 과목이 25%가량을 차지하므로, 몇 개가 빠졌는지를
  `excluded_count`로 함께 내려 평균이 그 학기 전체를 대표하는 것처럼 읽히지
  않게 한다. 등급이 매겨진 과목이 하나도 없는 학기는 `average_rank`가 null이고
  선에서 빠진다.
- **`semester_reviews`** — 학기당 1회 LLM 호출. **그 학기의** 성적/독서/활동
  원자료만 입력받아 세 개의 독립된 텍스트로 낸다. 자료가 없는 측면은 억지로
  채우지 않고 정직하게 "기록이 없다"고 쓴다.
- **`career_thread`** — **주제별 갈래의 목록**이다. 학생은 보통 여러 갈래를 동시에
  굴리므로(로봇 만들기 / 데이터 분석 / 지역 봉사), 시간순 평면 배열로 늘어놓으면
  무엇이 무엇의 심화인지 읽히지 않는다. 각 갈래는 제목·요약과 학년-학기 순으로
  정렬된 `entries`를 갖는다(정렬은 코드가 보증한다). 갈래는 진단 출력으로 끝나지
  않고 `activity_threads`에 저장되며 `activities.thread_id`가 채워진다.

  활동 전체(계보 `parent_activity_id` 포함) + 수상 + 봉사를
  함께 입력받는 1회 호출. 진로 관점에서 의미 있는 것만 사슬에 올리므로(중요하지
  않은 건 자동으로 빠짐), 활동뿐 아니라 수상·봉사도 노드가 될 수 있다. 과거
  (`completed`)와 학생의 현재 학년-학기 이후 제안(`suggested`)이 학년-학기 순으로
  한 배열에 담긴다. `semester`는 자율활동/진로활동처럼 원자료 자체가 학기 없이
  학년 단위로만 존재하는 근거를 든 `completed` 노드에 한해 `null`일 수 있다
  (`suggested` 노드는 항상 구체적인 학기를 갖는다 — 언제 할지 모르는 제안은
  실행 계획으로 옮길 수 없기 때문).
- **`activity_inventory`** — 학년 단위 배치 LLM 호출(활동이 많으면 출력이 잘릴
  위험이 있어 학년마다 나눠 부른다). `career_thread`와 달리 **필터링하지 않고
  전량**을 `competency`(전공관련교과역량/진로역량/공동체역량)와
  `depth_level`(단순참여/탐구시도/심화탐구)로 분류한다. 프론트는 학년-학기 ×
  역량 매트릭스에 카드로 배치하면 된다.
- **`knowledge_graph_links`** — **과목명이나 키워드로 후보를 미리 좁히지 않는다.**
  한국 고교 교육과정은 같은 과목이 여러 학기에 반복되는 경우가 드물어서
  (화학Ⅰ→화학Ⅱ처럼 과목명 자체가 바뀌며 심화된다) 문자열 매칭으로는 대부분의
  실제 연결을 놓친다 — 그리고 애초에 중요한 건 과목이 아니라 **활동의 내용이
  이어지는지**다(예: 정보 시간의 로봇 코딩과 동아리의 로봇 대회 참가는 과목이
  달라도 명백한 심화다). 대신 활동 전체 목록을 LLM에 통째로 주고 내용을 읽어
  직접 판단하게 한다(이미 `parent_activity_id`로 이어진 쌍은 제외). 활동이
  아주 많으면(현재 임계값 120건) 한 호출에 다 넣지 않고 인접한 두 학년씩 묶어
  나눠 부른 뒤 중복 링크를 병합한다. **이미 `parent_activity_id`로 이어진 쌍은
  응답에 나오지 않는다** — 그 연결은 `career_thread`와 계보 화면이 이미 다루므로
  그래프에 또 올리면 아무 정보도 더하지 못한다. 프롬프트로도 같은 규칙을 주지만
  LLM이 이를 무시하고 계보 쌍만 돌려주는 것이 실제로 관측돼, 서비스가 응답을
  받은 뒤 계보 쌍·자기 자신·방향만 뒤집힌 중복을 확정적으로 걸러낸다(프롬프트는
  부탁이고 필터가 보증이다). 그래서 이 배열은 **계보에 아직 안 잡힌 숨은 연결만**
  담으며, 그런 연결이 없으면 빈 배열일 수 있다. `link_type`은 같은 활동 계열이 학년이
  오르며 깊어진 `vertical`, 서로 다른 활동의 방법·소재가 결합한 `horizontal`
  중 하나. `relation_label`이 그 연결의 핵심 내용을 짧게 설명한다.
- **`strengths` / `weaknesses` / `opportunities` / `threats` / `headline_comment`**
  — 종합 평가(SWOT), 1회 호출. **원본 데이터가 아니라 `semester_reviews` /
  `career_thread` / `activity_inventory`의 결과만** 입력받아 생성된다.
  일반적인 경영 SWOT과 달리 이 서비스에는 "외부 입시 환경" 데이터가 없으므로,
  `opportunities`는 "아직 기록에 없지만 남은 기간에 채우면 강점이 될 수 있는
  것", `threats`는 "학기를 거듭해도 반복되거나 악화되는 내부 패턴"으로 이
  맥락에 맞게 재정의했다. `headline_comment`는 넷 중 가장 시급한 것 하나를
  1~3문장으로 짚는다.

`status`가 `done`이 아니면 모든 섹션이 빈 배열/`null`이다.

> **대학 적합도/전형 추천은 의도적으로 제외했다.** 실제 대학별 내신 산출식·
> 커트라인·전형 요강 데이터가 없는 상태에서 만들면 LLM이 그럴듯한 대학명과
> 점수를 지어내게 된다 — 실제 데이터를 확보하기 전까지는 넣지 않는다.

### 3.5 탭 관리 — 출결 / 성적 / 독서 / 수상 / 봉사 / 활동

6개 리소스가 동일한 CRUD 패턴을 따른다.

| 리소스 | 경로 | 필터 |
|---|---|---|
| 출결 | `/attendance` | grade |
| 교과 성적 | `/academic-performance` | grade, semester, subject, category |
| 독서 | `/reading-activities` | grade, semester, subject |
| 수상 | `/awards` | — |
| 봉사 | `/volunteer-records` | grade |
| 활동 | `/activities` | grade, semester, activity_category, activity_type, subject |

- **GET /{resource}** → `{ "items": [...], "total": 12 }` (공통 `limit`≤200, `offset`)
- **POST /{resource}** → 201, 생성된 행 전체
- **GET /{resource}/{id}** → 200
- **PATCH /{resource}/{id}** → 200 (부분 수정, 파싱 결과 보정 포함)
- **DELETE /{resource}/{id}** → 204

응답에는 읽기 전용 `source_upload_id`가 포함된다. null이면 직접 입력한 행이라
생기부 재업로드에도 살아남는다. 생성 요청으로는 이 값을 지정할 수 없다.

> 주의: 생기부에서 파싱된 행을 PATCH로 고친 뒤 생기부를 다시 업로드하면 그 수정은
> 새 파싱 결과로 교체된다. 유지되어야 하는 보정이라면 직접 입력 행으로 다시 만들 것.

**GET /activities/{id}/lineage** → 200
```json
{ "nodes": [
  { "kind": "activity", "id": "uuid", "title": "감염병 확산 모델", "grade": 2,
    "semester": 1, "status": "completed", "parent_id": null },
  { "kind": "plan", "id": "uuid", "title": "SIR 모델로 확장", "grade": 2,
    "semester": 2, "status": "planned", "parent_id": "uuid" }
] }
```
사슬의 어느 노드로 물어도 뿌리까지 거슬러 올라간 전체를 돌려준다. 이미 활동으로
승격된 계획은 그 활동 노드로 대체된다.

### 3.6 계획 & 로드맵

**GET /plans** → `{ items, total }` (필터: item_type, status, target_grade, target_semester)

**POST /plans** → 201
```json
{
  "item_type": "activity", "title": "SIR 모델로 확장",
  "description": "string 또는 null", "subject": "수학Ⅰ",
  "target_grade": 2, "target_semester": 2, "due_date": "2026-11-30",
  "keywords": ["감염병"], "source_activity_id": "uuid 또는 null",
  "source_recommendation_id": "uuid 또는 null"
}
```

**PATCH /plans/{id}** → 200 · **DELETE /plans/{id}** → 204

**POST /plans/{id}/complete** → 200
```json
// Request — 비우면 계획의 값과 사용자의 현재 학년/학기로 채운다
{ "grade": 2, "semester": 2, "activity_category": "과목세부특기사항",
  "activity_type": "report", "description": "…", "author": "…" }
// Response
{ "plan_item": { … , "status": "done" },
  "created_activity_id": "uuid 또는 null", "created_reading_id": "uuid 또는 null" }
```
`activity`/`assessment` 계획은 활동으로, `reading` 계획은 독서 기록으로 승격된다.
나머지 타입은 상태만 `done`이 된다. 이미 완료된 계획을 다시 완료하면 409
`INVALID_PLAN_TRANSITION`.

**POST /plans/roadmap** → 200
```json
// Request — 전부 선택
{ "until_grade": 3, "until_semester": 2, "focus": "string 또는 null",
  "replace_existing": true }
// Response
{ "semesters": [{ "grade": 2, "semester": 2, "theme": "…", "rationale": "…",
                  "items": [{ "item_type": "activity", "title": "…",
                              "description": "…", "subject": "…",
                              "keywords": ["…"], "source_activity_index": 3 }] }],
  "created_plan_items": [ … ] }
```
`semesters`는 LLM이 낸 초안 그대로다 — `source_activity_index`는 **그 호출 안에서만
유효한 정수**이며(LLM에게 UUID를 베끼게 하지 않으려고 쓰는 값), 클라이언트가 해석할
수 있는 식별자가 아니다. 실제로 어떤 활동에 계보가 붙었는지는 서버가 역참조를 끝낸
`created_plan_items[].source_activity_id`에서 읽어야 한다.

현재 학기 **다음**부터 목표 학기까지가 대상이다. `replace_existing`이 true여도
지워지는 것은 **대상 구간의 손대지 않은(`planned`) AI 로드맵 항목뿐**이며, 학생이
직접 세웠거나 이미 진행 중인 계획은 유지된다.

**GET /plans/roadmap-overview** → 200
```json
{
  "past": [{ "grade": 1, "summary": "기초 다지기 → 로봇 입문",
             "themes": ["기초 다지기", "로봇 입문"] }],
  "current": { "grade": 2, "semester": 1,
               "headline_comment": "가장 시급한 것은 독서 기록 부족입니다.",
               "weaknesses": ["…"] },
  "future": [{ "grade": 2, "semester": 2, "theme": "SIR 모델 심화",
               "plan_titles": ["SIR 모델 시뮬레이션"] }]
}
```
**새 LLM 호출이 없다.** 이미 있는 진단(`career_thread`, `headline_comment`,
`weaknesses`)과 계획(`plan_items`)을 과거/현재/미래 마일스톤 형태로 재배치만
한다 — `past`는 완료(`completed`) 노드를 학년별로 묶은 것, `current`는 사용자의
현재 학년-학기와 진단의 가장 시급한 지적, `future`는 제안(`suggested`) 노드의
테마와 그 학기에 이미 세워둔 계획 제목을 합친 것이다. 진단을 아직 안 돌렸으면
`past`가 비고 `current.headline_comment`가 `null`일 뿐, 계획만으로도 `future`는
채워진다. `career_thread`의 `completed` 노드 중 학기가 없는(`semester: null`)
것은 그 학년 안에서 맨 앞으로 정렬되고, `suggested` 노드는 학기가 없으면
마일스톤으로 배치할 수 없어 조용히 제외된다.

### 3.6b 3개년 서사 로드맵 & 정합

**POST /roadmaps** → 201 — 새 버전을 만든다. 이전 활성 버전은 지워지지 않고
`superseded`가 된다. 요청은 전부 선택(`focus`, `career_track`)이며 비우면 프로필에서
가져온다.

응답은 1-1부터 3-2까지 **6개 마디**다. 각 마디는 서사 단계(탐색 → 기초 → 연결 →
분화 → 독립 탐구 → 종합), 목표, 후보 과목, 역량 목표, 그리고 그 학기의 제안 주제
10개(`plan_events`, core 4 + optional 6)를 갖는다. 현재 학기보다 앞선 마디는
`narrative_stage: "회고"`, `status: "skipped"`이고 제안 주제가 비어 있다 — 이미
지나간 학기에 계획을 제안해도 학생이 할 수 있는 일이 없기 때문이다.

**GET /roadmaps/active** · **GET /roadmaps/{id}** · **POST /roadmaps/{id}/confirm**
(draft → active) · **PATCH /roadmaps/nodes/{id}** (학생이 제목·목표를 직접 수정)

**정합(Reconciliation)** — 활동을 저장하면(`POST /activities`) 그 자리에서 활성
노드와 대조해 판정을 남긴다. 로드맵이 없으면 조용히 넘어간다.

| 판정 | 의미 | 노드에 일어나는 일 |
|---|---|---|
| `MATCH` | 활동이 노드 목표와 직접 연결됨 | 노드 완료 + 다음 노드 활성화 |
| `PARTIAL_MATCH` | 일부만 충족 | 부분 충족으로 기록 + 다음 노드 활성화 |
| `DIVERGE` | 노드와 근거가 적음 | 바뀌지 않음 (이탈로 단정하지 않는다) |
| `MISS` | 학기가 지나도록 충족 활동이 없음 | 바뀌지 않음 (이월/건너뛰기는 학생이 결정) |
| `UNCLASSIFIABLE` | 활성 노드가 없음 | — |

판정에는 이유·조치·신뢰도가 함께 남고 **덮어쓰지 않는다.**

**GET /roadmaps/reconciliations/history** → 판정 이력
**POST /roadmaps/checkpoint** → 학기 체크포인트. 이미 지나간(또는 지금 끝나는)
학기의 활성 노드에 충족 활동이 없으면 `MISS`를 남기고, 남길 것이 없으면 `null`.
아직 오지 않은 학기에는 찍지 않으며 같은 노드에 두 번 쌓이지 않는다.

### 3.7 후속 탐구 추천 (기능2)

**POST /recommendations/follow-up** → 201
```json
// Request
{ "source_activity_id": "uuid", "desired_activity_type": "experiment",
  "note": "string 또는 null" }
// Response
{ "id": "uuid", "source_activity_id": "uuid", "desired_activity_type": "experiment",
  "options": [{
    "topic": "…", "connection_reason": "…", "subject_relevance": "…",
    "career_relevance": "…", "record_potential": "…", "difficulty": "medium",
    "materials": ["…"], "expected_output": "…", "expansion_potential": "…"
  }],
  "created_at": "…" }
```
프롬프트에는 대상 활동 하나가 아니라 그 활동의 **계보 사슬 전체**와 최신 진단이 함께
들어간다 — 범용 추천이 아니라 고도화 제안이어야 하기 때문이다.

**GET /recommendations**, **GET /recommendations/{id}**

**POST /recommendations/{id}/adopt** → 201 (생성된 계획)
```json
{ "option_index": 0, "item_type": "activity", "target_grade": 2, "target_semester": 2 }
```
선택지를 계획으로 담는다. 계획은 추천의 출처 활동을 물려받아, 나중에 완료하면 그
활동의 자식으로 기록된다.

### 3.7b 첨부파일 & 추천 피드백

**POST /activities/{activity_id}/attachments** (multipart, `file`) → 201
활동에 파일을 붙인다(수행평가 안내문, 보고서 등). 10MB까지. PDF면 본문 텍스트를
추출해 `extracted_text`로 보관한다 — 추출에 실패해도 첨부 자체는 성공한다.
LLM 컨텍스트에는 추출 텍스트만 실리고 파일 본문은 싣지 않는다.

**GET /activities/{activity_id}/attachments** → 목록(본문 제외)
**GET /activities/attachments/{id}/file** → 내려받기
**DELETE /activities/attachments/{id}** → 204

**POST /recommendations/{id}/feedback** → 201
```json
{ "option_index": 0, "action": "saved | rejected", "reason": "string 또는 null" }
```
추천 선택지에 대한 반응. **append-only다** — 같은 선택지에 마음이 바뀌어도 이전
기록을 고치지 않고 새 행을 쌓는다. "저장했다가 나중에 거절했다"는 것 자체가 다음
추천의 신호이기 때문이다.

**GET /recommendations/feedback/history** → 최신순 이력

### 3.8 AI 챗봇

**POST /conversations** → 201 `{ id, title, created_at, updated_at }`
**GET /conversations** → `{ items, total }` (최근 대화 순)
**DELETE /conversations/{id}** → 204
**GET /conversations/{id}/messages** → 200 메시지 배열

**POST /conversations/{id}/messages** → SSE (`text/event-stream`)
```json
{ "content": "이기적 유전자 읽었어요", "mode": "edit" }
```
```
event: action
data: {"tool": "add_reading", "arguments": {"title": "이기적 유전자"}, "result": {"reading_id": "uuid", "title": "이기적 유전자"}}

event: token
data: {"delta": "독서 기록에"}

event: done
data: {"message_id": "uuid", "applied_actions": [...]}

event: error
data: {"error_code": "LLM_UNAVAILABLE", "message": "잠시 후 다시 시도해주세요"}
```

**모드**

- `normal` — 도구를 전혀 넘기지 않는다. 개인화된 세특 메모리를 근거로 답하고 함께
  진로를 고민하는 역할만 한다. 이 모드에서는 어떤 것도 저장되지 않는다.
- `edit` — 사용자가 '수정' 토글을 켠 상태. 별도 확인 단계 없이 도구를 바로 실행한다
  (토글 자체가 동의다). 실행된 것은 `action` 이벤트로 흘러나오고 메시지의
  `applied_actions`에 남는다.

**수정 모드 도구** — `add_reading`, `add_activity`, `update_activity`, `add_award`,
`add_volunteer_record`, `add_academic_performance`, `add_plan`, `update_plan`,
`complete_plan`, `remember`(개인화 메모리), `update_profile_basics`, `run_diagnosis`,
`recommend_follow_up`.

> **삭제 도구는 의도적으로 없다.** 대화 중의 오해로 3년치 기록이 사라지는 사고를 막기
> 위해, 삭제는 탭의 DELETE 엔드포인트(명시적 조작)로만 가능하다.

챗봇의 개인화 재료는 매 요청마다 조립된다: 기본 정보 + `student_interests`(메모리) +
최신 진단 + 활동/성적/독서/수상/봉사/출결 + 진행 중인 계획 + 직전 20개 메시지. 각
영역에는 상한이 있고, 잘린 경우 `counts`에 전체 개수가 함께 들어가 챗봇이 "기록이 더
있다"는 사실을 알 수 있다.

---

## 4. 공통 규칙

### 4.1 에러

모든 에러는 `{ "error_code": "string", "message": "string" }` 형태다(검증 오류는
`details`가 추가된다).

| error_code | HTTP | 언제 |
|---|---|---|
| `VALIDATION_ERROR` | 422 | 요청 형식 오류 |
| `EMAIL_ALREADY_EXISTS` | 409 | 중복 가입 |
| `INVALID_CREDENTIALS` | 401 | 로그인 실패 |
| `INVALID_TOKEN` | 401 | 토큰 무효/만료/무효화됨 |
| `SOCIAL_AUTH_FAILED` | 401 | 카카오 토큰 검증 실패 |
| `USER_NOT_FOUND` | 404 | |
| `UNSUPPORTED_FILE` | 422 | 지원하지 않는 업로드 형식 |
| `UPLOAD_NOT_FOUND` / `UPLOAD_NOT_READY` | 404 / 409 | |
| `DIAGNOSIS_NOT_FOUND` / `DIAGNOSIS_NOT_READY` | 404 / 409 | |
| `RECORD_NOT_FOUND` | 404 | 탭 리소스 |
| `ACTIVITY_NOT_FOUND` | 404 | |
| `PLAN_ITEM_NOT_FOUND` | 404 | |
| `INVALID_PLAN_TRANSITION` | 409 | 이미 완료된 계획 재완료 등 |
| `CONVERSATION_NOT_FOUND` | 404 | |
| `RECOMMENDATION_NOT_FOUND` | 404 | 추천 또는 선택지 인덱스 없음 |
| `RATE_LIMITED` | 429 | 하루 사용량 초과 |
| `LLM_UNAVAILABLE` | 503 | LLM 3회 재시도 후 실패 |
| `INTERNAL_ERROR` | 500 | |

### 4.2 사용량 한도

사용자별 24시간 슬라이딩 윈도우. 기본값은 `.env.example` 참고.

| 작업 | 기본 한도/일 |
|---|---|
| 생기부 업로드 | 5 |
| 진단 | 5 |
| 로드맵 생성 | 10 |
| 후속 추천 | 20 |
| 챗봇 메시지 | 100 |

### 4.3 기타

- 모든 timestamp는 ISO 8601 UTC. 원문 날짜가 필요한 필드는 `raw_date`로 별도 보존.
- 모든 응답에 `X-Request-ID`가 붙는다. 클라이언트가 같은 헤더로 보내면 그 값을
  이어받아 로그와 대조할 수 있다.
- 헬스체크: `/health`(프로세스), `/health/ready`(DB 포함 — 배포 헬스체크는 이쪽).
- 웹 프론트엔드는 API와 다른 오리진에서 돌기 때문에 CORS가 필요하다. 허용 오리진은
  `CORS_ORIGINS`(콤마 구분)로 설정하며, 인증이 `Authorization` 헤더로만 이뤄지므로
  쿠키(`allow_credentials`)는 쓰지 않는다.
- 프로세스가 죽어 `processing`에 멈춘 파싱/진단 job은 서버 기동 시 실패로 확정된다
  (`STALE_JOB_TIMEOUT_MINUTES`).
