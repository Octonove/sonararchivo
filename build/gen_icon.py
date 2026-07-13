"""Genera build/icon.ico para SonarArchivo (ping de sonar sobre navy)."""

from pathlib import Path
from PIL import Image, ImageDraw

NAVY = (30, 58, 95, 255)
NAVY2 = (21, 48, 77, 255)
TERRA = (206, 110, 97, 255)
CYAN = (110, 193, 228, 255)
WHITE = (255, 255, 255, 255)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=NAVY)
    d.rounded_rectangle([0, int(size * 0.5), size - 1, size - 1], radius=r, fill=NAVY2)
    # ondas de sonar concentricas desde la esquina inf-izquierda
    cx, cy = int(size * 0.30), int(size * 0.72)
    for i, col in enumerate((CYAN, TERRA, CYAN)):
        rad = int(size * (0.18 + i * 0.16))
        w = max(2, size // 26)
        d.arc([cx - rad, cy - rad, cx + rad, cy + rad], start=270, end=360,
              fill=col, width=w)
    # 'blip' detectado
    bx, by = int(size * 0.66), int(size * 0.36)
    br = max(3, size // 12)
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=WHITE)
    d.ellipse([bx - br // 2, by - br // 2, bx + br // 2, by + br // 2], fill=TERRA)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent / "icon.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [make(s) for s in sizes]
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    make(256).save(out.with_name("icon_preview.png"))
    print("icono ->", out)


if __name__ == "__main__":
    main()
