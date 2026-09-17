#!/usr/bin/env python3
"""
Boss battle gerada a partir dos commits do GitHub, com o mundo do jogo em pixel art 32-bit e HUD inspirado em Persona 3 Reload
(azul profundo e ciano, lua cheia, cena submersa, tipografia itálica com rastro e vidro estilhaçado)
e elementos inspirados em Bleach (máscara de osso, fenda no céu, aura espiritual,
golpes em lua crescente, borboletas pretas e um cero oscuras no golpe crítico).

O cenário, o boss, o herói e os efeitos são sprites desenhados em baixa resolução (1 pixel = 3 px),
com rampas de cor, dithering e contorno, embutidos como PNG. HUD, menus, faixas e números são vetoriais.

- HP do boss = commits dos últimos 12 meses
- Cada turno é um mês: o dano é a quantidade de commits daquele mês
- A lua do HUD vai enchendo a cada turno e fica cheia na vitória
- O golpe muda conforme o mês foi fraco ou forte; o melhor mês vira crítico: o herói carrega e dispara
  um cero oscuras (feixe preto com borda azul clara)

Uso:
  GH_TOKEN=... GH_USER=Fervalinhos python boss_battle.py dist/boss-battle.svg
  python boss_battle.py preview.svg --mock      (dados de exemplo, sem API)

Sem dependências externas: só a biblioteca padrão do Python.
"""

import base64
import json
import math
import os
import random
import struct
import sys
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

# Tempo (segundos)
INTRO = 2.2
TURN = 1.5
VICTORY = 4.8
EPS = 0.02
SP_FULL = 0.30  # fração do turno em que a barra SP enche
THROW = 0.38    # fração do turno em que o golpe sai
HIT = 0.58      # fração do turno em que o golpe acerta

W, H = 840, 400
BOSS_NAME = "BUG LORD"

# Golpes: índice = nível do mês
ATTACKS = ["GIT STATUS", "GIT COMMIT", "GIT PUSH", "GIT MERGE", "GIT PUSH --FORCE"]
MENU = ["STATUS", "COMMIT", "PUSH", "MERGE", "FORCE"]

# Paleta
INK = "#020a1f"      # noite funda
NAVY = "#06205e"
BLUE = "#1150d8"
CYAN = "#2fd4ff"
ICE = "#bff3ff"
WHITE = "#ffffff"
RED = "#ff2447"      # olhos do boss
RED_DARK = "#7a0018"
BONE = "#f1ede2"

CERO_NAME = "CERO OSCURAS"

# Fontes do sistema (SVG em <img> não carrega fontes externas)
DISPLAY = "Impact,Haettenschweiler,'Franklin Gothic Heavy','Arial Narrow Bold','Arial Narrow','DejaVu Sans Condensed',sans-serif"
UI = "'Segoe UI','Helvetica Neue',Arial,'DejaVu Sans',sans-serif"

# Posições principais
BOSS_X, BOSS_Y, BOSS_S = 290, 172, 0.9
MOON_X, MOON_Y, MOON_R = 300, 140, 112
HERO_SPAWN = (520, 214)
ORB_X, ORB_Y = 500, 196
POP_X, POP_Y = 408, 104


# --------------------------------------------------------------------------- dados

def month_ranges(n=12, now=None):
    now = now or datetime.now(timezone.utc)
    out = []
    for i in range(n - 1, -1, -1):
        yy, mm = now.year, now.month - i
        while mm <= 0:
            mm += 12
            yy -= 1
        start = datetime(yy, mm, 1, tzinfo=timezone.utc)
        ny, nm = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
        end = datetime(ny, nm, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        out.append((yy, mm, start, min(end, now)))
    return out


def longest_streak(days):
    best = cur = 0
    for count in days:
        cur = cur + 1 if count > 0 else 0
        best = max(best, cur)
    return best


def fetch(user, token):
    ranges = month_ranges()
    fields = []
    for i, (_, _, start, end) in enumerate(ranges):
        fields.append(
            f'm{i}: contributionsCollection(from: "{start.isoformat()}", to: "{end.isoformat()}") '
            "{ totalCommitContributions }"
        )
    fields.append(
        "cal: contributionsCollection { contributionCalendar "
        "{ weeks { contributionDays { contributionCount } } } }"
    )
    query = "query($login: String!) { user(login: $login) { " + " ".join(fields) + " } }"
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": {"login": user}}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "boss-battle-readme",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if data.get("errors"):
        raise SystemExit(f"Erro na API do GitHub: {data['errors']}")
    u = data["data"]["user"]
    months = [
        (f"{MESES[mm - 1]}/{str(yy)[2:]}", u[f"m{i}"]["totalCommitContributions"])
        for i, (yy, mm, _, _) in enumerate(ranges)
    ]
    days = [d["contributionCount"] for w in u["cal"]["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    return months, longest_streak(days)


def mock():
    values = [0, 6, 14, 3, 22, 9, 31, 47, 40, 58, 36, 12]
    months = [(f"{MESES[mm - 1]}/{str(yy)[2:]}", values[i]) for i, (yy, mm, _, _) in enumerate(month_ranges())]
    return months, 5


# --------------------------------------------------------------------------- animação

class Anim:
    """Gera @keyframes com tempos absolutos dentro de um ciclo único."""

    def __init__(self, total):
        self.total = total
        self.css = []
        self.count = 0

    def add(self, frames, extra=""):
        self.count += 1
        name = f"k{self.count}"
        frames = sorted(frames, key=lambda f: f[0])
        if frames[0][0] > 0:
            frames.insert(0, (0, frames[0][1]))
        if frames[-1][0] < self.total:
            frames.append((self.total, frames[-1][1]))
        body = "".join(f"{max(0.0, min(100.0, t / self.total * 100)):.3f}%{{{p}}}" for t, p in frames)
        self.css.append(f"@keyframes {name}{{{body}}}")
        self.css.append(f".{name}{{animation:{name} {self.total:.2f}s linear infinite;{extra}}}")
        return name

    def show(self, start, end):
        """Visível entre start e end, invisível no resto do ciclo."""
        on, off = "opacity:1", "opacity:0"
        frames = [(0, on)] if start <= 0 else [(0, off), (start, off), (start + EPS, on)]
        frames += [(self.total, on)] if end >= self.total else [(end, on), (end + EPS, off), (self.total, off)]
        return self.add(frames)


# --------------------------------------------------------------------------- peças visuais

def pts(points):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def echo_text(text, fs, y=0, fill=WHITE, echo=INK, gap=None, cls="fd it"):
    """Texto itálico com dois rastros deslocados atrás, centralizado em x=0."""
    gap = gap if gap is not None else fs * 0.22
    t = escape(text)
    return (f'<text class="{cls}" x="{-gap * 2:.1f}" y="{y}" font-size="{fs}" fill="{echo}" fill-opacity=".18" text-anchor="middle">{t}</text>'
            f'<text class="{cls}" x="{-gap:.1f}" y="{y}" font-size="{fs}" fill="{echo}" fill-opacity=".4" text-anchor="middle">{t}</text>'
            f'<text class="{cls} outl" x="0" y="{y}" font-size="{fs}" fill="{fill}" text-anchor="middle">{t}</text>')


def band(h=84, grad="bandGrad", accent=CYAN):
    """Faixa diagonal de vidro com filetes, centralizada em (0, 0)."""
    top, bot = -h / 2, h / 2
    return (f'<polygon points="{pts([(-780, top), (780, top - 12), (780, bot - 12), (-780, bot)])}" fill="url(#{grad})"/>'
            f'<polygon points="{pts([(-780, top), (780, top - 12), (780, top - 1), (-780, top + 11)])}" fill="{WHITE}" fill-opacity=".25"/>'
            f'<polygon points="{pts([(-780, top - 7), (780, top - 19), (780, top - 16), (-780, top - 4)])}" fill="{WHITE}"/>'
            f'<polygon points="{pts([(-780, bot + 4), (780, bot - 8), (780, bot - 5), (-780, bot + 7)])}" fill="{accent}"/>')


def spikes(r, n, seed, colors, r0=0.18):
    """Estilhaços de vidro saindo do centro."""
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        a = 2 * math.pi * k / n + rnd.uniform(-.2, .2)
        d = rnd.uniform(.12, .22)
        tip = r * rnd.uniform(.7, 1.12)
        base = r * r0
        p = [(math.cos(a - d) * base, math.sin(a - d) * base), (math.cos(a) * tip, math.sin(a) * tip),
             (math.cos(a + d) * base, math.sin(a + d) * base)]
        out.append(f'<polygon points="{pts(p)}" fill="{colors[k % len(colors)]}"/>')
    return "".join(out)


def star4(x, y, r):
    q = r * 0.28
    return f"M{x} {y - r}L{x + q} {y - q}L{x + r} {y}L{x + q} {y + q}L{x} {y + r}L{x - q} {y + q}L{x - r} {y}L{x - q} {y - q}Z"


def moon_phase(cx, cy, r, phase):
    """Ícone de fase da lua: 0 = nova, 0.5 = quarto crescente, 1 = cheia."""
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{NAVY}" stroke="{ICE}" stroke-width="2"/>']
    if phase >= 0.99:
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r - 1}" fill="{ICE}"/>')
    elif phase > 0.01:
        rx = abs(1 - 2 * phase) * (r - 1)
        sweep = 0 if phase < 0.5 else 1
        out.append(f'<path d="M{cx} {cy - r + 1}A{r - 1} {r - 1} 0 0 1 {cx} {cy + r - 1}'
                   f'A{rx:.1f} {r - 1} 0 0 {sweep} {cx} {cy - r + 1}Z" fill="{ICE}"/>')
    return "".join(out)


# Boss: inseto escuro com contorno branco e brilho ciano. Coordenadas centradas em (0, 0).
BOSS_LEGS = [
    [(-40, -8), (-96, -44), (-122, 8)],
    [(-46, 14), (-110, 6), (-128, 62)],
    [(-36, 36), (-86, 58), (-104, 98)],
]
BOSS_ANTENNAE = [[(-16, -60), (-40, -98), (-72, -110)]]
BOSS_ABDOMEN = [(0, -30), (52, -18), (72, 20), (60, 64), (28, 92), (0, 100), (-28, 92), (-60, 64), (-72, 20), (-52, -18)]
BOSS_HEAD = [(-40, -30), (-32, -58), (0, -70), (32, -58), (40, -30), (0, -16)]
BOSS_CROWN = [(-26, -62), (-32, -96), (-14, -76), (0, -104), (14, -76), (32, -96), (26, -62)]
BOSS_MASK = [(-44, -30), (-38, -64), (0, -80), (38, -64), (44, -30), (28, -8), (0, -2), (-28, -8)]
BOSS_HOLE = (0, 34, 17)
SHARDS = 6


def mirror(points):
    return [(-x, y) for x, y in points]


HERO_BODY = [(474, 400), (484, 350), (500, 322), (530, 306), (560, 302), (590, 306), (620, 322), (636, 350), (646, 400)]
HERO_HEAD = [(522, 276), (516, 250), (524, 228), (514, 214), (536, 212), (542, 194), (556, 206), (570, 190),
             (578, 208), (598, 200), (594, 222), (606, 232), (602, 256), (596, 278), (560, 292), (524, 290)]
HERO_HOOD = [(518, 310), (540, 290), (580, 290), (602, 310), (586, 330), (560, 338), (534, 330)]


AURA_BASES = [(480, 372, -14), (486, 346, -18), (500, 322, -12), (520, 308, -6), (514, 222, -20), (532, 204, -10),
              (548, 196, -4), (570, 188, 2), (590, 200, 8), (604, 224, 16), (604, 314, 10), (626, 330, 16),
              (638, 358, 18), (644, 386, 16)]



# --------------------------------------------------------------------------- pixel art (32 bits)
# O mundo do jogo (cenário, boss, herói e efeitos) é desenhado em baixa resolução, com rampas de cor,
# dithering e contorno, e embutido como PNG. HUD, menus, faixas e números continuam vetoriais.

P = 3                         # 1 pixel lógico = 3 px na tela
LW, LH = W // P, H // P + 1   # 280 x 134
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
LIGHT = (-.55, -.83)          # luz vindo de cima à esquerda

CERO_LIGHT, CERO_MID, CERO_DEEP, CERO_CORE = "#8ee3ff", "#3aa8e0", "#1c6fb8", "#02040b"


def bayer(x, y):
    return (BAYER[int(y) % 4][int(x) % 4] + .5) / 16


def rgb(h, a=255):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), a)


def ramp(spec):
    return [rgb(c) for c in spec.split()]


def blend(c, other, k):
    o = rgb(other) if isinstance(other, str) else other
    return tuple(round(c[i] + (o[i] - c[i]) * k) for i in range(3)) + (c[3],)


def png_uri(w, h, px):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for c in px[y * w:(y + 1) * w]:
            raw += bytes(c) if c else b"\x00\x00\x00\x00"

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(data).decode()


def poly_mask(points):
    pixels = set()
    ys = [y for _, y in points]
    edges = list(zip(points, points[1:] + points[:1]))
    for y in range(math.floor(min(ys)), math.ceil(max(ys)) + 1):
        yc = y + .5
        xs = sorted(ax + (yc - ay) * (bx - ax) / (by - ay)
                    for (ax, ay), (bx, by) in edges if (ay <= yc < by) or (by <= yc < ay))
        for a, b in zip(xs[::2], xs[1::2]):
            pixels.update((x, y) for x in range(math.ceil(a - .5), math.floor(b - .5) + 1))
    return pixels


def disc_mask(cx, cy, r, r_in=None):
    out = set()
    for y in range(math.floor(cy - r) - 1, math.ceil(cy + r) + 1):
        for x in range(math.floor(cx - r) - 1, math.ceil(cx + r) + 1):
            d2 = (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2
            if d2 <= r * r and (r_in is None or d2 > r_in * r_in):
                out.add((x, y))
    return out


def dda(points):
    """Linha de 1 pixel passando pelos pontos."""
    out = set()
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        n = max(1, math.ceil(max(abs(x1 - x0), abs(y1 - y0))))
        out.update((math.floor(x0 + (x1 - x0) * i / n), math.floor(y0 + (y1 - y0) * i / n)) for i in range(n + 1))
    return out


def thick(points, width):
    out = set()
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0) or 1e-6
        nx, ny = -(y1 - y0) / length * width / 2, (x1 - x0) / length * width / 2
        out |= poly_mask([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
        out |= disc_mask(x1, y1, width / 2)
    return out | disc_mask(*points[0], width / 2) | dda(points)


def ramp_color(colors, f, x, y, dither=.55):
    f = max(0.0, min(1.0, f)) * (len(colors) - 1) + (bayer(x, y) - .5) * dither
    return colors[max(0, min(len(colors) - 1, round(f)))]


def shaded(mask, colors, cx, cy, radius, bias=0.0, dither=.55, edges=True):
    """Cor por pixel: mais clara no lado da luz, com borda escura embaixo/direita e clara em cima/esquerda."""
    def color(x, y):
        v = ((x + .5 - cx) * LIGHT[0] + (y + .5 - cy) * LIGHT[1]) / radius
        f = (v + 1) / 2 + bias
        if edges:
            if (x + 1, y) not in mask or (x, y + 1) not in mask:
                f -= .22
            if (x - 1, y) not in mask or (x, y - 1) not in mask:
                f += .18
        return ramp_color(colors, f, x, y, dither)
    return color


class Sprite:
    def __init__(self, w, h, ox=0.0, oy=0.0):
        self.w, self.h, self.ox, self.oy = w, h, ox, oy  # ox, oy: canto superior esquerdo no mundo lógico
        self.px = [None] * (w * h)
        self._uri = None

    def get(self, x, y):
        return self.px[y * self.w + x] if 0 <= x < self.w and 0 <= y < self.h else None

    def put(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y * self.w + x] = c
            self._uri = None

    def paint(self, mask, color):
        for x, y in mask:
            self.put(x, y, color(x, y) if callable(color) else color)

    def opaque(self):
        return {(i % self.w, i // self.w) for i, c in enumerate(self.px) if c}

    def _ring(self, pixels, seen):
        ring = set()
        for x, y in pixels:
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= n[0] < self.w and 0 <= n[1] < self.h and n not in seen:
                    ring.add(n)
        return ring

    def outline(self, color):
        solid = self.opaque()
        ring = self._ring(solid, solid)
        self.paint(ring, rgb(color) if isinstance(color, str) else color)
        return ring

    def glow(self, color, size=2, density=.5):
        c = rgb(color) if isinstance(color, str) else color
        seen = self.opaque()
        edge, added = seen, set()
        for k in range(size):
            ring = self._ring(edge, seen)
            seen |= ring
            for x, y in ring:
                if bayer(x + self.ox, y + self.oy) < density * (1 - k / size):
                    self.put(x, y, c)
                    added.add((x, y))
            edge = ring
        return added

    def uri(self):
        if self._uri is None:
            self._uri = png_uri(self.w, self.h, self.px)
        return self._uri

    def image(self, x=None, y=None, cls="", style=""):
        """<image> na escala da tela. Sem x/y, usa a posição do sprite no mundo."""
        x = self.ox * P if x is None else x
        y = self.oy * P if y is None else y
        extra = f' style="{style}"' if style else ""
        return (f'<image class="px {cls}"{extra} href="{self.uri()}" x="{x:.1f}" y="{y:.1f}" '
                f'width="{self.w * P}" height="{self.h * P}"/>')


def frames(sprites, duration, x=None, y=None):
    """Alterna sprites em loop, como animação de quadros."""
    n = len(sprites)
    return "".join(s.image(x, y, cls=f"fr{n}_{i}", style=f"animation-duration:{duration:.2f}s") for i, s in enumerate(sprites))


def frame_css(n):
    out = []
    for i in range(n):
        a, b = i / n * 100, (i + 1) / n * 100
        keys = [f"0%{{opacity:{1 if i == 0 else 0}}}"]
        if i > 0:
            keys.append(f"{a:.3f}%{{opacity:1}}")
        if i < n - 1:
            keys.append(f"{b:.3f}%{{opacity:0}}")
        keys.append(f"100%{{opacity:{1 if i == n - 1 else 0}}}")
        out.append(f"@keyframes fr{n}_{i}{{{''.join(keys)}}}.fr{n}_{i}{{animation:fr{n}_{i} 1s step-end infinite}}")
    return "".join(out)


# --------------------------------------------------------------------------- sprites do mundo

CHITIN = "#03060f #0a1430 #142456 #21397f #3558ad"
BONE_RAMP = "#6d6452 #a89d82 #d9d0b8 #f3eee0 #ffffff"
CYAN_RAMP = "#0a4f73 #1c8fc0 #3fd0f5 #aef0ff"
HOODIE = "#03081a #0a1636 #13265c #1f3b85 #3561c4"
HAIR = "#03081a #0b1a42 #16307a #2a52b8"
OUTLINE = "#01030a"


def floor_mask():
    return poly_mask([(0, 300 / P), (LW, 262 / P), (LW, LH), (0, LH)])


def sprite_background():
    s = Sprite(LW, LH)
    sky = ramp("#020a1f #03102e #051a4a #082766 #0c3a96 #1150d8")
    for y in range(LH):
        for x in range(LW):
            s.put(x, y, ramp_color(sky, (y / LH) ** 1.15, x, y, dither=.9))
    for x0, w in ((40, 70), (170, 40), (430, 90), (610, 50)):
        for x, y in poly_mask([(x0 / P, 0), ((x0 + w) / P, 0), ((x0 + w - 160) / P, 100), ((x0 - 190) / P, 100)]):
            if s.get(x, y) and bayer(x, y) < .32:
                s.put(x, y, blend(s.get(x, y), ICE, .16))
    mx, my, mr = MOON_X / P, MOON_Y / P, MOON_R / P
    for x, y in disc_mask(mx, my, mr + 16, mr):
        k = (math.hypot(x + .5 - mx, y + .5 - my) - mr) / 16
        if s.get(x, y) and bayer(x, y) < .62 * (1 - k):
            s.put(x, y, blend(s.get(x, y), CYAN, .5 - .3 * k))
    moon_ramp = ramp("#5fb8e8 #8fd4f5 #b7ecff #dcf8ff #ffffff")
    disc = disc_mask(mx, my, mr)
    s.paint(disc, shaded(disc, moon_ramp, mx, my, mr, bias=.12, dither=.8, edges=False))
    crater_ramp = moon_ramp[1:4][::-1]
    for dx, dy, r in ((-48, -30, 18), (30, 40, 26), (52, -46, 12), (-20, 60, 10), (-70, 30, 8), (10, -8, 7)):
        cm = disc_mask(mx + dx / P, my + dy / P, r / P) & disc
        s.paint(cm, shaded(cm, crater_ramp, mx + dx / P, my + dy / P, r / P, dither=.5, edges=False))
    floor = floor_mask()
    floor_ramp = ramp("#010411 #020818 #030d26 #051638 #07204f")
    for x, y in floor:
        top = 100 - x * (38 / P) / LW
        s.put(x, y, ramp_color(floor_ramp, 1 - (y - top) / (LH - top), x, y, dither=.9))
    for x, y in floor:
        if (x, y - 1) not in floor:
            s.put(x, y, rgb(CYAN))
            if bayer(x, y + 1) < .6:
                s.put(x, y + 1, rgb(BLUE))
    return s


def sprite_waves(phase):
    s = Sprite(LW, LH)
    floor = floor_mask()
    for k, base in enumerate((107, 114, 122, 130)):
        alpha = 170 - k * 32
        for x in range(LW):
            if (x - phase * 5 + k * 7) % 20 >= 12:
                continue
            y = round(base - x * .045 + 1.3 * math.sin(2 * math.pi * (x - phase * 5) / 20 + k))
            if (x, y - 2) in floor:
                s.put(x, y, rgb(CYAN, alpha))
    return s


def sprite_ground():
    s = Sprite(70, 8, BOSS_X / P - 35, (BOSS_Y + 100) / P - 4)
    for y in range(8):
        for x in range(70):
            if ((x + .5 - 35) / 32) ** 2 + ((y + .5 - 4) / 3.4) ** 2 <= 1 and bayer(x + s.ox, y + s.oy) < .62:
                s.put(x, y, rgb("#010411"))
    return s


BOSS_SOCKET = [(-34, -52), (-9, -44), (-11, -31), (-31, -38)]
BOSS_CX, BOSS_CY, BOSS_PS = 48, 44, .31   # centro dentro do sprite e escala vetor -> pixel


def sprite_boss():
    """Retorna (boss, silhueta branca, estilhaços, rachaduras)."""
    s = Sprite(96, 84, BOSS_X / P - BOSS_CX, BOSS_Y / P - BOSS_CY)
    cx, cy, k = BOSS_CX, BOSS_CY, BOSS_PS

    def m(points):
        return [(cx + x * k, cy + y * k) for x, y in points]

    chitin, bone, cyan = ramp(CHITIN), ramp(BONE_RAMP), ramp(CYAN_RAMP)
    shell = set()
    for p in BOSS_LEGS + [mirror(p) for p in BOSS_LEGS]:
        leg = thick(m(p), 3.2)
        s.paint(leg, shaded(leg, chitin, cx, cy - 12, 42))
        shell |= leg
    for p in BOSS_ANTENNAE + [mirror(p) for p in BOSS_ANTENNAE]:
        ant = thick(m(p), 1.7)
        s.paint(ant, shaded(ant, chitin, cx, cy - 20, 42, bias=.1))
        shell |= ant
    abdomen = poly_mask(m(BOSS_ABDOMEN))
    s.paint(abdomen, shaded(abdomen, chitin, cx, cy + 30 * k, 24))
    head = poly_mask(m(BOSS_HEAD))
    s.paint(head, shaded(head, chitin, cx, cy - 44 * k, 14))
    shell |= abdomen | head
    crown = poly_mask(m(BOSS_CROWN))
    s.paint(crown, shaded(crown, cyan, cx, cy - 84 * k, 10, bias=.12))
    mask = poly_mask(m(BOSS_MASK))
    s.paint(mask, shaded(mask, bone, cx, cy - 42 * k, 13, bias=.12))
    dark, bone_dark = rgb("#05070d"), rgb("#5a523f")
    for sock in (BOSS_SOCKET, mirror(BOSS_SOCKET)):
        s.paint(poly_mask(m(sock)), dark)
    for side in (-1, 1):
        ex, ey = round(cx + side * 20 * k - .5), round(cy - 40 * k - .5)
        s.put(ex, ey, rgb(RED))
        s.put(ex + side, ey, rgb("#b3122b"))
        s.put(ex, ey - 1, rgb("#ffb3bd"))
    s.paint(dda(m([(x, -17 if i % 2 == 0 else -9) for i, x in enumerate(range(-26, 27, 6))])), bone_dark)
    s.paint(dda(m([(0, -78), (0, -62)])), bone_dark)
    s.paint(dda(m([(20, -68), (12, -58), (18, -50), (13, -44)])), bone_dark)
    for y, sc in ((66, .8), (84, .55)):
        chev = thick(m([(-44 * sc, y), (0, y + 16 * sc), (44 * sc, y)]), 1.8)
        s.paint(chev, lambda x, yy, c=chev: cyan[3] if (x, yy - 1) not in c else cyan[2])
    # rim light na carapaça
    for x, y in shell:
        c = s.get(x, y)
        if c in chitin and (s.get(x - 1, y) is None or s.get(x, y - 1) is None):
            s.put(x, y, rgb("#4f86e0"))
    # buraco no peito
    hx, hy, hr = cx, cy + 34 * k, 17 * k + .4
    rim = disc_mask(hx, hy, hr + 1.4, hr)
    s.paint(rim, lambda x, y: rgb(ICE) if (x + .5 - hx) + (y + .5 - hy) < 0 else rgb("#5fb8e8"))
    for x, y in disc_mask(hx, hy, hr):
        s.put(x, y, None)
    s.paint(dda([(hx + hr + 1, hy - 1), (hx + hr + 4, hy - 3), (hx + hr + 7, hy - 1)]), rgb(CYAN))
    s.paint(dda([(hx - hr - 1, hy + 1), (hx - hr - 4, hy + 3)]), rgb(CYAN))
    s.outline(OUTLINE)
    s.glow("#1c8fd0", size=2, density=.55)

    flash = Sprite(s.w, s.h, s.ox, s.oy)
    shards = [Sprite(s.w, s.h, s.ox, s.oy) for _ in range(SHARDS)]
    white = rgb(WHITE)
    for i, c in enumerate(s.px):
        if not c:
            continue
        x, y = i % s.w, i // s.w
        flash.px[i] = white
        ang = math.degrees(math.atan2(y + .5 - cy, x + .5 - cx))
        shards[int(((ang + 90 - 12) % 360) // (360 / SHARDS))].px[i] = c
    cracks = Sprite(s.w, s.h, s.ox, s.oy)
    for n in range(SHARDS):
        a = math.radians(n * 360 / SHARDS - 90 + 12)
        cracks.paint(dda([(cx, cy), (cx + math.cos(a) * 70 * k, cy + (math.sin(a) * 70 + 8) * k),
                          (cx + math.cos(a) * 150 * k, cy + math.sin(a) * 150 * k)]), white)
    cracks.glow(CYAN, size=1, density=.9)
    return s, flash, shards, cracks


HERO_OX, HERO_OY = 150, 58
PIXEL_GLYPHS = {"<": ["..#", ".#.", "#..", ".#.", "..#"], "/": ["..#", "..#", ".#.", "#..", "#.."],
                ">": ["#..", ".#.", "..#", ".#.", "#.."]}


def sprite_hero():
    s = Sprite(76, 76, HERO_OX, HERO_OY)

    def m(points):
        return [(x / P - HERO_OX, y / P - HERO_OY) for x, y in points]

    hoodie, hair = ramp(HOODIE), ramp(HAIR)
    body = poly_mask(m(HERO_BODY))
    s.paint(body, shaded(body, hoodie, 560 / P - HERO_OX, 336 / P - HERO_OY, 24, bias=.05))
    for line in ([(500, 322), (530, 306), (540, 400)], [(620, 322), (590, 306), (580, 400)]):
        s.paint(dda(m(line)) & body, rgb(BLUE))
    head = poly_mask(m(HERO_HEAD))
    s.paint(head, shaded(head, hair, 560 / P - HERO_OX, 240 / P - HERO_OY, 16, bias=.08))
    s.paint(dda([(x, y + 1.2) for x, y in m(HERO_HEAD[3:11])]) & head, rgb("#2a5ad8"))
    hood = poly_mask(m(HERO_HOOD))
    s.paint(hood, shaded(hood, ramp("#02050d #050b1d #0a1638"), 560 / P - HERO_OX, 300 / P - HERO_OY, 10))
    s.paint({(x, y) for x, y in hood if (x, y - 1) not in hood}, rgb(CYAN))
    gx, gy = round(560 / P - HERO_OX) - 5, round(368 / P - HERO_OY) - 2
    for n, ch in enumerate("</>"):
        for yy, row in enumerate(PIXEL_GLYPHS[ch]):
            for xx, bit in enumerate(row):
                if bit == "#":
                    s.put(gx + n * 4 + xx, gy + yy, rgb(CYAN))
    for x, y in body | head:
        if s.get(x, y) and (s.get(x - 1, y) is None or s.get(x, y - 1) is None):
            s.put(x, y, rgb("#4f86e0"))
    s.outline(OUTLINE)
    s.glow("#1c8fd0", size=2, density=.6)
    return s


def sprite_aura(outer, inner, seed, frame):
    s = Sprite(92, 90, 144, 44)
    rnd = random.Random(seed * 100 + frame)
    for x, y, tilt in AURA_BASES:
        bx, by = x / P - s.ox, y / P - s.oy
        h, w = rnd.uniform(10, 20), rnd.uniform(3, 4.6)
        sn, cs = math.sin(math.radians(tilt)), math.cos(math.radians(tilt))

        def flame(scale):
            hh, ww = h * scale, w * scale
            return [(bx - ww, by), (bx - ww * .75 + sn * hh * .5, by - cs * hh * .5), (bx + sn * hh, by - cs * hh),
                    (bx + ww * .75 + sn * hh * .5, by - cs * hh * .5), (bx + ww, by)]

        for px_, py_ in poly_mask(flame(1)):
            rel = (by - py_) / h
            if rel > .55 and bayer(px_ + s.ox, py_ + s.oy) < (rel - .55) * 2.4:
                continue
            s.put(px_, py_, rgb(outer))
        s.paint(poly_mask(flame(.55)), rgb(inner))
    return s


RIFT_CX, RIFT_CY = 62, 34


def sprite_rift():
    s = Sprite(124, 68, BOSS_X / P - RIFT_CX, BOSS_Y / P - RIFT_CY)
    rnd = random.Random(3)
    top, bottom = [], []
    for i in range(19):
        x = -175 + 350 * i / 18
        base = 72 * (1 - (x / 175) ** 2)
        top.append((x, -base - (rnd.uniform(4, 16) if i % 2 else -rnd.uniform(0, 6))))
        bottom.append((x, base + (rnd.uniform(4, 16) if i % 2 == 0 else -rnd.uniform(0, 6))))
    shape = [(RIFT_CX + x / P, RIFT_CY + y / P) for x, y in top + bottom[::-1]]
    mask = poly_mask(shape)
    s.paint(mask, rgb("#010308"))
    inner = poly_mask([(RIFT_CX + (x - RIFT_CX) * .8, RIFT_CY + (y - RIFT_CY) * .65) for x, y in shape])
    s.paint({p for p in inner if bayer(*p) < .42}, rgb(RED_DARK))
    s.paint({(x, y) for x, y in mask if any(n not in mask for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))}, rgb(ICE))
    s.outline(OUTLINE)
    s.glow(CYAN, size=2, density=.5)
    return s


def sprite_crescent():
    s = Sprite(26, 42)
    a, b = disc_mask(18, 21, 18), disc_mask(24, 21, 16.5)
    for x, y in a - b:
        da = 18 - math.hypot(x + .5 - 18, y + .5 - 21)
        db = math.hypot(x + .5 - 24, y + .5 - 21) - 16.5
        s.put(x, y, rgb(WHITE) if db < 1.3 else rgb(CYAN) if da < 1.2 else rgb(ICE))
    s.outline("#0a3f73")
    s.glow("#1c8fd0", size=2, density=.55)
    return s


def sprite_slash():
    s = Sprite(74, 58, 62, 30)
    core = set()
    for dx in (-28, 0, 28):
        line = [((BOSS_X + 64 + dx) / P - s.ox, (BOSS_Y - 68) / P - s.oy), ((BOSS_X - 64 + dx) / P - s.ox, (BOSS_Y + 68) / P - s.oy)]
        core |= dda(line)
        s.paint(dda([(x + 1, y) for x, y in line]), rgb(CYAN))
    s.paint(core, rgb(WHITE))
    s.glow("#1c8fd0", size=1, density=.8)
    return s


def sprite_orb(frame):
    s = Sprite(40, 40)
    core, light, mid, deep = rgb(CERO_CORE), rgb(CERO_LIGHT), rgb(CERO_MID), rgb(CERO_DEEP)
    for y in range(40):
        for x in range(40):
            d = math.hypot(x + .5 - 20, y + .5 - 20)
            ang = math.atan2(y + .5 - 20, x + .5 - 20) / (2 * math.pi)
            if d <= 6.4:
                s.put(x, y, core)
            elif d <= 7.5:
                s.put(x, y, mid)
            elif d <= 8.4:
                s.put(x, y, rgb("#dff7ff"))
            elif d <= 9.8:
                s.put(x, y, light)
            elif 11.6 <= d <= 12.9 and (ang * 12 + frame * .67) % 2 < 1:
                s.put(x, y, light)
            elif 14.6 <= d <= 15.6 and (-ang * 16 + frame * .5) % 2 < 1:
                s.put(x, y, mid)
            elif d <= 18.5 and bayer(x, y) < .5 * (1 - (d - 9.8) / 8.7):
                s.put(x, y, deep)
    s.put(18, 18, light)
    return s


BEAM_OY, BEAM_H = 26, 60


def sprite_beam(frame):
    """Feixe do cero oscuras já alinhado do herói até o boss e além (sem rotação)."""
    s = Sprite(178, BEAM_H, 0, BEAM_OY)
    ox_, oy_ = ORB_X / P, ORB_Y / P
    ux, uy = BOSS_X / P - ox_, BOSS_Y / P - oy_
    length = math.hypot(ux, uy)
    ux, uy = ux / length, uy / length
    nx, ny = -uy, ux
    core, light, mid, deep, hi = rgb(CERO_CORE), rgb(CERO_LIGHT), rgb(CERO_MID), rgb(CERO_DEEP), rgb("#dff7ff")
    for y in range(BEAM_H):
        for x in range(178):
            rx, ry = x + .5 - ox_, y + BEAM_OY + .5 - oy_
            along, d = rx * ux + ry * uy, abs(rx * nx + ry * ny)
            if along < 0:
                d = math.hypot(rx, ry)
                if d > 12:
                    continue
            if d <= 4.5:
                zig = 2.6 * (abs(((along + frame * 4.5) / 9) % 2 - 1) * 2 - 1)
                zig2 = 1.5 * (abs(((along - frame * 7) / 14) % 2 - 1) * 2 - 1)
                sd = rx * nx + ry * ny
                if along > 6 and abs(sd - zig) < .6:
                    s.put(x, y, light)
                elif along > 6 and abs(sd - zig2) < .5:
                    s.put(x, y, deep)
                else:
                    s.put(x, y, core)
            elif d <= 5.4:
                s.put(x, y, hi)
            elif d <= 6.6:
                s.put(x, y, light)
            elif d <= 7.6:
                s.put(x, y, mid)
            elif d <= 11.5 and bayer(x, y + BEAM_OY) < .6 * (1 - (d - 7.6) / 3.9):
                s.put(x, y, deep)
    return s


def sprite_boom():
    s = Sprite(64, 64)
    rnd = random.Random(17)
    for x, y in disc_mask(32, 32, 11):
        s.put(x, y, rgb(CERO_CORE))
    s.paint(disc_mask(32, 32, 13.5, 11), rgb(CERO_LIGHT))
    s.paint(disc_mask(32, 32, 15, 13.5), rgb(CERO_MID))
    for n in range(12):
        a = math.radians(n * 30 + rnd.uniform(-8, 8))
        r1 = rnd.uniform(24, 30)
        line = [(32 + math.cos(a) * 16, 32 + math.sin(a) * 16), (32 + math.cos(a) * r1, 32 + math.sin(a) * r1)]
        s.paint(thick(line, 2) if n % 2 == 0 else dda(line), rgb(WHITE if n % 3 == 0 else CERO_LIGHT))
    s.glow(CERO_DEEP, size=3, density=.6)
    return s


def sprite_butterfly(open_wings):
    s = Sprite(16, 12)
    k = .36 * (1 if open_wings else .35)
    wing_up = [(0, 0), (-13, -13), (-21, -6), (-14, 3)]
    wing_low = [(0, 2), (-11, 5), (-9, 14)]
    wings = set()
    for p in (wing_up, wing_low, mirror(wing_up), mirror(wing_low)):
        wings |= poly_mask([(8 + x * k * (1 if open_wings else 1), 5 + y * .36) for x, y in p])
    s.paint(wings, rgb(CERO_CORE))
    s.paint({(x, y) for x, y in wings if any(n not in wings for n in ((x + 1, y), (x - 1, y), (x, y - 1)))}, rgb(CYAN))
    s.paint(dda([(8, 3), (8, 8)]), rgb("#0a1430"))
    return s


def sprite_bubble(big):
    rows = ([".###.", "#...#", "#...#", "#...#", ".###."] if not big else
            ["..###..", ".#...#.", "#.....#", "#.....#", "#.....#", ".#...#.", "..###.."])
    s = Sprite(len(rows[0]), len(rows))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                s.put(x, y, rgb(ICE, 210))
    s.put(1 if not big else 2, 1, rgb(WHITE))
    return s


def sprite_sparkle():
    rows = ["...#...", "...#...", "..###..", "#######", "..###..", "...#...", "...#..."]
    s = Sprite(7, 7)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                s.put(x, y, rgb(WHITE if (x, y) == (3, 3) else ICE))
    return s


def hp_color(ratio):
    return CYAN if ratio > 0.3 else WHITE


# --------------------------------------------------------------------------- cena

def build(user, months, streak):
    turns_n = len(months)
    total = sum(n for _, n in months)
    max_hp = max(total, 1)
    peak = max((n for _, n in months), default=0)
    tv = INTRO + turns_n * TURN
    T = tv + VICTORY
    death = tv + 0.7
    A = Anim(T)

    turns = []
    hp = total
    for i, (label, n) in enumerate(months):
        if n == 0:
            lvl = 0
        elif n == peak:
            lvl = 4
        else:
            ratio = n / peak
            lvl = 1 if ratio < 0.34 else 2 if ratio < 0.67 else 3
        t0 = INTRO + i * TURN
        turns.append(dict(i=i, label=label, n=n, lvl=lvl, t0=t0,
                          throw=t0 + THROW * TURN, hit=t0 + HIT * TURN,
                          hp_before=hp, hp_after=hp - n))
        hp -= n
    hits = [t for t in turns if t["n"] > 0]

    parts = []
    add = parts.append
    rnd = random.Random(7)

    # ---------------- defs (só o que o HUD usa)
    add('<defs>'
        f'<clipPath id="card"><polygon points="16,0 {W},0 {W},{H - 16} {W - 16},{H} 0,{H} 0,16"/></clipPath>'
        f'<linearGradient id="bandGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{INK}" stop-opacity=".92"/>'
        f'<stop offset=".5" stop-color="{BLUE}" stop-opacity=".95"/><stop offset="1" stop-color="{INK}" stop-opacity=".92"/></linearGradient>'
        f'<linearGradient id="bandOsc" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{INK}" stop-opacity=".96"/>'
        f'<stop offset=".5" stop-color="#0b2f52" stop-opacity=".97"/><stop offset="1" stop-color="{INK}" stop-opacity=".96"/></linearGradient>'
        f'<linearGradient id="barGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>'
        '</defs>')
    add('<g clip-path="url(#card)">')

    # ---------------- mundo em pixel art
    add(sprite_background().image())

    # fenda que se abre no céu na entrada do boss
    rift = sprite_rift()
    k_rift = A.add([(0, "opacity:0;transform:scale(.2,0)"), (.1, "opacity:0;transform:scale(.2,0)"),
                    (.11, "opacity:1;transform:scale(.2,0)"), (.32, "opacity:1;transform:scale(1,1)"),
                    (.95, "opacity:1;transform:scale(1,1)"), (1.15, "opacity:1;transform:scale(1,0)"),
                    (1.16, "opacity:0;transform:scale(1,0)"), (T, "opacity:0;transform:scale(1,0)")])
    add(f'<g transform="translate({BOSS_X},{BOSS_Y})"><g class="{k_rift}">{rift.image(-RIFT_CX * P, -RIFT_CY * P)}</g></g>')

    # bolhas subindo
    bubbles = (sprite_bubble(False), sprite_bubble(True))
    for k in range(22):
        dur = rnd.uniform(5, 10)
        b = bubbles[1] if rnd.random() < .25 else bubbles[0]
        add(b.image(rnd.randint(3, LW - 8) * P, rnd.randint(84, 110) * P, cls="bubble",
                    style=f"animation-duration:{dur:.1f}s;animation-delay:-{rnd.uniform(0, dur):.1f}s"))

    # borboletas pretas
    wings = [sprite_butterfly(True), sprite_butterfly(False)]
    for i in range(3):
        add(f'<g class="fly{i}">{frames(wings, .32, -8 * P, -5 * P)}</g>')

    # chão com ondas animadas quadro a quadro
    add(frames([sprite_waves(f) for f in range(4)], 1.0, 0, 0))
    k_ground = A.show(0.45, death + .5 if total > 0 else T)
    add(f'<g class="{k_ground}">{sprite_ground().image()}</g>')

    # painel escuro no canto do turno (HUD)
    add(f'<polygon points="590,0 {W},0 {W},118 700,104" fill="{INK}" fill-opacity=".82"/>')
    add(f'<polygon points="700,104 {W},118 {W},122 698,108" fill="{CYAN}"/>')

    # ---------------- boss
    life = [(0, "opacity:0"), (0.3, "opacity:0"), (0.75, "opacity:1"), (tv, "opacity:1")]
    if total > 0:
        for k in range(5):
            life.append((tv + 0.12 * (k + 1), f"opacity:{'.2' if k % 2 == 0 else '1'}"))
        life += [(death, "opacity:1"), (death + EPS, "opacity:0"), (T, "opacity:0")]
    k_life = A.add(life)

    shake = [(0, "transform:translateX(0px)")]
    flash = [(0, "opacity:0")]
    for t in hits:
        a = 15 if t["lvl"] == 4 else 9
        h0 = t["hit"]
        shake += [(h0, "transform:translateX(0px)"), (h0 + .04, f"transform:translateX(-{a}px)"),
                  (h0 + .08, f"transform:translateX({a}px)"), (h0 + .12, f"transform:translateX(-{a - 3}px)"),
                  (h0 + .16, f"transform:translateX({a - 3}px)"), (h0 + .22, "transform:translateX(0px)")]
        flash += [(h0, "opacity:0"), (h0 + .01, "opacity:.95"), (h0 + .07, "opacity:0"),
                  (h0 + .12, "opacity:.6"), (h0 + .17, "opacity:0")]
    if total > 0:
        flash += [(tv, "opacity:0"), (tv + .05, "opacity:.9"), (tv + .2, "opacity:0"), (tv + .45, "opacity:.8"), (tv + .6, "opacity:0")]
    k_shake = A.add(shake)
    k_flash = A.add(flash)

    boss, boss_flash, shards, cracks = sprite_boss()
    bx, by = -BOSS_CX * P, -BOSS_CY * P
    k_emerge = A.add([(0, "transform:translateY(-9px) scale(.55)"), (.3, "transform:translateY(-9px) scale(.55)"),
                      (.85, "transform:translateY(0px) scale(1)"), (T, "transform:translateY(0px) scale(1)")])
    add(f'<g transform="translate({BOSS_X},{BOSS_Y})"><g class="{k_emerge}"><g class="bob"><g class="{k_shake}">')
    add(f'<g class="{k_life}">{boss.image(bx, by)}</g>')
    add(f'<g class="{k_flash}">{boss_flash.image(bx, by)}</g>')
    if total > 0:
        # estilhaça em pedaços de pixel
        gone = "opacity:0;transform:translate({x:.0f}px,{y:.0f}px) rotate({r:.0f}deg)"
        for k, shard in enumerate(shards):
            mid = math.radians((k + .5) * 360 / SHARDS - 90 + 12)
            dx, dy, rot = math.cos(mid) * 72, math.sin(mid) * 72 + 30, (-1) ** k * 15
            k_shard = A.add([(0, gone.format(x=0, y=0, r=0)), (death, gone.format(x=0, y=0, r=0)),
                             (death + EPS, "opacity:1;transform:translate(0px,0px) rotate(0deg)"),
                             (death + .12, "opacity:1;transform:translate(0px,0px) rotate(0deg)"),
                             (death + .5, f"opacity:1;transform:translate({dx * .5:.0f}px,{dy * .5:.0f}px) rotate({rot * .5:.0f}deg)"),
                             (death + 1.0, gone.format(x=dx, y=dy, r=rot)), (T, gone.format(x=dx, y=dy, r=rot))])
            add(f'<g class="{k_shard}">{shard.image(bx, by)}</g>')
        k_crack = A.add([(0, "opacity:0"), (death - .14, "opacity:0"), (death - .13, "opacity:1"),
                         (death - .06, "opacity:.4"), (death, "opacity:1"), (death + .3, "opacity:0"), (T, "opacity:0")])
        add(f'<g class="{k_crack}">{cracks.image(bx, by)}</g>')
    add('</g></g></g></g>')

    # cortes do golpe
    slash = [(0, "opacity:0")]
    for t in hits:
        if t["lvl"] == 4:
            continue
        h0 = t["hit"]
        slash += [(h0 - .01, "opacity:0"), (h0, "opacity:1"), (h0 + .06, "opacity:.5"), (h0 + .1, "opacity:1"), (h0 + .18, "opacity:0")]
    k_slash = A.add(slash)
    add(f'<g class="{k_slash}">{sprite_slash().image()}</g>')

    # ---------------- herói
    crits = [t for t in turns if t["lvl"] == 4]
    lunge = [(0, "transform:translate(0px,0px)")]
    for t in turns:
        if t["lvl"] == 4:
            continue
        lunge += [(t["throw"] - .14, "transform:translate(0px,0px)"), (t["throw"], "transform:translate(-15px,-9px)"),
                  (t["throw"] + .24, "transform:translate(0px,0px)")]
    k_lunge = A.add(lunge)
    jump = [(0, "transform:translateY(0px)"), (tv + .9, "transform:translateY(0px)")]
    for k in range(3):
        base = tv + .9 + k * .44
        jump += [(base + .22, "transform:translateY(-15px)"), (base + .44, "transform:translateY(0px)")]
    k_jump = A.add(jump)
    blue, cero_aura = [(0, "opacity:.55")], [(0, "opacity:0")]
    for t in crits:
        a, b = t["t0"] + .05, t["hit"] + .45
        blue += [(a, "opacity:.55"), (a + .1, "opacity:0"), (b, "opacity:0"), (b + .15, "opacity:.55")]
        cero_aura += [(a, "opacity:0"), (a + .1, "opacity:1"), (b, "opacity:1"), (b + .15, "opacity:0")]
    blue += [(tv + .8, "opacity:.55"), (tv + 1.1, "opacity:1"), (T - .4, "opacity:1"), (T, "opacity:.55")]
    k_blue, k_cero_aura = A.add(blue), A.add(cero_aura)
    aura_blue = [sprite_aura(CYAN, ICE, 1, f) for f in range(3)]
    aura_cero = [sprite_aura(CERO_LIGHT, CERO_CORE, 2, f) for f in range(3)]
    add(f'<g class="{k_lunge}"><g class="{k_jump}"><g class="bob2">'
        f'<g class="{k_blue}">{frames(aura_blue, .36)}</g><g class="{k_cero_aura}">{frames(aura_cero, .3)}</g>'
        f'{sprite_hero().image()}</g></g></g>')

    # onda em lua crescente (golpes normais e erros)
    sx, sy = HERO_SPAWN
    proj = [(0, f"opacity:0;transform:translate({sx}px,{sy}px) scale(1)")]
    for t in turns:
        if t["lvl"] == 4:
            continue
        sc = 0.7 + t["lvl"] * 0.16
        tx, ty = (BOSS_X + 30, BOSS_Y) if t["n"] > 0 else (BOSS_X - 60, BOSS_Y - 150)
        end_op = 1 if t["n"] > 0 else 0
        proj += [(t["throw"] - EPS, f"opacity:0;transform:translate({sx}px,{sy}px) scale({sc * .4:.2f})"),
                 (t["throw"], f"opacity:1;transform:translate({sx}px,{sy}px) scale({sc * .4:.2f})"),
                 (t["throw"] + .08, f"opacity:1;transform:translate({sx - 40}px,{sy - 6}px) scale({sc:.2f})"),
                 (t["hit"], f"opacity:{end_op};transform:translate({tx}px,{ty}px) scale({sc:.2f})"),
                 (t["hit"] + EPS, f"opacity:0;transform:translate({tx}px,{ty}px) scale({sc:.2f})")]
    k_proj = A.add(proj)
    add(f'<g class="{k_proj}">{sprite_crescent().image(-13 * P, -21 * P)}</g>')

    # cero oscuras no golpe crítico: carrega a esfera e dispara o feixe
    rnd_sp = random.Random(9)
    orb_frames = [sprite_orb(f) for f in range(3)]
    beam_frames = [sprite_beam(f) for f in range(2)]
    boom = sprite_boom()
    for t in crits:
        t0, h0 = t["t0"], t["hit"]
        # escurece a cena por baixo do cero, para o feixe brilhar
        k_tint = A.add([(0, "opacity:0"), (h0 - .01, "opacity:0"), (h0, "opacity:.5"), (h0 + .45, "opacity:0"), (T, "opacity:0")])
        add(f'<rect class="{k_tint}" width="{W}" height="{H}" fill="{INK}" pointer-events="none"/>')
        k_orb = A.add([(0, "opacity:0;transform:scale(0)"), (t0 + .08, "opacity:0;transform:scale(0)"),
                       (t0 + .1, "opacity:1;transform:scale(.1)"), (h0 - .06, "opacity:1;transform:scale(1)"),
                       (h0 - .02, "opacity:1;transform:scale(1.25)"), (h0 + .3, "opacity:1;transform:scale(.9)"),
                       (h0 + .42, "opacity:0;transform:scale(0)"), (T, "opacity:0;transform:scale(0)")])
        add(f'<g transform="translate({ORB_X},{ORB_Y})">')
        for sp in range(10):
            ang = 2 * math.pi * sp / 10 + rnd_sp.uniform(-.2, .2)
            dist = rnd_sp.uniform(60, 90)
            fx, fy = round(math.cos(ang) * dist / P) * P, round(math.sin(ang) * dist / P) * P
            keys = [(0, f"opacity:0;transform:translate({fx}px,{fy}px)")]
            for wave in range(3):
                w0 = t0 + .1 + wave * .12 + sp * .008
                keys += [(w0, f"opacity:0;transform:translate({fx}px,{fy}px)"),
                         (w0 + .01, f"opacity:1;transform:translate({fx}px,{fy}px)"),
                         (w0 + .11, "opacity:1;transform:translate(0px,0px)"),
                         (w0 + .12, f"opacity:0;transform:translate({fx}px,{fy}px)")]
            k_sp = A.add(keys)
            size = P * (2 if sp % 3 == 0 else 1)
            color = WHITE if sp % 4 == 0 else CERO_LIGHT if sp % 2 else CERO_MID
            add(f'<rect class="{k_sp}" x="{-size // 2}" y="{-size // 2}" width="{size}" height="{size}" fill="{color}"/>')
        add(f'<g class="{k_orb}">{frames(orb_frames, .3, -20 * P, -20 * P)}</g></g>')
        k_beam = A.add([(0, "opacity:0;transform:scale(0,.3)"), (h0 - .07, "opacity:0;transform:scale(0,.3)"),
                        (h0 - .06, "opacity:1;transform:scale(.05,.5)"), (h0, "opacity:1;transform:scale(1,1)"),
                        (h0 + .08, "opacity:1;transform:scale(1,1.25)"), (h0 + .3, "opacity:1;transform:scale(1,1)"),
                        (h0 + .42, "opacity:1;transform:scale(1,0)"), (h0 + .43, "opacity:0;transform:scale(1,0)"),
                        (T, "opacity:0;transform:scale(1,0)")])
        add(f'<g transform="translate({ORB_X},{ORB_Y})"><g class="{k_beam}">'
            f'{frames(beam_frames, .16, -ORB_X, BEAM_OY * P - ORB_Y)}</g></g>')
        k_boom = A.add([(0, "opacity:0;transform:scale(.2)"), (h0, "opacity:0;transform:scale(.2)"),
                        (h0 + .01, "opacity:1;transform:scale(.4)"), (h0 + .45, "opacity:0;transform:scale(1.9)"),
                        (T, "opacity:0;transform:scale(1.9)")])
        add(f'<g transform="translate({BOSS_X},{BOSS_Y})"><g class="{k_boom}">{boom.image(-32 * P, -32 * P)}</g></g>')

    # ---------------- HUD topo: boss
    add('<g transform="translate(16,14)">')
    add(f'<polygon points="0,0 312,0 302,56 -6,56" fill="{INK}" fill-opacity=".88"/>')
    add(f'<polygon points="0,0 7,0 1,56 -6,56" fill="{CYAN}"/>')
    add(f'<text class="fd it" x="18" y="28" font-size="25" fill="{WHITE}" letter-spacing="1">{BOSS_NAME}</text>')
    segments = [(0, total)] + [(t["hit"] + .1, t["hp_after"]) for t in hits]
    for idx, (start, value) in enumerate(segments):
        end = segments[idx + 1][0] if idx + 1 < len(segments) else T - .05
        k = A.show(start, end)
        add(f'<text class="{k} fd it" x="292" y="27" font-size="19" fill="{WHITE}" text-anchor="end">'
            f'HP <tspan fill="{CYAN}">{value}</tspan>/{total}</text>')
    if segments[-1][0] > 0:
        k = A.show(T - .05, T)
        add(f'<text class="{k} fd it" x="292" y="27" font-size="19" fill="{WHITE}" text-anchor="end">HP {total}/{total}</text>')
    add('<g transform="translate(12,36)">')
    add('<clipPath id="hpclip"><polygon points="4,0 280,0 276,12 0,12"/></clipPath>')
    add(f'<g clip-path="url(#hpclip)"><rect width="280" height="12" fill="{NAVY}"/>')
    bar = [(0, f"transform:scaleX(1);fill:{hp_color(1)}")]
    for t in hits:
        rb, ra = t["hp_before"] / max_hp, t["hp_after"] / max_hp
        bar += [(t["hit"], f"transform:scaleX({rb:.4f});fill:{hp_color(rb)}"),
                (t["hit"] + .18, f"transform:scaleX({ra:.4f});fill:{hp_color(ra)}")]
    bar += [(T - .05, bar[-1][1]), (T, f"transform:scaleX(1);fill:{hp_color(1)}")]
    k_bar = A.add(bar)
    add(f'<rect class="{k_bar}" width="280" height="12"/></g></g>')
    add('</g>')

    # ---------------- HUD topo: turno com fase da lua
    add(f'<text class="fd it" x="626" y="30" font-size="15" fill="{CYAN}" letter-spacing="3">TURNO</text>')
    turn_texts = [((0, INTRO), "00", "INÍCIO", 0.0)]
    turn_texts += [((t["t0"], t["t0"] + TURN), f"{t['i'] + 1:02d}", t["label"], (t["i"] + 1) / turns_n) for t in turns]
    turn_texts.append(((tv, T), f"{turns_n:02d}", "FIM", 1.0))
    for (start, end), num, tag, phase in turn_texts:
        k = A.show(start, end)
        add(f'<g class="{k}"><g transform="translate(676,96)">{echo_text(num, 70, gap=9, echo=CYAN)}</g>'
            f'{moon_phase(794, 44, 22, phase)}'
            f'<text class="fd it" x="794" y="96" font-size="21" fill="{WHITE}" text-anchor="middle">{escape(tag)}</text></g>')

    # ---------------- menu de comandos
    for idx, name in enumerate(MENU):
        y = 128 + idx * 27
        move = [(0, "transform:translateX(0px)")]
        slab = [(0, f"fill:{INK}")]
        label = [(0, f"fill:{WHITE}")]
        for t in turns:
            sel = t["lvl"] == idx
            move += [(t["t0"], move[-1][1]), (t["t0"] + .08, f"transform:translateX({-24 if sel else 0}px)")]
            slab += [(t["t0"], slab[-1][1]), (t["t0"] + EPS, f"fill:{WHITE if sel else INK}")]
            label += [(t["t0"], label[-1][1]), (t["t0"] + EPS, f"fill:{NAVY if sel else WHITE}")]
        move += [(tv, move[-1][1]), (tv + .08, "transform:translateX(0px)")]
        slab += [(tv, slab[-1][1]), (tv + EPS, f"fill:{INK}")]
        label += [(tv, label[-1][1]), (tv + EPS, f"fill:{WHITE}")]
        k_move, k_slab, k_label = A.add(move), A.add(slab), A.add(label)
        add(f'<g transform="translate(700,{y})"><g class="{k_move}">'
            f'<polygon points="-6,3 152,3 146,25 -12,25" fill="{CYAN}" fill-opacity=".5"/>'
            f'<polygon class="{k_slab}" points="0,0 150,0 144,22 -6,22" fill-opacity=".9"/>'
            f'<text class="{k_label} fd it" x="16" y="18" font-size="17" letter-spacing="1.5">{name}</text></g></g>')

    # ---------------- log de batalha
    add(f'<polygon points="22,312 462,300 458,396 28,398" fill="{CYAN}" fill-opacity=".55"/>')
    add(f'<polygon points="14,304 452,292 448,388 20,390" fill="{INK}" fill-opacity=".9" stroke="{WHITE}" stroke-width="2" stroke-linejoin="miter"/>')
    lines = [((0.1, INTRO), f"Um {BOSS_NAME} selvagem apareceu!", 1),
             ((0.9, INTRO), "HP = commits dos últimos 12 meses", 2)]
    for t in turns:
        verb = f"usou {CERO_NAME}!" if t["lvl"] == 4 else f"usou {ATTACKS[t['lvl']]}!"
        lines.append(((t["t0"], t["t0"] + TURN), f"{user} {verb}", 1))
        if t["n"] == 0:
            msg = f"{t['label']}: nenhum commit... errou!"
        elif t["lvl"] == 4:
            msg = f"{t['label']}: golpe crítico! {t['n']} de dano!"
        else:
            msg = f"{t['label']}: {t['n']} de dano!"
        lines.append(((t["hit"] + .05, t["t0"] + TURN), msg, 2))
    if total > 0:
        lines.append(((tv + .15, T - .35), f"{BOSS_NAME} foi derrotado!", 1))
        lines.append(((tv + 1.1, T - .35), f"+{total} XP  +{total} de aura", 2))
    else:
        lines.append(((tv + .15, T - .35), f"{BOSS_NAME} fugiu...", 1))
        lines.append(((tv + 1.1, T - .35), "Faça commits para derrotá-lo!", 2))
    for (start, end), text, row in lines:
        k = A.show(start, end)
        y, color = (336, WHITE) if row == 1 else (368, CYAN)
        add(f'<text class="{k} fu" x="38" y="{y}" font-size="19" fill="{color}" '
            f'transform="rotate(-1.5 230 350)">{escape(text)}</text>')
    add(f'<path class="blink" d="M420 370h18l-9 11z" fill="{CYAN}"/>')

    # ---------------- status do herói
    level = max(1, int(math.sqrt(total)))
    add('<g transform="rotate(-3 740 340)">')
    add(f'<polygon points="660,296 834,288 830,392 654,396" fill="{WHITE}" stroke="{CYAN}" stroke-width="3" stroke-linejoin="miter"/>')
    add(f'<polygon points="660,296 672,295.5 666,395.6 654,396" fill="{BLUE}"/>')
    add(f'<polygon points="770,276 828,272 826,298 768,302" fill="{NAVY}" stroke="{CYAN}" stroke-width="2"/>')
    add(f'<text class="fd it" x="797" y="294" font-size="17" fill="{WHITE}" text-anchor="middle">LV{level}</text>')
    add(f'<text class="fd it" x="680" y="322" font-size="19" fill="{NAVY}" letter-spacing=".3">{escape(user.upper()[:11])}</text>')
    add(f'<text class="fd it" x="680" y="344" font-size="15" fill="{BLUE}">HP</text>')
    add(f'<rect x="706" y="333" width="110" height="11" fill="{NAVY}"/><rect x="708" y="335" width="106" height="7" fill="url(#barGrad)"/>')
    add(f'<text class="fd it" x="680" y="364" font-size="15" fill="{BLUE}">SP</text>')
    add(f'<rect x="706" y="353" width="110" height="11" fill="{NAVY}"/>')
    sp = [(0, "transform:scaleX(0)")]
    for t in turns:
        sp += [(t["t0"], "transform:scaleX(0)"), (t["t0"] + SP_FULL * TURN, "transform:scaleX(1)"),
               (t["hit"], "transform:scaleX(1)"), (t["hit"] + EPS, "transform:scaleX(0)")]
    sp += [(tv, "transform:scaleX(0)"), (tv + .8, "transform:scaleX(1)"), (T - .05, "transform:scaleX(1)"), (T, "transform:scaleX(0)")]
    k_sp = A.add(sp)
    add(f'<g transform="translate(708,355)"><rect class="{k_sp}" width="106" height="7" fill="{ICE}"/></g>')
    add(f'<text class="fu" x="680" y="385" font-size="12" fill="{NAVY}">Maior combo: {streak} dias</text>')
    add('</g>')

    # ---------------- números de dano
    for t in turns:
        h0 = t["hit"]
        k = A.add([(0, "opacity:0;transform:scale(.2)"), (h0, "opacity:0;transform:scale(.2)"),
                   (h0 + .05, "opacity:1;transform:scale(1.25)"), (h0 + .12, "opacity:1;transform:scale(1)"),
                   (h0 + .55, "opacity:1;transform:scale(1)"), (h0 + .66, "opacity:0;transform:scale(1.15)"),
                   (T, "opacity:0;transform:scale(1.15)")])
        rot = [-10, 6, -4, 9][t["i"] % 4]
        if t["n"] == 0:
            add(f'<g transform="translate({POP_X - 40},{POP_Y - 20}) rotate({rot})"><g class="{k}">'
                f'<polygon points="-50,-18 52,-22 48,18 -54,20" fill="{INK}" fill-opacity=".9" stroke="{ICE}" stroke-width="2"/>'
                f'<text class="fd it" x="0" y="10" font-size="28" fill="{ICE}" text-anchor="middle" letter-spacing="3">MISS</text></g></g>')
        elif t["lvl"] == 4:
            add(f'<g transform="translate({POP_X + 6},{POP_Y + 8}) rotate(-8)"><g class="{k}">'
                f'{spikes(92, 14, 3 + t["i"], [CERO_LIGHT, WHITE, INK])}'
                f'<g transform="translate(0,22)">{echo_text(str(t["n"]), 60, gap=8, echo=CERO_LIGHT)}</g>'
                f'<g transform="translate(8,-58) rotate(4)"><polygon points="-62,-17 64,-21 60,15 -66,19" fill="{WHITE}"/>'
                f'<polygon points="-66,19 60,15 59,19 -67,23" fill="{CERO_LIGHT}"/>'
                f'<text class="fd it" x="0" y="9" font-size="27" fill="{NAVY}" text-anchor="middle" letter-spacing="1">CRÍTICO!</text></g></g></g>')
        else:
            add(f'<g transform="translate({POP_X},{POP_Y}) rotate({rot})"><g class="{k}">'
                f'{spikes(58, 8, 5 + t["i"], [CYAN, ICE], r0=.3)}'
                f'<g transform="translate(0,15)">{echo_text(str(t["n"]), 42, gap=6, echo=BLUE)}</g></g></g>')

    # ---------------- faixas: intro, cut-in do crítico e vitória
    def band_anim(t_in, t_out, travel=1300):
        return A.add([(0, f"opacity:0;transform:translateX({travel}px)"), (t_in, f"opacity:0;transform:translateX({travel}px)"),
                      (t_in + EPS, f"opacity:1;transform:translateX({travel}px)"), (t_in + .13, "opacity:1;transform:translateX(0px)"),
                      (t_out - .13, "opacity:1;transform:translateX(-24px)"), (t_out, f"opacity:1;transform:translateX(-{travel}px)"),
                      (t_out + EPS, f"opacity:0;transform:translateX(-{travel}px)"), (T, f"opacity:0;transform:translateX(-{travel}px)")])

    k = band_anim(1.05, 2.15)
    add(f'<g transform="translate(420,166) rotate(-6)"><g class="{k}">{band(88)}'
        f'<g transform="translate(0,14)">{echo_text(BOSS_NAME, 52, echo=CYAN, gap=16)}</g></g></g>')

    for t in turns:
        if t["lvl"] != 4:
            continue
        k = band_anim(t["t0"] + .1, t["t0"] + .62)
        add(f'<g transform="translate(420,148) rotate(-7)"><g class="{k}">{band(100, "bandOsc", CERO_LIGHT)}'
            f'<g transform="translate(-10,12)">{echo_text(CERO_NAME, 54, echo=CERO_LIGHT, gap=16)}</g>'
            f'<text class="fd it" x="-10" y="38" font-size="15" fill="{ICE}" text-anchor="middle" letter-spacing="3">{ATTACKS[4]}</text></g></g>')

    banner = "VITÓRIA!" if total > 0 else "FUGIU!"
    k = band_anim(tv + 1.7, T - .35)
    add(f'<g transform="translate(420,142) rotate(-6)"><g class="{k}">{band(100)}'
        f'<g transform="translate(0,16)">{echo_text(banner, 66, echo=CYAN, gap=18)}</g></g></g>')
    if total > 0:
        k = A.add([(0, "opacity:0;transform:scale(.2)"), (tv + 2.0, "opacity:0;transform:scale(.2)"),
                   (tv + 2.1, "opacity:1;transform:scale(1.2)"), (tv + 2.2, "opacity:1;transform:scale(1)"),
                   (T - .45, "opacity:1;transform:scale(1)"), (T - .35, "opacity:0;transform:scale(1)")])
        add(f'<g transform="translate(268,236) rotate(5)"><g class="{k}">'
            f'<polygon points="-70,-20 72,-24 68,18 -74,22" fill="{WHITE}"/>'
            f'<polygon points="-74,22 68,18 67,23 -75,27" fill="{CYAN}"/>'
            f'<text class="fd it" x="0" y="10" font-size="28" fill="{NAVY}" text-anchor="middle">+{total} XP</text></g></g>')
    sparkle = sprite_sparkle()
    k_spark = A.show(tv + 1.8, T - .45)
    add(f'<g class="{k_spark}">')
    for i, (x, y, r) in enumerate([(120, 70, 12), (760, 200, 16), (560, 40, 10), (200, 250, 9), (60, 190, 14), (470, 60, 11)]):
        add(sparkle.image(round(x / P - 3) * P, round(y / P - 3) * P, cls="spark", style=f"animation-delay:-{i * .17:.2f}s"))
    add('</g>')

    # transição do loop
    k_fade = A.add([(0, "opacity:1"), (.4, "opacity:0"), (T - .4, "opacity:0"), (T, "opacity:1")])
    add(f'<rect class="{k_fade}" width="{W}" height="{H}" fill="{INK}" pointer-events="none"/>')
    add('</g>')

    style = f"""
.fd{{font-family:{DISPLAY};font-weight:700}}
.fu{{font-family:{UI};font-weight:700}}
.it{{font-style:italic}}
.outl{{paint-order:stroke;stroke:{INK};stroke-width:5px;stroke-linejoin:round}}
.px{{image-rendering:optimizeSpeed;image-rendering:crisp-edges;image-rendering:pixelated}}
.bob{{animation:bob 2.6s step-end infinite}}
.bob2{{animation:bob2 1.3s step-end infinite}}
.blink{{animation:blink .9s steps(1) infinite}}
.spark{{animation:spark .7s steps(3) infinite}}
.bubble{{animation:bubble 7s steps(100) infinite}}
.fly0{{animation:fly0 19s steps(380) infinite}}
.fly1{{animation:fly1 23s steps(460) infinite}}
.fly2{{animation:fly2 27s steps(540) infinite}}
@keyframes bob{{0%{{transform:translateY(0px)}}25%{{transform:translateY(-3px)}}50%{{transform:translateY(-6px)}}75%{{transform:translateY(-3px)}}100%{{transform:translateY(0px)}}}}
@keyframes bob2{{0%{{transform:translateY(0px)}}50%{{transform:translateY(-3px)}}100%{{transform:translateY(0px)}}}}
@keyframes blink{{0%{{opacity:1}}50%{{opacity:0}}}}
@keyframes spark{{0%,100%{{opacity:.15}}50%{{opacity:1}}}}
@keyframes bubble{{0%{{transform:translateY(0px);opacity:0}}15%{{opacity:.9}}100%{{transform:translateY(-300px);opacity:0}}}}
@keyframes fly0{{0%{{transform:translate(42px,120px)}}25%{{transform:translate(150px,87px)}}50%{{transform:translate(111px,210px)}}75%{{transform:translate(30px,171px)}}100%{{transform:translate(42px,120px)}}}}
@keyframes fly1{{0%{{transform:translate(471px,69px)}}30%{{transform:translate(561px,120px)}}60%{{transform:translate(441px,150px)}}100%{{transform:translate(471px,69px)}}}}
@keyframes fly2{{0%{{transform:translate(609px,261px)}}35%{{transform:translate(519px,231px)}}70%{{transform:translate(639px,111px)}}100%{{transform:translate(609px,261px)}}}}
{frame_css(2)}{frame_css(3)}{frame_css(4)}
@media (prefers-reduced-motion:reduce){{.bubble,.fly0,.fly1,.fly2{{animation:none}}}}
"""
    style += "".join(A.css)

    title = f"Boss battle: {user} causou {total} de dano no {BOSS_NAME} com commits dos últimos 12 meses"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" aria-label="{escape(title)}">'
            f'<title>{escape(title)}</title><style>{style}</style>{"".join(parts)}</svg>')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = args[0] if args else "boss-battle.svg"
    user = os.environ.get("GH_USER", "Fervalinhos")
    if "--mock" in sys.argv:
        months, streak = mock()
    else:
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise SystemExit("Defina GH_TOKEN (ou rode com --mock para testar).")
        months, streak = fetch(user, token)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(user, months, streak))
    total = sum(n for _, n in months)
    print(f"{out} gerado: {total} commits em {len(months)} turnos")


if __name__ == "__main__":
    main()
