"""
ELDRANTH GM MAP GENERATOR (Labeled + Legend) - 6144x6144 JPG
Windows-friendly, robust font resolver.

Dependencies:
  - Python 3.10+
  - Pillow (PIL) 10+
  - numpy 1.24+
Optional:
  - matplotlib (only used to locate installed system fonts more robustly)

Install:
  pip install pillow numpy
Optional:
  pip install matplotlib

Run:
  python eldranth_gm_map.py

Output:
  Eldranth_GM_Labeled_6144.jpg

Font notes (Windows):
  - This script will try:
      1) Explicit font paths you provide via env vars
      2) matplotlib font discovery (if installed)
      3) Common Windows fonts in C:\\Windows\\Fonts
      4) Pillow default font (last resort; labels will be small and less pretty)
  - You can override fonts by setting:
      ELDRANTH_FONT_TITLE, ELDRANTH_FONT_SERIF_BOLD, ELDRANTH_FONT_SERIF, ELDRANTH_FONT_SANS
    to a .ttf or .ttc path.
"""

from __future__ import annotations

import glob
import math
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ----------------------------
# Geometry and drawing utilities
# ----------------------------

def irregular_polygon(
    cx: float,
    cy: float,
    radius: float,
    n: int = 18,
    irregularity: float = 0.35,
    spikiness: float = 0.25,
    rng: Optional[random.Random] = None,
) -> List[Tuple[float, float]]:
    rng = rng or random.Random()
    step = 2 * math.pi / n
    angles = []
    for i in range(n):
        delta = rng.uniform(-irregularity, irregularity) * step
        angles.append(i * step + delta)
    angles.sort()

    pts = []
    for ang in angles:
        r = radius * (1 + rng.uniform(-spikiness, spikiness))
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def point_in_poly(x: float, y: float, poly: List[Tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) + 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def poly_bbox(poly: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def sample_point_in_poly(
    poly: List[Tuple[float, float]],
    bbox: Tuple[float, float, float, float],
    rng: random.Random,
    max_tries: int = 500,
) -> Optional[Tuple[float, float]]:
    minx, miny, maxx, maxy = bbox
    for _ in range(max_tries):
        x = rng.uniform(minx, maxx)
        y = rng.uniform(miny, maxy)
        if point_in_poly(x, y, poly):
            return x, y
    return None


def rotated_rectangle_points(cx: float, cy: float, w: float, h: float, angle: float) -> List[Tuple[float, float]]:
    dx, dy = w / 2.0, h / 2.0
    corners = [(-dx, -dy), (dx, -dy), (dx, dy), (-dx, dy)]
    ca, sa = math.cos(angle), math.sin(angle)
    pts = []
    for x, y in corners:
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def dashed_line(
    draw: ImageDraw.ImageDraw,
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    dash: int = 18,
    gap: int = 12,
    fill=(0, 0, 0, 255),
    width: int = 3,
) -> None:
    x1, y1 = p1
    x2, y2 = p2
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist == 0:
        return
    vx, vy = (x2 - x1) / dist, (y2 - y1) / dist
    pos = 0.0
    while pos < dist:
        seg_end = min(pos + dash, dist)
        draw.line(
            [(x1 + vx * pos, y1 + vy * pos), (x1 + vx * seg_end, y1 + vy * seg_end)],
            fill=fill,
            width=width,
        )
        pos += dash + gap


def draw_dashed_polyline(
    draw: ImageDraw.ImageDraw,
    pts: List[Tuple[float, float]],
    dash: int = 26,
    gap: int = 18,
    fill=(90, 90, 90, 120),
    width: int = 5,
) -> None:
    if len(pts) < 2:
        return

    remaining = float(dash)
    draw_on = True
    prev = pts[0]

    for i in range(1, len(pts)):
        curr = pts[i]
        seg_len = math.hypot(curr[0] - prev[0], curr[1] - prev[1])
        if seg_len == 0:
            continue

        vx, vy = (curr[0] - prev[0]) / seg_len, (curr[1] - prev[1]) / seg_len
        dist = 0.0
        while dist < seg_len:
            step = min(remaining, seg_len - dist)
            nxt = (prev[0] + vx * step, prev[1] + vy * step)
            if draw_on:
                draw.line([prev, nxt], fill=fill, width=width)
            prev = nxt
            dist += step
            remaining -= step
            if remaining <= 1e-4:
                draw_on = not draw_on
                remaining = float(dash if draw_on else gap)
        prev = curr


def bezier_curve(p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], steps: int = 60):
    pts = []
    for t in np.linspace(0, 1, steps):
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
        pts.append((float(x), float(y)))
    return pts


def draw_glow_path(
    draw: ImageDraw.ImageDraw,
    pts: List[Tuple[float, float]],
    glow=(150, 90, 200, 70),
    core=(120, 70, 170, 170),
    glow_width: int = 28,
    core_width: int = 9,
) -> None:
    draw.line(pts, fill=glow, width=glow_width, joint="curve")
    draw.line(pts, fill=core, width=core_width, joint="curve")


def draw_step_ring(draw: ImageDraw.ImageDraw, x: float, y: float, r: float = 42) -> None:
    draw.ellipse((x - r, y - r, x + r, y + r), outline=(90, 70, 65, 220), width=5, fill=(240, 240, 255, 35))
    draw.ellipse((x - r * 0.62, y - r * 0.62, x + r * 0.62, y + r * 0.62), outline=(130, 85, 180, 180), width=4)
    for k in range(12):
        ang = k * 2 * math.pi / 12
        x1 = x + math.cos(ang) * r * 0.78
        y1 = y + math.sin(ang) * r * 0.78
        x2 = x + math.cos(ang) * r * 0.95
        y2 = y + math.sin(ang) * r * 0.95
        draw.line([(x1, y1), (x2, y2)], fill=(130, 85, 180, 140), width=3)


def draw_text_outline(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill=(20, 15, 12, 255),
    outline=(255, 255, 255, 220),
    width: int = 3,
    anchor: str = "mm",
) -> None:
    x, y = pos
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx * dx + dy * dy <= width * width:
                draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor, align="center")
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor, align="center")


# ----------------------------
# Robust font resolver (Windows-friendly)
# ----------------------------

@dataclass(frozen=True)
class FontSpec:
    env_var: str
    # Names/patterns to try, in order (works with Windows Fonts folder search and matplotlib)
    preferred_names: Tuple[str, ...]
    size: int


def _normalize_path(p: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))


def _existing_file(p: str) -> Optional[str]:
    p2 = _normalize_path(p)
    return p2 if os.path.isfile(p2) else None


def _windows_font_dir_candidates() -> List[str]:
    # Typical Windows font directories
    candidates = []
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates.append(os.path.join(windir, "Fonts"))
    # Some setups might have fonts elsewhere, but this covers most cases
    return [c for c in candidates if os.path.isdir(c)]


def _find_in_windows_fonts(preferred_names: Tuple[str, ...]) -> Optional[str]:
    font_dirs = _windows_font_dir_candidates()
    if not font_dirs:
        return None

    # Build an index of filename lower -> full path for quick matching
    all_paths: List[str] = []
    for d in font_dirs:
        all_paths.extend(glob.glob(os.path.join(d, "*.ttf")))
        all_paths.extend(glob.glob(os.path.join(d, "*.otf")))
        all_paths.extend(glob.glob(os.path.join(d, "*.ttc")))

    index = {os.path.basename(p).lower(): p for p in all_paths}

    # 1) Exact filename match attempts (case-insensitive)
    for name in preferred_names:
        key = name.lower()
        if key in index:
            return index[key]

    # 2) Fuzzy contains match: if user supplied family-like patterns
    # Example: "georgia" should match "georgia.ttf" or "georgiab.ttf"
    for name in preferred_names:
        token = os.path.splitext(name.lower())[0]
        for fn_lower, full in index.items():
            if token and token in fn_lower:
                return full

    return None


def _find_with_matplotlib(preferred_names: Tuple[str, ...]) -> Optional[str]:
    # Optional dependency: matplotlib
    try:
        from matplotlib import font_manager  # type: ignore
    except Exception:
        return None

    # Try to find by explicit file-ish names first
    for n in preferred_names:
        # If user gave a path-like string, skip here
        if any(sep in n for sep in ("/", "\\", ":")):
            continue
        try:
            # If n looks like a filename, font_manager might still find it if installed
            fp = font_manager.findfont(n, fallback_to_default=False)
            if os.path.isfile(fp):
                return fp
        except Exception:
            pass

    # Then try by common families derived from preferred_names
    # This increases hit rate on Windows
    families_to_try = []
    for n in preferred_names:
        base = os.path.splitext(n)[0]
        base = base.replace("_", " ").replace("-", " ").strip()
        if base:
            families_to_try.append(base)

    for fam in families_to_try:
        try:
            fp = font_manager.findfont(fam, fallback_to_default=False)
            if os.path.isfile(fp):
                return fp
        except Exception:
            pass

    return None


def resolve_font_path(spec: FontSpec) -> Optional[str]:
    # 1) Env var override
    env_val = os.environ.get(spec.env_var)
    if env_val:
        p = _existing_file(env_val)
        if p:
            return p

    # 2) If any preferred_names are absolute/relative paths, accept them
    for n in spec.preferred_names:
        if any(sep in n for sep in ("/", "\\", ":")):
            p = _existing_file(n)
            if p:
                return p

    # 3) matplotlib discovery (optional)
    p = _find_with_matplotlib(spec.preferred_names)
    if p:
        return p

    # 4) Windows Fonts directory search
    p = _find_in_windows_fonts(spec.preferred_names)
    if p:
        return p

    return None


def load_font(spec: FontSpec, default_fallback: bool = True) -> ImageFont.ImageFont:
    """
    Returns a usable font object.
    - If no font found and default_fallback=True, returns Pillow's default font.
      (This keeps the script runnable, but text will be small and less legible.)
    """
    path = resolve_font_path(spec)
    if path:
        # For TTC fonts, Pillow can load the first face with index=0.
        # For most Windows fonts, this works fine.
        try:
            if path.lower().endswith(".ttc"):
                return ImageFont.truetype(path, spec.size, index=0)
            return ImageFont.truetype(path, spec.size)
        except Exception:
            # If the font file is unreadable for some reason, fall through
            pass

    if default_fallback:
        return ImageFont.load_default()

    raise FileNotFoundError(
        f"Could not resolve a font for {spec.env_var}. "
        f"Set {spec.env_var} to a .ttf/.ttc file path, or install a system font."
    )


# ----------------------------
# Background
# ----------------------------

def make_parchment_bg(W: int, H: int, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base_col = np.array([244, 236, 210], dtype=np.float32)
    noise = rng.normal(loc=0.0, scale=18.0, size=(H, W, 1)).astype(np.float32)
    noise = np.clip(noise, -45, 45)
    tex = np.clip(base_col + noise, 0, 255).astype(np.uint8)

    img = Image.fromarray(np.repeat(tex, 4, axis=2), mode="RGBA")
    r, g, b, _a = img.split()
    img = Image.merge("RGBA", (r, g, b, Image.new("L", (W, H), 255)))
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))

    v = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(v)
    vd.ellipse((-W * 0.15, -H * 0.15, W * 1.15, H * 1.15), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(radius=220))
    img = Image.composite(img, Image.new("RGBA", (W, H), (225, 215, 190, 255)), v)
    return img


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    W = H = 6144
    SEED = 42
    rng = random.Random(SEED)
    np.random.seed(SEED)

    # Colors
    ink = (70, 55, 50, 200)
    building_fill = (252, 250, 244, 210)
    road_ink = (120, 105, 95, 120)
    water_col = (70, 120, 130, 140)
    glow_purple = (140, 80, 180, 140)
    glow_blue = (80, 120, 180, 140)
    glow_green = (80, 140, 100, 140)
    glow_orange = (190, 120, 70, 150)

    # Fonts (robust resolver; you can override each with env vars)
    # Windows defaults are chosen to be very likely present:
    # - Georgia/Times/Cambria for serif
    # - Arial/Calibri for sans
    font_title = load_font(FontSpec(
        env_var="ELDRANTH_FONT_TITLE",
        preferred_names=("georgiab.ttf", "georgia.ttf", "timesbd.ttf", "times.ttf", "cambria.ttc", "cambriaz.ttf"),
        size=78,
    ))
    font_district = load_font(FontSpec(
        env_var="ELDRANTH_FONT_SERIF_BOLD",
        preferred_names=("georgiab.ttf", "timesbd.ttf", "cambriaz.ttf", "cambria.ttc", "georgia.ttf", "times.ttf"),
        size=54,
    ))
    font_poi = load_font(FontSpec(
        env_var="ELDRANTH_FONT_SERIF",
        preferred_names=("georgia.ttf", "times.ttf", "cambria.ttc", "timesi.ttf", "georgiai.ttf"),
        size=34,
    ))
    font_small = load_font(FontSpec(
        env_var="ELDRANTH_FONT_SANS",
        preferred_names=("arial.ttf", "calibri.ttf", "segoeui.ttf", "tahoma.ttf"),
        size=28,
    ))

    # Background
    base = make_parchment_bg(W, H, seed=SEED)

    cx0 = cy0 = W // 2

    districts: List[Dict] = [
        dict(name="Scholarium Core", center=(cx0, cy0), radius=780, n=22, fill=(240, 232, 210, 255), outline=(45, 35, 30, 255), style="solid"),
        dict(name="Aegis Bastion", center=(cx0, cy0 - 820), radius=430, n=18, fill=(236, 228, 205, 255), outline=(45, 35, 30, 255), style="fort"),
        dict(name="Regal Reach", center=(cx0, cy0 - 1850), radius=650, n=20, fill=(238, 229, 208, 255), outline=(45, 35, 30, 255), style="royal"),
        dict(name="Marketspace", center=(cx0 + 900, cy0 + 200), radius=620, n=20, fill=(238, 230, 206, 255), outline=(45, 35, 30, 255), style="market"),
        dict(name="Concord Crescent", center=(cx0 + 1850, cy0 - 250), radius=740, n=22, fill=(236, 226, 202, 255), outline=(45, 35, 30, 255), style="diplomatic"),
        dict(name="Gatewright Ward", center=(cx0 + 1500, cy0 + 1550), radius=720, n=22, fill=(237, 227, 205, 255), outline=(45, 35, 30, 255), style="portal"),
        dict(name="Embercrown Deep", center=(cx0, cy0 + 1950), radius=720, n=22, fill=(236, 226, 200, 255), outline=(45, 35, 30, 255), style="forge"),
        dict(name="Verdancy Terraces", center=(cx0 - 1650, cy0 + 250), radius=820, n=24, fill=(236, 230, 204, 255), outline=(45, 35, 30, 255), style="garden"),
        dict(name="Stormhouse Row", center=(cx0 - 2000, cy0 - 1200), radius=560, n=20, fill=(235, 226, 205, 255), outline=(45, 35, 30, 255), style="utilities"),
        dict(name="Outer Trade Ring", center=(cx0 - 1700, cy0 + 1950), radius=640, n=22, fill=(235, 225, 200, 255), outline=(45, 35, 30, 255), style="yards"),
        dict(name="Commoner Estates", center=(cx0 - 2100, cy0 - 2350), radius=520, n=20, fill=(236, 228, 206, 255), outline=(45, 35, 30, 255), style="estates"),
    ]

    arcane = [
        ("The Deferred Hour (Elsewhen)", (cx0 + 2050, cy0 - 2100), 420, "chrono"),
        ("The Shattered Reflection (Mirage)", (cx0 + 2550, cy0 + 200), 420, "illusion"),
        ("The Veiled Prospect (Sightlines)", (cx0 + 2100, cy0 + 2200), 420, "divination"),
        ("The Pallid Perch (Quiet)", (cx0 + 600, cy0 + 2750), 390, "necromancy"),
        ("The Cinderreach (Blastward)", (cx0 - 2400, cy0 + 2250), 420, "evocation"),
        ("The Mutable Ring (Flux)", (cx0 - 2750, cy0 + 150), 420, "transmutation"),
        ("The Summoned Quarter (Call)", (cx0 - 2200, cy0 - 700), 420, "conjuration"),
    ]
    for nm, c, r, st in arcane:
        districts.append(dict(name=nm, center=c, radius=r, n=18, fill=(240, 236, 224, 190), outline=(70, 60, 55, 200), style=st, phased=True))

    # Draw districts
    district_polys: Dict[str, List[Tuple[float, float]]] = {}
    layer = base.copy()
    draw = ImageDraw.Draw(layer, "RGBA")

    for d in districts:
        cx, cy = d["center"]
        poly = irregular_polygon(cx, cy, d["radius"], n=d.get("n", 20), irregularity=0.28, spikiness=0.22, rng=rng)
        district_polys[d["name"]] = poly

        shadow = [(x + 8, y + 10) for x, y in poly]
        draw.polygon(shadow, fill=(30, 25, 22, 35))
        draw.polygon(poly, fill=d["fill"])

        if d.get("phased"):
            for i in range(len(poly)):
                dashed_line(draw, poly[i], poly[(i + 1) % len(poly)], dash=22, gap=14, fill=d["outline"], width=5)
        else:
            draw.line(poly + [poly[0]], fill=d["outline"], width=6, joint="curve")

    # Interior details
    detail = layer.copy()
    d2 = ImageDraw.Draw(detail, "RGBA")

    for d in districts:
        name = d["name"]
        poly = district_polys[name]
        bbox = poly_bbox(poly)
        cx, cy = d["center"]
        style = d["style"]
        phased = d.get("phased", False)

        plaza_r = d["radius"] * (0.13 if not phased else 0.16)
        d2.ellipse((cx - plaza_r, cy - plaza_r, cx + plaza_r, cy + plaza_r), outline=ink, width=4, fill=(255, 255, 255, 40))

        road_pts = []
        for _ in range(6 if not phased else 4):
            p = sample_point_in_poly(poly, bbox, rng=rng)
            if p:
                road_pts.append(p)
        for i in range(len(road_pts) - 1):
            d2.line([road_pts[i], road_pts[i + 1]], fill=road_ink, width=6)
        if len(road_pts) > 2:
            d2.line([road_pts[-1], road_pts[0]], fill=road_ink, width=5)

        if style == "garden":
            num = 80
        elif style in ("market", "diplomatic", "portal", "royal", "forge"):
            num = 110
        elif style in ("yards", "estates", "utilities"):
            num = 90
        else:
            num = 70 if not phased else 45

        for _ in range(num):
            p = sample_point_in_poly(poly, bbox, rng=rng)
            if not p:
                continue
            x, y = p
            if (x - cx) ** 2 + (y - cy) ** 2 < (plaza_r * 1.15) ** 2:
                continue
            w = rng.uniform(18, 56) * (1.25 if style in ("market", "royal") else 1.0) * (0.9 if phased else 1.0)
            h = rng.uniform(14, 48) * (1.15 if style == "diplomatic" else 1.0) * (0.9 if phased else 1.0)
            ang = rng.uniform(0, math.pi)
            pts = rotated_rectangle_points(x, y, w, h, ang)
            if all(point_in_poly(px, py, poly) for px, py in pts):
                d2.polygon(pts, outline=ink, fill=building_fill)

        if style == "garden":
            for t in range(10):
                y_off = cy - d["radius"] * 0.7 + t * (d["radius"] * 0.14)
                x1 = bbox[0] + 50
                x2 = bbox[2] - 50
                pts = []
                for xi in np.linspace(x1, x2, 14):
                    yi = y_off + 25 * math.sin((xi - x1) / 220.0 + t)
                    if point_in_poly(float(xi), float(yi), poly):
                        pts.append((float(xi), float(yi)))
                if len(pts) > 2:
                    d2.line(pts, fill=water_col, width=10)

        if style == "portal":
            for k in range(3):
                angle = k * 2 * math.pi / 3 + 0.4
                px = cx + math.cos(angle) * d["radius"] * 0.42
                py = cy + math.sin(angle) * d["radius"] * 0.42
                rr = 110
                d2.ellipse((px - rr, py - rr, px + rr, py + rr), outline=ink, width=6, fill=(220, 220, 255, 70))
                d2.ellipse((px - rr * 0.65, py - rr * 0.65, px + rr * 0.65, py + rr * 0.65), outline=glow_blue, width=6)

        if style == "forge":
            crev = [(cx - 220, cy + 50), (cx - 80, cy - 260), (cx + 60, cy - 80), (cx + 260, cy - 320),
                    (cx + 430, cy + 120), (cx + 130, cy + 240)]
            d2.line(crev, fill=(60, 40, 35, 220), width=50)
            d2.line(crev, fill=glow_orange, width=22)

        if style == "utilities":
            for _ in range(12):
                p = sample_point_in_poly(poly, bbox, rng=rng)
                if not p:
                    continue
                x, y = p
                hh = rng.uniform(60, 120)
                ww = hh * 0.18
                d2.rectangle((x - ww, y - hh, x + ww, y + hh * 0.3), outline=ink, fill=(220, 230, 255, 40))
                d2.line([(x, y - hh * 0.9), (x + ww * 0.4, y - hh * 0.4), (x - ww * 0.3, y), (x + ww * 0.2, y + hh * 0.25)],
                        fill=glow_blue, width=4)

        if style == "yards":
            rr = 220
            d2.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=ink, width=5, fill=(255, 255, 255, 15))

        if style == "market":
            size = 520
            for i in range(6):
                s = size - i * 70
                d2.rectangle((cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2),
                             outline=ink, width=6 if i == 0 else 4,
                             fill=(255, 255, 255, 18 if i % 2 == 0 else 8))
            d2.rectangle((cx - 110, cy - 110, cx + 110, cy + 110), outline=glow_purple, width=6, fill=(60, 40, 90, 50))

        if style == "royal":
            for i in range(7):
                angle = i * 2 * math.pi / 7
                px = cx + math.cos(angle) * d["radius"] * 0.35
                py = cy + math.sin(angle) * d["radius"] * 0.35
                rr = 55 + 10 * math.sin(i)
                d2.ellipse((px - rr, py - rr, px + rr, py + rr), outline=ink, width=5, fill=(255, 255, 255, 30))
                d2.ellipse((px - rr * 0.4, py - rr * 0.4, px + rr * 0.4, py + rr * 0.4), outline=glow_blue, width=4)
            d2.rectangle((cx - 160, cy - 120, cx + 160, cy + 120), outline=ink, width=6, fill=(255, 255, 255, 22))

        if style == "diplomatic":
            rr = 160
            d2.ellipse((cx + 260 - rr, cy + 220 - rr, cx + 260 + rr, cy + 220 + rr), outline=ink, width=6, fill=(230, 240, 255, 25))
            d2.ellipse((cx + 260 - rr * 0.55, cy + 220 - rr * 0.55, cx + 260 + rr * 0.55, cy + 220 + rr * 0.55), outline=glow_blue, width=5)

        if style == "fort":
            r = d["radius"] * 0.78
            d2.rectangle((cx - r, cy - r, cx + r, cy + r), outline=ink, width=8, fill=(255, 255, 255, 12))
            d2.rectangle((cx - r * 0.65, cy - r * 0.65, cx + r * 0.65, cy + r * 0.65), outline=ink, width=6, fill=(255, 255, 255, 10))

        if phased:
            rr = plaza_r * 0.9
            d2.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(90, 70, 65, 180), width=3)

    # POIs and paths (minimal: we keep labels/legend; POI art is optional but included)
    poi: Dict[str, Tuple[float, float]] = {}
    d3 = ImageDraw.Draw(detail, "RGBA")

    def center_of(name: str) -> Tuple[float, float]:
        for dd in districts:
            if dd["name"] == name:
                return dd["center"]
        raise KeyError(name)

    sc_cx, sc_cy = center_of("Scholarium Core")
    cc_cx, cc_cy = center_of("Concord Crescent")
    vt_cx, vt_cy = center_of("Verdancy Terraces")
    sr_cx, sr_cy = center_of("Stormhouse Row")
    ed_cx, ed_cy = center_of("Embercrown Deep")
    ot_cx, ot_cy = center_of("Outer Trade Ring")
    ce_cx, ce_cy = center_of("Commoner Estates")
    rr_cx, rr_cy = center_of("Regal Reach")
    gw_cx, gw_cy = center_of("Gatewright Ward")

    # A few POIs (enough to match labeling behavior)
    poi["Triarch Athenaeum"] = (sc_cx, sc_cy)
    poi["Index Pools"] = (sc_cx + 240, sc_cy + 40)
    poi["Veyl's Reliquary"] = (sc_cx - 420, sc_cy + 220)
    poi["Knights Librarian HQ"] = (sc_cx - 60, sc_cy - 320)
    poi["Threshold Terminal"] = (gw_cx + 200, gw_cy - 260)
    poi["Step-Ring Registry"] = (gw_cx - 250, gw_cy + 180)
    poi["Concord Hall"] = (cc_cx - 80, cc_cy - 40)
    poi["Veilmarket Exchange"] = (cc_cx + 240, cc_cy - 260)
    poi["Steamveil Rotunda"] = (cc_cx + 260, cc_cy + 240)
    poi["Lyricwell Plaza"] = (cc_cx - 300, cc_cy - 230)
    poi["Serion Square"] = (vt_cx - 120, vt_cy - 160)
    poi["Drownbloom Conservatory"] = (vt_cx + 240, vt_cy + 340)
    poi["Cleanspring Works"] = (vt_cx + 420, vt_cy - 220)
    poi["Stormcoil Exchange"] = (sr_cx + 80, sr_cy + 100)
    poi["The Crownless Crucible"] = (ed_cx - 260, ed_cy + 40)
    poi["Brasshorn Yards & Tack Hall"] = (ot_cx + 160, ot_cy - 200)
    poi["Commoner Watchtower"] = (ce_cx + 170, ce_cy - 180)
    poi["Imperial Spires"] = (rr_cx, rr_cy - 80)
    poi["Aegis Bastion"] = center_of("Aegis Bastion")
    poi["Glimmerpool Fountain"] = (sc_cx + 650, sc_cy - 120)

    overlay = detail.copy()
    d4 = ImageDraw.Draw(overlay, "RGBA")

    step_nodes: Dict[str, Tuple[float, float]] = {
        "Scholarium Core": (sc_cx + 120, sc_cy + 520),
        "Marketspace": (center_of("Marketspace")[0] - 260, center_of("Marketspace")[1] + 360),
        "Concord Crescent": (cc_cx - 540, cc_cy + 140),
        "Gatewright Ward": poi["Step-Ring Registry"],
        "Verdancy Terraces": (vt_cx - 420, vt_cy + 220),
        "Regal Reach": (rr_cx - 240, rr_cy + 260),
        "Embercrown Deep": (ed_cx + 340, ed_cy - 220),
        "Stormhouse Row": (sr_cx - 220, sr_cy - 120),
        "Outer Trade Ring": (ot_cx - 260, ot_cy - 220),
        "Commoner Estates": (ce_cx - 160, ce_cy + 160),
        "Aegis Bastion": (center_of("Aegis Bastion")[0] + 220, center_of("Aegis Bastion")[1] + 220),
    }
    for dd in districts:
        if dd.get("phased"):
            step_nodes[dd["name"]] = dd["center"]

    connections = [
        ("Scholarium Core", "Marketspace", (sc_cx + 450, sc_cy + 240)),
        ("Scholarium Core", "Concord Crescent", (sc_cx + 980, sc_cy - 420)),
        ("Scholarium Core", "Gatewright Ward", (sc_cx + 900, sc_cy + 950)),
        ("Scholarium Core", "Verdancy Terraces", (sc_cx - 720, sc_cy + 280)),
        ("Scholarium Core", "Regal Reach", (sc_cx - 70, sc_cy - 1350)),
        ("Scholarium Core", "Embercrown Deep", (sc_cx - 260, sc_cy + 1350)),
    ]
    for dd in districts:
        if dd.get("phased"):
            mid = (
                (dd["center"][0] + sc_cx) / 2 + rng.uniform(-250, 250),
                (dd["center"][1] + sc_cy) / 2 + rng.uniform(-250, 250),
            )
            connections.append((dd["name"], "Scholarium Core", mid))

    for a, b, ctrl in connections:
        pts = bezier_curve(step_nodes[a], ctrl, step_nodes[b], steps=80)
        draw_glow_path(d4, pts)

    for nm, (x, y) in step_nodes.items():
        r = 38 if nm.startswith("The ") else 44
        draw_step_ring(d4, x, y, r=r)

    # Skyroads + mist
    sky = overlay.copy()
    d5 = ImageDraw.Draw(sky, "RGBA")

    skyroads = [
        ("Regal Reach", "Scholarium Core", (sc_cx + 120, sc_cy - 900)),
        ("Scholarium Core", "Concord Crescent", (sc_cx + 900, sc_cy - 700)),
        ("Concord Crescent", "Gatewright Ward", (cc_cx + 680, cc_cy + 560)),
    ]
    for a, b, ctrl in skyroads:
        pts = bezier_curve(step_nodes[a], ctrl, step_nodes[b], steps=90)
        d5.line(pts, fill=(180, 180, 200, 45), width=22, joint="curve")
        draw_dashed_polyline(d5, pts, dash=34, gap=22, fill=(100, 110, 130, 120), width=7)

    mist = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mdraw = ImageDraw.Draw(mist, "RGBA")
    for _ in range(140):
        x = rng.uniform(0, W)
        y = rng.uniform(0, H)
        r = rng.uniform(90, 260)
        mdraw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 16))
    mist = mist.filter(ImageFilter.GaussianBlur(radius=22))
    sky = Image.alpha_composite(sky, mist)

    # Labels + legend + compass
    gm = sky.copy()
    gdraw = ImageDraw.Draw(gm, "RGBA")

    # Title
    gdraw.rounded_rectangle((120, 90, 1200, 320), radius=28, fill=(245, 240, 228, 210), outline=ink, width=4)
    draw_text_outline(gdraw, (660, 170), "ELDRANTH", font=font_title, fill=(30, 20, 18, 255), outline=(255, 255, 255, 200), width=4)
    draw_text_outline(gdraw, (660, 270), "The Unseen Capital", font=font_district, fill=(50, 35, 30, 255), outline=(255, 255, 255, 210), width=3)

    # District labels
    for dd in districts:
        nm = dd["name"]
        cx, cy = dd["center"]
        if dd.get("phased"):
            short = nm.replace("The ", "").replace(" (", "\n(")
            draw_text_outline(gdraw, (cx, cy), short, font=font_small, fill=(70, 55, 50, 220), outline=(255, 255, 255, 160), width=2)
        else:
            draw_text_outline(gdraw, (cx, cy), nm, font=font_district, fill=(35, 25, 22, 255), outline=(255, 255, 255, 210), width=4)

    # POI labels
    poi_offsets: Dict[str, Tuple[int, int]] = {
        "Triarch Athenaeum": (0, -210),
        "Knights Librarian HQ": (-80, -170),
        "Index Pools": (220, -40),
        "Veyl's Reliquary": (-260, 70),
        "Glimmerpool Fountain": (170, -130),
        "Threshold Terminal": (260, -120),
        "Step-Ring Registry": (-10, 170),
        "Concord Hall": (-320, 110),
        "Veilmarket Exchange": (280, -180),
        "Steamveil Rotunda": (320, 110),
        "Lyricwell Plaza": (-320, -150),
        "Serion Square": (-270, -150),
        "Drownbloom Conservatory": (320, 150),
        "Cleanspring Works": (270, -120),
        "Stormcoil Exchange": (220, 130),
        "The Crownless Crucible": (-320, 160),
        "Brasshorn Yards & Tack Hall": (320, -140),
        "Commoner Watchtower": (240, -120),
        "Imperial Spires": (240, -140),
        "Aegis Bastion": (260, 140),
    }
    for name, (x, y) in poi.items():
        if name not in poi_offsets:
            continue
        ox, oy = poi_offsets[name]
        lx, ly = x + ox, y + oy
        gdraw.line([(x, y), (lx, ly)], fill=(50, 40, 35, 200), width=4)

        tb = gdraw.textbbox((0, 0), name, font=font_poi)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        pad = 14
        gdraw.rounded_rectangle(
            (lx - tw / 2 - pad, ly - th / 2 - pad, lx + tw / 2 + pad, ly + th / 2 + pad),
            radius=18,
            fill=(245, 242, 234, 200),
            outline=(70, 55, 50, 210),
            width=3,
        )
        draw_text_outline(gdraw, (lx, ly), name, font=font_poi, fill=(30, 22, 18, 255), outline=(255, 255, 255, 210), width=2)

    # Legend
    leg_x1, leg_y1, leg_x2, leg_y2 = W - 1480, H - 820, W - 160, H - 160
    gdraw.rounded_rectangle((leg_x1, leg_y1, leg_x2, leg_y2), radius=28, fill=(245, 242, 234, 215), outline=ink, width=4)
    draw_text_outline(gdraw, ((leg_x1 + leg_x2) / 2, leg_y1 + 70), "Legend", font=font_district, fill=(35, 25, 22, 255), outline=(255, 255, 255, 210), width=3)

    lx = leg_x1 + 120
    ly = leg_y1 + 150
    draw_step_ring(gdraw, lx, ly, r=34)
    draw_text_outline(gdraw, (lx + 200, ly), "Public Step-Ring", font=font_poi, fill=(40, 30, 25, 255), outline=(255, 255, 255, 200), width=2, anchor="lm")

    ly += 90
    gdraw.line([(lx - 20, ly), (lx + 120, ly)], fill=(180, 180, 200, 60), width=18)
    draw_dashed_polyline(gdraw, [(lx - 20, ly), (lx + 120, ly)], dash=24, gap=14, fill=(100, 110, 130, 150), width=6)
    draw_text_outline(gdraw, (lx + 200, ly), "Skyroad Causeway (Aerial Lane)", font=font_poi, fill=(40, 30, 25, 255), outline=(255, 255, 255, 200), width=2, anchor="lm")

    ly += 90
    gdraw.line([(lx - 20, ly), (lx + 120, ly)], fill=(70, 55, 50, 180), width=6)
    gdraw.polygon([(lx + 40, ly - 30), (lx + 70, ly), (lx + 40, ly + 30)], outline=(70, 55, 50, 200), fill=(255, 255, 255, 30))
    draw_text_outline(gdraw, (lx + 200, ly), "Sigil-Gate (Restricted Access)", font=font_poi, fill=(40, 30, 25, 255), outline=(255, 255, 255, 200), width=2, anchor="lm")

    ly += 90
    gdraw.rectangle((lx - 10, ly - 25, lx + 110, ly + 25), outline=(70, 60, 55, 200), width=4)
    dashed_line(gdraw, (lx - 10, ly - 25), (lx + 110, ly - 25), dash=14, gap=10, fill=(70, 60, 55, 200), width=4)
    dashed_line(gdraw, (lx - 10, ly + 25), (lx + 110, ly + 25), dash=14, gap=10, fill=(70, 60, 55, 200), width=4)
    dashed_line(gdraw, (lx - 10, ly - 25), (lx - 10, ly + 25), dash=14, gap=10, fill=(70, 60, 55, 200), width=4)
    dashed_line(gdraw, (lx + 110, ly - 25), (lx + 110, ly + 25), dash=14, gap=10, fill=(70, 60, 55, 200), width=4)
    gdraw.rectangle((lx - 10, ly - 25, lx + 110, ly + 25), fill=(240, 236, 224, 120))
    draw_text_outline(gdraw, (lx + 200, ly), "Folded / Phased District", font=font_poi, fill=(40, 30, 25, 255), outline=(255, 255, 255, 200), width=2, anchor="lm")

    # Compass
    comp_cx, comp_cy = W - 360, 320
    rr = 110
    gdraw.ellipse((comp_cx - rr, comp_cy - rr, comp_cx + rr, comp_cy + rr), outline=ink, width=4, fill=(245, 242, 234, 200))
    for k in range(8):
        ang = k * math.pi / 4
        x1 = comp_cx + math.cos(ang) * rr * 0.15
        y1 = comp_cy + math.sin(ang) * rr * 0.15
        x2 = comp_cx + math.cos(ang) * rr * 0.9
        y2 = comp_cy + math.sin(ang) * rr * 0.9
        gdraw.line([(x1, y1), (x2, y2)], fill=(70, 55, 50, 220), width=4)
    draw_text_outline(gdraw, (comp_cx, comp_cy - rr * 0.95), "N", font=font_district, fill=(35, 25, 22, 255), outline=(255, 255, 255, 210), width=3)

    out_path = "Eldranth_GM_Labeled_6144.jpg"
    gm.convert("RGB").save(out_path, format="JPEG", quality=92, optimize=True, progressive=True)
    print(f"Saved: {out_path} ({W}x{H})")


if __name__ == "__main__":
    main()
