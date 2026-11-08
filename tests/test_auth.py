"""Anmeldung über Pocket ID. Aufruf: python -m pytest tests/test_auth.py"""
import os
import sys
import tempfile
import urllib.parse

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ["DISABLE_SCHEDULER"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_pocketid import FakePocketID  # noqa: E402
from app import pocketid  # noqa: E402
from app.main import app  # noqa: E402


def with_oidc(**extra):
    fake = FakePocketID()
    app.config["POCKETID"] = pocketid.PocketID(fake.env(**extra), opener=fake)
    return fake


def test_open_without_oidc():
    app.config["POCKETID"] = pocketid.PocketID({})
    assert app.test_client().get("/api/games").status_code == 200


def test_login_flow():
    fake = with_oidc()
    c = app.test_client()
    assert c.get("/api/games").status_code == 401
    assert c.get("/").headers["Location"] == "/auth/pocketid?next=/"
    assert c.get("/healthz").status_code == 200
    res = c.get("/auth/pocketid?next=/%23stats", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "t.test"})
    redirect, params = fake.login(res.headers["Location"])
    assert redirect == "https://t.test/auth/pocketid/zurueck"
    res = c.get("/auth/pocketid/zurueck?" + urllib.parse.urlencode(params),
                headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "t.test"})
    assert res.status_code == 302 and res.headers["Location"] == "/#stats"
    assert c.get("/api/games", headers={"X-Forwarded-Proto": "https"}).status_code == 200
    assert c.post("/api/sync", headers={"Origin": "https://boese.test", "X-Forwarded-Proto": "https"}).status_code == 403
    c.get("/auth/abmelden")
    assert c.get("/api/games").status_code == 401


def test_group_restriction():
    fake = with_oidc(OIDC_ALLOWED_GROUPS="admins")
    c = app.test_client()
    res = c.get("/auth/pocketid")
    _, params = fake.login(res.headers["Location"])
    res = c.get("/auth/pocketid/zurueck?" + urllib.parse.urlencode(params))
    assert res.status_code == 403
    assert c.get("/api/games").status_code == 401
