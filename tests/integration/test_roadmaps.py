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
