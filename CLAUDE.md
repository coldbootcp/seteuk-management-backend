# CLAUDE.md — 세특연구소 백엔드

이 파일은 개발 AI 에이전트(Claude Code 등)가 매 세션 시작 시 자동으로 읽는 프로젝트 컨텍스트입니다. 리포지토리 루트에 두세요.

## 프로젝트 개요

세특연구소는 학생부(생활기록부) 기반 AI 진단 및 후속 탐구 추천 서비스입니다.
- 사용자가 생기부를 업로드하거나 정보를 입력하면 AI가 학생부를 하나의 서사로 요약하고 강점/약점을 진단
- 이전 활동(보고서/발표 등)을 기반으로 "다음 단계" 탐구 주제를 추천 (범용 LLM과의 차별점)
- 웹(Next.js)과 별도 모바일 앱이 동일한 백엔드 API를 공유

## 기술 스택

| 영역 | 선택 |
|---|---|
| 프레임워크 | FastAPI (Python 3.11+) |
| DB | PostgreSQL + SQLAlchemy 2.0 + Alembic |
| 인증 | JWT (access + refresh), 카카오 소셜 로그인 |
| 실시간 응답 | SSE (`StreamingResponse`) — 챗봇 스트리밍 |
| LLM 연동 | Anthropic/OpenAI API, 구조화 출력 검증 (Pydantic + 재시도) |
| 배포 | Docker → Railway / Fly.io |
| 모니터링 | Sentry + structlog |
| 테스트 | pytest + pytest-asyncio |
| 린트/포맷 | ruff |

결제/구독은 현재 범위에서 제외되어 있습니다. 임의로 구현하지 마세요.

## 디렉토리 구조 (제안 — 아직 없다면 이 구조로 시작)

```
app/
  main.py
  core/           # config, security(JWT), dependencies
  db/             # session, base, alembic 연동
  models/         # SQLAlchemy 모델 (도메인별 파일 분리)
  schemas/        # Pydantic 스키마 (요청/응답, LLM 구조화 출력과 재사용)
  api/v1/         # 라우터: auth, seteuk, profile, diagnosis, conversations, activities, recommendations
  services/       # llm_service, parser_service, diagnosis_service, recommendation_service, chat_service
alembic/
tests/
  unit/
  integration/
docs/
  API_SPEC.md     # 전체 API 명세서 (별도 제공)
  PARSER_SPEC.md  # 생기부 파서 API 설명
```

## 개발 원칙

- **라우터에 비즈니스 로직을 넣지 않는다.** 라우터는 요청 검증 → 서비스 호출 → 응답 변환만 담당.
- **LLM 호출은 항상 서비스 레이어에서 재시도 + Pydantic 검증을 거친다.** 파싱 실패 시 최대 3회 재시도, 실패하면 `LLM_UNAVAILABLE` 에러 반환.
- **Pydantic 스키마를 재사용한다.** API 응답 모델과 LLM 구조화 출력 모델을 같은 클래스로 정의해 중복을 없앤다.
- **DB 마이그레이션은 항상 Alembic으로.** 모델을 직접 수정한 뒤 `alembic revision --autogenerate`로 생성하고 diff를 검토한다.
- **세특 문단은 단일 활동으로 뭉치지 않는다.** 파서가 한 문단에서 여러 개별 활동(`activity_type`별)을 추출하도록 구현 — 기능2(후속 추천) 품질에 직접 영향을 준다.
- **날짜는 항상 ISO 8601로 정규화**하고, 원문이 필요하면 `raw_date` 필드에 별도 보존한다.
- 커밋 전 `ruff check .`, `pytest` 통과 확인.

## 참고 문서

- **API 명세서**: `docs/API_SPEC.md` — 전체 엔드포인트, 요청/응답 스키마, 데이터 모델 정의. 새 엔드포인트를 만들 때 이 문서와 일치하는지 먼저 확인할 것.
- **개발 로드맵**: Phase 0(기반구축) → 1(생기부 파서) → 2(진단) → 3(챗봇) → 4(탭 관리) → 5(후속 추천) → 6(모니터링). 순서대로 구현하며, 이전 Phase의 스키마를 깨지 않도록 주의.

## 환경 변수 (`.env.example` 참고)

```
DATABASE_URL=
JWT_SECRET=
JWT_ALGORITHM=HS256
ANTHROPIC_API_KEY=
KAKAO_CLIENT_ID=
KAKAO_CLIENT_SECRET=
SENTRY_DSN=
```

## 현재 작업 중인 Phase

(여기에 현재 진행 중인 Phase와 완료된 작업을 최신 상태로 업데이트해서 사용하세요. AI 에이전트가 세션마다 참고합니다.)

- [x] Phase 0: 기반 구축 — FastAPI 스캐폴딩, docker-compose(PostgreSQL), SQLAlchemy(async)+Alembic, JWT 인증(회원가입/로그인/토큰 재발급/로그아웃), CI(GitHub Actions, 린트+테스트만) 완료. 카카오 소셜 로그인·배포 파이프라인·Sentry 실연동은 아직
- [x] Phase 1: 생기부 파서 — Rule-based(출결/성적/수상/봉사/독서/진로희망) + LLM(DeepSeek, 세특/창체/행발) 하이브리드 파서, `POST /seteuk/uploads` 구현. **실제 DeepSeek API 키로 end-to-end 검증 완료** — 실 샘플 PDF 업로드 시 attendance 3, academic_performance 57, reading_activities 30, awards 43, volunteer_records 23, activities 152~162건 정상 생성 및 DB 적재 확인(LLM 응답이 매번 살짝 달라 activities 건수는 실행마다 소폭 변동). 이 과정에서 DeepSeek이 프롬프트가 지정한 enum 밖의 `activity_type`(예: "lecture")을 가끔 반환하는 것을 발견해 알 수 없는 값은 블록 전체를 버리는 대신 `other`로 대체하도록 수정(`schemas/seteuk.py`의 `field_validator`). **API_SPEC.md에서 확정 변경**: 확인/적용 2단계 플로우를 없애고 업로드 하나로 파싱+DB 반영까지 자동 수행하도록 단순화(`apply-to-profile` 엔드포인트 삭제, PDF 원본은 파싱에만 쓰고 디스크에 저장하지 않음 — `seteuk_uploads.file_id` 컬럼도 제거). `GET .../uploads/{id}`(상태, done=파싱+DB반영 완료) → `GET .../result`(결과 조회)만 남음. **재업로드 시 데이터 처리**: 6개 도메인 테이블 모두 `source_upload_id`(nullable FK) 보유 — 생기부 업로드로 생성된 행만 이 값이 채워지고, 재업로드 시 같은 사용자의 `source_upload_id`가 채워진 기존 행만 삭제 후 교체됨(수동 입력 데이터는 유지). **PARSER_SPEC.md 설계와 실제 생기부 포맷이 상당히 달라** 사용자가 제공한 실제 샘플(`tmp.pdf`, 개인정보 포함·git 제외)과 참고용 프로토타입 코드(검토 후 삭제됨)로 규칙기반 파서를 재검증·재작성함: 출결/진로희망/창체/행특은 스펙이 가정한 "[N학년] 라벨 텍스트"가 아니라 pdfplumber로 깨끗이 잡히는 표였고, 교과성적은 표 셀에 과목명이 줄바꿈으로 뭉쳐 있어 표 대신 PyMuPDF 선형 텍스트에서 "단위수/점수/석차" 패턴으로 역추적하는 방식으로 전환함. 실 문서 대조 중 pdfplumber bytes 버그, 섹션 헤더 자간공백 미대응, 수상 등급 forward-fill 오적용, 날짜 별칭 누락, 봉사기록이 무관한 표에서 오염되는 문제, 셀 줄바꿈이 텍스트에 그대로 노출되는 문제 등을 다수 발견·수정함. **알려진 한계**: (1) 교과성적은 한 셀에 여러 과목이 줄바꿈으로 압축된 행은 안전하게 스킵함(오귀속 방지 목적, 완전 수집률 아님), (2) 과목명/문장 줄바꿈 병합 시 "운 용"처럼 공백이 낀 경우 있음(인식엔 지장 없음, 완벽 복원은 아님), (3) `parsing_confidence`는 사용자 결정에 따라 항상 null, (4) 검증은 실제 샘플 1건 기준이라 다른 학교/연도 포맷에서는 재조정 필요할 수 있음
- [ ] Phase 2: 기능1 — 진단
- [ ] Phase 3: AI 챗봇
- [ ] Phase 4: 탭 관리
- [ ] Phase 5: 기능2 — 후속 추천
- [ ] Phase 6: 모니터링
