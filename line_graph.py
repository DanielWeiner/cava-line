
from typing import Generator
from numbers import Number


LINE_CHAR_FLAT                       = 0xE001
LINE_ASCENDING_S_CURVE_BLOCK_START   = 0xE002  # gap=1 → E002, gap=100 → E065
LINE_DESCENDING_S_CURVE_BLOCK_END    = 0xE0C9  # gap=-1 → E0C9, gap=-100 → E066

FONT_FAMILY  = "LineFont"


def sign(x: Number):
    """
    Return the sign of a number: -1 for negative, 0 for zero, and 1 for positive.

    :param Number x: The number whose sign is being evaluated
    :return: The sign of the number
    :rtype: int
    """
    return (x > 0) - (x < 0)


def calculate_vpos(value_from: int, value_to: int) -> int:
    """
    Calculate the vertical displacement of the drawn glyph. This drives the VPOS axis of the variable font. Will always evaluate to the
    lower terminal of the character.

    :param int value_from: The height of the left end of the glyph
    :param int value_to: The height of the right end of the glyph
    :return: The vertical displacement, i.e. VPOS axis, of the glyph
    :rtype: int
    """
    return min(value_from, value_to)


def calculate_slope_character(value_from: int, value_to: int) -> str:
    """
    Calculate the Unicode character that represents the slope from :param:`value_from` to :param:`value_to`.
    
    :param int value_from: The height of the left end of the glyph 
    :param int value_to: The height of the right end of the glyph
    :return: The character whose slope matches the input values
    :rtype: int
    """

    gap = value_to - value_from
    match sign(gap):
        case 0:
            base = LINE_CHAR_FLAT
        # since these character blocks start at gap=1 and gap=-1, 
        # we need to subtract/add 1 to get the correct character for the given gap
        case 1:
            base = LINE_ASCENDING_S_CURVE_BLOCK_START - 1 # gap=1 yields E002
        case -1:
            base = LINE_DESCENDING_S_CURVE_BLOCK_END + 1 # gap=-1 yields E0C9
    return chr(base + gap)


def parse_cava_line(line: str) -> list[int]:
    """
    Process a line from cava of the form `a1,a2,a3,...an,`. This is specified in the cava config for this widget, located at
    'cava_config' in the root of the project. Values range from 0 to 100 as percentages of the total height of the graph.

    :param str line: A line of cava output representing the heights of the bars in the graph
    :return: A list of integers representing the heights of the bars in the graph
    :rtype: list[int]
    """
    return [int(x) for x in line.split(',')[0:-1]] # the last element is empty due to trailing comma in cava output


def generate_line_graph(values: list[int], font_weight: int, curve: int) -> Generator[str, None, None]:
    """
    Generate a line graph as a sequence of Pango markup strings, given a list of values representing the heights of the bars in the graph. 
    Each character represents a transition from one value of the graph to the next, producing a continuous line.

    :param list[int] values: A list of integers representing the heights of the bars in the graph
    :param int font_weight: The weight axis of the variable font, controlling the thickness of the line (100-900)
    :param int curve: The curve axis of the variable font, controlling the curvature strength of the line (0-100)
    :return: A generator yielding Pango markup strings that, when concatenated, produce the line graph
    :rtype: Generator[str, None, None]
    """
    
    for i in range(len(values) - 1):
        vpos = calculate_vpos(values[i], values[i + 1])
        char = calculate_slope_character(values[i], values[i + 1])
        yield f'<span font="{FONT_FAMILY} @wght={font_weight},CRVE={curve},VPOS={vpos}">{char}</span>'
