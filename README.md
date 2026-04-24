# cava-line

A real-time audio spectrum visualizer for [Waybar](https://github.com/Alexays/Waybar), rendered as a smooth line graph using a custom variable font.

Example:

![example](example.png)

## How it works

`cava_line.py` reads frequency data from [cava](https://github.com/karlstav/cava) and maps each pair of adjacent bars to a Unicode character from a custom variable font (`LineFont-VF.ttf`). The font encodes slope as a glyph (ascending S-curve, descending S-curve, or flat) and exposes three axes — stroke weight, curve sharpness, and vertical position — so the full line shape can be expressed purely through Pango `<span>` markup with no image rendering.

## Dependencies

- Python 3.10+
- [`cava`](https://github.com/karlstav/cava) — must be installed and in `$PATH`
- [`playerctl`](https://github.com/altdesktop/playerctl) — for the tooltip (track title / artist / position)
- `fonttools` — only needed to regenerate the font (see below)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/DanielWeiner/cava-line.git
```

### 2. Install the font

The pre-built font is at `line-font/fonts/LineFont-VF.ttf`. Copy it to your local font directory and refresh the cache:

```bash
cp line-font/fonts/LineFont-VF.ttf ~/.local/share/fonts/
fc-cache -f
```

### 3. Add to Waybar

In your Waybar config:

```json
"custom/cava": {
    "return-type": "json",
    "exec": "<path-to-cava-line>/cava_line.py --font-weight=600 --curve=25"
}
```

Add it to your `modules-left`, `modules-center`, or `modules-right` as desired. The widget emits JSON continuously, so no `interval` is needed.

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--font-weight=N` | 600 | Stroke thickness; maps to the font's `wght` axis (100–900) |
| `--curve=N` | 25 | S-curve sharpness; maps to the font's `CRVE` axis (0–100) |

### 4. Style in CSS

The widget has class `custom-cava-widget`. Font size and color can be modified via CSS,
but weight and font family are controlled by the widget.

```css
#custom-cava-widget {
    font-size: 18px;
}
```

## Regenerating the font

If you modify `line-font/make_line_font.py`, rebuild the font with:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./line-font/make_line_font.py
```

The updated font is written to `line-font/fonts/LineFont-VF.ttf`. Re-run the `fc-cache` step from above to install it.
