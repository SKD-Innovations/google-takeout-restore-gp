"""Generate a restrained install background; Finder supplies the real draggable icons."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
font_path = "/System/Library/Fonts/SFNS.ttf"
for scale, suffix in [(1, ""), (2, "@2x")]:
    image = Image.new("RGB", (660 * scale, 440 * scale), "#f6f7f9")
    draw = ImageDraw.Draw(image)

    def text(y, value, size, color="#222c32"):
        font = ImageFont.truetype(font_path, size * scale)
        box = draw.textbbox((0, 0), value, font=font)
        draw.text(((660 * scale - (box[2] - box[0])) / 2, y * scale), value, font=font, fill=color)

    text(35, "Install Takeout Restore", 26)
    text(77, "Drag the app to Applications", 16, "#596672")
    # Icons are centered at (175,210) and (485,210) by the Finder view settings.
    draw.line([(295 * scale, 210 * scale), (363 * scale, 210 * scale)], fill="#8eaaa0", width=4 * scale)
    draw.line(
        [(350 * scale, 197 * scale), (363 * scale, 210 * scale), (350 * scale, 223 * scale)],
        fill="#8eaaa0",
        width=4 * scale,
    )
    text(336, "Then open Takeout Restore from Applications.", 14, "#596672")
    text(366, "Once installed, eject this disk image.", 12, "#7b858d")
    image.save(root / f"packaging/dmg-background{suffix}.png")
