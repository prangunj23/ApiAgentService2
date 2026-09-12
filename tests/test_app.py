import httpx
import pytest
from fastapi.testclient import TestClient

from consumer.app import app, get_operation_client
from operation import OperationClient


def use_upstream(handler) -> None:
    client = OperationClient("http://operation", transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_operation_client] = lambda: client


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_compute_calls_operation():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/operation/numeric_op"
        assert request.read() == b'{"a":2.0,"b":3.0}'
        return httpx.Response(200, json={"result": 5.0})

    use_upstream(handler)
    response = client.post("/compute", json={"a": 2, "b": 3})
    assert response.status_code == 200
    assert response.json() == {"result": 5.0, "source": "operation"}


def test_compute_upstream_error_returns_502():
    use_upstream(lambda request: httpx.Response(500))
    response = client.post("/compute", json={"a": 2, "b": 3})
    assert response.status_code == 502


def test_compute_upstream_unreachable_returns_503():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    use_upstream(handler)
    response = client.post("/compute", json={"a": 2, "b": 3})
    assert response.status_code == 503


def test_compute_bad_input_returns_422():
    use_upstream(lambda request: httpx.Response(200, json={"result": 0}))
    response = client.post("/compute", json={"a": "x"})
    assert response.status_code == 422


def test_health_reports_upstream_status():
    use_upstream(lambda request: httpx.Response(200, json={"status": "ok"}))
    assert client.get("/health").json() == {"status": "ok", "operation": "ok"}
