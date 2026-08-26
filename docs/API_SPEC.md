# 세특연구소 백엔드 개발 계획 및 API 명세서 (v2)

## 1. 전체 개발 로드맵

기능 의존성 순서에 따라 단계를 나눕니다. 각 단계는 이전 단계의 API/스키마를 기반으로 하므로 순서를 지키는 것을 권장합니다. (결제/구독은 이번 범위에서 제외)

### Phase 0. 기반 구축
- FastAPI 프로젝트 스캐폴딩, Docker 구성
- PostgreSQL 스키마 설계 및 Alembic 마이그레이션 초기화
- JWT 인증 (회원가입/로그인/토큰 재발급), 카카오 소셜 로그인
- CI/CD (GitHub Actions) + Railway/Fly.io 배포 파이프라인
- Sentry, structlog 초기 세팅

### Phase 1. 생기부 파서
- 생기부 파일 업로드 API (PDF/이미지)
- LLM 기반 파싱 서비스: 출결, 교과성적, 독서활동, 수상경력, 봉사활동, 활동(자율/동아리/진로/세특/행발) 추출
- 세특 문단 내 개별 활동(보고서/발표/실험 등) 세분화 로직 (`activity_type`)
- 파싱 신뢰도 산출 및 저장, 원문 블록 보존
- 파싱 결과 저장/조회 API

### Phase 2. 기능1 — 학생부 DNA 진단
- 학생 프로필 입력 API (필수/선택 2단계, 생기부 업로드 시 자동 채움 지원)
- LLM 진단 서비스 레이어 (프롬프트 설계, 구조화 출력 검증, 재시도 로직)
- 진단 결과 저장/조회 API
- 온보딩 플로우: 회원가입 → (선택) 생기부 업로드 → 필수 정보 입력/확인 → 진단 실행 → AI 탭 이동

### Phase 3. AI 챗봇 대화
- 대화 세션/메시지 테이블 설계
- SSE 스트리밍 응답 엔드포인트
- 컨텍스트 조립 로직 (프로필 + 최근 활동 + 최근 대화 이력)
- `<수정>` 모드: 별도 시스템 프롬프트, 수정 제안 → 사용자 확인 → 프로필 반영 흐름

### Phase 4. 탭 관리 — 성적 / 독서 / 활동
- 파서 결과 기반 각 리소스 CRUD API (출결, 교과성적, 독서활동, 수상, 봉사, 활동)
- 목록 조회 시 페이지네이션/필터(과목, 학년, 학기 등)
- 파싱 결과를 사용자가 직접 수정/보완할 수 있는 편집 API

### Phase 5. 기능2 — 이전 활동 기반 후속 탐구 추천
- 활동 선택(`activity_type` 기반 필터) → LLM 추천 서비스 호출 → 추천 결과 저장/조회
- 추천 결과와 원본 활동 간 연결 관계 저장 (후속 확장 이력 추적용)

### Phase 6. 모니터링 및 안정화
- LLM 호출 실패율, 응답시간 대시보드
- 파싱 신뢰도 낮은 케이스 재검토 플로우
- Rate limiting (무료 진단 남용 방지)
- 부하 테스트 및 로그 기반 프롬프트 튜닝

---

## 2. 데이터 모델 개요

| 테이블 | 주요 필드 | 비고 |
|---|---|---|
| `users` | id, email, kakao_id, created_at | 인증 기본 |
| `seteuk_uploads` | id, user_id, parsing_confidence, status, raw_result, created_at | 생기부 업로드 이력 (PDF 원본은 저장하지 않고 파싱에만 사용) |
| `attendance` | id, user_id, source_upload_id, grade, total_days, absence, note | 출결 상황 |
| `academic_performance` | id, user_id, source_upload_id, grade, semester, category, subject, units, achievement_grade, student_count, raw_score, subject_average, std_deviation, rank | 교과 성적 |
| `reading_activities` | id, user_id, source_upload_id, grade, semester, subject, title, author | 독서 활동 |
| `awards` | id, user_id, source_upload_id, name, rank, date, raw_date | 수상 경력 (date는 ISO 8601 정규화, raw_date는 원문 보존) |
| `volunteer_records` | id, user_id, source_upload_id, grade, date, raw_date, place, content, hours | 봉사 활동 |
| `activities` | id, user_id, source_upload_id, grade, semester, activity_category, subject, activity_name, activity_type, role, description, keywords(JSONB), source_block, parsing_confidence | 자율/동아리/진로/세특/행발 통합 타임라인 |

위 6개 테이블은 모두 `source_upload_id`(nullable, `seteuk_uploads.id` FK)를 가집니다. 생기부 업로드로 만들어진 행만 이 값이 채워지며, 수동 입력(향후 탭 관리 편집 등)은 null입니다. 같은 사용자가 생기부를 다시 업로드하면 `source_upload_id`가 채워진 기존 행만 삭제 후 새 결과로 교체되고, null인(수동 입력) 행은 그대로 유지됩니다.
| `student_profiles` | user_id, grade, career_goal, interests, favorite_subjects, current_subject, self_assessed_strengths, self_assessed_weaknesses | 필수 입력 (생기부 업로드 시 자동 채움 가능) |
| `student_profile_optional` | user_id, target_department, current_assignment | 선택 입력 (독서/동아리/보고서는 위 테이블과 연동) |
| `diagnoses` | id, user_id, narrative_summary, strengths(JSONB), weaknesses(JSONB), risk_directions(JSONB), recommendations(JSONB), keyword_map(JSONB), created_at | 기능1 결과 |
| `conversations` | id, user_id, created_at | 대화 세션 |
| `messages` | id, conversation_id, role, content, mode(normal/edit), created_at | 챗봇 대화 |
| `recommendations` | id, user_id, source_activity_id, topic, connection_reason, subject_relevance, career_relevance, difficulty, materials(JSONB), expected_output, expansion_potential | 기능2 결과 |

`activity_type`은 `report | presentation | experiment | project | reading_linked | other` 중 하나이며, `activity_category`는 `과목세부특기사항 | 자율활동 | 동아리활동 | 진로활동 | 행동특성및종합의견` 중 하나입니다.

---

## 3. API 명세서

Base URL: `/api/v1`
인증: `Authorization: Bearer {access_token}` (로그인/회원가입 제외 전 구간 필수)

### 3.1 인증 (Auth)

**POST /auth/signup**
```json
// Request
{ "email": "student@example.com", "password": "string" }
// Response 201
{ "user_id": "uuid", "access_token": "string", "refresh_token": "string" }
```

**POST /auth/login**
```json
{ "email": "string", "password": "string" }
// Response 200
{ "access_token": "string", "refresh_token": "string" }
```

**POST /auth/social/kakao**
```json
{ "kakao_access_token": "string" }
// Response 200 (신규면 201)
{ "access_token": "string", "refresh_token": "string", "is_new_user": true }
```

**POST /auth/refresh**
```json
{ "refresh_token": "string" }
// Response 200
{ "access_token": "string" }
```

**POST /auth/logout** — 204 No Content

---

### 3.2 생기부 파서

**POST /seteuk/uploads** (파일 업로드, multipart/form-data) — 별도 확인/적용 단계 없이,
파싱이 끝나면(`status: done`) 결과가 자동으로 출결/성적/독서/수상/봉사/활동 테이블에
반영됨. PDF 원본은 파싱에만 쓰이고 저장하지 않음. 같은 사용자가 다시 업로드하면 이전
생기부 업로드로 채워진 행만 삭제 후 새 결과로 교체(수동 입력 데이터는 유지).
```json
// Response 201
{ "upload_id": "uuid", "status": "processing" }
```

**GET /seteuk/uploads/{upload_id}** — 처리 상태 조회
```json
// Response 200
{ "status": "done", "parsing_confidence": 0.92 }
// status: processing(파싱 및 저장 진행 중) | done(파싱+DB 반영 완료) | failed
```

**GET /seteuk/uploads/{upload_id}/result** — 파싱 결과 전체 조회
```json
// Response 200
{
  "attendance": [{ "grade": 2, "total_days": 190, "absence": 1, "note": "질병 결석 1일" }],
  "academic_performance": [{
    "grade": 2, "semester": 1, "category": "수학", "subject": "수학Ⅰ",
    "units": 4, "achievement_grade": "A", "student_count": 236,
    "raw_score": 96, "subject_average": 78.4, "std_deviation": 12.1, "rank": ""
  }],
  "reading_activities": [{ "grade": 2, "semester": 1, "subject": "생명과학", "title": "이기적 유전자", "author": "리처드 도킨스" }],
  "awards": [{ "name": "수학 경시대회", "rank": "금상(1위)", "date": "2023-05-20" }],
  "volunteer_records": [{ "grade": 2, "date": "2023-07-15", "place": "지역아동센터", "content": "학습 멘토링", "hours": 8 }],
  "activities": [{
    "grade": 2, "semester": 1, "activity_category": "과목세부특기사항", "subject": "수학Ⅰ",
    "activity_name": "감염병 확산과 지수함수 모델", "activity_type": "report", "role": "",
    "description": "string", "keywords": ["수학적 모델링", "감염병"], "parsing_confidence": 0.95
  }],
  "errors": []
}
```

---

### 3.3 학생 프로필 & 진단 (기능1)

**POST /profile**
```json
{
  "grade": 2,
  "career_goal": "데이터 기반 의학 연구",
  "interests": ["생명과학", "통계"],
  "favorite_subjects": ["수학", "생명과학"],
  "past_activities": [{ "activity_id": "uuid" }]
}
// Response 201
{ "profile_id": "uuid" }
```

**PATCH /profile/optional**
```json
{ "target_department": "의예과", "current_assignment": "string" }
// Response 200
```

**GET /profile/me** — 현재 프로필 전체 조회 (필수+선택 병합)

**POST /diagnosis**
```json
// Response 201
{
  "diagnosis_id": "uuid",
  "narrative_summary": "string",
  "strengths": ["string"],
  "weaknesses": ["string"],
  "risk_directions": ["string"],
  "recommendations": ["string"],
  "keyword_map": ["string"]
}
```

**GET /diagnosis/latest**
**GET /diagnosis/{diagnosis_id}**

---

### 3.4 AI 챗봇 대화

**POST /conversations**
```json
{ "conversation_id": "uuid" }
```

**GET /conversations/{conversation_id}/messages**

**POST /conversations/{conversation_id}/messages** (SSE 스트리밍)
```json
{ "content": "저는 사실 의대보다 생명공학 쪽에 관심이 더 커요", "mode": "edit" }
```
```
// Response: text/event-stream
event: token
data: {"delta": "말씀"}

event: done
data: {"message_id": "uuid", "edit_proposal": {"career_goal": "생명공학 연구"} }
```

**POST /conversations/{conversation_id}/messages/{message_id}/confirm-edit**
```json
{ "accepted": true, "final_values": { "career_goal": "생명공학 연구" } }
// Response 200
```

---

### 3.5 탭 관리 — 출결 / 성적 / 독서 / 수상 / 봉사 / 활동

각 리소스는 동일한 CRUD 패턴을 따릅니다.

**GET /academic-performance?grade=2&semester=1**
```json
{ "items": [{ "id": "uuid", "subject": "수학Ⅰ", "achievement_grade": "A", "student_count": 236, "raw_score": 96 }], "total": 8 }
```

**GET /activities?activity_type=report&subject=수학**
```json
{ "items": [{ "id": "uuid", "activity_name": "string", "activity_type": "report", "description": "string" }], "total": 5 }
```

**POST /activities**
```json
{ "activity_category": "과목세부특기사항", "subject": "수학Ⅰ", "activity_name": "string", "activity_type": "report", "description": "string", "keywords": ["string"] }
// Response 201
{ "id": "uuid" }
```

**PATCH /activities/{id}** — 부분 수정 (파싱 결과 사용자 보정 포함)
**DELETE /activities/{id}** — 204 No Content

동일한 패턴으로 `/attendance`, `/reading-activities`, `/awards`, `/volunteer-records`도 제공합니다.

---

### 3.6 후속 탐구 추천 (기능2)

**POST /recommendations/follow-up**
```json
{ "source_activity_id": "uuid", "desired_activity_type": "report" }
// Response 201
{
  "recommendation_id": "uuid",
  "options": [
    {
      "topic": "로지스틱 함수로 분석한 감염병 확산 모델의 한계",
      "connection_reason": "string",
      "subject_relevance": "string",
      "career_relevance": "string",
      "record_potential": "string",
      "difficulty": "medium",
      "materials": ["string"],
      "expected_output": "string",
      "expansion_potential": "string"
    }
  ]
}
```

**GET /recommendations/{id}**

---

## 4. 공통 규칙

- 모든 에러 응답: `{ "error_code": "string", "message": "string" }`
- LLM 호출 실패 시: `503 { "error_code": "LLM_UNAVAILABLE", "message": "잠시 후 다시 시도해주세요" }` + 클라이언트 재시도 버튼 노출
- 생기부 파싱 실패/저신뢰도 시: `parsing_confidence < 0.6`인 섹션은 응답에 `low_confidence: true` 플래그 포함, 클라이언트는 사용자 확인 UI 노출
- 날짜/시간: 모든 timestamp는 ISO 8601 UTC, 원문 날짜가 필요한 필드는 `raw_date`로 별도 보존