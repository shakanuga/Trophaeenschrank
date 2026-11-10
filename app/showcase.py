"""Übersichtsbild der 100-%-Spiele, z.B. für die Artwork-Vitrine im Steam-Profil."""
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from . import covers, db

log = logging.getLogger("showcase")

# Breite in Pixeln, Spalten
FORMATS = {
    "featured": {"label": "Steam: Featured Artwork Showcase (630 px)", "width": 630, "cols": 5},
    "artwork": {"label": "Steam: Artwork Showcase, Hauptbild (506 px)", "width": 506, "cols": 4},
    "wide": {"label": "Breit (1920 px)", "width": 1920, "cols": 10},
}
MAX_BYTES = 4_900_000  # Steam nimmt Artwork bis ca. 5 MB

BG_TOP, BG_BOTTOM = (24, 34, 62), (10, 14, 26)
GOLD, GOLD_DARK, PLATIN = (217, 178, 94), (150, 112, 40), (197, 214, 236)
TEXT, MUTED = (236, 232, 222), (168, 176, 196)


def _font(size, weight=800):
    try:
        from .casecover import FONT_URL, _asset
        f = ImageFont.truetype(_asset("fonts/NunitoSans.ttf", FONT_URL), size)
        try:
            f.set_variation_by_axes([weight, 100, 12, 500])
        except Exception:  # noqa: BLE001
            pass
        return f
    except Exception:  # noqa: BLE001
        return ImageFont.load_default(size=size)


def select_games(platform="", year="", limit=0):
    q = "SELECT * FROM games WHERE status='completed' AND hidden=0"
    args = []
    if platform:
        q += " AND platform=?"
        args.append(platform)
    rows = [dict(r) for r in db.conn().execute(q + " ORDER BY completed_at DESC, title", args)]
    if year:
        rows = [g for g in rows if g["completed_at"] and datetime.fromtimestamp(g["completed_at"]).year == int(year)]
    return rows[:limit] if limit else rows


def _cover(g, style, w, h):
    f = None
    try:
        f = covers.resolve(g, style)
    except Exception as e:  # noqa: BLE001
        log.debug("Cover %s: %s", g["title"], e)
    if f:
        try:
            with Image.open(os.path.join(covers.COVER_DIR, f)) as im:
                im = im.convert("RGBA")
            s = max(w / im.width, h / im.height)
            im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
            x, y = (im.width - w) // 2, (im.height - h) // 2
            return im.crop((x, y, x + w, y + h))
        except Exception as e:  # noqa: BLE001
            log.debug("Cover %s: %s", g["title"], e)
    # Platzhalter: Titel auf dunklem Grund
    im = Image.new("RGBA", (w, h), (36, 44, 66, 255))
    d = ImageDraw.Draw(im)
    font = _font(max(10, w // 9))
    words, lines, line = g["title"].split(), [], ""
    for word in words:
        test = (line + " " + word).strip()
        if d.textlength(test, font=font) > w - 12 and line:
            lines.append(line)
            line = word
        else:
            line = test
    lines.append(line)
    lh = font.size + 3
    y = (h - lh * len(lines[:5])) // 2
    for ln in lines[:5]:
        d.text(((w - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill=TEXT)
        y += lh
    return im


def _gradient(w, h):
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(round(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3)))
    return col.resize((w, h)).convert("RGBA")


def _fit(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw:
        return text
    while text and d.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text.rstrip() + "…"


def render(fmt="featured", platform="", year="", limit=20, style="official", title="", show_dates=True,
           show_stats=True, scale=1):
    spec = FORMATS.get(fmt, FORMATS["featured"])
    games = select_games(platform, year, limit)
    all_done = select_games(platform, year, 0)
    W = spec["width"] * scale
    cols = spec["cols"]
    pad = round(W * 0.035)
    gap = round(W * 0.022)
    cw = (W - 2 * pad - (cols - 1) * gap) // cols
    ch = round(cw * 1.5)
    date_h = round(cw * 0.2) if show_dates else 0
    rows = max(1, -(-len(games) // cols))

    title = title or "Trophäenschrank"
    sub = f"{len(all_done)} Spiele auf 100 %" + (f" · {year}" if year else "")
    tf = _font(round(W * 0.055), 900)
    sf = _font(round(W * 0.028), 600)
    cf = _font(round(W * 0.024), 700)
    u = W / 630  # Grundeinheit, damit alle Formate gleich aussehen
    y_title = round(18 * u)
    y_sub = y_title + tf.getbbox("Ag")[3] + round(4 * u)
    y_chips = y_sub + sf.getbbox("Ag")[3] + round(10 * u)
    chip_h = cf.getbbox("Ag")[3] + round(10 * u)
    head_h = (y_chips + chip_h if show_stats else y_sub + sf.getbbox("Ag")[3]) + round(14 * u)

    H = head_h + pad + rows * (ch + date_h) + (rows - 1) * gap + pad
    img = _gradient(W, H)
    d = ImageDraw.Draw(img)

    # Kopf
    d.text((pad, y_title), _fit(d, title, tf, W - 2 * pad), font=tf, fill=TEXT)
    d.text((pad, y_sub), sub, font=sf, fill=MUTED)
    if show_stats:
        plat = sum(1 for g in all_done if g["platinum"])
        ach = sum(g["total"] or 0 for g in all_done)
        hours = round(sum(g["playtime_min"] or 0 for g in all_done) / 60)
        chips = [f"{len(all_done)}× 100 %"] + ([f"{plat}× Platin"] if plat else []) + \
                ([f"{ach:,} Erfolge".replace(",", ".")] if ach else []) + ([f"{hours:,} Std.".replace(",", ".")] if hours else [])
        x = pad
        for c in chips:
            tw = d.textlength(c, font=cf)
            box = [x, y_chips, x + tw + round(16 * u), y_chips + chip_h]
            if box[2] > W - pad:
                break
            d.rounded_rectangle(box, radius=round(6 * u), fill=(0, 0, 0, 90), outline=(90, 80, 50), width=max(1, scale))
            d.text((x + round(8 * u), y_chips + round(4 * u)), c, font=cf, fill=(232, 220, 192))
            x = box[2] + round(7 * u)
    d.line([(0, head_h), (W, head_h)], fill=GOLD, width=max(2, round(W * 0.004)))

    # Cover parallel laden (meist aus dem Cache)
    with ThreadPoolExecutor(max_workers=8) as ex:
        tiles = list(ex.map(lambda g: _cover(g, style, cw, ch), games))
    df = _font(max(9, round(cw * 0.105)), 700)
    for i, (g, tile) in enumerate(zip(games, tiles)):
        r, c = divmod(i, cols)
        x = pad + c * (cw + gap)
        y = head_h + pad + r * (ch + date_h + gap)
        border = PLATIN if g["platinum"] else GOLD
        bw = max(2, round(cw * 0.022))
        if not style.startswith("case"):  # die Spielhülle hat schon einen eigenen Rahmen
            d.rounded_rectangle([x - bw, y - bw, x + cw + bw - 1, y + ch + bw - 1], radius=round(cw * 0.04), fill=border)
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=round(cw * 0.03), fill=255)
        img.paste(tile, (x, y), mask)
        if show_dates and g["completed_at"]:
            txt = datetime.fromtimestamp(g["completed_at"]).strftime("%d.%m.%Y")
            d.text((x + (cw - d.textlength(txt, font=df)) / 2, y + ch + bw + round(date_h * 0.12)), txt, font=df, fill=MUTED)

    if not games:
        ef = _font(round(W * 0.03), 600)
        msg = "Noch keine Spiele auf 100 %"
        d.text(((W - d.textlength(msg, font=ef)) / 2, head_h + pad), msg, font=ef, fill=MUTED)

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    data = out.getvalue()
    if len(data) > MAX_BYTES:  # zu groß für Steam → auf 256 Farben reduzieren
        out = io.BytesIO()
        img.convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT).save(out, "PNG", optimize=True)
        data = out.getvalue()
    return data, (W, H), len(games), len(all_done)
