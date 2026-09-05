# 포팅 원본 (프론트엔드에서 걷어낸 도메인 로직)

시나리오 A 통합에서 프론트엔드의 서버 로직을 전부 제거했습니다. 그중 **백엔드로
옮겨야 하는 도메인 자산**의 원본을 여기 보존합니다. 포팅이 끝나면 이 폴더는 지웁니다.

| 파일 | 옮겨야 할 것 |
|---|---|
| `product-harness.ts` | `GENERIC_ROADMAP_STAGES`(6단계 서사 템플릿: 탐색→기초→연결→분화→…), `generateRoadmap`, `diagnoseStudent`, `makeNextMission`, `analyzeAssignment`, `reconcileActivity` |
| `school-record-parser.ts` | `parseSchoolRecordText` — 백엔드 파서로 통일하므로 참고용. 클라이언트 헬퍼(`parseSchoolRecordJson`, `getLatestSchoolRecordPeriod`)는 프론트에 남겼습니다 |
| `frontend-schema.ts` | Drizzle 스키마 — `roadmaps`/`roadmap_nodes`/`roadmap_plan_events`/`reconciliation_logs`/`activity_attachments`/`recommendation_feedback`를 Postgres 모델로 옮길 때의 원본 |

원본은 프론트엔드 리포의 `main` 브랜치 히스토리에도 남아 있습니다
(`git show main:lib/product-harness.ts`).
