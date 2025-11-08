
import importlib
def test_health_ok():
    m = importlib.import_module("main")
    assert getattr(m, "health", lambda: None)() == "ok"
