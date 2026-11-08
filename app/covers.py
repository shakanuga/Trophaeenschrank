"""Cover-Quellen: Steam (offiziell), SteamGridDB-Stile, eigene URL-Vorlagen (z.B. GitHub-Repos)."""
import hashlib
import html
import logging
import os
import re
import threading
import urllib.parse

import requests

from . import db

log = logging.getLogger("covers")
UA = {"User-Agent": "Trophaeenschrank/1.0 (self-hosted)"}
COVER_DIR = os.path.join(db.DATA_DIR, "covers")
SGDB = "https://www.steamgriddb.com/api/v2"
NEG_TTL = 7 * 86400
SGDB_STYLES = ["alternate", "material", "white_logo", "no_logo", "blurred"]
STYLE_LABELS = {
    "alternate": "Alternate", "material": "Material", "white_logo": "White Logo",
    "no_logo": "Ohne Logo", "blurred": "Blurred",
}
_fetch_locks = {}
_fetch_locks_guard = threading.Lock()


# ------------------------------------------------------------- Stile ------

def custom_templates():
    """Eigene Vorlagen aus den Einstellungen: je Zeile „Name | URL“."""
    out = []
    for line in (db.get_setting("custom_templates") or "").splitlines():
        if "|" in line:
            name, url = line.split("|", 1)
            if url.strip():
                out.append((name.strip() or f"Eigene {len(out) + 1}", url.strip()))
        elif line.strip().startswith("http"):
            out.append((f"Eigene {len(out) + 1}", line.strip()))
    return out


def available_styles():
    styles = [{"id": "official", "label": "Offiziell"}, {"id": "case", "label": "Spielhülle"}]
    if db.get_setting("sgdb_api_key"):
        styles.append({"id": "case:sgdb", "label": "Spielhülle – SteamGridDB-Bild"})
        styles.append({"id": "sgdb", "label": "SteamGridDB – Top"})
        styles += [{"id": f"sgdb:{s}", "label": f"SteamGridDB – {STYLE_LABELS[s]}"} for s in SGDB_STYLES]
    for i, (name, _) in enumerate(custom_templates()):
        styles.append({"id": f"custom:{i}", "label": name})
    return styles


def slugify(s):
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def fill_template(tpl, g):
    clean = re.sub(r"[®™©]", "", g["title"]).strip()
    rep = {
        "{appid}": g["ext_id"], "{id}": g["ext_id"], "{platform}": g["platform"],
        "{title}": urllib.parse.quote(clean), "{title_raw}": clean,
        "{slug}": slugify(clean), "{title_underscore}": urllib.parse.quote(clean.replace(" ", "_")),
    }
    for k, v in rep.items():
        tpl = tpl.replace(k, str(v))
    return tpl


def steam_urls(appid):
    return [
        f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
    ]


# --------------------------------------------------------- SteamGridDB ----

def _sgdb(path, params=None):
    key = db.get_setting("sgdb_api_key")
    if not key:
        return None
    r = requests.get(f"{SGDB}{path}", params=params or {},
                     headers={**UA, "Authorization": f"Bearer {key}"}, timeout=20)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    d = r.json()
    return d.get("data") if d.get("success") else []


def sgdb_game_id(g):
    c = db.conn()
    row = c.execute("SELECT sgdb_id FROM sgdb_ids WHERE game_id=?", (g["id"],)).fetchone()
    if row:
        return row["sgdb_id"]
    sid = None
    if g["platform"] == "steam":
        d = _sgdb(f"/games/steam/{g['ext_id']}")
        sid = d.get("id") if isinstance(d, dict) else None
    if sid is None:
        term = re.sub(r"[®™©:]", " ", g["title"]).strip()
        res = _sgdb(f"/search/autocomplete/{urllib.parse.quote(term)}") or []
        sid = res[0]["id"] if res else None
    if sid is not None:
        c.execute("INSERT OR REPLACE INTO sgdb_ids(game_id, sgdb_id) VALUES(?,?)", (g["id"], sid))
        c.commit()
    return sid


def sgdb_grids(g, style=None):
    params = {"dimensions": "600x900,342x482,660x930", "types": "static", "nsfw": "false"}
    if style:
        params["styles"] = style
    sid = sgdb_game_id(g)
    if sid is None:
        return []
    return _sgdb(f"/grids/game/{sid}", params) or []


# --------------------------------------------------------- Auflösung -----

def candidate_urls(g, style):
    """Liefert eine Liste von (quelle, url-oder-callable) in Prioritätsreihenfolge."""
    out = []
    if g["cover_override"]:
        out.append(("override", g["cover_override"]))
    if style.startswith("custom:"):
        tpls = custom_templates()
        idx = int(style.split(":")[1]) if style.split(":")[1].isdigit() else -1
        if 0 <= idx < len(tpls):
            out.append((style, fill_template(tpls[idx][1], g)))
    elif style.startswith("sgdb"):
        st = style.split(":")[1] if ":" in style else None
        out.append((style, lambda st=st: (sgdb_grids(g, st) or [{}])[0].get("url")))
    # Fallbacks
    if g["platform"] == "steam":
        out += [("official", u) for u in steam_urls(g["ext_id"])]
    else:
        out.append(("sgdb", lambda: (sgdb_grids(g) or [{}])[0].get("url")))
        if g["cover_src"]:
            out.append(("platform", g["cover_src"]))
    return out


def _lock_for(key):
    with _fetch_locks_guard:
        return _fetch_locks.setdefault(key, threading.Lock())


def _download(url):
    r = requests.get(url, headers=UA, timeout=20)
    ct = r.headers.get("content-type", "")
    if not r.ok or not ct.startswith("image/") or len(r.content) < 500:
        return None
    ext = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(ct.split(";")[0], "jpg")
    os.makedirs(COVER_DIR, exist_ok=True)
    name = hashlib.sha1(url.encode()).hexdigest() + "." + ext
    with open(os.path.join(COVER_DIR, name), "wb") as fh:
        fh.write(r.content)
    return name


def resolve(g, style):
    """Gibt den Dateinamen des gecachten Covers zurück oder None (→ Platzhalter)."""
    if style.startswith("case"):
        return resolve_case(g, style)
    c = db.conn()
    cache_key = f"{style}|{hashlib.sha1((g['cover_override'] or '').encode()).hexdigest()[:8]}"
    with _lock_for((g["id"], cache_key)):
        row = c.execute("SELECT file, ts FROM cover_cache WHERE game_id=? AND source=?",
                        (g["id"], cache_key)).fetchone()
        if row:
            if row["file"] and os.path.exists(os.path.join(COVER_DIR, row["file"])):
                return row["file"]
            if not row["file"] and db.now() - row["ts"] < NEG_TTL:
                return None
        found, used_url = None, ""
        for _, cand in candidate_urls(g, style):
            try:
                url = cand() if callable(cand) else cand
                if not url:
                    continue
                found = _download(url)
                if found:
                    used_url = url
                    break
            except requests.RequestException as e:
                log.debug("Cover %s: %s", g["title"], e)
        c.execute("INSERT OR REPLACE INTO cover_cache(game_id, source, url, file, ts) VALUES(?,?,?,?,?)",
                  (g["id"], cache_key, used_url, found or "", db.now()))
        c.commit()
        return found


def resolve_case(g, style):
    """Spielhüllen-Cover: Grundbild holen (offiziell oder SteamGridDB) und in die Hülle setzen."""
    from . import casecover  # Pillow nur laden, wenn der Stil benutzt wird
    color = db.get_setting("case_color", "blau") or "blau"
    marks = db.get_setting("case_marks", "full") or "full"
    ps_plat = db.get_setting("case_ps_platinum", "1") != "0"
    done = (1 if g["status"] == "completed" else 0) + (2 if ps_plat and g["platinum"] else 0)
    ovh = hashlib.sha1((g["cover_override"] or "").encode()).hexdigest()[:8]
    key = f"{style}|{color}|{marks}|{done}|{casecover.case_for(g)}|{ovh}"
    c = db.conn()
    with _lock_for((g["id"], key)):
        row = c.execute("SELECT file FROM cover_cache WHERE game_id=? AND source=?", (g["id"], key)).fetchone()
        if row and row["file"] and os.path.exists(os.path.join(COVER_DIR, row["file"])):
            return row["file"]
        base = resolve(g, "sgdb" if style == "case:sgdb" else "official")
        if not base:
            return None
        try:
            with open(os.path.join(COVER_DIR, base), "rb") as fh:
                png = casecover.compose(fh.read(), g, color, marks, ps_plat)
        except Exception as e:  # noqa: BLE001 – z.B. GitHub nicht erreichbar: dann normales Cover
            log.warning("Spielhülle für %s: %s", g["title"], e)
            return base
        name = hashlib.sha1(key.encode() + str(g["id"]).encode()).hexdigest() + ".png"
        with open(os.path.join(COVER_DIR, name), "wb") as fh:
            fh.write(png)
        c.execute("INSERT OR REPLACE INTO cover_cache(game_id, source, url, file, ts) VALUES(?,?,?,?,?)",
                  (g["id"], key, "case", name, db.now()))
        c.commit()
        return name


def clear_cache(game_id=None):
    c = db.conn()
    if game_id is None:
        c.execute("DELETE FROM cover_cache")
    else:
        c.execute("DELETE FROM cover_cache WHERE game_id=?", (game_id,))
    c.commit()


def options(g):
    """Alle wählbaren Cover für den Auswahl-Dialog."""
    out = []
    if g["platform"] == "steam":
        out.append({"url": steam_urls(g["ext_id"])[0], "thumb": steam_urls(g["ext_id"])[0],
                    "label": "Steam offiziell"})
    elif g["cover_src"]:
        out.append({"url": g["cover_src"], "thumb": g["cover_src"], "label": "Plattform"})
    for name, tpl in custom_templates():
        u = fill_template(tpl, g)
        out.append({"url": u, "thumb": u, "label": name})
    try:
        for grid in sgdb_grids(g)[:60]:
            out.append({"url": grid["url"], "thumb": grid.get("thumb") or grid["url"],
                        "label": f"SGDB · {STYLE_LABELS.get(grid.get('style'), grid.get('style', ''))}"})
    except requests.RequestException as e:
        log.warning("SGDB: %s", e)
    return out


PLATFORM_COLORS = {
    "steam": ("#1b2838", "#2a475e"), "playstation": ("#00246b", "#0070d1"),
    "xbox": ("#0e3b0e", "#107c10"), "nintendo": ("#5a0a0a", "#e60012"),
    "other": ("#2b2b36", "#4a4a5a"),
}


def placeholder_svg(g):
    a, b = PLATFORM_COLORS.get(g["platform"], PLATFORM_COLORS["other"])
    words, lines, line = g["title"].split(), [], ""
    for w in words:
        if len(line) + len(w) > 14 and line:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    lines.append(line)
    lines = lines[:6]
    y0 = 450 - (len(lines) - 1) * 32
    text = "".join(
        f'<text x="300" y="{y0 + i * 64}" text-anchor="middle">{html.escape(t)}</text>'
        for i, t in enumerate(lines)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 900">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
<rect width="600" height="900" fill="url(#g)"/>
<g fill="#fff" font-family="Segoe UI, Roboto, sans-serif" font-size="52" font-weight="700">{text}</g>
</svg>"""
