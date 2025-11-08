# tests/test_routes_core.py
import importlib

def login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "uid123"

def test_home_lists_notes(client):
    login(client)
    resp = client.get("/")
    # Our fake render_template returns the template name
    assert resp.status_code == 200
    assert b"home.html" in resp.data

def test_flashcards_requires_login(client):
    resp = client.get("/flashcards/n1", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers["Location"]

def test_flashcards_ok_with_login(client, monkeypatch):
    login(client)
    main = importlib.import_module("main")
    def fake_get_flashcards(db, user_id, note_id):
        return [{"q":"Q1","a":"A1"}]
    monkeypatch.setattr(main, "get_flashcards", fake_get_flashcards)
    resp = client.get("/flashcards/n1")
    assert resp.status_code == 200
    assert b"flashcards.html" in resp.data

def test_edit_note_save_creates_note_and_redirects(client, monkeypatch):
    login(client)
    main = importlib.import_module("main")
    calls = {}
    monkeypatch.setattr(main, "save_note", lambda db, uid, text, _none, title: "note123")
    monkeypatch.setattr(main, "generate_flashcards", lambda db, uid, nid, text, client: calls.setdefault("gen", True))

    resp = client.post("/edit_note", data={"title":"T","notes":"Body","action":"save"}, follow_redirects=False)
    assert resp.status_code in (301,302)
    assert resp.headers["Location"].endswith("/")

def test_edit_note_summarise_renders(client, monkeypatch):
    login(client)
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "aiSummariser", lambda text, client: "SUM")
    resp = client.post("/edit_note", data={"title":"T","notes":"Body","action":"summarise"})
    assert resp.status_code == 200
    assert b"write.html" in resp.data

def test_upload_doc_requires_login(client):
    resp = client.get("/upload_doc", follow_redirects=False)
    assert resp.status_code in (301,302)
    assert "/login" in resp.headers["Location"]

def test_upload_doc_missing_file_returns_400(client):
    login(client)
    resp = client.post("/upload_doc", data={"action":"save","title":"T"})
    assert resp.status_code == 400
