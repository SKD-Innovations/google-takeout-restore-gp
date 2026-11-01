"""Rasterize the repository's simple geometric app mark for native packaging."""

from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
s = 4
image = Image.new("RGBA", (256 * s, 256 * s))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, 256 * s - 1, 256 * s - 1), radius=54 * s, fill="#e3ece8")
for points in [
    [(128, 174), (128, 61)],
    [(85, 104), (128, 61), (171, 104)],
    [(64, 164), (64, 198), (192, 198), (192, 164)],
]:
    scaled = [(x * s, y * s) for x, y in points]
    draw.line(scaled, fill="#28594b", width=15 * s, joint="curve")
    for x, y in scaled:
        r = 7.5 * s
        draw.ellipse((x - r, y - r, x + r, y + r), fill="#28594b")
image.save(root / "packaging/icon.icns", format="ICNS")
image.resize((256, 256), Image.Resampling.LANCZOS).save(
    root / "packaging/icon.ico",
    format="ICO",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
