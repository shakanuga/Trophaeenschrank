"""Trophäenschrank – Web-App (Flask)."""
import json
import logging
import os
import threading
import uuid
from datetime import datetime

from urllib.parse import quote, urlsplit

from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from . import covers, db, pocketid, sync

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["POCKETID"] = pocketid.PocketID()
SESSION_COOKIE = "trophaeen_session"
SESSION_MAX_AGE = 180 * 86400
OPEN_PATHS = {"/healthz", "/manifest.webmanifest", "/static/icon.svg",
              "/auth/pocketid", "/auth/pocketid/zurueck", "/auth/abmelden"}

PLATFORMS = ["steam", "playstation", "xbox", "nintendo", "other"]
STATUSES = ["none", "playing", "finished", "completed", "backlog", "shelved"]
SECRET_KEYS = ["steam_api_key", "psn_npsso", "xbl_api_key", "sgdb_api_key"]
PLAIN_KEYS = ["steam_id", "language", "sync_interval_hours", "cover_style",
              "custom_templates", "case_color", "case_marks", "case_ps_platinum"]

db.init()
_started = False


def start_background():
    global _started
    if not _started and os.environ.get("DISABLE_SCHEDULER") != "1":
        _started = True
        threading.Thread(target=sync.scheduler, daemon=True).start()


start_background()


def game_or_404(gid):
    row = db.conn().execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
    if not row:
        abort(404)
    return dict(row)


def public_game(r):
    d = dict(r)
    d.pop("ach_checked_lp", None)
    d["tags"] = [t for t in (d.get("tags") or "").split(",") if t]
    return d


# --------------------------------------------- Anmeldung über Pocket ID --
# Nur aktiv, wenn OIDC_ISSUER, OIDC_CLIENT_ID und OIDC_CLIENT_SECRET gesetzt sind.

def _oidc():
    return app.config["POCKETID"]


def _key():
    return pocketid.secret_key(db.DATA_DIR)


def _auth_page(msg, status=403):
    html = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>Trophäenschrank</title><body style='font-family:system-ui;max-width:420px;margin:12vh auto;"
            f"padding:0 16px'><h1>Trophäenschrank</h1><p>{msg.replace('<', '&lt;')}</p>"
            f"<p><a href='/auth/pocketid'>{_oidc().label}</a></p></body>")
    return Response(html, status, mimetype="text/html")


@app.before_request
def require_login():
    oidc = _oidc()
    if not oidc.enabled or request.path in OPEN_PATHS:
        return None
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error="Anfrage von fremder Seite"), 403
    if pocketid.unsign(request.cookies.get(SESSION_COOKIE), _key(), max_age=SESSION_MAX_AGE):
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="Bitte anmelden", login="/auth/pocketid"), 401
    return redirect("/auth/pocketid?next=" + quote(request.full_path.rstrip("?"), safe="/?=&"))


@app.get("/auth/pocketid")
def oidc_start():
    try:
        url, pending = _oidc().begin(request.host_url.rstrip("/") + "/auth/pocketid/zurueck",
                                     request.args.get("next", "/"))
    except pocketid.OIDCError as e:
        return _auth_page(str(e))
    res = redirect(url)
    res.set_cookie(pocketid.PENDING_COOKIE, pocketid.sign(pending, _key()), max_age=pocketid.PENDING_MAX_AGE,
                   httponly=True, samesite="Lax", secure=request.is_secure)
    return res


@app.get("/auth/pocketid/zurueck")
def oidc_callback():
    pending = pocketid.unsign(request.cookies.get(pocketid.PENDING_COOKIE), _key())
    try:
        info = _oidc().complete(request.args, pending)
    except pocketid.OIDCError as e:
        return _auth_page(str(e))
    res = redirect(pending["next"])
    res.set_cookie(SESSION_COOKIE, pocketid.sign({"sub": info["sub"], "name": info["name"] or info["username"],
                                                  "t": int(datetime.now().timestamp())}, _key()),
                   max_age=SESSION_MAX_AGE, httponly=True, samesite="Lax", secure=request.is_secure)
    res.delete_cookie(pocketid.PENDING_COOKIE)
    return res


@app.get("/auth/abmelden")
def oidc_logout():
    res = _auth_page("Du bist abgemeldet.", 200)
    res.delete_cookie(SESSION_COOKIE)
    return res


# ------------------------------------------------------------------ Seiten --

@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(STATIC, "manifest.webmanifest")


# ---------------------------------------------------------------- Spiele ---

@app.get("/api/games")
def list_games():
    rows = db.conn().execute("SELECT * FROM games ORDER BY last_played DESC").fetchall()
    return jsonify([public_game(r) for r in rows])


def _clean_tags(v):
    if isinstance(v, list):
        v = ",".join(v)
    return ",".join(sorted({t.strip() for t in (v or "").split(",") if t.strip()}, key=str.lower))


def _date_to_ts(v):
    if v in (None, "", 0):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    return int(datetime.fromisoformat(v).timestamp())


@app.post("/api/games")
def add_game():
    d = request.get_json(force=True)
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify(error="Titel fehlt"), 400
    platform = d.get("platform") if d.get("platform") in PLATFORMS else "other"
    status = d.get("status") if d.get("status") in STATUSES else "completed"
    ts = db.now()
    completed_at = _date_to_ts(d.get("completed_at")) or (ts if status == "completed" else 0)
    c = db.conn()
    cur = c.execute(
        """INSERT INTO games(platform, ext_id, title, sub_platform, status, status_locked,
           unlocked, total, platinum, completed_at, completed_locked, cover_override, tags, notes,
           manual, last_played, created_at, updated_at)
           VALUES(?,?,?,?,?,1,?,?,?,?,1,?,?,?,1,?,?,?)""",
        (platform, "manual-" + uuid.uuid4().hex[:12], title, d.get("sub_platform", ""), status,
         int(d.get("unlocked") or 0), int(d.get("total") or 0), 1 if d.get("platinum") else 0,
         completed_at, d.get("cover_override", ""), _clean_tags(d.get("tags")),
         d.get("notes", ""), completed_at or ts, ts, ts),
    )
    c.commit()
    return jsonify(public_game(game_or_404(cur.lastrowid))), 201


@app.patch("/api/games/<int:gid>")
def edit_game(gid):
    g = game_or_404(gid)
    d = request.get_json(force=True)
    upd = {}
    if "status" in d and d["status"] in STATUSES:
        upd["status"] = d["status"]
        # „automatisch“ = Sperre aufheben, nächster Sync bestimmt den Status
        upd["status_locked"] = 0 if (d.get("status_auto") and not g["manual"]) else 1
    elif "status_auto" in d and not g["manual"]:
        upd["status_locked"] = 0 if d["status_auto"] else 1
    if "completed_at" in d:
        upd["completed_at"] = _date_to_ts(d["completed_at"])
        upd["completed_locked"] = 1 if upd["completed_at"] else 0
    for k in ("title", "notes", "cover_override", "sub_platform"):
        if k in d and (k != "title" or g["manual"]):
            upd[k] = d[k] or ""
    if "tags" in d:
        upd["tags"] = _clean_tags(d["tags"])
    if "hidden" in d:
        upd["hidden"] = 1 if d["hidden"] else 0
    if g["manual"]:
        for k in ("unlocked", "total"):
            if k in d:
                upd[k] = int(d[k] or 0)
        if "platinum" in d:
            upd["platinum"] = 1 if d["platinum"] else 0
        if "platform" in d and d["platform"] in PLATFORMS:
            upd["platform"] = d["platform"]
    if upd:
        upd["updated_at"] = db.now()
        c = db.conn()
        c.execute(f"UPDATE games SET {', '.join(k + '=?' for k in upd)} WHERE id=?",
                  list(upd.values()) + [gid])
        c.commit()
        if "cover_override" in upd:
            covers.clear_cache(gid)
    return jsonify(public_game(game_or_404(gid)))


@app.delete("/api/games/<int:gid>")
def delete_game(gid):
    g = game_or_404(gid)
    c = db.conn()
    if g["manual"]:
        c.execute("DELETE FROM games WHERE id=?", (gid,))
    else:
        c.execute("UPDATE games SET hidden=1 WHERE id=?", (gid,))  # käme beim Sync sonst zurück
    c.commit()
    return jsonify(ok=True)


# ----------------------------------------------------------------- Cover ---

@app.get("/cover/<int:gid>")
def cover(gid):
    g = game_or_404(gid)
    style = request.args.get("style") or db.get_setting("cover_style", "official")
    f = covers.resolve(g, style)
    if f:
        resp = send_from_directory(covers.COVER_DIR, f, max_age=7 * 86400)
        return resp
    return Response(covers.placeholder_svg(g), mimetype="image/svg+xml",
                    headers={"Cache-Control": "max-age=3600"})


@app.get("/api/games/<int:gid>/cover-options")
def cover_options(gid):
    return jsonify(covers.options(game_or_404(gid)))


@app.post("/api/covers/clear")
def covers_clear():
    covers.clear_cache()
    return jsonify(ok=True)


@app.post("/api/covers/refresh-cases")
def covers_refresh_cases():
    from . import casecover
    try:
        casecover.refresh_assets()
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Hüllen konnten nicht geladen werden: {e}"), 502
    covers.clear_cache()
    return jsonify(ok=True)


@app.get("/api/styles")
def styles():
    return jsonify(covers.available_styles())


# ------------------------------------------------------------ Statistik ---

@app.get("/api/stats")
def stats():
    c = db.conn()
    rows = c.execute("SELECT platform, status, completed_at, platinum FROM games WHERE hidden=0").fetchall()
    by_year, by_platform = {}, {}
    for r in rows:
        if r["status"] == "completed":
            by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
            if r["completed_at"]:
                y = datetime.fromtimestamp(r["completed_at"]).year
                by_year[y] = by_year.get(y, 0) + 1
    return jsonify(
        total=len(rows),
        completed=sum(by_platform.values()),
        platinum=sum(1 for r in rows if r["platinum"]),
        by_year=dict(sorted(by_year.items())),
        by_platform=by_platform,
    )


# ------------------------------------------------------- Einstellungen ----

@app.get("/api/settings")
def get_settings():
    s = db.all_settings()
    out = {k: s.get(k, "") for k in PLAIN_KEYS}
    out.setdefault("sync_interval_hours", "6")
    out["sync_interval_hours"] = out["sync_interval_hours"] or "6"
    out["language"] = out["language"] or "german"
    out["cover_style"] = out["cover_style"] or "official"
    out["case_color"] = out["case_color"] or "blau"
    out["case_marks"] = out["case_marks"] or "full"
    out["case_ps_platinum"] = out["case_ps_platinum"] or "1"
    for k in SECRET_KEYS:
        v = s.get(k, "")
        out[k] = ("•" * 8 + v[-4:]) if v else ""
    out["configured"] = sync.configured_platforms()
    out["last_sync"] = {p: int(s.get(f"last_sync_{p}") or 0) for p in sync.SYNCERS}
    out["last_sync_msg"] = {p: s.get(f"last_sync_msg_{p}", "") for p in sync.SYNCERS}
    return jsonify(out)


@app.post("/api/settings")
def save_settings():
    d = request.get_json(force=True)
    for k in PLAIN_KEYS:
        if k in d:
            db.set_setting(k, d[k])
    for k in SECRET_KEYS:
        v = d.get(k)
        if v is not None and not str(v).startswith("•"):
            db.set_setting(k, str(v).strip())
    if "custom_templates" in d or "sgdb_api_key" in d:
        covers.clear_cache()
    return get_settings()


# ---------------------------------------------------------------- Sync ----

@app.post("/api/sync")
def start_sync():
    d = request.get_json(silent=True) or {}
    plats = d.get("platforms") or sync.configured_platforms()
    plats = [p for p in plats if p in sync.SYNCERS]
    if not plats:
        return jsonify(error="Keine Plattform eingerichtet – bitte in den Einstellungen Zugangsdaten eintragen."), 400
    if not sync.run(plats, full=bool(d.get("full"))):
        return jsonify(error="Es läuft bereits ein Abgleich."), 409
    return jsonify(ok=True, platforms=plats)


@app.get("/api/sync/status")
def sync_status():
    return jsonify(sync.progress.snapshot())


# ------------------------------------------------------- Backup/Import ----

@app.get("/api/export")
def export():
    rows = [dict(r) for r in db.conn().execute("SELECT * FROM games")]
    return Response(json.dumps({"version": 1, "games": rows}, ensure_ascii=False, indent=1),
                    mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=trophaeenschrank-backup.json"})


@app.post("/api/import")
def import_backup():
    data = request.get_json(force=True)
    c = db.conn()
    cols = [r["name"] for r in c.execute("PRAGMA table_info(games)")]
    n = 0
    for g in data.get("games", []):
        g = {k: v for k, v in g.items() if k in cols and k != "id"}
        if not g.get("platform") or not g.get("ext_id"):
            continue
        keys = list(g)
        c.execute(
            f"INSERT INTO games({','.join(keys)}) VALUES({','.join('?' * len(keys))}) "
            f"ON CONFLICT(platform, ext_id) DO UPDATE SET "
            + ", ".join(f"{k}=excluded.{k}" for k in keys if k not in ("platform", "ext_id")),
            [g[k] for k in keys],
        )
        n += 1
    c.commit()
    return jsonify(imported=n)


@app.get("/healthz")
def health():
    return "ok"
