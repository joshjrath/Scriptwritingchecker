"""Rasterize the brand SVGs into assets/png/.

The SVGs are the source of truth; every PNG here is derived. Run this after
changing the artwork so the two never drift apart:

    pip install cairosvg
    python assets/render_png.py
"""

from pathlib import Path

import cairosvg

HERE = Path(__file__).parent
OUT = HERE / "png"

#: The lockup's aspect, taken from its viewBox, so widths stay undistorted.
LOCKUP_W, LOCKUP_H = 745, 104


def render(src: str, name: str, width: int, height: int | None = None) -> None:
    cairosvg.svg2png(
        url=str(HERE / src),
        write_to=str(OUT / name),
        output_width=width,
        output_height=height or width,
    )
    print(f"  {name}")


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # The mark holds its ruled lines down to 64px. Below that they silt up, so
    # the small sizes come from the check-only variant instead.
    for size in (1024, 512, 256, 128, 64):
        render("mark.svg", f"mark-{size}.png", size)
    for size in (48, 32, 16):
        render("favicon.svg", f"icon-{size}.png", size)

    for width in (1600, 800, 400):
        height = round(width * LOCKUP_H / LOCKUP_W)
        render("logo.svg", f"logo-{width}.png", width, height)
        render("logo-dark.svg", f"logo-dark-{width}.png", width, height)


if __name__ == "__main__":
    main()
