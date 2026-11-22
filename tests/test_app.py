"""Flask app, plugin loader, cases, evidence storage and access token (no network)."""
import textwrap

import pytest


@pytest.fixture(scope="module")
def client():
    import app
    app.app.testing = True
    return app.app.test_client()


def test_health_and_catalog(client):
    h = client.get("/healthz").get_json()
    assert h["ok"] and h["plugins"] >= 6 and h["tools"] > 40
    c = client.get("/api/catalog").get_json()
    assert set(c["types"]) >= {"username", "email", "crypto"}
    assert any(x["id"] == "crypto" for x in c["map"]["crypto"])
    assert c["plugin_errors"] == []


def test_tools_english_overlay(client):
    tools = {t["id"]: t for t in client.get("/api/tools?lang=en").get_json()}
    assert tools["namesearch"]["title"] == "Name research"
    assert tools["fediverse"]["fields"][0]["label"] == "Username"
    assert tools["maigret"]["about"]["what"].startswith("An improved Sherlock")
    tr = {t["id"]: t for t in client.get("/api/tools").get_json()}
    assert tr["namesearch"]["title"] == "İsim araştırma"


def test_cases_timeline_and_report(client):
    cid = client.post("/api/cases", json={"name": "test"}).get_json()["id"]
    client.post(f"/api/cases/{cid}/items", json={"tool": "unified", "query": "bob", "items": [
        {"title": "GitHub", "url": "https://github.com/bob", "status": "found", "meta": {"Hesap açılışı": "2015-02-01"}}]})
    ev = client.get(f"/api/cases/{cid}/timeline").get_json()["events"]
    assert any(e["date"] == "2015-02-01" for e in ev)
    html = client.get(f"/case/{cid}/report?lang=en").get_data(as_text=True)
    assert "OSINT CASE REPORT" in html and "by Seesternn" in html
    w = client.post(f"/api/cases/{cid}/watch", json={"enabled": True, "interval_h": 12}).get_json()["watch"]
    assert w["enabled"] == 1 and w["interval_h"] == 12
    assert client.delete(f"/api/cases/{cid}").status_code == 200


def test_evidence_refuses_private_urls(client):
    import store
    cid = store.create_case("ev")
    store.add_items(cid, "x", "q", [{"title": "local", "url": "http://127.0.0.1:5050/", "status": "found"}])
    iid = store.get_case(cid)["items"][0]["id"]
    r = client.post(f"/api/items/{iid}/evidence")
    assert r.status_code == 400


def test_token_required_when_set(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "PANEL_TOKEN", "s3cret")
    assert client.get("/api/catalog").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/catalog", headers={"X-Panel-Token": "s3cret"}).status_code == 200


def test_broken_user_plugin_is_reported(tmp_path, monkeypatch):
    import plugins
    (tmp_path / "good.py").write_text(textwrap.dedent('''
        from plugin_api import F
        PLUGIN = {"id": "good-one", "title": "Good", "group": "Eklentiler", "fields": [F("q", "Q")],
                  "run": lambda job, inp, emit: emit(title="ok", status="found")}
    '''))
    (tmp_path / "bad.py").write_text("PLUGIN = {'id': 'bad'}\n")
    monkeypatch.setenv("OSINT_PLUGIN_DIR", str(tmp_path))
    reg, by_id, about = [], {}, {}
    plugins.load_all(reg, by_id, about)
    assert "good-one" in by_id
    assert any(f == "bad.py" and "missing keys" in e for f, e in plugins.LOAD_ERRORS)
    rows = []
    by_id["good-one"]["run"]({}, {}, lambda **r: rows.append(r))
    assert rows == [{"title": "ok", "status": "found"}]
