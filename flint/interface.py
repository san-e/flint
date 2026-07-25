"""
Copyright (C) 2016, 2017, 2020 biqqles.

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Interface-related functions, such as routines for translating RDL.
"""

import xml.etree.ElementTree as xml
from . import paths, cached
from .formats import ini
import re


def strip_html(text):
    """Remove HTML tags from a string"""
    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)


def rdl_to_html(rdl: str) -> str:
    """Translate RDL to HTML. Does not implement fonts. Heavily based on the Librelancer implementation:
    https://github.com/Librelancer/Librelancer/blob/main/src/LibreLancer/Infocards/RDLParse.cs"""
    def get_color(color: str) -> int:
        """Returns the little-endian RGB integer for the given RDL color"""
        color = color.strip()
        if color in RDL_NAMED_COLORS:
            return RDL_NAMED_COLORS.get(color)
        if color.startswith("0x"):
            return int(color, 16)
        if color.startswith('#'):
            if len(color) == 4:
                # turns a string of the form #rgb into #rrggbb
                r = int(color[1], 16)
                g = int(color[2], 16)
                b = int(color[3], 16)
                r = ((r << 4) | r)
                g = ((g << 4) | g)
                b = ((b << 4) | b)
                return (b << 24) | (g << 16) | (r << 8)
            elif len(color) == 7:
                # expects #rrggbb
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                return (b << 24) | (g << 16) | (r << 8)
            raise ValueError("Invalid color: " + color)
        return int(color)

    def parse_text_render_attribute(attrib: dict[str, str]) -> dict[str, str | bool]:
        """Parses RDL tag attributes."""
        attrib = {x.upper(): y for x, y in attrib.items()}
        _data = 0
        _mask = 0
        _def = 0

        if "DATA" in attrib:
            _data = int(attrib["DATA"], 16)
        if "MASK" in attrib:
            _mask = int(attrib["MASK"], 16)
        if "DEF" in attrib:
            _def = int(attrib["DEF"], 16)
        if "COLOR" in attrib:
            _mask |= RDL_TRA_COLOR
            if attrib["COLOR"].lower() == "default":
                _def |= RDL_TRA_COLOR
            else:
                _data &= ~RDL_TRA_COLOR
                _data |= get_color(attrib["COLOR"])
        if "FONT" in attrib:
            _mask |= RDL_TRA_FONT
            if attrib["FONT"].lower() == "default":
                _def |= RDL_TRA_FONT
            else:
                _data &= ~RDL_TRA_FONT
                _data |= int(attrib["FONT"]) << 3

        for attribute, flag in [("BOLD", RDL_TRA_BOLD), ("ITALIC", RDL_TRA_ITALIC), ("UNDERLINE", RDL_TRA_UNDERLINE)]:
            if attribute in attrib:
                _mask |= flag
                if attrib[attribute].lower() == "default":
                    _def |= flag
                elif attrib[attribute].lower() == "true":
                    _data |= flag
                else:
                    _data &= ~RDL_TRA_BOLD

        html_attributes = {
            "bold": False,
            "italic": False,
            "underline": False,
            "color": "",
            "font": {"name": "", "size": 0},
        }

        if (_def & RDL_TRA_BOLD) != 0:
            html_attributes["bold"] = False
        elif (_mask & RDL_TRA_BOLD) != 0:
            html_attributes["bold"] = (_data & RDL_TRA_BOLD) != 0

        if (_def & RDL_TRA_ITALIC) != 0:
            html_attributes["italic"] = False
        elif (_mask & RDL_TRA_ITALIC) != 0:
            html_attributes["italic"] = (_data & RDL_TRA_ITALIC) != 0

        if (_def & RDL_TRA_UNDERLINE) != 0:
            html_attributes["underline"] = False
        elif (_mask & RDL_TRA_UNDERLINE) != 0:
            html_attributes["underline"] = (_data & RDL_TRA_UNDERLINE) != 0

        if (_def & RDL_TRA_COLOR) != 0:
            html_attributes["color"] = "";
        elif (_mask & RDL_TRA_COLOR) != 0:
            bytes = (_data & RDL_TRA_COLOR).to_bytes(4, byteorder="little")
            html_attributes["color"] = f"#{bytes[1]:02x}{bytes[2]:02x}{bytes[3]:02x}"

        return html_attributes

    def remove_element(el: xml.Element, parent_map: dict[xml.Element, xml.Element]) -> None:
        """Removes an element from the tree while preserving its contents"""
        parent = parent_map.get(el)
        if parent is None:
            return # dont delete the root element
        idx = list(parent).index(el)
        text_target_idx = idx - 1
        for child in el:
            parent.insert(idx, child)
            idx += 1
        parent.remove(el)

        if el.text:
            target = parent if text_target_idx == -1 else parent[text_target_idx]
            if target.text:
                target.text += el.text
            else:
                target.text = el.text

    if not rdl:
        return rdl

    try:
        root = xml.fromstring(rdl)
    except xml.ParseError:
        return rdl

    root.tag = "div"

    style_state = {"color": "", "bold": False, "italic": False, "underline": False}
    current_elements = []

    remove_list = []
    for node in list(root.iter()):
        if node == root:
            continue
        if node.tag.lower() in RDL_IGNORED_TAGS:
            remove_list.append(node)
            continue

        attributes = parse_text_render_attribute(node.attrib)
        attrib_copy = node.attrib.copy()
        node.attrib = {}
        if node.tag.lower() == "tra":
            style_state = attributes
            remove_list.append(node)
            continue

        if node.tag.lower() == "para":
            node.tag = "p"
        if node.tag.lower() == "just":
            node.tag = "p"
            node.attrib["align"] = attrib_copy.get("loc", "left")
        if node.tag.lower() == "text":
            node.tag = "span"
            style_parts = []
            if attributes["color"]:
                style_parts.append(f"color: {attributes['color']};")
            elif style_state["color"]:
                style_parts.append(f"color: {style_state['color']};")
            if attributes["bold"] or style_state["bold"]:
                style_parts.append("font-weight: bold;")
            if attributes["italic"] or style_state["italic"]:
                style_parts.append("font-style: italic;")
            if attributes["underline"] or style_state["underline"]:
                style_parts.append("text-decoration: underline;")
            node.attrib["style"] = " ".join(style_parts)

            if not node.attrib.get("style"):
                remove_list.append(node)

    # since XML elements don't have a parent pointer we need to construct this map first
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for node in remove_list:
        remove_element(node, parent_map)

    return xml.tostring(root, encoding="unicode")



def rdl_to_plaintext(rdl: str) -> str:
    """Translate RDL to plaintext, stripping all tags and replacing <PARA/> with a newline."""
    return strip_html(rdl_to_html(rdl).replace("<p>", "\n")).replace("&nbsp;", "")
    rdl = rdl.replace("<PARA/>", "\n").replace("</PARA>", "")
    tree = xml.fromstring(rdl)
    return xml.tostring(tree, encoding="unicode", method="text")


def html_to_rdl(html: str) -> str:
    """Translate HTML to RDL. See the docstring for `rdl_to_html` for more information."""
    result = html
    for rdl_tag, html_tag in RDL_TO_HTML.items():
        result = result.replace(html_tag, rdl_tag)
    return result


@cached
def get_infocardmap() -> dict:
    """Return a dict of each ID in infocardmap.ini mapped to the other ID idk"""
    return {
        id0: id1
        for id0, id1 in ini.parse(
            paths.construct_path("DATA/INTERFACE/infocardmap.ini")
        )[0][1]["map"]
    }


@cached
def get_constants() -> dict:
    path = paths.inis["constants"]
    return dict(ini.parse(path))

RDL_NAMED_COLORS = {
    "fuchsia": 0xC2008800,
    "gray": 0x80808000,
    "blue": 0xE0484800,
    "green": 0x13BF3B00,
    "aqua": 0xE0C38700,
    "red": 0x1D1DBF00,
    "yellow": 0x52EAF500,
    "white": 0xFFFFFF00
}
RDL_IGNORED_TAGS = {
    "rdl", "push", "pop"
}
RDL_TRA_BOLD = 0x01
RDL_TRA_ITALIC = 0x02
RDL_TRA_UNDERLINE = 0x04
RDL_TRA_FONT = 0xF8
RDL_TRA_COLOR = 0xFFFFFF00

# A lookup table mapping RDL (Render Display List) tags to HTML(4). Freelancer, to my eternal horror, uses these for
# formatting for strings inside these resource DLLs. Based on work by adoxa and cshake.
# More information can be found in this thread: <https://the-starport.net/modules/newbb/viewtopic.php?&topic_id=562>
RDL_TO_HTML = {
    '<TRA data="1" mask="1" def="-2"/>': "<b>",  # bold
    '<TRA bold="true"/>': "<b>",  # rare bold
    '<TRA data="0" mask="1" def="-1"/>': "</b>",  # un-bold
    '<TRA data="0x00000001" mask="-1" def="-2"/>': "<b>",  # bold
    '<TRA data="0x00000000" mask="-1" def="-1"/>': "</b>",  # un-bold
    '<TRA bold="default"/>': "</b>",  # un-bold
    '<TRA data="2" mask="3" def="-3"/>': "<i>",  # italic 1
    '<TRA data="0" mask="3" def="-1"/>': "</i>",  # un-italic 1
    '<TRA data="98" mask="-29" def="-3"/>': "<i>",  # italic 2
    '<TRA data="96" mask="-29" def="-1"/>': "</i>",  # un-italic 2
    '<TRA data="2" mask="2" def="-3"/>': "<i>",  # italic 3
    '<TRA data="0" mask="2" def="-1"/>': "</i>",  # un-italic 3
    '<TRA data="5" mask="5" def="-6"/>': "<b><u>",  # (bold, underline) 1
    '<TRA data="0" mask="5" def="-1"/>': "</b></u>",  # un-(bold, underline) 1
    '<TRA data="5" mask="7" def="-6"/>': "<b><u>",  # (bold, underline) 2
    '<TRA data="0" mask="7" def="-1"/>': "</b></u>",  # un-(bold, underline) 2
    '<TRA color="default" bold="default"/>': "</font></b>",  # un-color, un-bold
    '<TRA data="65280" mask="-32" def="31"/>': '<font color="red">',  # red
    '<TRA color="#ff0000" bold="true"/>': '<font color="red"><b>',  # red, bold
    '<TRA data="96" mask="-32" def="-1"/>': "</font>",  # un-colour
    '<TRA color="default"/>': "</font>",  # un-color
    '<TRA data="65281" mask="-31" def="30"/>': '<b><font color="red">',  # (bold, red)
    '<TRA data="96" mask="-31" def="-1"/>': "</b></font>",  # un-(bold, red)
    '<TRA data="-16777216" mask="-32" def="31"/>': '<font color="blue">',  # blue
    '<TRA color="white" bold="default"/>': '</b><font color="white>',  # unbold, white
    "<PARA/>": "<p>",  # newline
    "</PARA>": "</p>",
    '<JUST loc="left"/>': '<p align="left">',  # newline with left-aligned text
    '<JUST loc="center"/>': '<p align="center">',  # newline with centred text
    "\xa0": "&nbsp;",  # non-breaking space, is often present after the title
    "<RDL>": "",  # seemingly meaningless tags...
    "</RDL>": "",
    "<TEXT>": "",
    "</TEXT>": "",
    "<PUSH/>": "",
    "<POP/>": "",
    '<?xml version="1.0" encoding="UTF-16"?>': "",  # xml header; removed for neatness
}
