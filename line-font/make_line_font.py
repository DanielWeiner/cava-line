#!/usr/bin/env python3
"""Generate LineFont-VF.ttf — a 3-axis variable font.

Axes
----
  wght  100-900   stroke weight (hs 30-260 font units)
  CRVE  0-100     S-curve sharpness
  VPOS  0-100     vertical position; y-shift for audio level

Glyph layout (Unicode PUA)
--------------------------
  E000          empty
  E001          flat (n=0)
  E002-E065     ascending S-curve, n=1-100
  E066-E0C9     descending S-curve, n=100-1

S-curve geometry
----------------
  Centerline: smoothstep-based interpolation from (0,ly) to (ADV,ry).
    x(t) = t · ADV
    y(t) = ly + (ry − ly) · f(t, c)

  where c = CRVE/CRVE_MAX and f is a blend between the cubic smoothstep
  S(t) = 3t²−2t³ and its self-composition S(S(t)):
    f(t, c) = (1−c)·S(t) + c·S(S(t))

  Both S(t) and S(S(t)) have zero first derivatives at t=0 and t=1, so the
  tangent is horizontal at both endpoints for all CRVE values — required for
  seamless tiling. The self-composition sharpens the midpoint slope from 1.5
  to 2.25 (= 1.5²), producing a crisper S at high CRVE.

  The outline is the parallel curve of the centerline at distance ±hs,
  approximated as a polygon (N_SAMPLES vertices per side).

Masters (4 total)
-----------------
  default    (wght=100, CRVE=0,   VPOS=0)
  wght max   (wght=900, CRVE=0,   VPOS=0)
  CRVE max   (wght=100, CRVE=100, VPOS=0)
  VPOS max   (wght=100, CRVE=0,   VPOS=100)
"""

import math
import os
from typing import Callable
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.designspaceLib import DesignSpaceDocument, AxisDescriptor, SourceDescriptor
from fontTools import varLib

# ── constants ────────────────────────────────────────────────────────────────
UPM   = 2020                  # units per em; chosen to give good resolution for the curves and divisibity into 101 steps of the S-curve and vertical position axes
ADV   = UPM // 4              # advance width
SCALE = UPM // 101            # maps values 0-100 to font units 0-1000
PUA   = 0xE000                # Unicode Private Use Area start for glyph codepoints
WGHT_MIN, WGHT_MAX = 100, 900 # stroke weight axis range, maps to hs 30-260 font units
HS_MIN,   HS_MAX   =  30, 260 # half stroke width range in font units, derived from wght axis range and mapping function
CRVE_MAX           = 100      # maximum S-curve sharpness, maps to c=1 in shaped_smoothstep
VPOS_MAX           = 100      # maximum vertical position shift, maps to y-offset of 100·SCALE font units
ASC = 100 * SCALE + HS_MAX    # ascent for vertical metrics, includes max positive y-offset and stroke overshoot
DSC = -HS_MAX                 # descent for vertical metrics, includes max stroke overshoot

N_SAMPLES = 40   # polygon vertices per side of the parallel-curve outline

# ── glyph catalogue ──────────────────────────────────────────────────────────
GLYPHS = []

GLYPHS.append(("empty", 0, PUA + 0))        # E000  empty
GLYPHS.append(("asc",   0, PUA + 1))        # E001  flat (n=0)

for n in range(1, 101):                      # E002-E065  ascending S-curve
    GLYPHS.append(("asc",  n, 0xE001 + n))

for n in range(100, 0, -1):                  # E066-E0C9  descending S-curve
    GLYPHS.append(("desc", n, 0xE0CA - n))

# ── master axis configurations ───────────────────────────────────────────────
MASTER_CONFIGS = [
    (WGHT_MIN, 0,        0),        # 0  default
    (WGHT_MAX, 0,        0),        # 1  wght max
    (WGHT_MIN, CRVE_MAX, 0),        # 2  CRVE max
    (WGHT_MIN, 0,        VPOS_MAX), # 3  VPOS max
]


def smoothstep(t: float) -> float:
    """
    Cubic smoothstep: S(t) = 3t² − 2t³.
    S(0)=0, S(1)=1, S'(0)=S'(1)=0 (horizontal tangents at both ends).
    see https://en.wikipedia.org/wiki/Smoothstep

    :param float t: Parameter value ∈ [0, 1]
    :return: Smoothed interpolation value ∈ [0, 1]
    :rtype: float
    """
    return t * t * (3.0 - 2.0 * t)


def shaped_smoothstep(t: float, c: float) -> float:
    """
    Blend between S(t) and S(S(t)) via c ∈ [0,1].
    
    Both S and S∘S have zero first derivatives at t=0 and t=1:
      d/dt[S(S(t))] = S'(S(t))·S'(t)
      At t=0: S(0)=0, S'(0)=0  →  product = 0  ✓
      At t=1: S(1)=1, S'(1)=0  →  product = 0  ✓

    Linear blending preserves this, so f'(0,c) = f'(1,c) = 0 for all c.
    
    Midpoint slope of S = 1.5; of S∘S = S'(S(0.5))·S'(0.5) = 1.5·1.5 = 2.25.
    
    Blending interpolates the midpoint slope from 1.5 to 2.25, sharpening
    the S without introducing tangent discontinuities.

    :param float t: Parameter value ∈ [0, 1]
    :param float c: Blend factor ∈ [0, 1]; 0 = plain smoothstep, 1 = self-composed
    :return: Shaped interpolation value ∈ [0, 1]
    :rtype: float
    """
    s  = smoothstep(t)
    ss = smoothstep(s)
    return (1.0 - c) * s + c * ss


def calculate_parallel_curve_point(t: float, distance: float, curve_fn: Callable[[float], tuple[float, float]]) -> tuple[float, float]:
    """
    Calculate a point on the parallel curve at a signed distance from the centerline at parameter t.

    :param float t: Parameter value along the curve
    :param float distance: Signed perpendicular offset from the centerline (positive = left side, negative = right side)
    :param Callable curve_fn: Parametric curve function returning (x, y) for a given t
    :return: The (x, y) coordinates of the point on the parallel curve
    :rtype: tuple[float, float]
    """
    SMALL_STEP = 0.0001  # small step for numerical derivative approximation
    ref_x, ref_y = curve_fn(t)

    # Central difference for the derivative — two evaluations straddle t.
    prev_x, prev_y = curve_fn(t - SMALL_STEP)
    next_x, next_y = curve_fn(t + SMALL_STEP)
    x_prime = (next_x - prev_x) / (2 * SMALL_STEP)
    y_prime = (next_y - prev_y) / (2 * SMALL_STEP)

    # see https://en.wikipedia.org/wiki/Parallel_curve#Parallel_curve_of_a_parametrically_given_curve
    magnitude = math.sqrt(x_prime**2 + y_prime**2)
    x = ref_x + distance * y_prime / magnitude
    y = ref_y - distance * x_prime / magnitude

    return x, y


def wght_to_hs(wght: int) -> float:
    """
    Linearly map a wght axis value to a half-stroke width in font units.

    :param int wght: The wght axis value (WGHT_MIN-WGHT_MAX)
    :return: The half-stroke width in font units (HS_MIN-HS_MAX)
    :rtype: float
    """
    return HS_MIN + (wght - WGHT_MIN) / (WGHT_MAX - WGHT_MIN) * (HS_MAX - HS_MIN)


def draw_s_curve_outline(pen: TTGlyphPen, left_y: float, right_y: float, hs: float, crve: int):
    """
    Stroke the smoothstep S-curve centerline as a polygon parallel curve, drawing into ``pen``.
    Endpoints are forced to exact vertical offsets because S'(0) = S'(1) = 0.

    :param TTGlyphPen pen: The pen to draw into
    :param float left_y: Y coordinate of the left endpoint on the centerline
    :param float right_y: Y coordinate of the right endpoint on the centerline
    :param float hs: Half-stroke width in font units
    :param int crve: CRVE axis value controlling S-curve sharpness (0-CRVE_MAX)
    """
    c = crve / CRVE_MAX  # normalise CRVE to [0, 1] for shaped_smoothstep

    def curve_fn(t: float) -> tuple[float, float]:
        # x is linear in t so the curve spans [0, ADV] with no x-overshoot
        # on the centerline. y follows the shaped smoothstep.
        x = t * ADV
        y = left_y + (right_y - left_y) * shaped_smoothstep(t, c)
        return x, y

    top, bot = [], []

    for i in range(N_SAMPLES):
        t = i / (N_SAMPLES - 1)
        cx, cy = curve_fn(t)

        if i == 0 or i == N_SAMPLES - 1:
            # Tangent is horizontal at endpoints (S'(0)=S'(1)=0), so the
            # perpendicular is vertical — force a clean vertical offset.
            top.append((round(cx), round(cy + hs)))
            bot.append((round(cx), round(cy - hs)))
        else:
            for sign, lst in [(-1, top), (+1, bot)]:
                px, py = calculate_parallel_curve_point(t, sign * hs, curve_fn)
                if px < 0 or px > ADV:
                    # Inside edge overshoots x boundary at steep slopes. The
                    # correct y at the boundary matches the forced endpoint
                    # offset (boundary_cy ± hs), which is what the parallel
                    # curve converges to as t→0 or t→1.
                    bx = 0.0 if px < 0 else float(ADV)
                    boundary_cy = left_y if px < 0 else right_y
                    px, py = bx, boundary_cy - sign * hs
                lst.append((round(px), round(py)))

    pen.moveTo(top[0])
    for pt in top[1:]:
        pen.lineTo(pt)
    for pt in reversed(bot):
        pen.lineTo(pt)
    pen.closePath()


def draw_outline(pen: TTGlyphPen, kind: str, n: int, hs: float, crve: int, y_offset: int):
    """
    Draw the glyph outline for one master into ``pen``. Dispatches to a flat rectangle for n=0
    and to :func:`draw_s_curve_outline` for n>0; does nothing for the empty glyph.

    :param TTGlyphPen pen: The pen to draw into
    :param str kind: ``"empty"``, ``"asc"``, or ``"desc"``
    :param int n: Gap magnitude (0 = flat, 1-100 = ascending/descending S-curve)
    :param float hs: Half-stroke width in font units
    :param int crve: CRVE axis value controlling S-curve sharpness
    :param int y_offset: Vertical offset in font units derived from the VPOS axis
    """
    if kind == "empty":
        return

    base_kind = "asc" if kind == "asc" else "desc"
    left_y = float((n * SCALE if base_kind == "desc" else 0) + y_offset)
    right_y = float((n * SCALE if base_kind == "asc"  else 0) + y_offset)

    if n == 0:
        pen.moveTo((0,   left_y + hs))
        pen.lineTo((ADV, right_y + hs))
        pen.lineTo((ADV, right_y - hs))
        pen.lineTo((0,   left_y - hs))
        pen.closePath()
    else:
        draw_s_curve_outline(pen, left_y, right_y, hs, crve)


def make_master(wght: int, crve: int, vpos: int) -> object:
    """
    Build a complete font object for one design-space location (one master).

    :param int wght: The wght axis value for this master
    :param int crve: The CRVE axis value for this master
    :param int vpos: The VPOS axis value for this master
    :return: A fontTools TTFont object with all glyphs drawn at the given axis coordinates
    :rtype: object
    """
    hs       = wght_to_hs(wght)
    y_offset = vpos * SCALE

    glyph_order = [".notdef"] + [f"uni{cp:04X}" for _, _, cp in GLYPHS]

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(glyph_order)

    nd = TTGlyphPen(None)
    nd.moveTo((50, 0));    nd.lineTo((50, UPM))
    nd.lineTo((450, UPM)); nd.lineTo((450, 0))
    nd.closePath()
    glyphs = {".notdef": nd.glyph()}

    for kind, n, cp in GLYPHS:
        p = TTGlyphPen(None)
        draw_outline(p, kind, n, hs, crve, y_offset)
        glyphs[f"uni{cp:04X}"] = p.glyph()

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({g: (ADV, 0) for g in glyph_order})
    fb.setupCharacterMap({cp: f"uni{cp:04X}" for _, _, cp in GLYPHS})
    fb.setupHorizontalHeader(ascent=ASC, descent=DSC)
    fb.setupNameTable({"familyName": "LineFont", "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=ASC, sTypoDescender=DSC, sTypoLineGap=0,
        usWinAscent=ASC,   usWinDescent=abs(DSC),
        usWeightClass=wght,
        fsSelection=0x40,
    )
    fb.setupPost()
    fb.setupHead(unitsPerEm=UPM)
    return fb.font


def build_font(out_dir: str):
    """
    Assemble all masters into a variable font and save it to ``out_dir/LineFont-VF.ttf``.

    :param str out_dir: Directory where the .ttf file will be written (created if absent)
    """
    doc = DesignSpaceDocument()

    for tag, lo, hi in [
        ("wght", WGHT_MIN, WGHT_MAX),
        ("CRVE", 0,        CRVE_MAX),
        ("VPOS", 0,        VPOS_MAX),
    ]:
        ax         = AxisDescriptor()
        ax.tag     = tag
        ax.name    = tag
        ax.minimum = lo
        ax.default = lo
        ax.maximum = hi
        doc.addAxis(ax)

    for wght, crve, vpos in MASTER_CONFIGS:
        src            = SourceDescriptor()
        src.font       = make_master(wght, crve, vpos)
        src.location   = {"wght": wght, "CRVE": crve, "VPOS": vpos}
        src.familyName = "LineFont"
        src.styleName  = "Regular"
        doc.addSource(src)

    built    = varLib.build(doc)
    var_font = built[0] if isinstance(built, tuple) else built

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "LineFont-VF.ttf")
    var_font.save(path)
    print(f"  {path}")
    print(f"  {len(GLYPHS)} glyphs, {len(MASTER_CONFIGS)} masters, 3 axes (wght/CRVE/VPOS)")


def run_font_builder(out_dir: str):
    """
    Print progress messages and delegate to :func:`build_font`.

    :param str out_dir: Directory where the .ttf file will be written
    """
    print("Generating LineFont-VF…")
    build_font(out_dir)
    print("Done.")


if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    run_font_builder(out_dir)
