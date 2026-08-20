"""API health-path tests with fake probes injected through the factory seam."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from crucible.domain import ComponentHealth, HealthState
from crucible_api.main import create_app
from crucible_api.settings import ApiSettings


class FakeProbe:
    def __init__(self, name: str, state: HealthState) -> None:
        self._name, self._state = name, state

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> ComponentHealth:
        return ComponentHealth(name=self._name, state=self._state)


class ExplodingProbe:
    @property
    def name(self) -> str:
        return "boom"

    async def check(self) -> ComponentHealth:
        raise RuntimeError("dependency exploded")


def make_client(*probes: object) -> Iterator[TestClient]:
    settings = ApiSettings(_env_file=None, profile="test", git_sha="cafe123")  # type: ignore[call-arg]
    app = create_app(settings=settings, probes=list(probes))  # type: ignore[arg-type]
    with TestClient(app) as client:
        yield client


@pytest.fixture
def healthy_client() -> Iterator[TestClient]:
    yield from make_client(
        FakeProbe("postgres", HealthState.OK), FakeProbe("redis", HealthState.OK)
    )


def test_healthz_is_dependency_free(healthy_client: TestClient) -> None:
    r = healthy_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


def test_readyz_ok_when_all_probes_ok(healthy_client: TestClient) -> None:
    r = healthy_client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ok"
    assert {c["name"] for c in body["components"]} == {"postgres", "redis"}


def test_readyz_503_when_a_dependency_is_down() -> None:
    client_gen = make_client(
        FakeProbe("postgres", HealthState.OK), FakeProbe("redis", HealthState.DOWN)
    )
    client = next(client_gen)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["state"] == "down"


def test_readyz_survives_probe_exception() -> None:
    client = next(make_client(ExplodingProbe()))
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["components"][0]["detail"].startswith("probe raised")


def test_version_reports_git_sha(healthy_client: TestClient) -> None:
    r = healthy_client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert body["git_sha"] == "cafe123"
    assert body["profile"] == "test"


def test_errors_render_as_problem_json(healthy_client: TestClient) -> None:
    r = healthy_client.get("/no-such-route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404


def test_openapi_document_is_served(healthy_client: TestClient) -> None:
    r = healthy_client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Crucible API"
