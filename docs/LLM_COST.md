# AI(LLM) 비용 보기

모든 AI 호출은 `llm_usage_events`에 한 줄씩 남는다(`app/services/llm/usage.py`). 내용은 남기지
않고 숫자만 남긴다: 누가(`user_id`), 어느 기능에서(`path`), 입력·출력·생각·캐시 토큰.

- Gemini는 생각 토큰을 `total_tokens`에만 넣는다. `thinking_tokens = total − 입력 − 출력`으로 계산해
  둔다. 생각 토큰은 **출력 요금**으로 과금된다.
- 2026-10 기준 `gemini-3.8-flash` 일반 요금: 입력 $0.75 / 출력 $3.75 (100만 토큰당).
  **2027-01-01부터 두 배**. 요금이 바뀌면 아래 조회문의 단가만 고친다.
- 운영 DB 접속: `fly postgres connect -a seteuk-backend-db` → `\c seteuk_backend`

## 기능별 비용 (최근 1일)

```sql
select
  case
    when path like '%/seteuk/uploads%' then '생기부 분석'
    when path like '%/diagnosis%' then '진단'
    when path like '%/consultation/%' then '상담'
    when path like '%/conversations/%' then 'AI 컨설턴트'
    when path like '%/review%' then '활동 검토'
    when path like '%/profile/suggest%' then '온보딩 추천'
    else coalesce(path, '기타')
  end as feature,
  count(*) as calls,
  sum(input_tokens) as input_tokens,
  sum(output_tokens + thinking_tokens) as billed_output_tokens,
  round((sum(input_tokens) * 0.75 + sum(output_tokens + thinking_tokens) * 3.75) / 1e6 * 1400, 1) as krw
from llm_usage_events
where created_at > now() - interval '1 day'
group by 1 order by krw desc;
```

## 학생 1인당 비용 (최근 7일)

```sql
select user_id, count(*) as calls,
  round((sum(input_tokens) * 0.75 + sum(output_tokens + thinking_tokens) * 3.75) / 1e6 * 1400, 1) as krw
from llm_usage_events
where created_at > now() - interval '7 days'
group by user_id order by krw desc limit 30;
```

환율은 1달러 = 1,400원으로 어림했다.
