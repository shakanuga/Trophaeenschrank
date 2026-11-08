# SPDX-License-Identifier: GPL-3.0-or-later
# Hüllen-Logik angelehnt an steam-case-covers, Copyright (C) 2026 Diego Bergonsi
# https://github.com/diegobergonsi/steam-case-covers (GPL-3.0-or-later)
"""Cover im Stil einer Spielhülle (Steam-, PlayStation-, Xbox- oder Switch-Case).

Die Hüllen-Grafiken stammen aus https://github.com/diegobergonsi/steam-case-covers (GPL-3.0).
Sie werden NICHT mit dieser App ausgeliefert, sondern beim ersten Gebrauch von GitHub geladen
und unter /data/case-assets abgelegt. Erzeugte Cover enthalten Artwork der Spiele-Publisher:
nur für den privaten Gebrauch.
"""
import io
import json
import logging
import os
import threading

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import db

log = logging.getLogger("casecover")
UA = {"User-Agent": "Trophaeenschrank/1.0 (self-hosted)"}
ASSET_BASE = os.environ.get(
    "CASE_ASSETS_URL", "https://raw.githubusercontent.com/diegobergonsi/steam-case-covers/main/assets/")
ASSET_DIR = os.path.join(db.DATA_DIR, "case-assets")
ASSET_FILES = ["fonts/NunitoSans.ttf", "frame.png", "completion_overlay.png", "cases/cases.json"] + [
    f"cases/{p}.png" for p in ("ps3", "ps4", "ps5", "xbox360", "xboxone", "xboxseries", "switch", "switch2")]

SIZE = (600, 900)
STEAM_WINDOW = (14, 96, 586, 872)   # Bildfenster in frame.png
GAP = 14                            # Abstand der Rosette vom Rand des Bildfensters
RIBBON_W, RIBBON_GAP = 482, 28
ROSETTE_ROWS = 450                  # im Overlay: darüber Rosette, darunter Band
BORDER = 14

COLORS = {  # Name: (Farbton-Drehung in Grad, Sättigung %, Helligkeit %)
    "blau": (0, 100, 100), "violett": (42, 100, 100), "magenta": (84, 100, 100), "rot": (134, 100, 100),
    "gold": (176, 100, 100), "gruen": (276, 100, 100),
    "schwarz": (0, 0, 14), "grafit": (0, 0, 34), "silber": (0, 0, 78),
}
COLOR_LABELS = {"blau": "Blau", "violett": "Violett", "magenta": "Magenta", "rot": "Rot", "gold": "Gold",
                "gruen": "Grün", "schwarz": "Schwarz", "grafit": "Grafit", "silber": "Silber"}
MARKS = {"full": "Rosette + Band", "rosette": "Nur Rosette", "gold": "Goldrahmen + Rosette", "none": "Keine"}

FONT_URL = ASSET_BASE.rsplit("assets/", 1)[0] + "tools/src/fonts/NunitoSans.ttf"   # SIL OFL 1.1
PLATINUM = ((0xf4, 0xf8, 0xfd), (0x9c, 0xb2, 0xcc))   # hell → dunkel
NAVY = (0x1c, 0x2c, 0x4a)

_lock = threading.Lock()
_cache = {}


# ------------------------------------------------------------- Assets ----

def _asset(name, url=None):
    path = os.path.join(ASSET_DIR, name)
    if not os.path.exists(path):
        with _lock:
            if not os.path.exists(path):
                r = requests.get(url or ASSET_BASE + name, headers=UA, timeout=30)
                r.raise_for_status()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".tmp", "wb") as fh:
                    fh.write(r.content)
                os.replace(path + ".tmp", path)
    return path


def _image(name):
    if name not in _cache:
        with Image.open(_asset(name)) as im:
            _cache[name] = im.convert("RGBA")
    return _cache[name]


def _windows():
    if "cases.json" not in _cache:
        with open(_asset("cases/cases.json"), encoding="utf-8") as fh:
            _cache["cases.json"] = json.load(fh)
    return _cache["cases.json"]


def refresh_assets():
    """Hüllen neu von GitHub laden (z.B. nach einem Update des Repos)."""
    _cache.clear()
    for f in ASSET_FILES:
        p = os.path.join(ASSET_DIR, f)
        if os.path.exists(p):
            os.remove(p)
    for f in ASSET_FILES:
        _asset(f, FONT_URL if f.startswith("fonts/") else None)


# --------------------------------------------------------- Hülle wählen --

def case_for(g):
    """Welche Hülle zum Spiel passt: Steam-Case oder Konsolen-Case nach Plattform."""
    sub = (g.get("sub_platform") or "").lower().replace(" ", "")
    title = g.get("title", "").lower()
    if g["platform"] == "playstation":
        for p in ("ps3", "ps4", "ps5"):
            if p in sub:
                return p
        return "ps5"
    if g["platform"] == "xbox":
        if "360" in sub:
            return "xbox360"
        if "xboxone" in sub and "series" not in sub:
            return "xboxone"
        return "xboxseries"
    if g["platform"] == "nintendo":
        return "switch2" if ("switch2" in sub or "switch 2" in title) else "switch"
    return "steam"


def _recolor(frame, hue, sat, val):
    if not hue and sat == 100 and val == 100:
        return frame
    r, g, b, a = frame.split()
    h, s, v = Image.merge("RGB", (r, g, b)).convert("HSV").split()
    shift = round((hue % 360) * 256 / 360) % 256
    if shift:
        h = h.point(lambda x: (x + shift) % 256)
    # Weiße Teile (Logo, Schrift) bleiben weiß: nur farbige Pixel werden abgedunkelt
    s2 = s.point([round(x * sat / 100) for x in range(256)])
    weight = [min(1.0, x / 255 / 0.02) for x in range(256)]
    v = ImageChops.multiply(v, s.point([round(255 * (1 - w * (1 - val / 100))) for w in weight]))
    return Image.merge("RGBA", (*Image.merge("HSV", (h, s2, v)).convert("RGB").split(), a))


def _frame(case, color):
    key = ("frame", case, color)
    if key not in _cache:
        if case == "steam":
            _cache[key] = _recolor(_image("frame.png"), *COLORS.get(color, COLORS["blau"]))
        else:
            _cache[key] = _image(f"cases/{case}.png")
    return _cache[key]


def _window(case):
    if case == "steam":
        return STEAM_WINDOW, None
    info = _windows()[case]
    return tuple(info["window"]), info.get("overlay")


# ------------------------------------------------------------ Zeichnen --

def _fit(art, window):
    x0, y0, x1, y1 = window
    ww, wh = x1 - x0, y1 - y0
    s = max(ww / art.width, wh / art.height)
    w, h = max(ww, round(art.width * s)), max(wh, round(art.height * s))
    if h > wh:  # 2:3-Bilder sind etwas höher als das Fenster: halb stauchen, halb abschneiden
        h = (h + wh) // 2
    art = art.resize((w, h), Image.LANCZOS)
    cx, cy = (w - ww) // 2, (h - wh) // 2
    return art.crop((cx, cy, cx + ww, cy + wh))


def _marks(cover, window, tab, kind):
    over = _image("completion_overlay.png")
    out = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    rosette = over.crop((0, 0, SIZE[0], ROSETTE_ROWS))
    rb = rosette.getchannel("A").getbbox()
    rosette = rosette.crop(rb)
    top = max(window[1], tab[3] if tab else window[1]) + GAP
    out.alpha_composite(rosette, (window[0] + GAP, top))
    if kind == "full":
        below = over.crop((0, ROSETTE_ROWS, SIZE[0], SIZE[1]))
        bb = below.getchannel("A").getbbox()
        if bb:
            tape = below.crop(bb)
            tape = tape.resize((RIBBON_W, round(tape.height * RIBBON_W / tape.width)), Image.LANCZOS)
            cx = (window[0] + window[2]) // 2
            out.alpha_composite(tape, (cx - RIBBON_W // 2, window[3] - RIBBON_GAP - tape.height))
    out.putalpha(ImageChops.multiply(out.getchannel("A"), cover.getchannel("A")))
    return Image.alpha_composite(cover, out)


def _gold_plate(platinum=False):
    key = "plate-platinum" if platinum else "gold"
    if key not in _cache:
        w, h, k = SIZE[0], SIZE[1], 3
        top, bottom = PLATINUM if platinum else ((0xff, 0xe2, 0x78), (0xc4, 0x88, 0x16))
        col = Image.new("RGB", (1, h))
        for y in range(h):
            t = y / (h - 1)
            col.putpixel((0, y), tuple(round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
        plate = col.resize(SIZE).convert("RGBA")
        mask = Image.new("L", (w * k, h * k), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=(24 + BORDER) * k, fill=255)
        plate.putalpha(mask.resize(SIZE, Image.LANCZOS))
        _cache[key] = plate
    return _cache[key]


# ------------------------------------------------- Platin (PlayStation) --
# Eigene Zeichnung im Stil einer Platin-Trophäe – nicht Sonys Original-Grafik.

def _gradient(size, top, bottom, horizontal=False):
    w, h = size
    n = w if horizontal else h
    line = Image.new("RGB", (n, 1) if horizontal else (1, n))
    for i in range(n):
        t = i / max(1, n - 1)
        line.putpixel((i, 0) if horizontal else (0, i), tuple(round(top[c] * (1 - t) + bottom[c] * t) for c in range(3)))
    return line.resize(size).convert("RGBA")


def _shape(size, draw_fn, fill_img):
    mask = Image.new("L", size, 0)
    draw_fn(ImageDraw.Draw(mask))
    out = fill_img.copy()
    out.putalpha(mask)
    return out


def platinum_medal(d=150):
    """Runde Medaille mit Pokal in Platin-Optik, d × d Pixel."""
    if ("medal", d) in _cache:
        return _cache[("medal", d)]
    k = 4
    S = d * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    plat = _gradient((S, S), *PLATINUM)
    # Schatten, Platinring, dunkle Scheibe
    shadow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(shadow).ellipse([S * .04, S * .07, S * .98, S * 1.0], fill=110)
    img.paste((0, 0, 0, 255), (0, 0), shadow)
    img.alpha_composite(_shape((S, S), lambda dr: dr.ellipse([S * .02, S * .02, S * .96, S * .96], fill=255), plat))
    disc = _gradient((S, S), (0x2a, 0x45, 0x78), (0x0e, 0x18, 0x30))
    img.alpha_composite(_shape((S, S), lambda dr: dr.ellipse([S * .09, S * .09, S * .89, S * .89], fill=255), disc))
    # Strahlen hinter dem Pokal
    rays = Image.new("L", (S, S), 0)
    rd = ImageDraw.Draw(rays)
    import math
    cx, cy = S * .49, S * .44
    for i in range(12):
        a = math.radians(i * 30 + 15)
        b1, b2 = a - .09, a + .09
        rd.polygon([(cx, cy), (cx + math.cos(b1) * S * .4, cy + math.sin(b1) * S * .4),
                    (cx + math.cos(b2) * S * .4, cy + math.sin(b2) * S * .4)], fill=38)
    clip = Image.new("L", (S, S), 0)
    ImageDraw.Draw(clip).ellipse([S * .09, S * .09, S * .89, S * .89], fill=255)
    rays = ImageChops.multiply(rays, clip)
    img.paste((255, 255, 255, 255), (0, 0), rays)

    def cup(dr):
        u = S / 100
        # Henkel
        dr.ellipse([30 * u, 26 * u, 44 * u, 46 * u], outline=255, width=round(3.6 * u))
        dr.ellipse([54 * u, 26 * u, 68 * u, 46 * u], outline=255, width=round(3.6 * u))
        # Schale
        dr.polygon([(34 * u, 24 * u), (64 * u, 24 * u), (62 * u, 40 * u), (56 * u, 51 * u),
                    (42 * u, 51 * u), (36 * u, 40 * u)], fill=255)
        dr.ellipse([36 * u, 40 * u, 62 * u, 56 * u], fill=255)
        dr.rectangle([33 * u, 21 * u, 65 * u, 26 * u], fill=255)
        # Stiel und Sockel
        dr.polygon([(46 * u, 54 * u), (52 * u, 54 * u), (54 * u, 64 * u), (44 * u, 64 * u)], fill=255)
        dr.rounded_rectangle([38 * u, 63 * u, 60 * u, 68 * u], radius=1.5 * u, fill=255)
        dr.rounded_rectangle([34 * u, 67 * u, 64 * u, 74 * u], radius=2 * u, fill=255)

    cupmask = Image.new("L", (S, S), 0)
    cup(ImageDraw.Draw(cupmask))
    # dunkler Umriss: Maske leicht vergrößert
    from PIL import ImageFilter
    outline = cupmask.filter(ImageFilter.MaxFilter(2 * round(S * .012) + 1))
    img.paste(NAVY + (255,), (0, 0), outline)
    shine = _gradient((S, S), (0xff, 0xff, 0xff), (0x8a, 0xa2, 0xc2), horizontal=True)
    img.alpha_composite(_masked(shine, cupmask))
    # Glanzlicht auf der Schale
    hl = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hl).ellipse([S * .39, S * .27, S * .45, S * .42], fill=170)
    img.paste((255, 255, 255, 255), (0, 0), ImageChops.multiply(hl, cupmask))
    # Funkeln
    sd = ImageDraw.Draw(img)
    for (x, y, r) in ((.70, .24, .045), (.27, .62, .03)):
        x, y, r = x * S, y * S, r * S
        sd.polygon([(x, y - r * 2.2), (x + r * .35, y - r * .35), (x + r * 2.2, y), (x + r * .35, y + r * .35),
                    (x, y + r * 2.2), (x - r * .35, y + r * .35), (x - r * 2.2, y), (x - r * .35, y - r * .35)],
                   fill=(255, 255, 255, 235))
    out = img.resize((d, d), Image.LANCZOS)
    _cache[("medal", d)] = out
    return out


def _masked(fill, mask):
    out = fill.copy()
    out.putalpha(mask)
    return out


def _font(size):
    try:
        f = ImageFont.truetype(_asset("fonts/NunitoSans.ttf", FONT_URL), size)
        try:
            f.set_variation_by_axes([900, 100, 12, 500])
        except Exception:  # noqa: BLE001
            pass
        return f
    except Exception:  # noqa: BLE001 – ohne Schrift-Download: eingebaute Schrift
        return ImageFont.load_default(size=size)


def platinum_ribbon(width=RIBBON_W, text="PLATIN"):
    """Band in Platin-Optik mit gefalteten Enden, wie das „100% Complete“-Band."""
    key = ("ribbon", width, text)
    if key in _cache:
        return _cache[key]
    k = 3
    W, H = width * k, round(width * .14) * k
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tail_w, band_h, drop = W * .1, H * .72, H * .28
    dark = _gradient((W, H), (0x7d, 0x93, 0xb2), (0x55, 0x6a, 0x8a))
    tails = Image.new("L", (W, H), 0)
    td = ImageDraw.Draw(tails)
    for side in (0, 1):
        x0, x1 = (0, tail_w * 1.6) if side == 0 else (W - tail_w * 1.6, W)
        notch = x0 + tail_w * .45 if side == 0 else x1 - tail_w * .45
        outer, inner = (x0, x1) if side == 0 else (x1, x0)
        td.polygon([(outer, drop), (inner, drop), (inner, H), (outer, H), (notch, drop + (H - drop) / 2)], fill=255)
    img.alpha_composite(_masked(dark, tails))
    band = Image.new("L", (W, H), 0)
    ImageDraw.Draw(band).rectangle([tail_w, 0, W - tail_w, band_h], fill=255)
    img.alpha_composite(_masked(_gradient((W, H), *PLATINUM), band))
    # Falten-Schatten
    fd = ImageDraw.Draw(img)
    fd.polygon([(tail_w, band_h), (tail_w * 1.6, drop), (tail_w * 1.6, band_h)], fill=(0x3c, 0x4c, 0x66, 255))
    fd.polygon([(W - tail_w, band_h), (W - tail_w * 1.6, drop), (W - tail_w * 1.6, band_h)], fill=(0x3c, 0x4c, 0x66, 255))
    font = _font(round(band_h * .62))
    tb = fd.textbbox((0, 0), text, font=font)
    fd.text(((W - (tb[2] - tb[0])) / 2 - tb[0], (band_h - (tb[3] - tb[1])) / 2 - tb[1]), text, font=font, fill=NAVY + (255,))
    out = img.resize((width, H // k), Image.LANCZOS)
    _cache[key] = out
    return out


def _platinum_marks(cover, window, tab, kind):
    out = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    top = max(window[1], tab[3] if tab else window[1]) + GAP
    out.alpha_composite(platinum_medal(), (window[0] + GAP, top))
    if kind == "full":
        tape = platinum_ribbon()
        cx = (window[0] + window[2]) // 2
        out.alpha_composite(tape, (cx - tape.width // 2, window[3] - RIBBON_GAP - tape.height))
    out.putalpha(ImageChops.multiply(out.getchannel("A"), cover.getchannel("A")))
    return Image.alpha_composite(cover, out)


def compose(art_bytes, g, color="blau", marks="full", ps_platinum=True):
    """PNG-Bytes: das Cover-Bild in der passenden Hülle, bei 100 % mit Auszeichnung."""
    case = case_for(g)
    window, tab = _window(case)
    with Image.open(io.BytesIO(art_bytes)) as im:
        art = im.convert("RGBA")
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    canvas.paste(_fit(art, window), window[:2])
    cover = Image.alpha_composite(canvas, _frame(case, color))
    if g.get("status") == "completed" and marks != "none":
        platin = ps_platinum and g["platform"] == "playstation" and g.get("platinum")
        draw = _platinum_marks if platin else _marks
        cover = draw(cover, window, tab, "rosette" if marks == "gold" else marks)
        if marks == "gold":
            plate = _gold_plate(platinum=bool(platin)).copy()
            plate.alpha_composite(cover.resize((SIZE[0] - 2 * BORDER, SIZE[1] - 2 * BORDER), Image.LANCZOS),
                                  (BORDER, BORDER))
            cover = plate
    buf = io.BytesIO()
    cover.save(buf, "PNG", optimize=True)
    return buf.getvalue()
