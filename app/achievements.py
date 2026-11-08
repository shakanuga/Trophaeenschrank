"""Einzelne Erfolge/Trophäen: speichern, Details nachladen, auswerten."""
import logging
import os
from datetime import datetime, timedelta

import requests

from . import db

log = logging.getLogger("achievements")
UA = {"User-Agent": "Trophaeenschrank/1.0 (self-hosted)"}
STEAM_API = "https://api.steampowered.com"
RARITY_TTL = 7 * 86400

# Seltenheits-Stufen (Anteil aller Spieler in %)
RARITY_BANDS = [
    ("extrem", "Extrem selten", 0, 5),
    ("sehr", "Sehr selten", 5, 10),
    ("selten", "Selten", 10, 25),
    ("ungewoehnlich", "Ungewöhnlich", 25, 50),
    ("haeufig", "Häufig", 50, 101),
]


def band(r):
    if r is None:
        return None
    for key, _, lo, hi in RARITY_BANDS:
        if lo <= r < hi:
            return key
    return "haeufig"


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
    except Exception:  # noqa: BLE001 – ohne Zeitzonen-Daten: Serverzeit
        return None


def _meta(game_id):
    row = db.conn().execute("SELECT * FROM ach_meta WHERE game_id=?", (game_id,)).fetchone()
    return dict(row) if row else {"game_id": game_id, "details_ts": 0, "rarity_ts": 0}


def _set_meta(game_id, **kw):
    m = _meta(game_id)
    m.update(kw)
    db.conn().execute("INSERT OR REPLACE INTO ach_meta(game_id, details_ts, rarity_ts) VALUES(?,?,?)",
                      (game_id, m["details_ts"], m["rarity_ts"]))


# ------------------------------------------------------------- Steam -----

def store_steam(game_id, ach):
    """Speichert die Liste aus GetPlayerAchievements (mit l=… inkl. Name/Beschreibung)."""
    c = db.conn()
    for i, a in enumerate(ach):
        c.execute(
            """INSERT INTO achievements(game_id, api_name, name, description, unlocked, unlock_time, sort)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(game_id, api_name) DO UPDATE SET
                 unlocked=excluded.unlocked, unlock_time=excluded.unlock_time,
                 name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE achievements.name END,
                 description=CASE WHEN excluded.description<>'' THEN excluded.description ELSE achievements.description END""",
            (game_id, a.get("apiname", ""), a.get("name") or "", a.get("description") or "",
             1 if a.get("achieved") else 0, int(a.get("unlocktime") or 0), i),
        )


def steam_rarity(appid):
    r = requests.get(f"{STEAM_API}/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/",
                     params={"gameid": appid}, headers=UA, timeout=20)
    if not r.ok:
        return {}
    items = (r.json().get("achievementpercentages") or {}).get("achievements") or []
    out = {}
    for x in items:
        try:
            out[x["name"]] = round(float(x["percent"]), 2)
        except (KeyError, TypeError, ValueError):
            pass
    return out


def store_rarity(game_id, rarity):
    c = db.conn()
    for name, pct in rarity.items():
        c.execute("UPDATE achievements SET rarity=? WHERE game_id=? AND api_name=?", (pct, game_id, name))
    _set_meta(game_id, rarity_ts=db.now())


def rarity_due(game_id):
    return db.now() - _meta(game_id)["rarity_ts"] > RARITY_TTL


def _steam_details(g):
    key = db.get_setting("steam_api_key")
    if not key:
        return
    lang = db.get_setting("language", "german") or "german"
    r = requests.get(f"{STEAM_API}/ISteamUserStats/GetSchemaForGame/v2/",
                     params={"key": key, "appid": g["ext_id"], "l": lang}, headers=UA, timeout=20)
    if not r.ok:
        return
    schema = ((r.json().get("game") or {}).get("availableGameStats") or {}).get("achievements") or []
    c = db.conn()
    for i, a in enumerate(schema):
        c.execute(
            """INSERT INTO achievements(game_id, api_name, name, description, icon, icon_gray, hidden, sort)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(game_id, api_name) DO UPDATE SET
                 name=excluded.name, description=CASE WHEN excluded.description<>'' THEN excluded.description
                                                      ELSE achievements.description END,
                 icon=excluded.icon, icon_gray=excluded.icon_gray, hidden=excluded.hidden, sort=excluded.sort""",
            (g["id"], a.get("name", ""), a.get("displayName", ""), a.get("description", ""),
             a.get("icon", ""), a.get("icongray", ""), int(a.get("hidden") or 0), i),
        )
    _set_meta(g["id"], details_ts=db.now())


_steamid_cache = {}


def _steam_player(g):
    """Eigenen Stand (freigeschaltet + Datum) für ein Spiel laden."""
    from .sync import steam_resolve_id
    key, sid = db.get_setting("steam_api_key"), db.get_setting("steam_id")
    if not key or not sid:
        return
    if sid not in _steamid_cache:
        _steamid_cache[sid] = steam_resolve_id(key, sid)
    lang = db.get_setting("language", "german") or "german"
    r = requests.get(f"{STEAM_API}/ISteamUserStats/GetPlayerAchievements/v1/",
                     params={"key": key, "steamid": _steamid_cache[sid], "appid": g["ext_id"], "l": lang},
                     headers=UA, timeout=20)
    if r.ok:
        store_steam(g["id"], (r.json().get("playerstats") or {}).get("achievements") or [])


def _out_of_sync(g):
    """Stimmt die Zahl der freigeschalteten Einzelerfolge nicht mit dem Spiel überein?"""
    row = db.conn().execute("SELECT COUNT(*) n, COALESCE(SUM(unlocked), 0) u FROM achievements WHERE game_id=?",
                            (g["id"],)).fetchone()
    return row["n"] == 0 or row["u"] != (g["unlocked"] or 0)


# ------------------------------------------------------- PlayStation -----

PSN_API = "https://m.np.playstation.com/api/trophy/v1"


def psn_service(platform):
    return "trophy" if any(p in (platform or "") for p in ("PS3", "PS4", "PSVITA")) else "trophy2"


def store_psn_earned(game_id, trophies):
    """Trophäen aus /users/me/…/trophies (Status, Datum, Typ, Seltenheit)."""
    from .sync import _iso_to_ts
    c = db.conn()
    for t in trophies:
        try:
            rate = round(float(t.get("trophyEarnedRate")), 2) if t.get("trophyEarnedRate") is not None else None
        except (TypeError, ValueError):
            rate = None
        c.execute(
            """INSERT INTO achievements(game_id, api_name, trophy_type, hidden, unlocked, unlock_time, rarity, sort)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(game_id, api_name) DO UPDATE SET trophy_type=excluded.trophy_type,
                 unlocked=excluded.unlocked, unlock_time=excluded.unlock_time,
                 rarity=COALESCE(excluded.rarity, achievements.rarity)""",
            (game_id, str(t.get("trophyId")), t.get("trophyType", ""), 1 if t.get("trophyHidden") else 0,
             1 if t.get("earned") else 0, _iso_to_ts(t.get("earnedDateTime")) if t.get("earned") else 0,
             rate, int(t.get("trophyId") or 0)),
        )
    _set_meta(game_id, rarity_ts=db.now())


def _psn_details(g):
    from .sync import _psn_token
    npsso = db.get_setting("psn_npsso")
    if not npsso:
        return
    tok = _psn_token(npsso.strip())
    hdr = {**UA, "Authorization": f"Bearer {tok}"}
    svc = {"npServiceName": psn_service(g["sub_platform"])}
    path = f"npCommunicationIds/{g['ext_id']}/trophyGroups/all/trophies"
    r = requests.get(f"{PSN_API}/{path}", params=svc, headers={**hdr, "Accept-Language": "de-DE"}, timeout=30)
    if r.ok:
        c = db.conn()
        for t in r.json().get("trophies", []):
            c.execute(
                """INSERT INTO achievements(game_id, api_name, name, description, icon, icon_gray, trophy_type, hidden, sort)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(game_id, api_name) DO UPDATE SET name=excluded.name, description=excluded.description,
                     icon=excluded.icon, icon_gray=excluded.icon_gray, trophy_type=excluded.trophy_type,
                     hidden=excluded.hidden""",
                (g["id"], str(t.get("trophyId")), t.get("trophyName", ""), t.get("trophyDetail", ""),
                 t.get("trophyIconUrl", ""), t.get("trophyIconUrl", ""), t.get("trophyType", ""),
                 1 if t.get("trophyHidden") else 0, int(t.get("trophyId") or 0)),
            )
    r = requests.get(f"{PSN_API}/users/me/{path}", params=svc, headers=hdr, timeout=30)
    if r.ok:
        store_psn_earned(g["id"], r.json().get("trophies", []))
    _set_meta(g["id"], details_ts=db.now())


# --------------------------------------------------------- Abrufen -------

def ensure_details(g, force=False):
    """Namen, Icons und Seltenheit beim ersten Öffnen nachladen."""
    if g["platform"] not in ("steam", "playstation") or g["manual"]:
        return
    m = _meta(g["id"])
    try:
        if g["platform"] == "steam":
            if force or not m["details_ts"]:
                _steam_details(g)
            if force or _out_of_sync(g):
                _steam_player(g)
            if force or db.now() - m["rarity_ts"] > RARITY_TTL:
                store_rarity(g["id"], steam_rarity(g["ext_id"]))
        elif force or not m["details_ts"] or db.now() - m["rarity_ts"] > RARITY_TTL or _out_of_sync(g):
            _psn_details(g)
    except Exception as e:  # noqa: BLE001 – Details sind nett, aber nicht nötig
        log.warning("Erfolge für %s: %s", g["title"], e)
    db.conn().commit()


def for_game(g):
    rows = [dict(r) for r in db.conn().execute(
        "SELECT * FROM achievements WHERE game_id=? ORDER BY sort, api_name", (g["id"],))]
    for r in rows:
        r["band"] = band(r["rarity"])
        r.pop("game_id", None)
    known = [r["rarity"] for r in rows if r["rarity"] is not None]
    locked = [r for r in rows if not r["unlocked"]]
    unlocked = [r for r in rows if r["unlocked"]]
    rarest = min((r for r in unlocked if r["rarity"] is not None), key=lambda r: r["rarity"], default=None)
    hardest = min((r for r in rows if r["rarity"] is not None), key=lambda r: r["rarity"], default=None)
    times = sorted(r["unlock_time"] for r in unlocked if r["unlock_time"])
    summary = {
        "total": len(rows),
        "unlocked": len(unlocked),
        # Wer 100 % hat, hat auch den seltensten Erfolg → höchstens so viele Spieler
        "max_100_pct": min(known) if known and len(known) == len(rows) else None,
        "hardest": hardest and {"name": hardest["name"], "rarity": hardest["rarity"]},
        "rarest_unlocked": rarest and {"name": rarest["name"], "rarity": rarest["rarity"]},
        "first_unlock": times[0] if times else 0,
        "last_unlock": times[-1] if times else 0,
        "unlock_days": len({datetime.fromtimestamp(t, _tz()).date() for t in times}),
        "easiest_open": [
            {"name": r["name"] or r["api_name"], "rarity": r["rarity"], "icon": r["icon_gray"] or r["icon"],
             "hidden": r["hidden"]}
            for r in sorted((r for r in locked if r["rarity"] is not None), key=lambda r: -r["rarity"])[:5]],
        "bands": _band_counts(rows),
        "types": _type_counts(rows) if g["platform"] == "playstation" else None,
    }
    return {"achievements": rows, "summary": summary}


def _band_counts(rows):
    out = {k: {"key": k, "label": lbl, "total": 0, "unlocked": 0} for k, lbl, _, _ in RARITY_BANDS}
    for r in rows:
        b = band(r["rarity"])
        if b:
            out[b]["total"] += 1
            out[b]["unlocked"] += r["unlocked"]
    return list(out.values())  # Liste, damit die Reihenfolge (selten → häufig) erhalten bleibt


def _type_counts(rows):
    out = {t: {"key": t, "total": 0, "unlocked": 0} for t in ("platinum", "gold", "silver", "bronze")}
    for r in rows:
        if r["trophy_type"] in out:
            out[r["trophy_type"]]["total"] += 1
            out[r["trophy_type"]]["unlocked"] += r["unlocked"]
    return list(out.values())


# ------------------------------------------------------- Statistik -------

def global_stats(year=None):
    tz = _tz()
    c = db.conn()
    q = """SELECT a.unlock_time, a.rarity, a.name, a.api_name, a.icon, g.id AS game_id, g.title, g.platform
           FROM achievements a JOIN games g ON g.id=a.game_id
           WHERE a.unlocked=1 AND a.unlock_time>0 AND g.hidden=0"""
    rows = [dict(r) for r in c.execute(q)]
    years = sorted({datetime.fromtimestamp(r["unlock_time"], tz).year for r in rows}, reverse=True)
    if year:
        rows = [r for r in rows if datetime.fromtimestamp(r["unlock_time"], tz).year == int(year)]

    heat = [[0] * 24 for _ in range(7)]
    per_day, per_month, per_game = {}, {}, {}
    for r in rows:
        d = datetime.fromtimestamp(r["unlock_time"], tz)
        heat[d.weekday()][d.hour] += 1
        per_day[d.date().isoformat()] = per_day.get(d.date().isoformat(), 0) + 1
        mk = f"{d.year}-{d.month:02d}"
        per_month[mk] = per_month.get(mk, 0) + 1
        per_game[r["game_id"]] = per_game.get(r["game_id"], 0) + 1

    # Kalender: die letzten 53 Wochen bzw. das gewählte Jahr
    if year:
        start, end = datetime(int(year), 1, 1).date(), datetime(int(year), 12, 31).date()
    else:
        end = datetime.now(tz).date()
        start = end - timedelta(days=364)
    calendar = []
    d = start
    while d <= end:
        calendar.append([d.isoformat(), per_day.get(d.isoformat(), 0)])
        d += timedelta(days=1)

    best_day = max(per_day.items(), key=lambda kv: kv[1], default=(None, 0))
    wd = [sum(h) for h in heat]
    hrs = [sum(heat[w][h] for w in range(7)) for h in range(24)]
    cell = max(((w, h) for w in range(7) for h in range(24)), key=lambda x: heat[x[0]][x[1]], default=(0, 0))
    known = [r for r in rows if r["rarity"] is not None]
    bands = {k: {"key": k, "label": lbl, "count": 0} for k, lbl, _, _ in RARITY_BANDS}
    for r in known:
        bands[band(r["rarity"])]["count"] += 1
    rarest = sorted(known, key=lambda r: r["rarity"])[:10]
    titles = {r["game_id"]: (r["title"], r["platform"]) for r in rows}
    top_games = sorted(per_game.items(), key=lambda kv: -kv[1])[:8]
    return {
        "years": years,
        "total": len(rows),
        "days_active": len(per_day),
        "best_day": {"date": best_day[0], "count": best_day[1]},
        "best_weekday": wd.index(max(wd)) if rows else None,
        "best_hour": hrs.index(max(hrs)) if rows else None,
        "best_cell": {"weekday": cell[0], "hour": cell[1], "count": heat[cell[0]][cell[1]]},
        "heatmap": heat,
        "calendar": calendar,
        "per_month": sorted(per_month.items())[-24:],
        "rarity_bands": list(bands.values()),
        "rarity_known": len(known),
        "rarest": [{"name": r["name"] or r["api_name"], "rarity": r["rarity"], "icon": r["icon"],
                    "game": r["title"], "game_id": r["game_id"], "time": r["unlock_time"]} for r in rarest],
        "top_games": [{"game_id": gid, "title": titles[gid][0], "platform": titles[gid][1], "count": n}
                      for gid, n in top_games],
    }
