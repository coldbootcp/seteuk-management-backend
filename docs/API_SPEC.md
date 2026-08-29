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
| `diagnoses` | id, user_id, status, failure_reason, semester_summaries, domain_feedback, career_thread, overall_summary, strengths, weaknesses, career_gap_analysis, keyword_map | |
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
PDF 원본은 저장하지 않는다.

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
  "semester_summaries": [{ "grade": 2, "semester": 1, "summary": "…",
                           "standout_activities": ["…"] }],
  "domain_feedback": [{ "domain": "성적", "feedback": "…" }],
  "career_thread": [{ "grade": 1, "semester": 1, "type": "completed",
                      "theme": "…", "source": "…", "connection": "…" }],
  "overall_summary": "…", "strengths": ["…"], "weaknesses": ["…"],
  "career_gap_analysis": "…", "keyword_map": ["…"]
}
```

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
                              "keywords": ["…"], "source_activity_id": "uuid 또는 null" }] }],
  "created_plan_items": [ … ] }
```
현재 학기 **다음**부터 목표 학기까지가 대상이다. `replace_existing`이 true여도
지워지는 것은 **대상 구간의 손대지 않은(`planned`) AI 로드맵 항목뿐**이며, 학생이
직접 세웠거나 이미 진행 중인 계획은 유지된다.

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
- 프로세스가 죽어 `processing`에 멈춘 파싱/진단 job은 서버 기동 시 실패로 확정된다
  (`STALE_JOB_TIMEOUT_MINUTES`).
