#!/usr/bin/env python3
import json
import subprocess
import sys
import threading
import os
import time

from line_graph import generate_line_graph, parse_cava_line

CAVA_CONFIG  = f"{os.path.dirname(__file__)}/cava_config"
FONT_WEIGHT  = 600
CURVE        = 25

# see https://github.com/altdesktop/playerctl#printing-properties-and-metadata
PLAYERCTL_FORMAT = ('{'
    '"title":"{{markup_escape(title)}}",'
    '"artist":"{{markup_escape(artist)}}",'
    '"album":"{{markup_escape(album)}}",'
    '"playerName":"{{markup_escape(playerName)}}",'
    '"status":"{{status}}",'
    '"position":"{{duration(position)}}",'
    '"length":"{{duration(mpris:length)}}",'
    '"artUrl":"{{mpris:artUrl}}",'
    '"url":"{{xesam:url}}"'
'}')


text = None # current widget text, protected by dirty_condition
tooltip = None # current widget tooltip, protected by dirty_condition
dirty_condition = threading.Condition() # signaled when text or tooltip is updated


def widget_text_thread(font_weight: int, curve: int):
    """
    Read cava's CSV output in a loop, convert each frame to Pango markup, and update the shared
    ``text`` global. Restarts cava with exponential backoff (doubling from 1s up to 60s) if cava
    exits unexpectedly; kills the process via ``os._exit(1)`` if the backoff would exceed the max.

    :param int font_weight: The wght axis value passed through to the variable font
    :param int curve: The CRVE axis value passed through to the variable font
    """
    global text

    delay = 1
    max_delay = 60

    while True:
        cava_process = subprocess.Popen(['cava', '-p', CAVA_CONFIG ], stdout=subprocess.PIPE, text=True)
        for line in cava_process.stdout:
            if not line.strip():
                continue
            delay = 1  # reset backoff on successful read
            values = parse_cava_line(line)
            line_output = ''.join(generate_line_graph(values, font_weight, curve))
            with dirty_condition:
                text = line_output
                dirty_condition.notify()

        cava_process.wait() # cava will break upon startup, which is why there's a retry

        if delay > max_delay:
            os._exit(1)

        print(f"cava exited unexpectedly, retrying in {delay}s", file=sys.stderr, flush=True)
        print(CAVA_CONFIG)
        time.sleep(delay)
        delay = min(delay * 2, max_delay)


def widget_tooltip_thread():
    """
    Follow ``playerctl`` metadata in a loop and update the shared ``tooltip`` global. The tooltip
    is a ``\\r``-joined string of title, artist (in a small Pango span), and playback position
    while a track is playing, or ``None`` when nothing is playing.
    """
    global tooltip
    playerctl_process = subprocess.Popen(['playerctl', '-F', '--format', PLAYERCTL_FORMAT, 'metadata'], stdout=subprocess.PIPE, text=True)
    while (line := playerctl_process.stdout.readline()):
        if not line.strip():
            continue
        playerctl_data = json.loads(line)
        with dirty_condition:
            tooltip = "\r".join([
                f'{playerctl_data["title"]}',
                f'<span size="small">{playerctl_data["artist"]}</span>',
                f'{playerctl_data["position"]} / {playerctl_data["length"]}'
            ]) if playerctl_data["status"] == "Playing" else None

            dirty_condition.notify()


def read_argv_params():
    """
    Parse ``--font-weight=`` and ``--curve=`` from ``sys.argv``, falling back to the module-level
    defaults if not supplied.

    :return: Tuple of (font_weight, curve)
    :rtype: tuple[int, int]
    """
    font_weight = FONT_WEIGHT
    curve       = CURVE
    for arg in sys.argv[1:]:
        if arg.startswith('--font-weight='):
            font_weight = int(arg.split('=')[1])
        elif arg.startswith('--curve='):
            curve = int(arg.split('=')[1])
    return font_weight, curve


def build_widget():
    """
    Serialize the current ``text`` and ``tooltip`` globals as a Waybar-compatible JSON object.

    :return: JSON string with ``text``, ``tooltip``, and ``class`` keys
    :rtype: str
    """
    return json.dumps({
        "text": text,
        "tooltip": tooltip,
        "class": "custom-cava-widget"
    })


def main():
    """
    Launch the widget text and tooltip daemon threads, then block on ``dirty_condition``, printing
    updated widget JSON to stdout on every change.
    """
    font_weight, curve = read_argv_params()
    threading.Thread(target=widget_text_thread, args=(font_weight, curve), daemon=True).start()
    threading.Thread(target=widget_tooltip_thread, daemon=True).start()
    
    while True:
        with dirty_condition:
            dirty_condition.wait()
            print(build_widget(), flush=True)

if __name__ == '__main__':
    main()
