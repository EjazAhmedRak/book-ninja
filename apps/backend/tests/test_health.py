from unittest.mock import AsyncMock, patch


def test_liveness_does_not_call_external_integrations(test_client):
    with (
        patch("api.routes.health.ping_mongo", new_callable=AsyncMock) as mongo,
        patch("api.routes.health.httpx.AsyncClient") as http,
    ):
        response = test_client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mongo.assert_not_called()
    http.assert_not_called()


def test_health_returns_200(test_client):
    with (
        patch("api.routes.health.ping_mongo", new_callable=AsyncMock, return_value=True),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_get.return_value)
        mock_get.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_get.return_value.status_code = 200

        res = test_client.get("/health")

    assert res.status_code == 200


def test_health_response_has_required_keys(test_client):
    with (
        patch("api.routes.health.ping_mongo", new_callable=AsyncMock, return_value=True),
        patch("httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=AsyncMock(status_code=200))
        mock_client_class.return_value = mock_client

        res = test_client.get("/health")

    body = res.json()
    assert "status" in body
    assert "integrations" in body
    assert set(body["integrations"].keys()) == {"hardcover", "mongodb", "tavily", "langsmith"}


def test_health_no_auth_required(test_client):
    """Health endpoint must be accessible without a Bearer token."""
    with (
        patch("api.routes.health.ping_mongo", new_callable=AsyncMock, return_value=False),
        patch("httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client_class.return_value = mock_client

        res = test_client.get("/health")

    assert res.status_code == 200
    assert res.json()["status"] == "degraded"
