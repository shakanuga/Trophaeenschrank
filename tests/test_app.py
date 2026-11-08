"""Tests mit nachgebauten API-Antworten (kein Netz nötig).  Aufruf: python -m tests.test_app"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp()
os.environ["DATA_DIR"] = TMP
os.environ["DISABLE_SCHEDULER"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import covers, db, sync  # noqa: E402
from app.main import app  # noqa: E402


class Resp:
    def __init__(self, data=None, status=200, headers=None, content=b""):
        self._d, self.status_code = data, status
        self.headers = headers or {"content-type": "application/json"}
        self.content = content
        self.ok = status < 400

    def json(self):
        return self._d

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.HTTPError(str(self.status_code))


NOW = int(time.time())


def _jpeg():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (600, 900), (40, 90, 160)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


JPEG = _jpeg()
OWNED = {"response": {"game_count": 4, "games": [
    {"appid": 243470, "name": "Watch_Dogs", "playtime_forever": 1710, "playtime_2weeks": 78, "rtime_last_played": NOW - 86400},
    {"appid": 1172380, "name": "STAR WARS Jedi: Survivor", "playtime_forever": 2400, "rtime_last_played": NOW - 60 * 86400},
    {"appid": 220, "name": "Half-Life 2", "playtime_forever": 0, "rtime_last_played": 0},
    {"appid": 1145360, "name": "Hades", "playtime_forever": 3000, "rtime_last_played": NOW - 200 * 86400},
]}}
ACH = {
    "243470": [{"apiname": f"a{i}", "achieved": 1 if i < 13 else 0, "unlocktime": NOW - 86400 if i < 13 else 0} for i in range(49)],
    "1172380": [{"apiname": f"a{i}", "achieved": 1, "unlocktime": 1756800000 + i} for i in range(53)],
    "220": [{"apiname": "x", "achieved": 0, "unlocktime": 0}],
}
calls = []


def fake_get(url, params=None, **kw):
    calls.append(url)
    if "GetOwnedGames" in url:
        return Resp(OWNED)
    if "ResolveVanityURL" in url:
        return Resp({"response": {"success": 1, "steamid": "76561190000000000"}})
    if "GetGlobalAchievementPercentagesForApp" in url:
        a = ACH.get(str(params["gameid"])) or []
        return Resp({"achievementpercentages": {"achievements": [
            {"name": x["apiname"], "percent": str(round(80 - i * 1.5, 1))} for i, x in enumerate(a)]}})
    if "GetSchemaForGame" in url:
        a = ACH.get(str(params["appid"])) or []
        return Resp({"game": {"availableGameStats": {"achievements": [
            {"name": x["apiname"], "displayName": f"Erfolg {i}", "description": f"Beschreibung {i}",
             "icon": f"https://img/ach{i}.jpg", "icongray": f"https://img/ach{i}g.jpg", "hidden": int(i == 3)}
            for i, x in enumerate(a)]}}})
    if "GetPlayerAchievements" in url:
        a = ACH.get(str(params["appid"]))
        if a is None:
            return Resp({"playerstats": {"error": "Requested app has no stats", "success": False}}, 400)
        return Resp({"playerstats": {"achievements": a, "success": True}})
    if "oauth/authorize" in url:
        return Resp(status=302, headers={"Location": "com.scee.psxandroid.scecompcall://redirect/?code=v3.ABC&cid=x"})
    if "trophyTitles" in url:
        return Resp({"trophyTitles": [
            {"npCommunicationId": "NPWR1", "trophyTitleName": "Astro Bot", "trophyTitlePlatform": "PS5",
             "trophyTitleIconUrl": "https://img/astro.png", "progress": 100,
             "earnedTrophies": {"bronze": 40, "silver": 2, "gold": 2, "platinum": 1},
             "definedTrophies": {"bronze": 40, "silver": 2, "gold": 2, "platinum": 1},
             "lastUpdatedDateTime": "2025-10-02T18:00:00Z"},
            {"npCommunicationId": "NPWR2", "trophyTitleName": "Ghost of Tsushima", "trophyTitlePlatform": "PS4",
             "trophyTitleIconUrl": "", "progress": 40,
             "earnedTrophies": {"bronze": 20, "silver": 3, "gold": 0, "platinum": 0},
             "definedTrophies": {"bronze": 40, "silver": 10, "gold": 2, "platinum": 1},
             "lastUpdatedDateTime": "2024-01-01T10:00:00Z"},
        ], "totalItemCount": 2})
    if "/trophies" in url:
        assert params["npServiceName"] in ("trophy", "trophy2")
        return Resp({"trophies": [
            {"trophyId": 1, "trophyName": "Erste", "trophyDetail": "x", "trophyIconUrl": "https://img/t1.png",
             "trophyType": "bronze", "earned": True, "earnedDateTime": "2025-09-30T10:00:00Z", "trophyEarnedRate": "60.2"},
            {"trophyId": 0, "trophyName": "Alle", "trophyDetail": "y", "trophyIconUrl": "https://img/t0.png",
             "trophyType": "platinum", "earned": True, "earnedDateTime": "2025-10-01T21:15:00Z", "trophyEarnedRate": "3.1"}]})
    if "xbl.io" in url:
        return Resp({"titles": [{"titleId": "1234", "name": "Forza Horizon 5", "devices": ["XboxSeries"],
                                 "displayImage": "https://img/fh5.png",
                                 "achievement": {"currentAchievements": 10, "totalAchievements": 10, "progressPercentage": 100},
                                 "titleHistory": {"lastTimePlayed": "2025-03-03T12:00:00Z"}}]})
    if url.startswith("https://img/") or "steamstatic" in url or "githubusercontent" in url:
        if "missing" in url:
            return Resp(status=404, headers={"content-type": "text/html"})
        return Resp(status=200, headers={"content-type": "image/jpeg"}, content=JPEG)
    raise AssertionError("Unerwartete URL " + url)


def fake_post(url, **kw):
    assert kw["data"]["code"] == "v3.ABC"
    return Resp({"access_token": "TOKEN"})


sync.requests.get = fake_get
sync.requests.post = fake_post
covers.requests.get = fake_get


def g(title):
    return dict(db.conn().execute("SELECT * FROM games WHERE title=?", (title,)).fetchone())


def run():
    db.init()
    c = app.test_client()
    import types
    sync.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time)

    # Ohne Zugangsdaten → saubere Meldung
    assert c.post("/api/sync", json={}).status_code == 400

    c.post("/api/settings", json={"steam_api_key": "KEY", "steam_id": "meinname",
                                  "psn_npsso": "NPSSO", "xbl_api_key": "XBL"})
    s = c.get("/api/settings").get_json()
    assert s["steam_api_key"].endswith("•KEY"[-4:]) and "KEY" != s["steam_api_key"]
    assert set(s["configured"]) == {"steam", "playstation", "xbox"}

    print(sync.sync_steam())
    print(sync.sync_playstation())
    print(sync.sync_xbox())

    wd = g("Watch_Dogs")
    assert (wd["unlocked"], wd["total"], wd["status"]) == (13, 49, "playing"), wd
    jedi = g("STAR WARS Jedi: Survivor")
    assert jedi["status"] == "completed" and jedi["completed_at"] == 1756800052, jedi
    hades = g("Hades")
    assert hades["status"] == "none" and hades["total"] == 0
    astro = g("Astro Bot")
    assert astro["status"] == "completed" and astro["platinum"] == 1
    assert astro["completed_at"] == int(sync._iso_to_ts("2025-10-01T21:15:00Z")), astro
    assert g("Ghost of Tsushima")["status"] == "none"
    assert g("Forza Horizon 5")["status"] == "completed"

    # Zweiter Sync: nur geänderte Spiele werden neu abgefragt
    calls.clear()
    sync.sync_steam()
    assert sum("GetPlayerAchievements" in u for u in calls) == 0, calls

    # Nutzer setzt Hades auf "Durchgespielt" → bleibt nach Sync
    r = c.patch(f"/api/games/{hades['id']}", json={"status": "finished", "status_auto": False})
    assert r.get_json()["status"] == "finished"
    OWNED["response"]["games"][3]["rtime_last_played"] = NOW - 10
    sync.sync_steam()
    assert g("Hades")["status"] == "finished"

    # Watch Dogs wird 100 % → überschreibt alles, Datum = letzter Erfolg
    for a in ACH["243470"]:
        a.update(achieved=1, unlocktime=NOW - 3600)
    OWNED["response"]["games"][0]["rtime_last_played"] = NOW - 3000
    sync.sync_steam()
    wd = g("Watch_Dogs")
    assert wd["status"] == "completed" and wd["completed_at"] == NOW - 3600

    # DLC fügt Erfolge hinzu → 100 % verloren → "Durchgespielt"
    ACH["1172380"].append({"apiname": "dlc", "achieved": 0, "unlocktime": 0})
    OWNED["response"]["games"][1]["rtime_last_played"] = NOW - 5
    sync.sync_steam()
    assert g("STAR WARS Jedi: Survivor")["status"] == "finished"

    # Manuell: Nintendo-Spiel
    r = c.post("/api/games", json={"title": "Zelda: Tears of the Kingdom", "platform": "nintendo",
                                    "status": "completed", "completed_at": "2024-06-01", "tags": "Lieblingsspiel, Switch"})
    assert r.status_code == 201, r.get_json()
    zid = r.get_json()["id"]
    assert r.get_json()["tags"] == ["Lieblingsspiel", "Switch"]

    st = c.get("/api/stats").get_json()
    print("Stats:", st)
    assert st["completed"] == 4 and st["platinum"] == 1

    # Cover: Steam offiziell, eigene Vorlage mit Fallback, Platzhalter
    r = c.get(f"/cover/{wd['id']}")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    c.post("/api/settings", json={"custom_templates": "Repo | https://raw.githubusercontent.com/x/y/main/{appid}.jpg\nKaputt | https://raw.githubusercontent.com/missing/{slug}.png"})
    styles = [s["id"] for s in c.get("/api/styles").get_json()]
    assert styles == ["official", "case", "custom:0", "custom:1"], styles
    calls.clear()
    assert c.get(f"/cover/{wd['id']}?style=custom:0").status_code == 200
    assert any("githubusercontent.com/x/y/main/243470.jpg" in u for u in calls), calls
    calls.clear()
    r = c.get(f"/cover/{wd['id']}?style=custom:1")
    assert r.mimetype == "image/jpeg" and any("missing/watch-dogs.png" in u for u in calls)
    r = c.get(f"/cover/{zid}")
    assert r.mimetype == "image/svg+xml"
    opts = c.get(f"/api/games/{wd['id']}/cover-options").get_json()
    assert len(opts) == 3

    # Ausblenden / Löschen
    assert c.delete(f"/api/games/{hades['id']}").get_json()["ok"]
    assert g("Hades")["hidden"] == 1
    c.delete(f"/api/games/{zid}")
    assert db.conn().execute("SELECT COUNT(*) n FROM games WHERE id=?", (zid,)).fetchone()["n"] == 0

    # Export/Import
    dump = c.get("/api/export").get_json()
    assert c.post("/api/import", json=dump).get_json()["imported"] == len(dump["games"])

    # Hintergrund-Sync über die API
    assert c.post("/api/sync", json={"platforms": ["steam"]}).status_code == 200
    for _ in range(100):
        if not c.get("/api/sync/status").get_json()["running"]:
            break
        time.sleep(0.05)
    st = c.get("/api/sync/status").get_json()
    assert not st["running"] and not st["errors"], st
    # Einzelerfolge: gespeichert beim Sync, Details beim Öffnen
    wd = g("Watch_Dogs")
    d = c.get(f"/api/games/{wd['id']}/achievements").get_json()
    assert d["summary"]["total"] == 49 and d["summary"]["unlocked"] == 49, d["summary"]
    a0 = d["achievements"][0]
    assert a0["name"] == "Erfolg 0" and a0["icon"] and a0["rarity"] == 80.0, a0
    assert d["achievements"][3]["hidden"] == 1
    assert d["summary"]["max_100_pct"] == 8.0, d["summary"]["max_100_pct"]
    gh = g("Ghost of Tsushima")
    d = c.get(f"/api/games/{gh['id']}/achievements").get_json()
    assert d["summary"]["types"][0]["key"] == "platinum" and d["summary"]["types"][0]["total"] == 1 and d["achievements"][0]["name"], d
    st = c.get("/api/stats/achievements").get_json()
    assert st["total"] >= 49 and len(st["heatmap"]) == 7 and len(st["calendar"]) == 365, st["total"]
    assert st["rarest"][0]["rarity"] <= st["rarest"][-1]["rarity"]
    print("Alle Tests bestanden.")




def run_cover_fallback_test():
    """Ältere/aus dem Shop genommene Spiele: kein library_600x900 → Store-API → erzeugtes Hochformat."""
    import io
    from PIL import Image
    c = db.conn()
    ts = db.now()
    for appid, title in (("111", "Hash Game"), ("222", "Delisted Game"), ("333", "Nichts")):
        c.execute("INSERT INTO games(platform, ext_id, title, status, created_at, updated_at) VALUES('steam',?,?,'completed',?,?)",
                  (appid, title, ts, ts))
    c.commit()
    land = io.BytesIO()
    Image.new("RGB", (460, 215), (200, 30, 30)).save(land, "JPEG")
    seen = []

    def get(url, params=None, **kw):
        seen.append(url)
        if "GetItems" in url:
            import json as _j
            appid = _j.loads(params["input_json"])["ids"][0]["appid"]
            if appid == 111:
                return Resp({"response": {"store_items": [{"assets": {
                    "asset_url_format": "steam/apps/111/abc123/${FILENAME}?t=1",
                    "library_capsule": "library_600x900.jpg", "header": "header.jpg"}}]}})
            return Resp({"response": {"store_items": [{"success": 2}]}})
        if "abc123/library_600x900.jpg" in url:
            return Resp(status=200, headers={"content-type": "image/jpeg"}, content=JPEG)
        if "/222/header.jpg" in url:
            return Resp(status=200, headers={"content-type": "image/jpeg"}, content=land.getvalue())
        return Resp(status=404, headers={"content-type": "text/html"})

    covers.requests.get = get
    cl = app.test_client()
    ids = {r["title"]: r["id"] for r in c.execute("SELECT id, title FROM games WHERE ext_id IN ('111','222','333')")}
    r = cl.get(f"/cover/{ids['Hash Game']}?style=official")
    assert r.mimetype == "image/jpeg" and r.data == JPEG, "Store-API-Cover nicht genutzt"
    r = cl.get(f"/cover/{ids['Delisted Game']}?style=official")
    im = Image.open(io.BytesIO(r.data))
    assert r.mimetype == "image/jpeg" and im.size == (600, 900), (r.mimetype, im.size)
    im.save(os.path.join(TMP, "generated.jpg"))
    r = cl.get(f"/cover/{ids['Nichts']}?style=official")
    assert r.mimetype == "image/svg+xml" and r.headers["Cache-Control"] == "no-cache"
    # Neustart vergisst Fehlschläge
    db.init()
    assert c.execute("SELECT COUNT(*) n FROM cover_cache WHERE file=''").fetchone()["n"] == 0
    covers.requests.get = fake_get
    print("Cover-Fallback-Test bestanden")


def run_case_test(repo_assets):
    """Spielhülle mit den echten Grafiken aus einem lokalen Klon von steam-case-covers."""
    from app import casecover
    from PIL import Image
    import io

    def local_get(url, **kw):
        if url == casecover.FONT_URL:
            with open(os.path.join(repo_assets, "..", "tools/src/fonts/NunitoSans.ttf"), "rb") as fh:
                return Resp(status=200, content=fh.read())
        if url.startswith(casecover.ASSET_BASE):
            with open(os.path.join(repo_assets, url[len(casecover.ASSET_BASE):]), "rb") as fh:
                return Resp(status=200, headers={"content-type": "image/png"}, content=fh.read())
        return fake_get(url, **kw)

    casecover.requests.get = local_get
    art = io.BytesIO()
    Image.new("RGB", (600, 900), (200, 60, 40)).save(art, "JPEG")
    for plat, sub, status in [("steam", "", "completed"), ("playstation", "PS4", "completed"),
                              ("nintendo", "", "finished"), ("xbox", "XboxSeries", "completed")]:
        g = {"platform": plat, "sub_platform": sub, "status": status, "title": "Test"}
        png = casecover.compose(art.getvalue(), g, "gruen" if plat == "steam" else "blau", "full")
        im = Image.open(io.BytesIO(png))
        assert im.size == (600, 900) and im.mode == "RGBA"
        im.save(os.path.join(TMP, f"case-{plat}.png"))
    png = casecover.compose(art.getvalue(), {"platform": "steam", "status": "completed", "title": "x"}, "schwarz", "gold")
    for marks in ("full", "rosette", "gold"):
        ps = {"platform": "playstation", "sub_platform": "PS5", "status": "completed", "platinum": 1, "title": "x"}
        plat = Image.open(io.BytesIO(casecover.compose(art.getvalue(), ps, "blau", marks)))
        rose = Image.open(io.BytesIO(casecover.compose(art.getvalue(), ps, "blau", marks, ps_platinum=False)))
        assert plat.tobytes() != rose.tobytes()
    Image.open(io.BytesIO(png)).save(os.path.join(TMP, "case-gold.png"))

    c = app.test_client()
    wd = g_ = dict(db.conn().execute("SELECT * FROM games WHERE platform='steam' AND status='completed'").fetchone())
    r = c.get(f"/cover/{wd['id']}?style=case")
    assert r.status_code == 200 and r.mimetype == "image/png", r.mimetype
    print("Spielhüllen-Test bestanden, Bilder in", TMP)



if __name__ == "__main__":
    run()
    run_cover_fallback_test()
    if len(sys.argv) > 1:
        run_case_test(sys.argv[1])
