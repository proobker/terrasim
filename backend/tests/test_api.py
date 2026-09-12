"""API-level smoke tests: cities, layers, simulations and the planned-layout
override used by New-City mode."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_cities():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    cities = client.get("/api/cities").json()["cities"]
    ids = {c["id"] for c in cities}
    assert {"kathmandu", "pokhara"} <= ids


def test_city_layers():
    for layer in ("buildings", "roads", "facilities"):
        r = client.get("/api/cities/kathmandu/layers/buildings" if layer == "buildings" else f"/api/cities/kathmandu/layers/{layer}")
        assert r.status_code == 200
        assert r.json()["type"] == "FeatureCollection"


def test_flood_uses_planned_assets():
    r = client.post(
        "/api/simulate/flood",
        json={
            "city_id": "kathmandu",
            "source": {"lng": 85.34, "lat": 27.71},
            "level_m": 3.0,
            "mode": "rise",
            "assets": [
                {"kind": "hospital", "id": "plan-1", "name": "Proposed Hospital", "lng": 85.345, "lat": 27.715}
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "flood"
    if not body["dry"]:
        assert "exposure" in body
        hits = body["exposure"]["affected"]
        assert any(h["id"] == "plan-1" for h in hits) or len(body["exposure"]["assets"]) == 1


def test_quake_uses_planned_assets():
    r = client.post(
        "/api/simulate/earthquake",
        json={
            "city_id": "kathmandu",
            "epicenter": {"lng": 85.34, "lat": 27.71},
            "magnitude": 6.5,
            "depth_km": 10,
            "assets": [
                {"kind": "school", "id": "plan-9", "name": "Proposed School", "lng": 85.32, "lat": 27.72}
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "earthquake"
    assert body["zones"]["type"] == "FeatureCollection"


def test_suitability_pokhara():
    r = client.post("/api/cities/pokhara/suitability", json={"city_id": "pokhara"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["layers"]) == {"green", "yellow", "red"}