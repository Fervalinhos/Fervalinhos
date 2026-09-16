#!/usr/bin/env python3
"""
Boss battle gerada a partir dos commits do GitHub, com visual inspirado em Persona 3 Reload
(azul profundo e ciano, lua cheia, cena submersa, tipografia itálica com rastro e vidro estilhaçado).

- HP do boss = commits dos últimos 12 meses
- Cada turno é um mês: o dano é a quantidade de commits daquele mês
- A lua do HUD vai enchendo a cada turno e fica cheia na vitória
- O golpe muda conforme o mês foi fraco ou forte (o melhor mês vira crítico, com cut-in)

Uso:
  GH_TOKEN=... GH_USER=Fervalinhos python boss_battle.py dist/boss-battle.svg
  python boss_battle.py preview.svg --mock      (dados de exemplo, sem API)

Sem dependências externas: só a biblioteca padrão do Python.
"""

import json
import math
import os
import random
import sys
import urllib.request
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

# Fontes do sistema (SVG em <img> não carrega fontes externas)
DISPLAY = "Impact,Haettenschweiler,'Franklin Gothic Heavy','Arial Narrow Bold','Arial Narrow','DejaVu Sans Condensed',sans-serif"
UI = "'Segoe UI','Helvetica Neue',Arial,'DejaVu Sans',sans-serif"

# Posições principais
BOSS_X, BOSS_Y, BOSS_S = 290, 172, 0.9
MOON_X, MOON_Y, MOON_R = 300, 140, 112
HERO_SPAWN = (532, 188)
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


def band(h=84):
    """Faixa diagonal de vidro azul com filetes brancos, centralizada em (0, 0)."""
    top, bot = -h / 2, h / 2
    return (f'<polygon points="{pts([(-780, top), (780, top - 12), (780, bot - 12), (-780, bot)])}" fill="url(#bandGrad)"/>'
            f'<polygon points="{pts([(-780, top), (780, top - 12), (780, top - 1), (-780, top + 11)])}" fill="{WHITE}" fill-opacity=".25"/>'
            f'<polygon points="{pts([(-780, top - 7), (780, top - 19), (780, top - 16), (-780, top - 4)])}" fill="{WHITE}"/>'
            f'<polygon points="{pts([(-780, bot + 4), (780, bot - 8), (780, bot - 5), (-780, bot + 7)])}" fill="{CYAN}"/>')


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
SHARDS = 6


def mirror(points):
    return [(-x, y) for x, y in points]


def boss_defs():
    legs = BOSS_LEGS + [mirror(p) for p in BOSS_LEGS]
    ants = BOSS_ANTENNAE + [mirror(p) for p in BOSS_ANTENNAE]
    silhouette = []
    for p in legs:
        silhouette.append(f'<polyline points="{pts(p)}" fill="none" stroke="currentColor" stroke-width="19" stroke-linejoin="miter"/>')
    for p in ants:
        silhouette.append(f'<polyline points="{pts(p)}" fill="none" stroke="currentColor" stroke-width="12" stroke-linejoin="miter"/>')
    for p in (BOSS_ABDOMEN, BOSS_HEAD, BOSS_CROWN):
        silhouette.append(f'<polygon points="{pts(p)}" fill="currentColor" stroke="currentColor" stroke-width="12" stroke-linejoin="miter"/>')
    body = []
    for p in legs:
        body.append(f'<polyline points="{pts(p)}" fill="none" stroke="{INK}" stroke-width="9" stroke-linejoin="miter"/>')
    for p in ants:
        body.append(f'<polyline points="{pts(p)}" fill="none" stroke="{INK}" stroke-width="4"/>')
    body.append(f'<polygon points="{pts(BOSS_ABDOMEN)}" fill="url(#bossGrad)"/>')
    body.append(f'<polygon points="{pts(BOSS_HEAD)}" fill="{INK}"/>')
    body.append(f'<polygon points="{pts(BOSS_CROWN)}" fill="{CYAN}" stroke="{INK}" stroke-width="3" stroke-linejoin="miter"/>')
    eye = [(-32, -48), (-8, -38), (-12, -30), (-30, -36)]
    body.append(f'<polygon points="{pts(eye)}" fill="{WHITE}"/><polygon points="{pts(mirror(eye))}" fill="{WHITE}"/>')
    body.append(f'<rect x="-20" y="-40" width="6" height="6" fill="{BLUE}"/><rect x="14" y="-40" width="6" height="6" fill="{BLUE}"/>')
    fang = [(-14, -22), (-6, -4), (-2, -20)]
    body.append(f'<polygon points="{pts(fang)}" fill="{WHITE}"/><polygon points="{pts(mirror(fang))}" fill="{WHITE}"/>')
    for y in (16, 44, 70):
        s = 1 - (y - 16) / 140
        body.append(f'<polyline points="{pts([(-44 * s, y), (0, y + 20 * s), (44 * s, y)])}" fill="none" stroke="{CYAN}" stroke-width="6" stroke-linejoin="miter"/>')
    wedges = []
    for k in range(SHARDS):
        a1 = math.radians(k * 360 / SHARDS - 90 + 12)
        a2 = math.radians((k + 1) * 360 / SHARDS - 90 + 12)
        wedges.append(f'<clipPath id="shard{k}"><polygon points="0,0 {math.cos(a1) * 700:.0f},{math.sin(a1) * 700:.0f} '
                      f'{math.cos((a1 + a2) / 2) * 700:.0f},{math.sin((a1 + a2) / 2) * 700:.0f} '
                      f'{math.cos(a2) * 700:.0f},{math.sin(a2) * 700:.0f}"/></clipPath>')
    return (f'<g id="bossSil">{"".join(silhouette)}</g>'
            f'<g id="bossArt"><use href="#bossSil" filter="url(#glow)" style="color:{CYAN}" opacity=".75"/>'
            f'<use href="#bossSil" transform="translate(9,8)" style="color:{NAVY}"/>'
            f'<use href="#bossSil" style="color:{WHITE}"/>{"".join(body)}</g>'
            f'{"".join(wedges)}')


# Herói visto de costas (moletom com capuz), em primeiro plano.
HERO_BODY = [(474, 400), (484, 350), (500, 322), (530, 306), (560, 302), (590, 306), (620, 322), (636, 350), (646, 400)]
HERO_HEAD = [(522, 276), (516, 250), (524, 228), (514, 214), (536, 212), (542, 194), (556, 206), (570, 190),
             (578, 208), (598, 200), (594, 222), (606, 232), (602, 256), (596, 278), (560, 292), (524, 290)]
HERO_HOOD = [(518, 310), (540, 290), (580, 290), (602, 310), (586, 330), (560, 338), (534, 330)]


def hero_art():
    shapes = [HERO_BODY, HERO_HEAD, HERO_HOOD]
    out = [f'<polygon points="{pts(p)}" fill="{CYAN}" stroke="{CYAN}" stroke-width="14" stroke-linejoin="miter" filter="url(#glow)" opacity=".55"/>' for p in shapes]
    out += [f'<polygon points="{pts(p)}" fill="{WHITE}" stroke="{WHITE}" stroke-width="8" stroke-linejoin="miter"/>' for p in shapes]
    out.append(f'<polygon points="{pts(HERO_BODY)}" fill="{INK}"/>')
    out.append(f'<polyline points="500,322 530,306 540,400" fill="none" stroke="{BLUE}" stroke-width="5"/>')
    out.append(f'<polyline points="620,322 590,306 580,400" fill="none" stroke="{BLUE}" stroke-width="5"/>')
    out.append(f'<polygon points="{pts(HERO_HEAD)}" fill="{INK}"/>')
    out.append(f'<polyline points="{pts(HERO_HEAD[3:11])}" fill="none" stroke="{BLUE}" stroke-width="3" stroke-opacity=".8"/>')
    out.append(f'<polygon points="{pts(HERO_HOOD)}" fill="{INK}" stroke="{CYAN}" stroke-width="2.5" stroke-linejoin="miter"/>')
    out.append(f'<text class="fu" x="560" y="378" font-size="28" fill="{CYAN}" text-anchor="middle">&lt;/&gt;</text>')
    return "".join(out)


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

    # ---------------- defs
    add('<defs>'
        f'<clipPath id="card"><polygon points="16,0 {W},0 {W},{H - 16} {W - 16},{H} 0,{H} 0,16"/></clipPath>'
        f'<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{INK}"/>'
        f'<stop offset=".55" stop-color="{NAVY}"/><stop offset="1" stop-color="{BLUE}"/></linearGradient>'
        f'<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NAVY}"/><stop offset="1" stop-color="{INK}"/></linearGradient>'
        f'<radialGradient id="moonGrad" cx=".42" cy=".38" r=".7"><stop offset="0" stop-color="{WHITE}"/>'
        f'<stop offset=".6" stop-color="{ICE}"/><stop offset="1" stop-color="#7fd6ff"/></radialGradient>'
        f'<radialGradient id="halo"><stop offset=".55" stop-color="{CYAN}" stop-opacity=".55"/>'
        f'<stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="bandGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{INK}" stop-opacity=".92"/>'
        f'<stop offset=".5" stop-color="{BLUE}" stop-opacity=".95"/><stop offset="1" stop-color="{INK}" stop-opacity=".92"/></linearGradient>'
        f'<linearGradient id="bossGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{INK}"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>'
        f'<linearGradient id="barGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>'
        '<filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="6"/></filter>'
        f'{boss_defs()}'
        '</defs>')
    add('<g clip-path="url(#card)">')
    add(f'<rect width="{W}" height="{H}" fill="url(#sky)"/>')

    # feixes de luz vindos da superfície
    for x, w in ((40, 70), (170, 40), (430, 90), (610, 50)):
        add(f'<polygon points="{x},0 {x + w},0 {x + w - 160},300 {x - 190},300" fill="{ICE}" fill-opacity=".06"/>')

    # lua cheia atrás do boss
    add(f'<circle class="pulse" cx="{MOON_X}" cy="{MOON_Y}" r="{MOON_R + 46}" fill="url(#halo)"/>')
    add(f'<circle cx="{MOON_X}" cy="{MOON_Y}" r="{MOON_R}" fill="url(#moonGrad)"/>')
    for dx, dy, r in ((-48, -30, 18), (30, 40, 26), (52, -46, 12), (-20, 60, 10), (-70, 30, 8), (10, -8, 7)):
        add(f'<circle cx="{MOON_X + dx}" cy="{MOON_Y + dy}" r="{r}" fill="#8fdcff" fill-opacity=".35"/>')

    # bolhas subindo
    for k in range(22):
        x = rnd.randint(10, 830)
        r = rnd.choice([2, 3, 3, 4, 6])
        dur = rnd.uniform(5, 10)
        add(f'<circle class="bubble" cx="{x}" cy="{rnd.randint(250, 330)}" r="{r}" fill="none" stroke="{ICE}" stroke-width="1.5" '
            f'style="animation-duration:{dur:.1f}s;animation-delay:-{rnd.uniform(0, dur):.1f}s"/>')

    # painel escuro no canto do turno
    add(f'<polygon points="590,0 {W},0 {W},118 700,104" fill="{INK}" fill-opacity=".82"/>')
    add(f'<polygon points="700,104 {W},118 {W},122 698,108" fill="{CYAN}"/>')

    # chão submerso com ondas
    add(f'<polygon points="0,300 {W},262 {W},{H} 0,{H}" fill="url(#floor)"/>')
    add(f'<polygon points="0,297 {W},259 {W},263 0,301" fill="{CYAN}"/>')
    for k, y in enumerate((318, 340, 366, 392)):
        path = "M-40 " + " ".join(f"Q{x + 30} {y - 6 - k * 9} {x + 60} {y - k * 9}" for x in range(-40, 900, 60))
        add(f'<path class="wave" d="{path}" fill="none" stroke="{CYAN}" stroke-opacity="{.35 - k * .06:.2f}" stroke-width="2" '
            f'stroke-dasharray="70 50" style="animation-duration:{4 + k * 1.3:.1f}s" transform="rotate(-2.6 420 330)"/>')
    k_ground = A.show(0.45, death + .5 if total > 0 else T)
    add(f'<ellipse class="{k_ground}" cx="{BOSS_X}" cy="{BOSS_Y + 100}" rx="96" ry="9" fill="{INK}" fill-opacity=".6"/>')

    # ---------------- boss
    life = [(0, "opacity:0"), (0.35, "opacity:0"), (0.45, "opacity:1"), (0.55, "opacity:.15"),
            (0.65, "opacity:1"), (0.75, "opacity:.25"), (0.9, "opacity:1"), (tv, "opacity:1")]
    if total > 0:
        for k in range(5):
            life.append((tv + 0.12 * (k + 1), f"opacity:{'.2' if k % 2 == 0 else '1'}"))
        life += [(death, "opacity:1"), (death + EPS, "opacity:0"), (T, "opacity:0")]
    k_life = A.add(life)

    shake = [(0, "transform:translateX(0px)")]
    flash = [(0, "opacity:0")]
    for t in hits:
        a = 14 if t["lvl"] == 4 else 8
        h0 = t["hit"]
        shake += [(h0, "transform:translateX(0px)"), (h0 + .04, f"transform:translateX(-{a}px)"),
                  (h0 + .08, f"transform:translateX({a}px)"), (h0 + .12, f"transform:translateX(-{a * .6:.1f}px)"),
                  (h0 + .16, f"transform:translateX({a * .6:.1f}px)"), (h0 + .22, "transform:translateX(0px)")]
        flash += [(h0, "opacity:0"), (h0 + .01, "opacity:.95"), (h0 + .07, "opacity:0"),
                  (h0 + .12, "opacity:.6"), (h0 + .17, "opacity:0")]
    if total > 0:
        flash += [(tv, "opacity:0"), (tv + .05, "opacity:.9"), (tv + .2, "opacity:0"), (tv + .45, "opacity:.8"), (tv + .6, "opacity:0")]
    k_shake = A.add(shake)
    k_flash = A.add(flash)

    add(f'<g transform="translate({BOSS_X},{BOSS_Y}) scale({BOSS_S})"><g class="bob"><g class="{k_shake}">')
    add(f'<g class="{k_life}"><use href="#bossArt"/></g>')
    add(f'<g class="{k_flash}"><use href="#bossSil" style="color:{WHITE}"/></g>')
    if total > 0:
        # estilhaça como vidro
        gone = "opacity:0;transform:translate({x:.1f}px,{y:.1f}px) rotate({r:.1f}deg)"
        for k in range(SHARDS):
            mid = math.radians((k + .5) * 360 / SHARDS - 90 + 12)
            dx, dy, rot = math.cos(mid) * 70, math.sin(mid) * 70 + 30, (-1) ** k * 16
            k_shard = A.add([(0, gone.format(x=0, y=0, r=0)), (death, gone.format(x=0, y=0, r=0)),
                             (death + EPS, "opacity:1;transform:translate(0px,0px) rotate(0deg)"),
                             (death + .12, "opacity:1;transform:translate(0px,0px) rotate(0deg)"),
                             (death + .5, f"opacity:1;transform:translate({dx * .5:.1f}px,{dy * .5:.1f}px) rotate({rot * .5:.1f}deg)"),
                             (death + 1.0, gone.format(x=dx, y=dy, r=rot)), (T, gone.format(x=dx, y=dy, r=rot))])
            add(f'<g class="{k_shard}"><g clip-path="url(#shard{k})"><use href="#bossArt"/></g></g>')
        k_crack = A.add([(0, "opacity:0;stroke-dashoffset:150"), (death - .14, "opacity:0;stroke-dashoffset:150"),
                         (death - .13, "opacity:1;stroke-dashoffset:150"), (death, "opacity:1;stroke-dashoffset:0"),
                         (death + .3, "opacity:0;stroke-dashoffset:0")])
        add(f'<g class="{k_crack}" stroke="{WHITE}" stroke-width="4" stroke-dasharray="150" fill="none">')
        for k in range(SHARDS):
            a = math.radians(k * 360 / SHARDS - 90 + 12)
            add(f'<path d="M0 0L{math.cos(a) * 70:.0f} {math.sin(a) * 70 + 8:.0f}L{math.cos(a) * 150:.0f} {math.sin(a) * 150:.0f}"/>')
        add('</g>')
    add('</g></g></g>')

    # cortes do golpe
    slash = [(0, "opacity:0;stroke-dashoffset:200")]
    for t in hits:
        h0 = t["hit"]
        slash += [(h0 - .01, "opacity:0;stroke-dashoffset:200"), (h0, "opacity:1;stroke-dashoffset:200"),
                  (h0 + .08, "opacity:1;stroke-dashoffset:0"), (h0 + .18, "opacity:0;stroke-dashoffset:0")]
    k_slash = A.add(slash)
    add(f'<g class="{k_slash}" fill="none" stroke-dasharray="200">')
    for dx in (-28, 0, 28):
        x1, y1, x2, y2 = BOSS_X + 64 + dx, BOSS_Y - 68, BOSS_X - 64 + dx, BOSS_Y + 68
        add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{CYAN}" stroke-width="10" stroke-opacity=".6"/>')
        add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{WHITE}" stroke-width="3"/>')
    add('</g>')

    # ---------------- herói
    lunge = [(0, "transform:translate(0px,0px)")]
    for t in turns:
        lunge += [(t["throw"] - .14, "transform:translate(0px,0px)"), (t["throw"], "transform:translate(-16px,-10px)"),
                  (t["throw"] + .24, "transform:translate(0px,0px)")]
    k_lunge = A.add(lunge)
    jump = [(0, "transform:translateY(0px)"), (tv + .9, "transform:translateY(0px)")]
    for k in range(3):
        base = tv + .9 + k * .44
        jump += [(base + .22, "transform:translateY(-16px)"), (base + .44, "transform:translateY(0px)")]
    k_jump = A.add(jump)
    add(f'<g class="{k_lunge}"><g class="{k_jump}"><g class="bob2">{hero_art()}</g></g></g>')

    # cristal arremessado
    sx, sy = HERO_SPAWN
    proj = [(0, f"opacity:0;transform:translate({sx}px,{sy}px) rotate(0deg) scale(1)")]
    for t in turns:
        sc = 0.8 + t["lvl"] * 0.14
        tx, ty = (BOSS_X, BOSS_Y) if t["n"] > 0 else (BOSS_X - 30, BOSS_Y - 150)
        end_op = 1 if t["n"] > 0 else 0
        proj += [(t["throw"] - EPS, f"opacity:0;transform:translate({sx}px,{sy}px) rotate(0deg) scale({sc})"),
                 (t["throw"], f"opacity:1;transform:translate({sx}px,{sy}px) rotate(0deg) scale({sc})"),
                 (t["hit"], f"opacity:{end_op};transform:translate({tx}px,{ty}px) rotate(-540deg) scale({sc})"),
                 (t["hit"] + EPS, f"opacity:0;transform:translate({tx}px,{ty}px) rotate(-540deg) scale({sc})")]
    k_proj = A.add(proj)
    add(f'<g class="{k_proj}"><path d="{star4(0, 0, 22)}" fill="{CYAN}" fill-opacity=".45"/>'
        f'<path d="{star4(0, 0, 15)}" fill="{WHITE}" stroke="{BLUE}" stroke-width="2" stroke-linejoin="miter"/></g>')

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
        lines.append(((t["t0"], t["t0"] + TURN), f"{user} usou {ATTACKS[t['lvl']]}!", 1))
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
                f'{spikes(92, 14, 3 + t["i"], [CYAN, WHITE, BLUE])}'
                f'<g transform="translate(0,22)">{echo_text(str(t["n"]), 60, gap=8, echo=BLUE)}</g>'
                f'<g transform="translate(8,-58) rotate(4)"><polygon points="-62,-17 64,-21 60,15 -66,19" fill="{WHITE}"/>'
                f'<polygon points="-66,19 60,15 59,19 -67,23" fill="{CYAN}"/>'
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

    k = band_anim(0.3, 2.0)
    add(f'<g transform="translate(420,166) rotate(-6)"><g class="{k}">{band(88)}'
        f'<g transform="translate(0,14)">{echo_text(BOSS_NAME, 52, echo=CYAN, gap=16)}</g></g></g>')

    for t in turns:
        if t["lvl"] != 4:
            continue
        k = band_anim(t["throw"] - .22, t["hit"] + .06)
        add(f'<g transform="translate(420,150) rotate(-7)"><g class="{k}">{band(78)}'
            f'<g transform="translate(-6,8)">{echo_text(ATTACKS[4], 40, echo=CYAN, gap=14)}</g></g></g>')

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
    k_spark = A.show(tv + 1.8, T - .45)
    add(f'<g class="{k_spark}">')
    for i, (x, y, r) in enumerate([(120, 70, 12), (760, 200, 16), (560, 40, 10), (200, 250, 9), (60, 190, 14), (470, 60, 11)]):
        add(f'<path class="spark" style="animation-delay:-{i * .17:.2f}s" d="{star4(x, y, r)}" fill="{ICE}"/>')
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
.bob{{animation:bob 2.6s ease-in-out infinite}}
.bob2{{animation:bob2 1.3s ease-in-out infinite}}
.blink{{animation:blink .9s steps(1) infinite}}
.spark{{animation:spark .7s ease-in-out infinite}}
.pulse{{animation:pulse 4s ease-in-out infinite}}
.bubble{{animation:bubble 7s linear infinite}}
.wave{{animation:wave 5s linear infinite}}
@keyframes bob{{0%,100%{{transform:translateY(0px)}}50%{{transform:translateY(-7px)}}}}
@keyframes bob2{{0%,100%{{transform:translateY(0px)}}50%{{transform:translateY(-2px)}}}}
@keyframes blink{{0%{{opacity:1}}50%{{opacity:0}}}}
@keyframes spark{{0%,100%{{opacity:.15}}50%{{opacity:1}}}}
@keyframes pulse{{0%,100%{{opacity:.7}}50%{{opacity:1}}}}
@keyframes bubble{{0%{{transform:translateY(0px);opacity:0}}15%{{opacity:.8}}100%{{transform:translateY(-300px);opacity:0}}}}
@keyframes wave{{from{{stroke-dashoffset:0}}to{{stroke-dashoffset:-120}}}}
@media (prefers-reduced-motion:reduce){{.bubble,.wave,.pulse{{animation:none}}}}
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
