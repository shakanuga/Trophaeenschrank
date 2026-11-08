"""Macht aus einem Querformat-Bild (Steam-Header, PSN-Icon) ein 2:3-Hochformat-Cover:
unscharfer, abgedunkelter Hintergrund aus demselben Bild, das Bild selbst groß in der Mitte."""
import io

from PIL import Image, ImageDraw, ImageFilter

SIZE = (600, 900)


def is_portrait(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.height / max(1, im.width) >= 1.3


def portraitize(data):
    with Image.open(io.BytesIO(data)) as im:
        src = im.convert("RGB")
    W, H = SIZE
    # Hintergrund: Bild füllend, stark weichgezeichnet und abgedunkelt
    s = max(W / src.width, H / src.height)
    bg = src.resize((round(src.width * s) + 1, round(src.height * s) + 1), Image.LANCZOS)
    bx, by = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((bx, by, bx + W, by + H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", SIZE, (10, 12, 18)), 0.45).convert("RGBA")
    # Vordergrund: volle Breite (mit Rand), mittig leicht oberhalb
    margin = 24
    fw = W - 2 * margin
    fh = round(src.height * fw / src.width)
    if fh > H - 2 * margin:
        fh = H - 2 * margin
        fw = round(src.width * fh / src.height)
    fg = src.resize((fw, fh), Image.LANCZOS).convert("RGBA")
    x, y = (W - fw) // 2, round((H - fh) * 0.42)
    shadow = Image.new("L", SIZE, 0)
    ImageDraw.Draw(shadow).rounded_rectangle([x - 4, y + 6, x + fw + 4, y + fh + 14], radius=10, fill=170)
    bg.paste((0, 0, 0, 255), (0, 0), shadow.filter(ImageFilter.GaussianBlur(12)))
    mask = Image.new("L", (fw, fh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, fh - 1], radius=8, fill=255)
    bg.paste(fg, (x, y), mask)
    out = io.BytesIO()
    bg.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()
