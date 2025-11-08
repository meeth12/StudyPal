# tests/test_routes_auth.py
import importlib

def test_login_get_shows_login_template(client, monkeypatch):
    main = importlib.import_module("studyPal.main")

    # GET /login should render login.html
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"login.html" in resp.data

def test_home_redirects_if_not_logged_in(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers.get("Location", "")

def test_signup_post_creates_user_and_redirects(client, monkeypatch):
    created = {}
    main = importlib.import_module("studyPal.main")
    def fake_create_user(db, name, email, password):
        created.update(dict(name=name, email=email, password=password))
    monkeypatch.setattr(main, "create_user", fake_create_user)

    resp = client.post("/signup", data={"name":"N", "email":"e@e.com", "password":"pw"}, follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers["Location"]
    assert created["email"] == "e@e.com"

def test_login_post_success_sets_session_and_redirects(client, monkeypatch):
    main = importlib.import_module("studyPal.main")
    def fake_login_user(db, email, password):
        return True, None, "uid123"
    monkeypatch.setattr(main, "login_user", fake_login_user)

    resp = client.post("/login", data={"email":"u@u.com","password":"pw"}, follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert resp.headers["Location"].endswith("/")

def test_logout_clears_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "uid123"
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code in (301,302)
    assert "/login" in resp.headers["Location"]
