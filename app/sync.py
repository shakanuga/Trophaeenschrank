"""Abgleich mit Steam, PlayStation Network und Xbox (OpenXBL)."""
import base64
import logging
import threading
import time
import urllib.parse
from datetime import datetime, timezone

import requests

from . import db

log = logging.getLogger("sync")
UA = {"User-Agent": "Trophaeenschrank/1.0 (self-hosted)"}
PLAYING_WINDOW = 14 * 86400


class SyncError(Exception):
    pass


# ---------------------------------------------------------------- Status --

class Progress:
    """Gemeinsamer Fortschritt, den die Oberfläche abfragt."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.platform = ""
        self.done = 0
        self.total = 0
        self.message = ""
        self.errors = {}
        self.last = {}

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running,
                "platform": self.platform,
                "done": self.done,
                "total": self.total,
                "message": self.message,
                "errors": dict(self.errors),
                "last": dict(self.last),
            }

    def set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)


progress = Progress()
_job_lock = threading.Lock()


def _iso_to_ts(s):
    if not s:
        return 0
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


# ----------------------------------------------------------- Upsert/Logik --

def upsert_synced(platform, ext_id, title, *, completed_candidate=0, playing=False, **f):
    """Legt ein Spiel an oder aktualisiert es und leitet den Status ab."""
    c = db.conn()
    row = c.execute(
        "SELECT * FROM games WHERE platform=? AND ext_id=?", (platform, str(ext_id))
    ).fetchone()
    ts = db.now()
    if row is None:
        c.execute(
            "INSERT INTO games(platform, ext_id, title, created_at, updated_at) VALUES(?,?,?,?,?)",
            (platform, str(ext_id), title, ts, ts),
        )
        row = c.execute(
            "SELECT * FROM games WHERE platform=? AND ext_id=?", (platform, str(ext_id))
        ).fetchone()

    cur = dict(row)
    cur.update({k: v for k, v in f.items() if v is not None})
    cur["title"] = title or cur["title"]

    complete = bool(cur.get("platinum")) or (cur["total"] > 0 and cur["unlocked"] >= cur["total"])
    if complete:
        cur["status"] = "completed"
        if not cur["completed_locked"]:
            cur["completed_at"] = completed_candidate or cur["completed_at"] or ts
    elif cur["status_locked"]:
        pass  # vom Nutzer gesetzt, bleibt
    elif cur["status"] == "completed":
        # War 100 %, aber z.B. durch DLC kamen neue Erfolge dazu
        cur["status"] = "finished"
    else:
        cur["status"] = "playing" if playing else "none"

    fields = [
        "title", "sub_platform", "status", "unlocked", "total", "platinum",
        "playtime_min", "playtime_2w", "last_played", "completed_at", "cover_src",
        "ach_checked_lp",
    ]
    c.execute(
        f"UPDATE games SET {', '.join(f + '=?' for f in fields)}, updated_at=? WHERE id=?",
        [cur[k] for k in fields] + [ts, cur["id"]],
    )
    return cur


# ------------------------------------------------------------------ Steam --

STEAM_API = "https://api.steampowered.com"


def _steam_get(path, params, allow_400=False):
    r = requests.get(f"{STEAM_API}/{path}", params=params, headers=UA, timeout=30)
    if r.status_code == 429:
        time.sleep(10)
        r = requests.get(f"{STEAM_API}/{path}", params=params, headers=UA, timeout=30)
    if r.status_code in (401, 403) and "GetOwnedGames" in path:
        raise SyncError("Steam lehnt den Zugriff ab – API-Key prüfen.")
    if r.status_code == 400 and allow_400:
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code == 403 and allow_400:
        return {"_private": True}
    r.raise_for_status()
    return r.json()


def steam_resolve_id(key, value):
    value = (value or "").strip().rstrip("/")
    if "steamcommunity.com" in value:
        value = value.split("/")[-1]
    if value.isdigit() and len(value) == 17:
        return value
    data = _steam_get("ISteamUser/ResolveVanityURL/v1/", {"key": key, "vanityurl": value})
    resp = data.get("response", {})
    if resp.get("success") != 1:
        raise SyncError(f"Steam-Profil „{value}“ nicht gefunden.")
    return resp["steamid"]


def sync_steam(full=False):
    key = db.get_setting("steam_api_key")
    sid = db.get_setting("steam_id")
    if not key or not sid:
        raise SyncError("Steam: API-Key und Steam-ID fehlen in den Einstellungen.")
    steamid = steam_resolve_id(key, sid)
    lang = db.get_setting("language", "german")

    progress.set(message="Steam: Bibliothek wird geladen …")
    data = _steam_get(
        "IPlayerService/GetOwnedGames/v1/",
        {"key": key, "steamid": steamid, "include_appinfo": 1,
         "include_played_free_games": 1, "format": "json"},
    )
    games = data.get("response", {}).get("games")
    if games is None:
        raise SyncError("Steam liefert keine Spiele – ist „Spieldetails“ im Profil auf öffentlich gestellt?")

    c = db.conn()
    existing = {
        r["ext_id"]: dict(r)
        for r in c.execute("SELECT ext_id, ach_checked_lp, total, unlocked FROM games WHERE platform='steam'")
    }

    todo = []
    for g in games:
        appid = str(g["appid"])
        lp = int(g.get("rtime_last_played") or 0)
        prev = existing.get(appid)
        needs = full or prev is None or prev["ach_checked_lp"] != lp
        if g.get("playtime_forever", 0) == 0 and not full:
            needs = prev is None  # nie gespielt: einmal prüfen, dann nicht mehr
        upsert_synced(
            "steam", appid, g.get("name", f"App {appid}"),
            playtime_min=g.get("playtime_forever", 0),
            playtime_2w=g.get("playtime_2weeks", 0),
            last_played=lp,
            playing=g.get("playtime_2weeks", 0) > 0,
            ach_checked_lp=None,
        )
        if needs:
            todo.append((appid, g))
    c.commit()

    progress.set(total=len(todo), done=0)
    private_hit = False
    for i, (appid, g) in enumerate(todo, 1):
        progress.set(done=i, message=f"Steam: Erfolge {i}/{len(todo)} – {g.get('name', appid)}")
        try:
            a = _steam_get(
                "ISteamUserStats/GetPlayerAchievements/v1/",
                {"key": key, "steamid": steamid, "appid": appid, "l": lang},
                allow_400=True,
            )
        except requests.RequestException as e:
            log.warning("Steam %s: %s", appid, e)
            continue
        if a.get("_private"):
            private_hit = True
            break
        ps = a.get("playerstats", {})
        ach = ps.get("achievements") or []
        unlocked = [x for x in ach if x.get("achieved")]
        last_unlock = max((x.get("unlocktime", 0) for x in unlocked), default=0)
        upsert_synced(
            "steam", appid, g.get("name", f"App {appid}"),
            unlocked=len(unlocked), total=len(ach),
            completed_candidate=last_unlock,
            playing=g.get("playtime_2weeks", 0) > 0,
            ach_checked_lp=int(g.get("rtime_last_played") or 0),
        )
        if i % 20 == 0:
            c.commit()
        time.sleep(0.15)
    c.commit()
    if private_hit:
        raise SyncError("Steam: Erfolge sind privat – im Steam-Profil „Spieldetails“ auf öffentlich stellen.")
    return f"{len(games)} Spiele, {len(todo)} Erfolgslisten aktualisiert"


# ----------------------------------------------------------- PlayStation --
# Inoffizielle API (dieselbe wie die PlayStation-App), Anmeldung per NPSSO-Token.

PSN_AUTH = "https://ca.account.sony.com/api/authz/v3/oauth"
PSN_CLIENT = "09515159-7237-4370-9b40-3806e67c0891"
PSN_BASIC = base64.b64encode(b"09515159-7237-4370-9b40-3806e67c0891:ucPjka5tntB2KqsP").decode()
PSN_REDIRECT = "com.scee.psxandroid.scecompcall://redirect"
PSN_API = "https://m.np.playstation.com/api/trophy/v1"


def _psn_token(npsso):
    params = {
        "access_type": "offline", "client_id": PSN_CLIENT, "redirect_uri": PSN_REDIRECT,
        "response_type": "code", "scope": "psn:mobile.v2.core psn:clientapp",
    }
    r = requests.get(f"{PSN_AUTH}/authorize", params=params, cookies={"npsso": npsso},
                     headers=UA, allow_redirects=False, timeout=30)
    loc = r.headers.get("Location", "")
    code = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("code", [None])[0]
    if not code:
        raise SyncError("PlayStation: NPSSO-Token ungültig oder abgelaufen – bitte neu eintragen.")
    r = requests.post(
        f"{PSN_AUTH}/token",
        data={"code": code, "redirect_uri": PSN_REDIRECT,
              "grant_type": "authorization_code", "token_format": "jwt"},
        headers={**UA, "Authorization": f"Basic {PSN_BASIC}"}, timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _psn_platinum_date(tok, npid, platform):
    service = "trophy" if any(p in platform for p in ("PS3", "PS4", "PSVITA")) else "trophy2"
    r = requests.get(
        f"{PSN_API}/users/me/npCommunicationIds/{npid}/trophyGroups/all/trophies",
        params={"npServiceName": service},
        headers={**UA, "Authorization": f"Bearer {tok}"}, timeout=30,
    )
    if not r.ok:
        return 0
    dates = [_iso_to_ts(t.get("earnedDateTime")) for t in r.json().get("trophies", [])
             if t.get("earned")]
    plat = [_iso_to_ts(t.get("earnedDateTime")) for t in r.json().get("trophies", [])
            if t.get("earned") and t.get("trophyType") == "platinum"]
    return (plat or [max(dates, default=0)])[0]


def sync_playstation(full=False):
    npsso = db.get_setting("psn_npsso")
    if not npsso:
        raise SyncError("PlayStation: NPSSO-Token fehlt in den Einstellungen.")
    progress.set(message="PlayStation: Anmeldung …")
    tok = _psn_token(npsso.strip())
    titles, offset = [], 0
    while True:
        r = requests.get(f"{PSN_API}/users/me/trophyTitles", params={"limit": 800, "offset": offset},
                         headers={**UA, "Authorization": f"Bearer {tok}"}, timeout=30)
        r.raise_for_status()
        d = r.json()
        titles += d.get("trophyTitles", [])
        offset = d.get("nextOffset")
        if not offset:
            break

    c = db.conn()
    known = {r["ext_id"]: dict(r) for r in c.execute(
        "SELECT ext_id, completed_at, platinum FROM games WHERE platform='playstation'")}
    progress.set(total=len(titles), done=0)
    for i, t in enumerate(titles, 1):
        npid = t["npCommunicationId"]
        progress.set(done=i, message=f"PlayStation: {t.get('trophyTitleName', npid)}")
        earned, defined = t.get("earnedTrophies", {}), t.get("definedTrophies", {})
        unlocked = sum(earned.get(k, 0) for k in ("bronze", "silver", "gold", "platinum"))
        total = sum(defined.get(k, 0) for k in ("bronze", "silver", "gold", "platinum"))
        updated = _iso_to_ts(t.get("lastUpdatedDateTime"))
        has_plat = bool(earned.get("platinum"))
        cand = updated
        prev = known.get(npid)
        if (has_plat or (total and unlocked >= total)) and (full or not prev or not prev["completed_at"]):
            try:
                cand = _psn_platinum_date(tok, npid, t.get("trophyTitlePlatform", "")) or updated
            except requests.RequestException:
                pass
        elif prev and prev["completed_at"]:
            cand = prev["completed_at"]
        upsert_synced(
            "playstation", npid, t.get("trophyTitleName", npid),
            sub_platform=t.get("trophyTitlePlatform", ""),
            unlocked=unlocked, total=total, platinum=1 if has_plat else 0,
            last_played=updated, cover_src=t.get("trophyTitleIconUrl", ""),
            completed_candidate=cand,
            playing=(db.now() - updated) < PLAYING_WINDOW,
        )
    c.commit()
    return f"{len(titles)} Trophäenlisten aktualisiert"


# ------------------------------------------------------------------- Xbox --
# Über OpenXBL (xbl.io), kostenloser API-Key nach Anmeldung mit dem Xbox-Konto.

def sync_xbox(full=False):
    key = db.get_setting("xbl_api_key")
    if not key:
        raise SyncError("Xbox: OpenXBL-API-Key fehlt in den Einstellungen.")
    progress.set(message="Xbox: Erfolge werden geladen …")
    r = requests.get("https://xbl.io/api/v2/achievements",
                     headers={**UA, "X-Authorization": key, "Accept": "application/json"}, timeout=60)
    if r.status_code in (401, 403):
        raise SyncError("Xbox: OpenXBL-Key ungültig.")
    r.raise_for_status()
    titles = r.json().get("titles", [])
    progress.set(total=len(titles), done=0)
    for i, t in enumerate(titles, 1):
        progress.set(done=i, message=f"Xbox: {t.get('name')}")
        a = t.get("achievement") or {}
        cur, tot = int(a.get("currentAchievements") or 0), int(a.get("totalAchievements") or 0)
        lp = _iso_to_ts((t.get("titleHistory") or {}).get("lastTimePlayed"))
        if tot == 0 and a.get("progressPercentage") == 100:
            cur = tot = 1
        upsert_synced(
            "xbox", t.get("titleId"), t.get("name", ""),
            sub_platform=", ".join(t.get("devices") or []),
            unlocked=cur, total=tot, last_played=lp,
            cover_src=t.get("displayImage", ""),
            completed_candidate=lp,
            playing=(db.now() - lp) < PLAYING_WINDOW,
        )
    db.conn().commit()
    return f"{len(titles)} Titel aktualisiert"


# ------------------------------------------------------------- Steuerung --

SYNCERS = {"steam": sync_steam, "playstation": sync_playstation, "xbox": sync_xbox}
CONFIG_KEYS = {"steam": "steam_api_key", "playstation": "psn_npsso", "xbox": "xbl_api_key"}


def configured_platforms():
    return [p for p, k in CONFIG_KEYS.items() if db.get_setting(k)]


def run(platforms, full=False):
    if not _job_lock.acquire(blocking=False):
        return False

    def worker():
        try:
            progress.set(running=True, errors={})
            errors = {}
            for p in platforms:
                progress.set(platform=p, done=0, total=0)
                try:
                    msg = SYNCERS[p](full=full)
                    db.set_setting(f"last_sync_{p}", db.now())
                    db.set_setting(f"last_sync_msg_{p}", msg)
                except Exception as e:  # noqa: BLE001 – Fehler pro Plattform anzeigen
                    log.exception("Sync %s fehlgeschlagen", p)
                    errors[p] = str(e)
                    db.conn().commit()
            last = {p: db.get_setting(f"last_sync_{p}") for p in SYNCERS}
            progress.set(errors=errors, last=last, message="Fertig")
        finally:
            progress.set(running=False, platform="")
            _job_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


def scheduler():
    """Synchronisiert alle konfigurierten Plattformen im eingestellten Intervall."""
    while True:
        time.sleep(60)
        try:
            hours = float(db.get_setting("sync_interval_hours", "6") or 0)
            if hours <= 0:
                continue
            due = []
            for p in configured_platforms():
                last = int(db.get_setting(f"last_sync_{p}", "0") or 0)
                if db.now() - last >= hours * 3600:
                    due.append(p)
            if due:
                run(due)
        except Exception:  # noqa: BLE001
            log.exception("Scheduler")
