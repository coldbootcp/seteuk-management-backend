"""과목 카탈로그 검색과 이번 학기 수강 과목 등록."""

from httpx import AsyncClient

from tests.integration.test_profile import PROFILE_PAYLOAD


async def _onboard(client: AsyncClient, headers: dict[str, str], freshman_year: int) -> None:
    payload = {
        **PROFILE_PAYLOAD,
        "grade": 2,
        "semester": 1,
        "freshman_academic_year": freshman_year,
    }
    response = await client.post("/api/v1/profile", headers=headers, json=payload)
    assert response.status_code == 200


async def test_search_uses_the_students_curriculum(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, 2025)

    response = await client.get("/api/v1/subjects/search?q=수1", headers=auth_headers)
    body = response.json()
    assert response.status_code == 200
    assert body["curriculum"] == "2022"
    assert [item["name"] for item in body["items"]] == ["대수"]
    assert body["items"][0]["code"] == "2022:대수"

    old = await client.get(
        "/api/v1/subjects/search?q=수1&curriculum=2015", headers=auth_headers
    )
    assert [item["name"] for item in old.json()["items"]] == ["수학Ⅰ"]


async def test_common_examples_follow_the_requested_semester(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, 2025)
    response = await client.get(
        "/api/v1/subjects/common?grade=1&semester=2", headers=auth_headers
    )
    assert response.json()["items"][0]["name"] == "공통국어2"


async def test_current_courses_accept_catalog_codes_and_custom_names_only(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, 2025)

    saved = await client.put(
        "/api/v1/profile/current-courses",
        headers=auth_headers,
        json={
            "courses": [
                {"subject_code": "2022:대수"},
                {"subject_code": "2022:물리학"},
                {"subject_code": "2022:대수"},
                {"custom_name": "  학교 자율 탐구  "},
            ]
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert (body["grade"], body["semester"]) == (2, 1)
    courses = {c["subject"]: c for c in body["courses"]}
    assert set(courses) == {"대수", "물리학", "학교 자율 탐구"}  # 중복은 한 번만
    assert courses["대수"]["subject_code"] == "2022:대수"
    assert courses["대수"]["category"] == "수학"
    assert courses["학교 자율 탐구"]["is_custom"] is True
    assert courses["학교 자율 탐구"]["category"] == "기타"

    # 카탈로그에 없는 코드, 코드와 이름을 함께 준 항목은 거부한다.
    bad_code = await client.put(
        "/api/v1/profile/current-courses",
        headers=auth_headers,
        json={"courses": [{"subject_code": "2022:수학Ⅰ"}]},
    )
    assert bad_code.status_code == 422
    both = await client.put(
        "/api/v1/profile/current-courses",
        headers=auth_headers,
        json={"courses": [{"subject_code": "2022:대수", "custom_name": "대수"}]},
    )
    assert both.status_code == 422

    # 다시 저장하면 덮어쓴다.
    replaced = await client.put(
        "/api/v1/profile/current-courses",
        headers=auth_headers,
        json={"courses": [{"subject_code": "2022:화학"}]},
    )
    assert [c["subject"] for c in replaced.json()["courses"]] == ["화학"]


async def test_courses_with_grades_are_kept_and_locked(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, 2025)
    graded = await client.post(
        "/api/v1/academic-performance",
        headers=auth_headers,
        json={
            "grade": 2,
            "semester": 1,
            "category": "과학",
            "subject": "물리학",
            "subject_code": "2022:물리학",
            "achievement_grade": "A",
        },
    )
    assert graded.status_code == 201

    saved = await client.put(
        "/api/v1/profile/current-courses",
        headers=auth_headers,
        json={"courses": [{"subject_code": "2022:물리학"}, {"subject_code": "2022:대수"}]},
    )
    courses = {c["subject"]: c for c in saved.json()["courses"]}
    assert set(courses) == {"물리학", "대수"}  # 성적 있는 물리학을 중복으로 만들지 않는다
    assert courses["물리학"]["locked"] is True
    assert courses["대수"]["locked"] is False

    cleared = await client.put(
        "/api/v1/profile/current-courses", headers=auth_headers, json={"courses": []}
    )
    assert [c["subject"] for c in cleared.json()["courses"]] == ["물리학"]


async def test_full_list_is_limited_to_one_curriculum(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, 2024)
    body = (await client.get("/api/v1/subjects", headers=auth_headers)).json()
    assert body["curriculum"] == "2015"
    names = {item["name"] for item in body["items"]}
    assert "수학Ⅰ" in names and "대수" not in names
