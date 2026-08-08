#!/usr/bin/env python3
"""Generate the integration's brand assets.

    python scripts/make_icon.py

## Where they go, and why there is only one destination

Home Assistant 2026.3 introduced the Brands Proxy API, and with it the ability for a
custom integration to carry its own icons in `custom_components/<domain>/brand/`.
Those take priority over the brands CDN, and the announcement is explicit that no
separate repository submission is needed.

So there is no pull request to home-assistant/brands here, and that is not an
omission. That repository's own pull request template now states that submissions for
new custom components are no longer accepted, and its type-of-change list covers core
integrations only. Sending one would waste a reviewer's time to be told the same
thing.

## What is generated

`icon.png` at 256x256 and `icon@2x.png` at 512x512, which are the two sizes the
brands specification requires.

No logo. When the logo would be the same image as the icon, the guidance is to ship
only the icon and let it stand in as the logo. A square 512x512 logo would fail the
size rule anyway, which wants the shortest side between 128 and 256 pixels. Dark
variants (`dark_icon.png` and friends) are supported by Home Assistant and could be
added here; the current icon reads well on both themes, so there are none.

## The design

Deliberately not derived from the manufacturer's visual identity, which would be a
trademark question nobody needs: a rounded square with a cold-to-warm gradient,
because these machines are reversible, and a three-blade fan, because that is the
universal shorthand for an outdoor unit.

Renders at 4x and downsamples, which is the simplest way to get decent anti-aliasing
with nothing but Pillow.
"""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw

REPO = pathlib.Path(__file__).resolve().parent.parent
IN_REPO = REPO / "custom_components" / "maxa_advantix" / "brand"

SS = 4  # supersampling factor

COLD = (31, 111, 235)  # blue: cooling
HOT = (249, 115, 22)  # orange: heating


def gradient(size: int) -> Image.Image:
    """Diagonal gradient from cold to warm."""
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            pixels[x, y] = tuple(round(COLD[i] + (HOT[i] - COLD[i]) * t) for i in range(3))
    return image


def rounded_mask(size: int, radius_fraction: float = 0.22) -> Image.Image:
    """Alpha mask for the rounded square the icon sits in."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_fraction), fill=255
    )
    return mask


def blade(centre: float, r0: float, r1: float, theta0: float) -> list[tuple[float, float]]:
    """One blade: a polygon between two spirals, narrowing towards the tip."""
    steps = 48
    twist = 0.85  # radians of twist between root and tip
    leading: list[tuple[float, float]] = []
    trailing: list[tuple[float, float]] = []
    for step in range(steps + 1):
        f = step / steps
        r = r0 + (r1 - r0) * f
        theta = theta0 + twist * f
        # widest in the middle of the blade, closing at both ends
        width = 0.52 * math.sin(math.pi * (0.15 + 0.85 * f)) * (1 - 0.35 * f)
        for offset, edge in ((-width, leading), (width, trailing)):
            edge.append(
                (centre + r * math.cos(theta + offset), centre + r * math.sin(theta + offset))
            )
    return leading + trailing[::-1]


def build(size: int) -> Image.Image:
    """Render the whole icon at `size` pixels, supersampled and downsampled."""
    big = size * SS
    background = gradient(big)
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    icon.paste(background, (0, 0), rounded_mask(big))

    draw = ImageDraw.Draw(icon)
    centre = big / 2
    for index in range(3):
        theta0 = index * 2 * math.pi / 3
        draw.polygon(
            blade(centre, big * 0.115, big * 0.415, theta0),
            fill=(255, 255, 255, 245),
        )
    # Centre hub, so the three blades read as a fan and not as a windmill.
    hub = big * 0.085
    draw.ellipse(
        [centre - hub, centre - hub, centre + hub, centre + hub],
        fill=(255, 255, 255, 255),
    )

    return icon.resize((size, size), Image.LANCZOS)


#: The required sizes, and nothing else. See the module docstring for why no logo.
SIZES = {"icon.png": 256, "icon@2x.png": 512}


def main() -> None:
    """Render the icons into the integration's brand directory."""
    IN_REPO.mkdir(parents=True, exist_ok=True)

    for name, size in SIZES.items():
        path = IN_REPO / name
        build(size).save(path)
        with Image.open(path) as opened:
            print(
                f"{path.relative_to(REPO)}: {opened.size[0]}x{opened.size[1]} "
                f"{opened.mode} {path.stat().st_size} bytes"
            )

    # A leftover file here ends up in the release zip and in front of users, so it
    # is worth naming rather than ignoring.
    unexpected = sorted(p.name for p in IN_REPO.iterdir() if p.name not in SIZES)
    if unexpected:
        print("\nunexpected files in the brand directory, remove them:")
        for name in unexpected:
            print(f"  {name}")


if __name__ == "__main__":
    main()
