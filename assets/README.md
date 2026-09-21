# Brand assets

| File | Use |
| --- | --- |
| `logo.svg` | Horizontal lockup for light backgrounds (README, docs, slides). |
| `logo-dark.svg` | Same lockup, light ink, for dark backgrounds. |
| `mark.svg` | The mark alone - app icon, avatar, anything 24px and up. |
| `favicon.svg` | Check only, no ruled lines. Use at 16-32px, where the full mark silts up. |

The mark is a script's ruled lines with the delivery check swept under them:
written, then confirmed - which is the whole job of this tool.

Purple runs `#7C5CFF` to `#4B2FE0` top to bottom, and stays that way in both
themes; the dashboard's `--accent` shifts between light and dark, the logo does
not. The wordmark is Archivo 700 (`wdth` 112, matching the dashboard's display
face) converted to outlines, so the files need no webfont anywhere they land.

## PNG exports

`png/` holds rasterized versions for anywhere SVG is not accepted - a Discord
bot avatar, an OG image, a slide, a favicon bundle.

| File | Use |
| --- | --- |
| `mark-1024/512/256/128/64.png` | The mark. 512 is the size Discord wants for a bot or app avatar. |
| `icon-48/32/16.png` | Check-only variant, for favicons and anywhere under 64px. |
| `logo-1600/800/400.png` | Lockup, dark ink, for light backgrounds. |
| `logo-dark-1600/800/400.png` | Lockup, light ink, for dark backgrounds. |

Every file is RGBA with a transparent background - the mark's purple tile *is*
its background, so nothing is baked in behind the rounded corners.

Regenerate them from the SVGs after any change to the artwork:

```bash
pip install cairosvg
python assets/render_png.py
```
