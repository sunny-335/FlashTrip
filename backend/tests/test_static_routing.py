"""回归：静态托管绝不吞掉 /api/*（对应计划 §7 首要坑）。"""


def test_unknown_api_is_json_not_spa(client):
    resp = client.get("/api/v1/definitely-not-exists")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["code"] == 1004
    assert "FlashTrip" not in resp.text


def test_spa_root_returns_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "FlashTrip" in resp.text


def test_spa_deep_link_returns_index(client):
    resp = client.get("/trips/abc/plan")
    assert resp.status_code == 200
    assert "FlashTrip" in resp.text


def test_assets_are_served(client):
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "test asset" in resp.text


def test_api_prefix_guard(client):
    resp = client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
