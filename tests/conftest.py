# tests/conftest.py
import json
import os
import sys
import types
import importlib
import pytest


def _make_fake_firebase():
    """Build a fake firebase_admin package with credentials, firestore, storage"""
    fa = types.ModuleType("firebase_admin")

    # Track initialize calls
    calls = {"init": 0}

    def initialize_app(cred):
        calls["init"] += 1
        return object()

    # credentials submodule
    creds_mod = types.ModuleType("firebase_admin.credentials")
    class DummyCred:
        def __init__(self, data):
            self.data = data
    def Certificate(data):
        return DummyCred(data)
    creds_mod.Certificate = Certificate

    # firestore submodule
    class FakeDoc:
        def __init__(self, data, id_="doc1", exists=True):
            self._data = data
            self.id = id_
            self.exists = exists
        def to_dict(self):
            return dict(self._data)

    class FakeDocRef:
        def __init__(self, store, id_):
            self._store = store
            self._id = id_
        def get(self):
            return self._store.get(self._id, FakeDoc({}, self._id, exists=False))
        def update(self, data):
            # simulate a doc existing to update
            if self._id not in self._store:
                self._store[self._id] = FakeDoc({}, self._id, exists=True)
            d = self._store[self._id].to_dict()
            d.update(data)
            self._store[self._id] = FakeDoc(d, self._id, exists=True)

    class FakeQuery:
        def __init__(self, docs):
            self._docs = docs
        def stream(self):
            return self._docs

    class FakeCollection:
        def __init__(self, notes_store):
            self._notes_store = notes_store
        def where(self, *_, **__):
            # return all docs for simplicity
            return FakeQuery(list(self._notes_store.values()))
        def document(self, id_):
            return FakeDocRef(self._notes_store, id_)
        def add(self, data):
            new_id = f"note_{len(self._notes_store)+1}"
            self._notes_store[new_id] = FakeDoc(data, new_id, exists=True)
            return (self._notes_store[new_id], None)

    class FakeFirestoreClient:
        def __init__(self):
            self._notes = {"n1": FakeDoc({"user_id": "u1", "text": "hello"}, "n1")}
        def collection(self, name):
            if name == "notes":
                return FakeCollection(self._notes)
            raise KeyError(name)

    def firestore_client():
        return FakeFirestoreClient()

    # storage submodule
    class FakeBlob:
        def __init__(self, path):
            self.path = path
            self._public_url = f"https://example.com/{path}"
        def upload_from_file(self, f):
            pass
        def make_public(self):
            pass
        @property
        def public_url(self):
            return self._public_url

    class FakeBucket:
        def blob(self, path):
            return FakeBlob(path)

    class storage_mod(types.ModuleType):
        @staticmethod
        def bucket(name=None):
            return FakeBucket()

    # Wire modules
    fa.initialize_app = initialize_app
    fa.credentials = creds_mod
    fa.firestore = types.SimpleNamespace(client=firestore_client)
    fa.storage = storage_mod("firebase_admin.storage")

    return fa, calls


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    """Provide fake service-account JSON so main.py can initialize."""
    service = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "dummy",
        "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
        "client_email": "test@test.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", json.dumps(service))
    # Provide a harmless OpenAI key
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def fake_firebase(monkeypatch):
    """Install a fake firebase_admin before importing main.py."""
    fake_fa, calls = _make_fake_firebase()
    sys.modules["firebase_admin"] = fake_fa
    sys.modules["firebase_admin.credentials"] = fake_fa.credentials
    sys.modules["firebase_admin.firestore"] = fake_fa.firestore
    sys.modules["firebase_admin.storage"] = fake_fa.storage
    return calls


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch):
    """Stub OpenAI client so no network happens."""
    class FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key
    # module import style: from openai import OpenAI
    import types
    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = FakeClient
    sys.modules["openai"] = fake_openai_mod


@pytest.fixture
def app(monkeypatch):
    """Import main.py with stubbed render_template to avoid real templates."""
    # Stub render_template in the module namespace main will import from
    def fake_render_template(name, **kwargs):
        # just return the template name so tests can assert
        return name
    # Ensure the render_template symbol used in main.py resolves to this stub
    import flask
    monkeypatch.setattr("flask.render_template", fake_render_template, raising=False)
    # Also patch the imported symbol path main.render_template uses
    monkeypatch.setenv("FLASK_ENV", "testing")

    # Import (or reload) main so top-level init runs once
    if "main" in sys.modules:
        del sys.modules["main"]
    mod = importlib.import_module("main")
    mod.app.testing = True
    return mod.app


@pytest.fixture
def client(app):
    return app.test_client()
