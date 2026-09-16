#!/usr/bin/env python3
"""
Gera o título "digitando" do README com degradê azul (escuro -> claro).

O readme-typing-svg só aceita uma cor, então este script cria um SVG próprio:
cada linha é digitada letra por letra, fica um tempo na tela e é apagada.
A fonte Fira Code vai embutida (só com as letras usadas), então aparece igual em qualquer sistema.

Uso:
  pip install fonttools brotli
  python .github/scripts/typing_svg.py FiraCode-SemiBold.ttf typing.svg

A fonte vem da release oficial: https://github.com/tonsky/FiraCode/releases
"""

import base64
import io
import sys
from xml.sax.saxutils import escape

LINES = [
    "Olá, eu sou o Matheus 👋",
    "Backend Developer | Python & Node.js",
    "Integrações + Migração de Dados",
    "> while(alive) { code(); }",
]

COLOR_DARK = "#0f4fd1"
COLOR_LIGHT = "#58b4ff"

W, H = 720, 50
FONT_SIZE = 28
TYPE = 0.075     # segundos por letra digitada
HOLD = 1.6       # tempo com a linha completa
DELETE = 0.03    # segundos por letra apagada
GAP = 0.35       # pausa entre linhas
EPS = 0.001
EMOJI_WIDTH = 1.25  # largura aproximada de um emoji, em em


def is_emoji(ch):
    return ord(ch) > 0x2FFF


def font_data(ttf_path):
    """Retorna (woff2 em base64 só com os caracteres usados, avanço do monoespaçado em em)."""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    full = TTFont(ttf_path)
    upm = full["head"].unitsPerEm
    advance = full["hmtx"]["zero"][0] / upm

    chars = {ch for line in LINES for ch in line if not is_emoji(ch)} | {"|"}
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = []
    options.name_IDs = []
    options.notdef_outline = False
    font = TTFont(ttf_path)
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(sorted(chars)))
    subsetter.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return base64.b64encode(buf.getvalue()).decode(), advance


def build(font_b64, advance):
    adv = advance * FONT_SIZE
    schedule = []
    t = 0.2
    for line in LINES:
        n = len(line)
        type_end = t + n * TYPE
        delete_start = type_end + HOLD
        schedule.append((line, t, delete_start))
        t = delete_start + n * DELETE + GAP
    total = t

    css, body, defs = [], [], []
    count = 0

    def anim(frames):
        nonlocal count
        count += 1
        name = f"a{count}"
        keys = "".join(f"{max(0, min(100, ft / total * 100)):.3f}%{{{prop}}}" for ft, prop in frames)
        css.append(f"@keyframes {name}{{{keys}}}.{name}{{animation:{name} {total:.3f}s linear infinite}}")
        return name

    def show(start, end):
        return anim([(0, "opacity:0"), (start, "opacity:0"), (start + EPS, "opacity:1"),
                     (end, "opacity:1"), (end + EPS, "opacity:0"), (total, "opacity:0")])

    baseline = H / 2 + FONT_SIZE * 0.36
    cursor = [(0, "transform:translateX(0px)")]

    for li, (line, start, delete_start) in enumerate(schedule):
        widths = [EMOJI_WIDTH * FONT_SIZE if is_emoji(ch) else adv for ch in line]
        line_w = sum(widths)
        x0 = (W - line_w) / 2
        defs.append(f'<linearGradient id="g{li}" gradientUnits="userSpaceOnUse" x1="{x0:.1f}" y1="0" x2="{x0 + line_w:.1f}" y2="0">'
                    f'<stop offset="0" stop-color="{COLOR_DARK}"/><stop offset="1" stop-color="{COLOR_LIGHT}"/></linearGradient>')
        n = len(line)
        x = x0
        cursor += [(max(start - EPS, 0), cursor[-1][1]), (start, f"transform:translateX({x0:.1f}px)")]
        for j, ch in enumerate(line):
            appear = start + j * TYPE
            vanish = delete_start + (n - 1 - j) * DELETE
            if ch != " ":
                cls = show(appear, vanish)
                fill = "" if is_emoji(ch) else f' fill="url(#g{li})"'
                body.append(f'<text class="{cls}" x="{x:.1f}" y="{baseline:.1f}"{fill}>{escape(ch)}</text>')
            x += widths[j]
            cursor += [(appear + TYPE - EPS, cursor[-1][1]), (appear + TYPE, f"transform:translateX({x:.1f}px)")]
        x_end = x
        for j in range(n):
            gone = delete_start + j * DELETE
            x_end -= widths[n - 1 - j]
            cursor += [(gone + DELETE - EPS, cursor[-1][1]), (gone + DELETE, f"transform:translateX({x_end:.1f}px)")]
    cursor.append((total, cursor[-1][1]))
    k_cursor = anim(cursor)

    font_css = (f"@font-face{{font-family:'FiraSVG';src:url(data:font/woff2;base64,{font_b64}) format('woff2');font-weight:600}}"
                if font_b64 else "")
    style = (font_css +
             f"text{{font-family:'FiraSVG','Fira Code',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
             f"font-size:{FONT_SIZE}px;font-weight:600}}"
             ".blink{animation:blink .9s steps(1) infinite}"
             "@keyframes blink{0%{opacity:1}50%{opacity:0}}" + "".join(css))
    cursor_rect = (f'<g class="{k_cursor}"><rect class="blink" x="2" y="{H / 2 - FONT_SIZE * 0.55:.1f}" width="3" '
                   f'height="{FONT_SIZE * 1.1:.1f}" fill="{COLOR_LIGHT}"/></g>')
    title = " / ".join(LINES)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
            f'aria-label="{escape(title)}"><title>{escape(title)}</title><style>{style}</style>'
            f'<defs>{"".join(defs)}</defs>{"".join(body)}{cursor_rect}</svg>')


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: python typing_svg.py FiraCode-SemiBold.ttf typing.svg")
    ttf, out = sys.argv[1], sys.argv[2]
    font_b64, advance = font_data(ttf)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(font_b64, advance))
    print(f"{out} gerado")


if __name__ == "__main__":
    main()
