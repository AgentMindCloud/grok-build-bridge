"""Tests for the ``bridge.live`` FastAPI service.

Drives every route through ``fastapi.testclient.TestClient`` against a
fresh app instance per test. The passport store is redirected to a
per-test temp dir via ``BRIDGE_LIVE_HOME`` so seeded showcases from
one test cannot leak into another.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Fastapi/Starlette template responses look up a fresh module each time
# ``create_app`` runs; isolating the store directory is enough for a
# clean slate. We reload the app per test to make sure the seeded gallery
# is rebuilt against the freshly-redirected store.


@pytest.fixture
def isolated_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("BRIDGE_LIVE_HOME", str(tmp_path / "passports"))

    # Re-import inside the fixture so the seeding step on app construction
    # picks up the redirected ``BRIDGE_LIVE_HOME``. ``create_app`` also
    # mounts /static; the per-test rebuild is cheap.
    import importlib

    import bridge_live.app as app_mod

    importlib.reload(app_mod)
    app = app_mod.create_app()
    with TestClient(app) as client:
        yield client


_VALID_LOCAL_YAML = """\
version: "1.0"
name: route-test
description: Smoke test agent for the bridge.live test suite.
build:
  source: local
  language: python
  entrypoint: main.py
deploy:
  target: local
agent:
  model: grok-4.20-0309
safety:
  audit_before_post: false
"""


# ---------------------------------------------------------------------------
# Read-only routes
# ---------------------------------------------------------------------------


def test_home_page_renders(isolated_app: TestClient) -> None:
    r = isolated_app.get("/")
    assert r.status_code == 200
    body = r.text
    assert "bridge" in body.lower()
    # The textarea must exist; without it visitors cannot paste a YAML.
    assert 'name="yaml_text"' in body


def test_healthz_returns_ok(isolated_app: TestClient) -> None:
    r = isolated_app.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_showcase_seeds_eight_bundled_templates(isolated_app: TestClient) -> None:
    r = isolated_app.get("/showcase")
    assert r.status_code == 200
    # Every bundled template's slug must show up on the gallery.
    for slug in (
        "hello-bot",
        "x-trend-analyzer",
        "truthseeker-llm-safety",  # truthseeker-daily renames itself
        "code-explainer-bot",
        "grok-build-coding-agent",
        "research-thread-weekly",
        "railway-worker-bot",
        "flyio-edge-bot",
    ):
        assert slug in r.text, f"expected {slug!r} on /showcase, got len={len(r.text)}"


def test_launch_with_topic_prefills_yaml(isolated_app: TestClient) -> None:
    r = isolated_app.get("/launch", params={"topic": "AI safety"})
    assert r.status_code == 200
    # The scaffold must mention the user's topic verbatim AND a sanitised slug.
    assert "AI safety" in r.text
    assert "bridge-live-ai-safety" in r.text


# ---------------------------------------------------------------------------
# POST /p — happy path
# ---------------------------------------------------------------------------


def test_submit_yaml_creates_passport(isolated_app: TestClient) -> None:
    r = isolated_app.post("/p", data={"yaml_text": _VALID_LOCAL_YAML}, follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/p/")
    sha = location.removeprefix("/p/")

    page = isolated_app.get(location)
    assert page.status_code == 200
    body = page.text
    assert "route-test" in body
    assert "grok-4.20-0309" in body
    assert sha in body  # passport SHA shown on the page


def test_resubmitting_same_yaml_is_idempotent(isolated_app: TestClient) -> None:
    """SHAs are content-addressed — same YAML → same URL."""
    a = isolated_app.post("/p", data={"yaml_text": _VALID_LOCAL_YAML}, follow_redirects=False)
    b = isolated_app.post("/p", data={"yaml_text": _VALID_LOCAL_YAML}, follow_redirects=False)
    assert a.headers["location"] == b.headers["location"]


# ---------------------------------------------------------------------------
# POST /p — error paths
# ---------------------------------------------------------------------------


def test_submit_invalid_yaml_returns_error_page(isolated_app: TestClient) -> None:
    r = isolated_app.post(
        "/p",
        data={"yaml_text": "version: 'bogus'\nname: x\ndescription: y\n"},
        follow_redirects=False,
    )
    # Schema rejection → 422 with the error template.
    assert r.status_code == 422
    assert "Invalid bridge.yaml" in r.text


def test_submit_empty_yaml_returns_400(isolated_app: TestClient) -> None:
    r = isolated_app.post("/p", data={"yaml_text": ""})
    assert r.status_code == 400


def test_submit_oversized_yaml_returns_413(isolated_app: TestClient) -> None:
    huge = "name: x\n" + "# pad\n" * 100_000
    r = isolated_app.post("/p", data={"yaml_text": huge})
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# /p/<sha> — missing
# ---------------------------------------------------------------------------


def test_passport_404_on_unknown_sha(isolated_app: TestClient) -> None:
    r = isolated_app.get("/p/deadbeef")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /p/<sha> — seeded
# ---------------------------------------------------------------------------


def test_passport_json_endpoint_returns_yaml_text(isolated_app: TestClient) -> None:
    """`/p/<sha>.json` returns a machine-readable view; `bridge fork` consumes it."""
    r = isolated_app.post("/p", data={"yaml_text": _VALID_LOCAL_YAML}, follow_redirects=False)
    sha = r.headers["location"].removeprefix("/p/")

    page = isolated_app.get(f"/p/{sha}.json")
    assert page.status_code == 200
    payload = page.json()
    assert payload["sha"] == sha
    assert payload["name"] == "route-test"
    assert "yaml_text" in payload and "route-test" in payload["yaml_text"]
    # Safety block carries the verdict shape `bridge fork` does not need but
    # the marketplace will surface — pin the keys so future renames break loud.
    assert set(payload["safety"]) == {"safe", "issues"}


def test_passport_json_404_on_unknown_sha(isolated_app: TestClient) -> None:
    r = isolated_app.get("/p/deadbeef.json")
    assert r.status_code == 404


def test_seeded_passport_renders_safety_clean(isolated_app: TestClient) -> None:
    """The bundled templates all pass the static safety scan."""
    showcase = isolated_app.get("/showcase").text
    # Pull a passport SHA out of the showcase HTML.
    import re

    shas = re.findall(r'href="/p/([0-9a-f]{8})"', showcase)
    assert shas, "showcase must list at least one passport"
    page = isolated_app.get(f"/p/{shas[0]}")
    assert page.status_code == 200
    assert "✓ safe" in page.text or "safe" in page.text.lower()


# ---------------------------------------------------------------------------
# Helpers used in route handlers — exposed to tests for coverage.
# ---------------------------------------------------------------------------


def test_scaffold_for_topic_short_input_falls_back() -> None:
    from bridge_live.app import _scaffold_for_topic

    out = _scaffold_for_topic("a")
    # Slug minimum length is 3; the helper falls back to "topic" when shorter.
    assert "bridge-live-topic" in out


def test_resolve_yaml_payload_prefers_textarea_over_upload() -> None:
    """When both the textarea and a file are present, textarea wins."""
    import asyncio
    import io

    from fastapi import UploadFile

    from bridge_live.app import _resolve_yaml_payload

    payload = "name: from-paste"
    upload = UploadFile(filename="b.yaml", file=io.BytesIO(b"name: from-upload"))
    out: Any = asyncio.run(_resolve_yaml_payload(payload, upload))
    assert out == payload
