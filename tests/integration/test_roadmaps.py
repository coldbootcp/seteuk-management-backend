from httpx import AsyncClient


async def _onboard(client: AsyncClient, headers: dict[str, str], grade: int, semester: int) -> None:
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": grade,
            "semester": semester,
            "career_goal": {"goal": "반도체 공정 엔지니어"},
            "target_department": "전기전자공학과",
            "interest_keywords": ["반도체 소자"],
            "career_specificity": {"level": "specific"},
            "preferred_output_types": ["report"],
            "activity_channels": ["동아리"],
            "self_assessed_strengths": "수학에 강함",
            "self_assessed_weaknesses": "독서가 부족함",
        },
        headers=headers,
    )


async def test_roadmap_spans_six_semesters_with_narrative_stages(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """로드맵은 평면 계획 목록이 아니라 1-1부터 3-2까지 서사 단계를 갖는 6개 마디다."""
    await _onboard(client, auth_headers, grade=1, semester=1)

    response = await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)
    assert response.status_code == 201
    body = response.json()

    assert body["version"] == 1
    assert body["status"] == "draft"
    assert [(n["grade"], n["semester"]) for n in body["nodes"]] == [
        (1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)
    ]
    assert [n["narrative_stage"] for n in body["nodes"]] == [
        "탐색", "기초", "연결", "분화", "독립 탐구", "종합"
    ]


async def test_past_semesters_become_retrospect_not_new_plans(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """이미 지나간 학기에 계획을 제안해도 학생이 할 수 있는 일이 없다. 그 자리는
    '회고'로 두고 제안 주제도 만들지 않는다."""
    await _onboard(client, auth_headers, grade=2, semester=2)

    body = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    nodes = body["nodes"]

    # 2학년 2학기는 index 3 — 앞의 세 학기는 지나갔다.
    past, active, future = nodes[:3], nodes[3], nodes[4:]

    assert all(n["narrative_stage"] == "회고" for n in past)
    assert all(n["status"] == "skipped" for n in past)
    assert all(n["plan_events"] == [] for n in past)
    assert all(n["candidate_subjects"] == [] for n in past)

    assert active["status"] == "active"
    # 현재 학기 마디만 관심 분야를 앞세운 제목을 갖는다.
    assert active["title"].startswith("반도체 소자 관점으로")

    assert all(n["status"] == "planned" for n in future)
    assert all(n["title"] and not n["title"].startswith("반도체 소자 관점으로") for n in future)


async def test_each_upcoming_node_offers_core_and_optional_topics(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """제안 주제는 전부 하는 목록이 아니라 골라 담는 목록이라, core와 optional이
    구분돼 있어야 한다."""
    await _onboard(client, auth_headers, grade=1, semester=1)

    body = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    first = body["nodes"][0]

    priorities = [e["priority"] for e in first["plan_events"]]
    assert priorities.count("core") == 4
    assert priorities.count("optional") == 6
    assert all(e["description"] for e in first["plan_events"])
    # 관심 분야가 주제 문구에 실제로 반영된다.
    assert any("반도체 소자" in e["title"] for e in first["plan_events"])
    # 1학기는 4월부터, 앞의 세 주제만 달을 밀어 배치한다.
    assert [e["month_day"] for e in first["plan_events"]][:4] == [
        "04-15", "05-15", "06-15", "06-15"
    ]


async def test_regenerating_supersedes_instead_of_deleting(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """재생성은 이전 버전을 지우지 않는다 — 실행 기록을 덮어쓰지 않는다는 원칙."""
    await _onboard(client, auth_headers, grade=1, semester=1)

    first = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    second = (
        await client.post("/api/v1/roadmaps", json={"focus": "광소자"}, headers=auth_headers)
    ).json()

    assert second["version"] == 2
    assert second["id"] != first["id"]
    assert second["nodes"][0]["title"].startswith("광소자 관점으로")

    # 이전 버전은 여전히 조회된다.
    old = await client.get(f"/api/v1/roadmaps/{first['id']}", headers=auth_headers)
    assert old.status_code == 200
    assert old.json()["status"] == "superseded"

    # 활성 로드맵은 새 것이다.
    active = await client.get("/api/v1/roadmaps/active", headers=auth_headers)
    assert active.json()["id"] == second["id"]


async def test_student_can_edit_a_node_and_confirm_the_draft(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """제안은 제안일 뿐이라 학생이 제목·목표를 고친 뒤 확정할 수 있다."""
    await _onboard(client, auth_headers, grade=1, semester=1)
    body = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    node_id = body["nodes"][0]["id"]

    edited = await client.patch(
        f"/api/v1/roadmaps/nodes/{node_id}",
        json={"title": "내가 직접 고친 제목"},
        headers=auth_headers,
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "내가 직접 고친 제목"

    confirmed = await client.post(
        f"/api/v1/roadmaps/{body['id']}/confirm", headers=auth_headers
    )
    assert confirmed.json()["status"] == "active"
    assert confirmed.json()["nodes"][0]["title"] == "내가 직접 고친 제목"


async def test_roadmap_is_scoped_to_its_owner(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)
    body = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()

    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-roadmap@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    response = await client.get(f"/api/v1/roadmaps/{body['id']}", headers=other)
    assert response.status_code == 404
    assert response.json()["error_code"] == "ROADMAP_NOT_FOUND"


async def test_topic_titles_use_the_right_korean_particle(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """조사는 앞말 받침에 따라 달라진다. 참조 구현은 항상 "와"를 붙여 받침 있는
    관심 분야에서 "데이터분석와"처럼 틀린 문구가 나왔다 — 학생에게 보이는 글이다."""
    await _onboard(client, auth_headers, grade=1, semester=1)

    # 받침이 있는 관심 분야("석") → 과
    body = (
        await client.post("/api/v1/roadmaps", json={"focus": "데이터분석"}, headers=auth_headers)
    ).json()
    titles = [e["title"] for e in body["nodes"][0]["plan_events"]]
    assert any("데이터분석과 현재 교과의 연결" in t for t in titles)
    assert not any("데이터분석와" in t for t in titles)

    # 받침이 없는 관심 분야("자") → 와
    body = (
        await client.post("/api/v1/roadmaps", json={"focus": "광소자"}, headers=auth_headers)
    ).json()
    titles = [e["title"] for e in body["nodes"][0]["plan_events"]]
    assert any("광소자와 현재 교과의 연결" in t for t in titles)
    assert not any("광소자과" in t for t in titles)


async def test_topic_order_is_stable_across_requests(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """같은 달에 여러 주제가 몰리므로, 순번 없이 month_day로만 정렬하면 새로고침할
    때마다 목록 순서가 바뀐다."""
    await _onboard(client, auth_headers, grade=1, semester=1)
    created = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()

    first = [e["title"] for e in created["nodes"][0]["plan_events"]]
    again = (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()
    assert [e["title"] for e in again["nodes"][0]["plan_events"]] == first

    # core 4개가 optional보다 앞에 온다.
    priorities = [e["priority"] for e in created["nodes"][0]["plan_events"]]
    assert priorities[:4] == ["core"] * 4
    assert set(priorities[4:]) == {"optional"}


async def _add_activity(client: AsyncClient, headers: dict[str, str], **kw) -> dict:
    payload = {
        "grade": 2,
        "semester": 1,
        "activity_category": "과목세부특기사항",
        "activity_name": "활동",
        "activity_type": "report",
        "description": "설명",
        **kw,
    }
    return (await client.post("/api/v1/activities", json=payload, headers=headers)).json()


async def test_saving_an_activity_reconciles_it_against_the_active_node(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """활동을 저장하면 그 자리에서 활성 노드와 대조되고, 판정이 이력으로 남는다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    active_before = next(n for n in roadmap["nodes"] if n["status"] == "active")

    await _add_activity(
        client,
        auth_headers,
        subject="물리학",
        activity_name="원리와 실제 사례를 비교한 정량 분석 보고서",
        description="교과 원리가 실제 사례로 이어지는 과정을 비교하고 모형을 해석했다.",
    )

    history = (
        await client.get("/api/v1/roadmaps/reconciliations/history", headers=auth_headers)
    ).json()
    assert len(history) == 1
    assert history[0]["match_type"] == "MATCH"
    assert history[0]["node_id"] == active_before["id"]
    assert history[0]["confidence"] >= 72
    assert history[0]["action"]

    # 노드가 완료되고 다음 노드가 활성화된다.
    after = (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()
    nodes = {n["id"]: n for n in after["nodes"]}
    assert nodes[active_before["id"]]["status"] == "done"
    assert nodes[active_before["id"]]["instantiated_activity_id"] is not None
    following = [n for n in after["nodes"] if n["order_index"] == active_before["order_index"] + 1]
    assert following[0]["status"] == "active"


async def test_an_unrelated_activity_does_not_advance_the_roadmap(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """로드맵 밖 활동을 저장했다고 노드가 완료되면 안 된다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    active_before = next(n for n in roadmap["nodes"] if n["status"] == "active")

    await _add_activity(
        client, auth_headers, subject="음악", activity_name="교내 합창대회 참가", description="합창"
    )

    history = (
        await client.get("/api/v1/roadmaps/reconciliations/history", headers=auth_headers)
    ).json()
    assert history[0]["match_type"] == "DIVERGE"

    after = (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()
    still_active = next(n for n in after["nodes"] if n["id"] == active_before["id"])
    assert still_active["status"] == "active"


async def test_activities_saved_without_a_roadmap_are_not_blocked(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """로드맵을 만들기 전에 기록부터 쌓는 것을 막을 이유가 없다."""
    await _onboard(client, auth_headers, grade=2, semester=1)

    created = await _add_activity(client, auth_headers, activity_name="로드맵 없이 저장")
    assert created["activity_name"] == "로드맵 없이 저장"

    history = (
        await client.get("/api/v1/roadmaps/reconciliations/history", headers=auth_headers)
    ).json()
    assert history == []


async def test_semester_checkpoint_records_a_miss_only_when_nothing_was_done(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """MISS는 활동 저장이 아니라 시간이 흘러서 생긴다. 노드 상태는 바꾸지 않는다 —
    이월할지 건너뛸지는 학생이 정한다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    active_before = next(n for n in roadmap["nodes"] if n["status"] == "active")

    miss = (await client.post("/api/v1/roadmaps/checkpoint", headers=auth_headers)).json()
    assert miss["match_type"] == "MISS"
    assert miss["activity_id"] is None
    assert "학생이 결정" in miss["action"]

    after = (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()
    assert next(n for n in after["nodes"] if n["id"] == active_before["id"])["status"] == "active"

    # 노드를 충족하는 활동이 생기면 더 이상 MISS를 남기지 않는다.
    await _add_activity(
        client,
        auth_headers,
        subject="물리학",
        activity_name="원리와 실제 사례를 비교한 정량 분석 보고서",
        description="교과 원리가 실제 사례로 이어지는 과정을 비교하고 모형을 해석했다.",
    )
    assert (await client.post("/api/v1/roadmaps/checkpoint", headers=auth_headers)).json() is None


async def test_checkpoint_does_not_flag_a_semester_that_has_not_happened_yet(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """활동이 노드를 충족해 다음 노드가 활성화된 직후에도 체크포인트가 돌 수 있다.
    시점 비교가 없으면 아직 오지 않은 학기에 곧바로 MISS가 찍힌다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)

    # 2-1 노드를 충족시키면 2-2가 활성화된다 — 학생은 아직 2학년 1학기다.
    await _add_activity(
        client,
        auth_headers,
        subject="물리학",
        activity_name="원리와 실제 사례를 비교한 정량 분석 보고서",
        description="교과 원리가 실제 사례로 이어지는 과정을 비교하고 모형을 해석했다.",
    )
    active = next(
        n
        for n in (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()["nodes"]
        if n["status"] == "active"
    )
    assert (active["grade"], active["semester"]) == (2, 2)

    assert (await client.post("/api/v1/roadmaps/checkpoint", headers=auth_headers)).json() is None


async def test_checkpoint_does_not_pile_up_duplicate_misses(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """체크포인트는 여러 번 호출될 수 있다. 같은 노드에 MISS가 쌓이면 안 된다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)

    assert (await client.post("/api/v1/roadmaps/checkpoint", headers=auth_headers)).json()
    assert (await client.post("/api/v1/roadmaps/checkpoint", headers=auth_headers)).json() is None

    history = (
        await client.get("/api/v1/roadmaps/reconciliations/history", headers=auth_headers)
    ).json()
    assert [h["match_type"] for h in history] == ["MISS"]


async def test_courses_attach_to_a_semester_node_without_a_second_grade_table(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """수강 과목은 별도 테이블이 아니라 academic_performance에 roadmap_node_id를
    붙이는 방식이다(D-3). 성적 레코드를 둘로 나누면 진단의 학기별 평균 석차등급이
    어느 쪽을 봐야 할지 모호해진다 — 과목은 하나고, 로드맵 연결은 그 속성이다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    node = next(n for n in roadmap["nodes"] if n["status"] == "active")

    created = await client.post(
        "/api/v1/academic-performance",
        json={
            "grade": node["grade"],
            "semester": node["semester"],
            "category": "과학",
            "subject": "물리학Ⅰ",
            "roadmap_node_id": node["id"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["roadmap_node_id"] == node["id"]

    listed = await client.get(
        f"/api/v1/roadmaps/nodes/{node['id']}/courses", headers=auth_headers
    )
    assert [c["subject"] for c in listed.json()] == ["물리학Ⅰ"]

    # 성적과 메모는 같은 행을 고쳐서 넣는다.
    updated = await client.patch(
        f"/api/v1/academic-performance/{created.json()['id']}",
        json={"rank": "2", "raw_score": 91, "note": "시험 범위가 달랐음"},
        headers=auth_headers,
    )
    assert updated.json()["rank"] == "2"
    assert updated.json()["note"] == "시험 범위가 달랐음"

    # 같은 행이므로 진단의 성적 추이도 이 점수를 그대로 본다.
    listed = await client.get(
        f"/api/v1/roadmaps/nodes/{node['id']}/courses", headers=auth_headers
    )
    assert listed.json()[0]["rank"] == "2"


async def test_the_three_layers_stay_separate_and_connect(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """마디 → 제안 주제 → 계획 → 기록. 네 층은 각자 다른 것을 뜻하고, 담기와 완료가
    그 사이를 잇는다. 마디로 계획을 대신할 수 없는 이유는 마디가 6개 고정인 데 반해
    계획은 개수가 자유롭고, 완료 승격이 계획의 성질이기 때문이다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    node = next(n for n in roadmap["nodes"] if n["status"] == "active")
    suggestion = node["plan_events"][0]

    # 제안 주제를 담으면 계획이 생기고, 마디와 제안 양쪽에 매달린다.
    adopted = await client.post(
        f"/api/v1/roadmaps/plan-events/{suggestion['id']}/adopt",
        json={"item_type": "activity"},
        headers=auth_headers,
    )
    assert adopted.status_code == 201
    plan = adopted.json()
    assert plan["title"] == suggestion["title"]
    assert plan["roadmap_node_id"] == node["id"]
    assert plan["source_plan_event_id"] == suggestion["id"]
    assert (plan["target_grade"], plan["target_semester"]) == (node["grade"], node["semester"])

    # 제안은 지워지지 않는다 — 나중에 다른 것을 골라 담을 수 있어야 한다.
    still_there = (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()
    same_node = next(n for n in still_there["nodes"] if n["id"] == node["id"])
    assert len(same_node["plan_events"]) == len(node["plan_events"])

    # 마디에 매달린 계획으로 조회된다.
    listed = await client.get(
        f"/api/v1/roadmaps/nodes/{node['id']}/plans", headers=auth_headers
    )
    assert [p["id"] for p in listed.json()] == [plan["id"]]

    # 같은 제안을 두 번 담을 수는 없다.
    duplicate = await client.post(
        f"/api/v1/roadmaps/plan-events/{suggestion['id']}/adopt",
        json={"item_type": "activity"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409


async def test_completing_a_plan_also_advances_the_roadmap(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """계획대로 해냈는데 로드맵이 그대로면 루프가 끊긴 것이다. 탭에서 만든 활동은
    라우터 훅이 정합을 돌리지만 완료 승격은 그 경로를 지나지 않아, 따로 이어야 한다."""
    await _onboard(client, auth_headers, grade=2, semester=1)
    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    node = next(n for n in roadmap["nodes"] if n["status"] == "active")

    created = await client.post(
        "/api/v1/plans",
        json={
            "item_type": "activity",
            "title": "원리와 실제 사례를 비교한 정량 분석 보고서",
            "description": "교과 원리가 실제 사례로 이어지는 과정을 비교하고 모형을 해석했다.",
            "subject": "물리학",
            "target_grade": 2,
            "target_semester": 1,
            "roadmap_node_id": node["id"],
        },
        headers=auth_headers,
    )
    plan_id = created.json()["id"]

    completed = await client.post(
        f"/api/v1/plans/{plan_id}/complete", json={}, headers=auth_headers
    )
    assert completed.status_code == 200
    assert completed.json()["created_activity_id"] is not None

    history = (
        await client.get("/api/v1/roadmaps/reconciliations/history", headers=auth_headers)
    ).json()
    assert history[0]["match_type"] == "MATCH"

    after = (await client.get("/api/v1/roadmaps/active", headers=auth_headers)).json()
    assert next(n for n in after["nodes"] if n["id"] == node["id"])["status"] == "done"
