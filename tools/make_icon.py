"""Genera assets/icon.ico y assets/icon.png (mismo diseño que ui/assets/logo.svg)."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024  # se dibuja grande y se reduce para un borde suave


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient() -> Image.Image:
    stops = [(0.0, (0x8B, 0x5C, 0xF6)), (0.5, (0x63, 0x66, 0xF1)), (1.0, (0x22, 0xD3, 0xEE))]
    img = Image.new("RGB", (S, S))
    px = img.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * (S - 1))
            for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
                if t <= t1:
                    px[x, y] = lerp(c0, c1, (t - t0) / (t1 - t0))
                    break
    return img


def build() -> Image.Image:
    base = gradient().convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.25), fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(out)
    unit = S / 64
    bars = [(13, 27, 10, 191), (21.5, 19, 26, 230), (30, 12, 40, 255), (38.5, 21, 22, 230), (47, 28, 8, 191)]
    for x, y, h, a in bars:
        d.rounded_rectangle([x * unit, y * unit, (x + 5) * unit, (y + h) * unit], radius=2.5 * unit,
                            fill=(255, 255, 255, a))
    return out


if __name__ == "__main__":
    img = build()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(assets / "icon.png")
    img.save(assets / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Iconos generados en", assets)
