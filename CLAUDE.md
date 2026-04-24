# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**cava-line** is a real-time audio spectrum visualizer that displays audio frequencies as smooth line graphs using a custom TrueType variable font rendered via Pango markup. It consists of two independent components:

1. **`cava_line.py`** — reads CSV output from the `cava` CLI, maps frequency deltas to glyph characters, and emits JSON-wrapped Pango `<span>` markup to stdout.
2. **`line-font/`** — a font generation pipeline (using `fontTools`) that produces the custom TrueType variable font the visualizer depends on.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fontTools
```

System dependency: `cava` must be installed and in `$PATH` to run the main app.

## Commands

### Run the visualizer
```bash
python cava_line.py [--font-weight=700] [--curve=270]
```

### Regenerate the font
```bash
./line-font/make_line_font.py   # builds LineFont-VF.ttf
```

Output goes to `line-font/fonts/LineFont-VF.ttf`.

### Build and install the font system-wide
```bash
./build.sh   # regenerates font, copies to ~/.local/share/fonts/, runs fc-cache -f
```

## Architecture

### Module layout

- **`cava_line.py`** — entry point; spawns two daemon threads and loops printing JSON widget output
- **`line_graph.py`** — pure functions for parsing cava output and generating Pango markup spans; no I/O
- **`cava_config`** — cava configuration: 40 bars, values 0–100, raw ASCII CSV (comma-delimited), 60 fps
- **`line-font/make_line_font.py`** — font generation; standalone, no dependency on the above
- **`build.sh`** — regenerates font and installs it to the system font cache

### Data flow
```
cava -p cava_config (subprocess) → CSV stdout
  → parse_cava_line(line) → list[int]
  → generate_line_graph(values, font_weight, curve) → Pango <span> strings
  → JSON to stdout (for use by a status bar / widget)
```

`playerctl -F metadata` runs in a parallel thread and provides the tooltip — three lines joined by `\r`: title, artist (in a small Pango `<span>`), and `position / length`.

### Cava crash recovery

`widget_text_thread` in `cava_line.py` restarts cava with exponential backoff (1s, 2s, 4s… up to 60s) when cava exits unexpectedly. The backoff resets to 1s on each successful line read. If the delay would exceed 60s, the whole process is killed via `os._exit(1)`.

### Variable font axes (`LineFont-VF.ttf`)

The font has three axes:

| Axis | Range | Purpose |
|------|-------|---------|
| `wght` | 100–900 | stroke width (HS_MIN=30 to HS_MAX=260 font units) |
| `CRVE` | 0–100 | S-curve sharpness; blends smoothstep with sharpened self-composition |
| `VPOS` | 0–100 | vertical position; shifts all glyph y-coords by `VPOS * SCALE` |

Four masters suffice (default, wght-max, CRVE-max, VPOS-max) because the three axes have additive, separable effects on coordinates.

### Font glyph layout (Unicode Private Use Area)

All glyphs live in the PUA starting at U+E000:

| Codepoint | Description |
|-----------|-------------|
| U+E000 | Empty |
| U+E001 | Horizontal (flat, n=0) |
| U+E002–U+E065 | Ascending S-curves (n=1–100) |
| U+E066–U+E0C9 | Descending S-curves (n=100–1) |

### Font constants (`make_line_font.py`)
- **UPM** = 2020, **ADV** = UPM // 4 = 505 (advance width)
- **SCALE** = UPM // 101 ≈ 20 — maps the 0–100 value range to glyph coordinate space
- Metrics are set statically to cover the full VPOS range (`ASC = 100*SCALE + HS_MAX`, `DSC = -HS_MAX`), so Pango never expands the line box regardless of VPOS value

### Key design decisions
- **Smoothstep S-curve**: the centerline uses a shaped smoothstep `f(t, c) = (1−c)·S(t) + c·S(S(t))` where `S(t) = 3t²−2t³`. Blending S with its self-composition sharpens the midpoint slope (1.5 → 2.25) as CRVE increases, without introducing tangent discontinuities.
- **Polygon parallel curve**: the glyph outline is the parallel curve of the centerline at distance ±hs, approximated as a polygon with `N_SAMPLES=40` vertices per side, drawn with `lineTo` (no native bezier curves in the font file).
- **Seamless tiling**: both S(t) and S(S(t)) have zero first derivatives at t=0 and t=1, so perpendiculars at the endpoints are forced vertical — adjacent glyph endpoints match exactly regardless of CRVE.
- **VPOS axis**: replaces the old Pango `rise` attribute, which caused line-box expansion at peak audio levels (past ~75), producing a visible downward shift of the graph. Vertical position is now baked into glyph coordinates.
- **Mathematical model**: slope `m` is encoded in the codepoint; offset `b` is handled via VPOS. `cava_line.py` sets `VPOS = min(value_from, value_to)` — the lower endpoint.

## Good-to-know gotchas
- `cava_config` sets `bars = 40` and `ascii_max_range = 100`. The font's VPOS axis and glyph codepoint range are designed for bar values 0–100; changing `ascii_max_range` would break the mapping.
