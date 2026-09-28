# 다음 세션 인수인계 — 2026-09-28

> **처리 완료(2026-09-28 로컬 세션).** 1절 검증은 모두 통과했다(ruff 2건 수정, pytest·alembic
> check·프론트 typecheck/build/test, api-types 재생성, 실제 DeepSeek 최초 상담은 소유자가 직접
> 확인). 이후 작업(과목 내용 근거, 카탈로그 정정, 채팅 스크롤)은 CLAUDE.md "과목 내용 근거 +
> 2022 카탈로그 정정" 항목에 있다. 아래는 기록으로 남긴다.

클라우드 세션(Claude 앱 작업 모드)에서 한 작업을 로컬 Claude Code가 이어받기 위한 글.
그 세션은 맥 파일을 복사해 고친 뒤 다시 써 넣었고, **패키지 설치가 막혀 통합 테스트·
ruff·alembic·next build를 한 번도 돌리지 못했다.** 로컬 세션의 첫 일은 아래 "1. 먼저 할
일"이다.

## 0. 소유자와 일하는 방식

- 소유자: 한준. 대화는 한국어.
- **git 커밋·푸시는 요청받았을 때만.** 작업 결과는 워킹 트리에 두고 보고한다.
- 같은 저장소를 다른 에이전트가 동시에 만질 수 있다. 파일을 크게 덮어쓰기 전에 지금
  내용이 예상과 같은지 확인한다.
- 계획을 먼저 보여 달라고 할 때가 있다("계획부터 짜줘 → 내가 시작 명령을 줄게").
  그런 말이 있으면 계획 단계에서 멈춘다.
- 원칙 "프롬프트는 부탁, 코드가 보증"(CLAUDE.md)을 소유자도 중요하게 여긴다. LLM
  행동 문제는 프롬프트만 고치지 말고 코드로 막을 방법을 먼저 찾는다.

## 1. 먼저 할 일 — 검증

백엔드(이 저장소, Postgres가 떠 있어야 함):
```
uv run alembic upgrade head && uv run alembic check && uv run ruff check . && uv run pytest
```
프론트엔드(`../seteuk-management-frontend-integrated`):
```
npm run typecheck && npm run build && npm test
```
그다음 백엔드를 띄운 채 프론트 `lib/api-types.ts`를 `/openapi.json`에서 다시 생성한다
(`TimetableSlotInput.subject_code` 한 줄만 손으로 넣어 둠. 새 엔드포인트 타입은
`lib/subjects-api.ts`에 손으로 적어 두었으니 재생성 후 그쪽으로 바꿔도 된다).

실패하면 고치고, 특히 새로 쓴 통합 테스트 `tests/integration/test_subjects.py`,
`test_timetables.py`(subject_code 테스트), `test_consultation.py`(destination)를 본다.
ruff 줄 길이는 한글을 2칸으로 센다(100 제한).

마지막으로 **실제 DeepSeek으로 최초 상담을 한 번 태워** 순서가 지켜지는지 본다:
기록 읽기 → 3학년 말 도착점 합의 → 남은 학기 배치(흐름 카드) → '이 흐름으로 확정' 버튼
→ 이번 학기 목표 → 주제 10개 → 마무리. 확정 전에는 이번 학기 이야기를 구체화하면 안 되고,
"초안이에요… 버튼 눌러야 확정" 문구는 마무리 버튼이 켜지는 턴에만 나와야 한다.

## 2. 이번 라운드에 소유자가 요청한 것과 한 일

(1라운드 — 상담 3단계 분리, 시간표 예시가 보고 있는 학기·교육과정을 따르게, 대화
제목 이름 바꾸기/주제 기반 자동 제목 — 는 CLAUDE.md에 이미 기록됨.)

1. **상담 순서 강제**: 여전히 이번 학기를 먼저 구체화한다는 피드백.
   - `chat/consultation_tools.tools_for_stage(session)` — 매 턴 모델이 볼 수 있는 도구를
     단계로 고정(flow 단계엔 `propose_three_year_flow`만).
   - 최초 상담 1단계 프롬프트를 거꾸로 설계로: 기록 읽기 → 도착점 → 학기 배치 → 확정.
     `propose_three_year_flow`에 `destination`(필수) 추가, 프론트 흐름 카드에 표시.
2. **확정 안내 문구**: `chat_service`의 출력 필터가 `signal_ready_to_conclude` 턴이 아니면
   안내 문장을 지우고, "나가기 버튼"을 "'상담 마치고 메인 화면으로' 버튼"으로 치환.
   관문 배너("이 상담을 마쳐야 …") 삭제.
3. **과목 카탈로그**: `services/subject_catalog.py` — 2015·2022 보통 교과 + 특목고 전문 교과
   534과목, 코드 `"2022:대수"`. 별칭("수1", "확통")·교과 구분 순 정렬 검색.
   `GET /subjects`, `/subjects/search`, `/subjects/common`.
   `academic_performance.subject_code` 추가(마이그레이션 `c5f2d8e1a9b3`).
4. **이번 학기 수강 과목 단계**: 온보딩이 프로필 → 과목 → 상담.
   - 소유자 결정: 필수는 아니지만 확정된 과목은 다 넣도록 강하게 유도(건너뛰기 전 재확인),
     과목은 전 과목 대상, 목록에 없는 학교 자체 과목은 "기타"로 직접 입력.
   - **자유 입력으로 목록 과목을 만들 수 없어야 한다**(1:1 매칭이 목적). 엔터는 후보 선택뿐.
   - `GET/PUT /profile/current-courses`(`course_service`) — 성적 칸이 빈
     `academic_performance` 행으로 저장, 생기부발·성적 있는 행은 locked.
   - 프론트: `app/course-picker.tsx`(SubjectSearchField, CurrentCoursePicker),
     `app/workspace-app.tsx`의 courses 단계, 상담 화면 왼쪽 "이번 학기 수강 과목" 카드.
   - 상담 컨텍스트 `current_semester_courses` = 이 목록 + 이번 학기 기본 시간표 과목.
5. **시간표도 같은 카탈로그**: `app/timetable-view.tsx`의 검색·직접 추가를 카탈로그로,
   칸에 `subjectCode` 저장(백엔드 `TimetableSlotInput.subject_code`, JSONB라 마이그레이션
   없음). 카탈로그 과목은 편집 모달에서 이름 변경 불가. 프론트 하드코딩 목록 제거
   (`SUBJECT_PRESETS`는 `lib/academic-records-api.ts`가 아직 써서 남김).

## 3. 알려진 한계 / 확인 필요

- 카탈로그 중 예술 계열 전체와 2015 전문교과Ⅰ은 공식 페이지와 대조하지 못해
  `verified=False`. 직업계고 NCS 전문 교과는 범위 밖("기타").
- 온보딩에서 과목을 건너뛰면 상담 프롬프트가 한 번 등록을 권한다(규칙 10). 실제로
  너무 조르지 않는지 실 대화로 볼 것.
- `lib/academic-records-api.ts`의 성적 쪽 과목 추정은 아직 옛 `SUBJECT_PRESETS`를 쓴다.
  성적 입력도 카탈로그로 옮길지는 소유자에게 물어볼 것.
