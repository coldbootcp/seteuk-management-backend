from httpx import AsyncClient

SIGNUP_PAYLOAD = {"email": "student@example.com", "password": "s3cure-passw0rd"}


async def test_signup_returns_tokens(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert "user_id" in body
    assert body["access_token"]
    assert body["refresh_token"]


async def test_signup_duplicate_email_rejected(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    response = await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["error_code"] == "EMAIL_ALREADY_EXISTS"


async def test_login_success(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_wrong_password_rejected(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"


async def test_refresh_issues_new_access_token(client: AsyncClient) -> None:
    signup_response = await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    refresh_token = signup_response.json()["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_refresh_with_access_token_rejected(client: AsyncClient) -> None:
    signup_response = await client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    access_token = signup_response.json()["access_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_TOKEN"
