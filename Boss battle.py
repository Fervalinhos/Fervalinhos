#!/usr/bin/env python3
"""
Boss battle estilo RPG gerada a partir dos commits do GitHub.

- HP do boss = commits dos últimos 12 meses
- Cada turno é um mês: o dano é a quantidade de commits daquele mês
- O golpe muda conforme o mês foi fraco ou forte (o melhor mês vira crítico)

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
ATB_FULL = 0.30  # fração do turno em que a barra ATB enche
THROW = 0.38     # fração do turno em que o golpe sai
HIT = 0.58       # fração do turno em que o golpe acerta

W, H = 840, 400
BOSS_NAME = "BUG LORD"

# Golpes: índice = nível do mês
ATTACKS = ["GIT STATUS", "GIT COMMIT", "GIT PUSH", "GIT MERGE", "GIT PUSH --FORCE"]
MENU = ["STATUS", "COMMIT", "PUSH", "MERGE", "FORCE"]
BLOCK_COLORS = ["#30363d", "#0e4429", "#006d32", "#26a641", "#39d353"]  # tons do gráfico de contribuições

FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono','Courier New',monospace"


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


def sprite(rows, palette, px, ox, oy, solid=None):
    """Desenha pixel art juntando pixels vizinhos da mesma cor em um único rect."""
    out = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            c = row[x]
            if c == ".":
                x += 1
                continue
            x2 = x
            while x2 < len(row) and row[x2] != "." and (solid or row[x2] == c):
                x2 += 1
            color = solid or palette[c]
            out.append(f'<rect x="{ox + x * px}" y="{oy + y * px}" width="{(x2 - x) * px}" height="{px}" fill="{color}"/>')
            x = x2
    return "".join(out)


BOSS = [
    "...K.................K...",
    "....K....G..G..G....K....",
    ".....K...GgGGGgG...K.....",
    "......KKKGGGGGGGKKK......",
    ".......KPPPPPPPPPK.......",
    "......KPpRRPPPRRpPK......",
    "......KPPRYPPPYRPPK......",
    "......KDPPPPPPPPPDK......",
    "....KKKDWDPPPPPDWDKKK....",
    "...KPPPDWPDDDDDPWDPPPK...",
    "LLLKpPPCPPPPPPPPPCPPpKLLL",
    "L..KPPPCPPPCCCPPPCPPPK..L",
    "LLLKDPPCCCCCCCCCCCPPDKLLL",
    "L..KDPPPPPPPCPPPPPPPDK..L",
    "LLLKDDPPPPPPCPPPPPPDDKLLL",
    "L...KDDPPPPPPPPPPPDDK...L",
    "L....KKDDDDDDDDDDDKK....L",
    "L......KKKKKKKKKKK......L",
    "KK.....................KK",
]
BOSS_PALETTE = {
    "K": "#12071a", "P": "#6b2fa0", "p": "#a45ee0", "D": "#3d1766",
    "R": "#ff3b3b", "Y": "#ffd23f", "W": "#f4f4f4", "G": "#f5c542",
    "g": "#a8740c", "L": "#5a3590", "C": "#39d353",
}

HERO = [
    "..x.............",
    "..X....KKKK.....",
    "..X...KHHHHK....",
    "..X..KHHHHHHK...",
    "..X..KHSSHHHK...",
    "..X..KSESSHHK...",
    "..X..KSSSSSK....",
    "..X...KsSSK.....",
    ".hhh.KBBBBBK....",
    "..S.KBBBBBBBK...",
    "..SSBBBbBBBBK...",
    "...KBBBbBBBBK...",
    "...KBBBBBBBBK...",
    "....KBBBBBBK....",
    "....KNNNNNNK....",
    "....KNNKKNNK....",
    "....KNNK.KNNK...",
    "...KOOOK.KOOOK..",
    "...KKKKK.KKKKK..",
]
HERO_PALETTE = {
    "K": "#0a0a14", "H": "#2b1b12", "S": "#f1c27d", "s": "#c68e55", "E": "#111111",
    "B": "#1f6feb", "b": "#0b3d91", "N": "#2d2d3a", "O": "#16161f",
    "X": "#9fe8ff", "x": "#ffffff", "h": "#f5c542",
}


def hp_color(ratio):
    return "#3fb950" if ratio > 0.5 else "#f5c542" if ratio > 0.2 else "#f85149"


def build(user, months, streak):
    turns_n = len(months)
    total = sum(n for _, n in months)
    max_hp = max(total, 1)
    peak = max((n for _, n in months), default=0)
    tv = INTRO + turns_n * TURN
    T = tv + VICTORY
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

    boss_px, boss_x, boss_y = 8, 100, 72
    boss_cx, boss_cy = boss_x + 25 * boss_px // 2, boss_y + 19 * boss_px // 2
    hero_px, hero_x, hero_y = 5, 650, 124
    parts = []
    add = parts.append

    # ---------------- cenário
    add('<defs>'
        '<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#060a1c"/><stop offset="1" stop-color="#1e1350"/></linearGradient>'
        '<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#241760"/><stop offset="1" stop-color="#07071a"/></linearGradient>'
        '<linearGradient id="win" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2f43b0"/><stop offset="1" stop-color="#0b1256"/></linearGradient>'
        '<clipPath id="card"><rect width="840" height="400" rx="12"/></clipPath>'
        '<clipPath id="floorclip"><rect x="0" y="192" width="840" height="70"/></clipPath>'
        '</defs>')
    add('<g clip-path="url(#card)">')
    add('<rect width="840" height="400" fill="#05060f"/>')
    add('<rect width="840" height="262" fill="url(#sky)"/>')

    rnd = random.Random(42)
    for _ in range(46):
        x, y = rnd.randint(4, 836), rnd.randint(6, 170)
        size = rnd.choice([1, 2, 2, 3])
        cls = rnd.choice(["tw1", "tw2", "tw3", ""])
        delay = f' style="animation-delay:-{rnd.random() * 3:.2f}s"' if cls else ""
        add(f'<rect class="{cls}" x="{x}" y="{y}" width="{size}" height="{size}" fill="#c9d1ff" opacity="{rnd.choice([0.35, 0.6, 0.9])}"{delay}/>')

    # racks de servidor no horizonte
    rx = 0
    while rx < 840:
        w = rnd.randint(34, 64)
        h = rnd.randint(26, 58)
        if rnd.random() < 0.75:
            add(f'<rect x="{rx}" y="{192 - h}" width="{w}" height="{h}" fill="#110c33"/>')
            for ly in range(192 - h + 8, 188, 9):
                for lx in range(rx + 6, rx + w - 6, 10):
                    if rnd.random() < 0.35:
                        color = rnd.choice(["#39d353", "#58a6ff", "#39d353"])
                        cls = rnd.choice(["led1", "led2", "led3"])
                        add(f'<rect class="{cls}" x="{lx}" y="{ly}" width="3" height="2" fill="{color}" style="animation-delay:-{rnd.random() * 2:.2f}s"/>')
        rx += w + rnd.randint(4, 40)

    add('<rect x="0" y="192" width="840" height="70" fill="url(#floor)"/>')
    add('<g clip-path="url(#floorclip)" stroke="#5b46c9" stroke-opacity=".35" stroke-width="1">')
    for k in range(-14, 15):
        add(f'<line x1="420" y1="150" x2="{420 + k * 70}" y2="262"/>')
    for k in range(1, 7):
        y = 192 + int((k / 6) ** 2 * 70)
        add(f'<line x1="0" y1="{y}" x2="840" y2="{y}"/>')
    add('</g>')

    # ---------------- boss
    boss_life = [
        (0, "opacity:0;transform:translateY(0px)"), (0.35, "opacity:0;transform:translateY(0px)"),
        (0.45, "opacity:1;transform:translateY(0px)"), (0.55, "opacity:.15;transform:translateY(0px)"),
        (0.65, "opacity:1;transform:translateY(0px)"), (0.75, "opacity:.25;transform:translateY(0px)"),
        (0.9, "opacity:1;transform:translateY(0px)"), (tv, "opacity:1;transform:translateY(0px)"),
    ]
    for k in range(5):
        boss_life.append((tv + 0.12 * (k + 1), f"opacity:{'.15' if k % 2 == 0 else '1'};transform:translateY(0px)"))
    boss_life += [(tv + 1.4, "opacity:0;transform:translateY(16px)"), (T, "opacity:0;transform:translateY(16px)")]
    k_life = A.add(boss_life)
    shadow_life = A.add([(f, p.split(";")[0]) for f, p in boss_life])

    shake = [(0, "transform:translateX(0px)")]
    flash = [(0, "opacity:0")]
    for t in hits:
        a = 13 if t["lvl"] == 4 else 8
        h0 = t["hit"]
        shake += [(h0, "transform:translateX(0px)"), (h0 + .04, f"transform:translateX(-{a}px)"),
                  (h0 + .08, f"transform:translateX({a}px)"), (h0 + .12, f"transform:translateX(-{a * .6:.1f}px)"),
                  (h0 + .16, f"transform:translateX({a * .6:.1f}px)"), (h0 + .22, "transform:translateX(0px)")]
        flash += [(h0, "opacity:0"), (h0 + .01, "opacity:.95"), (h0 + .07, "opacity:0"),
                  (h0 + .12, "opacity:.6"), (h0 + .17, "opacity:0")]
    flash += [(tv, "opacity:0"), (tv + .05, "opacity:.9"), (tv + .2, "opacity:0"), (tv + .5, "opacity:.7"), (tv + .7, "opacity:0")]
    k_shake = A.add(shake)
    k_flash = A.add(flash)

    add(f'<ellipse class="{shadow_life}" cx="{boss_cx}" cy="{boss_y + 19 * boss_px + 4}" rx="92" ry="9" fill="#000" fill-opacity=".5"/>')
    add(f'<g class="{k_life}"><g class="{k_shake}"><g class="bob">')
    add(sprite(BOSS, BOSS_PALETTE, boss_px, boss_x, boss_y))
    add(f'<g class="{k_flash}">{sprite(BOSS, BOSS_PALETTE, boss_px, boss_x, boss_y, solid="#ffffff")}</g>')
    add('</g></g></g>')

    # cortes do golpe
    slash = [(0, "opacity:0;stroke-dashoffset:190")]
    for t in hits:
        h0 = t["hit"]
        slash += [(h0 - .01, "opacity:0;stroke-dashoffset:190"), (h0, "opacity:1;stroke-dashoffset:190"),
                  (h0 + .08, "opacity:1;stroke-dashoffset:0"), (h0 + .16, "opacity:0;stroke-dashoffset:0")]
    k_slash = A.add(slash)
    add(f'<g class="{k_slash}" fill="none" stroke-linecap="square" stroke-dasharray="190">')
    for dx in (-26, 0, 26):
        add(f'<line x1="{boss_cx - 62 + dx}" y1="{boss_cy - 64}" x2="{boss_cx + 62 + dx}" y2="{boss_cy + 64}" stroke="#9fe8ff" stroke-width="7" stroke-opacity=".5"/>')
        add(f'<line x1="{boss_cx - 62 + dx}" y1="{boss_cy - 64}" x2="{boss_cx + 62 + dx}" y2="{boss_cy + 64}" stroke="#ffffff" stroke-width="3"/>')
    add('</g>')

    # ---------------- herói
    lunge = [(0, "transform:translateX(0px)")]
    for t in turns:
        lunge += [(t["throw"] - .14, "transform:translateX(0px)"), (t["throw"], "transform:translateX(-30px)"),
                  (t["throw"] + .22, "transform:translateX(0px)")]
    k_lunge = A.add(lunge)
    jump = [(0, "transform:translateY(0px)"), (tv + .9, "transform:translateY(0px)")]
    for k in range(3):
        base = tv + .9 + k * .44
        jump += [(base + .22, "transform:translateY(-20px)"), (base + .44, "transform:translateY(0px)")]
    k_jump = A.add(jump)
    add(f'<ellipse cx="{hero_x + 40}" cy="{hero_y + 19 * hero_px + 3}" rx="30" ry="6" fill="#000" fill-opacity=".5"/>')
    add(f'<g class="{k_lunge}"><g class="{k_jump}"><g class="bob2">')
    add(sprite(HERO, HERO_PALETTE, hero_px, hero_x, hero_y))
    add('</g></g></g>')

    # bloco de contribuição arremessado
    sx, sy = hero_x + 12, hero_y + 30
    proj = [(0, f"opacity:0;transform:translate({sx}px,{sy}px) rotate(0deg);fill:{BLOCK_COLORS[1]}")]
    for t in turns:
        c = BLOCK_COLORS[t["lvl"]]
        tx, ty = (boss_cx, boss_cy) if t["n"] > 0 else (boss_cx - 20, boss_y - 40)
        end_op = 1 if t["n"] > 0 else 0
        proj += [(t["throw"] - EPS, f"opacity:0;transform:translate({sx}px,{sy}px) rotate(0deg);fill:{c}"),
                 (t["throw"], f"opacity:1;transform:translate({sx}px,{sy}px) rotate(0deg);fill:{c}"),
                 (t["hit"], f"opacity:{end_op};transform:translate({tx}px,{ty}px) rotate(-720deg);fill:{c}"),
                 (t["hit"] + EPS, f"opacity:0;transform:translate({tx}px,{ty}px) rotate(-720deg);fill:{c}")]
    k_proj = A.add(proj)
    add(f'<rect class="{k_proj}" x="-10" y="-10" width="20" height="20" rx="4" stroke="#aff5b4" stroke-width="2"/>')

    # números de dano (desenhados depois do HUD, para ficarem por cima)
    pops = []
    for t in turns:
        h0 = t["hit"]
        k = A.add([(0, "opacity:0;transform:translateY(8px)"), (h0, "opacity:0;transform:translateY(8px)"),
                   (h0 + .03, "opacity:1;transform:translateY(0px)"), (h0 + .14, "opacity:1;transform:translateY(-12px)"),
                   (h0 + .5, "opacity:1;transform:translateY(-20px)"), (h0 + .62, "opacity:0;transform:translateY(-26px)"),
                   (T, "opacity:0;transform:translateY(-26px)")])
        if t["n"] == 0:
            pops.append(f'<text class="{k} pop" x="{boss_cx}" y="{boss_y + 40}" fill="#8b949e">MISS</text>')
        elif t["lvl"] == 4:
            pops.append(f'<g class="{k}"><text class="pop small" x="{boss_cx}" y="{boss_cy - 34}" fill="#ffd23f">CRÍTICO!</text>'
                f'<text class="pop big" x="{boss_cx}" y="{boss_cy + 4}" fill="#ffd23f">{t["n"]}</text></g>')
        else:
            pops.append(f'<text class="{k} pop" x="{boss_cx}" y="{boss_cy}" fill="#ffffff">{t["n"]}</text>')

    # ---------------- vitória
    k_vic = A.add([(0, "opacity:0;transform:scale(.5)"), (tv + .9, "opacity:0;transform:scale(.5)"),
                   (tv + 1.15, "opacity:1;transform:scale(1.12)"), (tv + 1.32, "opacity:1;transform:scale(1)"),
                   (T - .45, "opacity:1;transform:scale(1)"), (T - .3, "opacity:0;transform:scale(1)")],
                  extra="transform-box:fill-box;transform-origin:center")
    banner = "VITÓRIA!" if total > 0 else "FUGIU!"
    add(f'<text class="{k_vic} banner" x="420" y="118">{banner}</text>')
    k_spark = A.show(tv + 1.1, T - .45)
    add(f'<g class="{k_spark}">')
    for i, (x, y) in enumerate([(610, 90), (748, 120), (690, 70), (560, 150), (300, 70), (250, 160)]):
        add(f'<path class="spark" style="animation-delay:-{i * .17:.2f}s" d="M{x} {y - 8}v16M{x - 8} {y}h16" stroke="#ffd23f" stroke-width="3"/>')
    add('</g>')

    # ---------------- HUD topo: boss
    add('<g transform="translate(16,14)">')
    add('<rect width="318" height="52" rx="6" fill="#0a0e2e" fill-opacity=".88" stroke="#e8ebff" stroke-width="2"/>')
    add(f'<text class="t" x="12" y="21">{BOSS_NAME}</text>')
    segments = [(0, total)] + [(t["hit"] + .1, t["hp_after"]) for t in hits]
    for idx, (start, value) in enumerate(segments):
        end = segments[idx + 1][0] if idx + 1 < len(segments) else T
        if idx == len(segments) - 1:
            end = T - .05
        k = A.show(start, end)
        add(f'<text class="{k} t" x="306" y="21" text-anchor="end">HP {value}/{total}</text>')
    if segments[-1][0] > 0:
        k = A.show(T - .05, T)
        add(f'<text class="{k} t" x="306" y="21" text-anchor="end">HP {total}/{total}</text>')
    add('<rect x="12" y="31" width="294" height="11" rx="2" fill="#262b48"/>')
    bar = [(0, f"transform:scaleX(1);fill:{hp_color(1)}")]
    for t in hits:
        rb, ra = t["hp_before"] / max_hp, t["hp_after"] / max_hp
        bar += [(t["hit"], f"transform:scaleX({rb:.4f});fill:{hp_color(rb)}"),
                (t["hit"] + .18, f"transform:scaleX({ra:.4f});fill:{hp_color(ra)}")]
    last = bar[-1][1]
    bar += [(T - .05, last), (T, f"transform:scaleX(1);fill:{hp_color(1)}")]
    k_bar = A.add(bar, extra="transform-box:fill-box;transform-origin:0% 50%")
    add(f'<rect class="{k_bar}" x="12" y="31" width="294" height="11" rx="2"/>')
    add('</g>')

    parts.extend(pops)

    # ---------------- HUD topo: turno
    add('<g transform="translate(634,14)">')
    add('<rect width="190" height="34" rx="6" fill="#0a0e2e" fill-opacity=".88" stroke="#e8ebff" stroke-width="2"/>')
    k = A.show(0, INTRO)
    add(f'<text class="{k} t" x="95" y="22" text-anchor="middle">BOSS BATTLE</text>')
    for t in turns:
        k = A.show(t["t0"], t["t0"] + TURN)
        add(f'<text class="{k} t" x="95" y="22" text-anchor="middle">TURNO {t["i"] + 1:02d} {t["label"]}</text>')
    k = A.show(tv, T)
    add(f'<text class="{k} t" x="95" y="22" text-anchor="middle">FIM DA BATALHA</text>')
    add('</g>')

    # ---------------- janelas estilo RPG
    def window(x, y, w, h):
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="url(#win)" stroke="#f2f4ff" stroke-width="3"/>')
        add(f'<rect x="{x + 4}" y="{y + 4}" width="{w - 8}" height="{h - 8}" rx="4" fill="none" stroke="#8fa0ff" stroke-opacity=".45"/>')

    # log de batalha
    window(12, 272, 470, 116)
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
        y = 318 if row == 1 else 350
        add(f'<text class="{k} log" x="34" y="{y}">{escape(text)}</text>')
    add('<path class="blink" d="M452 370h14l-7 8z" fill="#ffffff"/>')

    # menu de comandos
    window(490, 272, 140, 116)
    for idx, name in enumerate(MENU):
        frames = [(0, "fill:#ffffff")]
        for t in turns:
            color = "#ffd23f" if t["lvl"] == idx else "#ffffff"
            frames += [(t["t0"], frames[-1][1]), (t["t0"] + EPS, f"fill:{color}")]
        frames += [(tv, frames[-1][1]), (tv + EPS, "fill:#ffffff")]
        k = A.add(frames)
        add(f'<text class="{k} menu" x="528" y="{299 + idx * 20}">{name}</text>')
    cursor = [(0, "transform:translateY(20px)")]
    for t in turns:
        cursor += [(t["t0"], cursor[-1][1]), (t["t0"] + EPS, f"transform:translateY({t['lvl'] * 20}px)")]
    k_cursor = A.add(cursor)
    add(f'<g class="{k_cursor}"><path class="nudge" d="M506 286l10 7-10 7z" fill="#ffffff"/></g>')

    # status do herói
    window(638, 272, 190, 116)
    level = max(1, int(math.sqrt(total)))
    add(f'<text class="t" x="656" y="300">{escape(user.upper()[:11])}</text>')
    add(f'<text class="t" x="812" y="300" text-anchor="end">LV{level}</text>')
    add('<text class="sm" x="656" y="327">HP</text>')
    add('<rect x="690" y="318" width="122" height="9" rx="2" fill="#0a0e2e"/>')
    add('<rect x="690" y="318" width="122" height="9" rx="2" fill="#3fb950"/>')
    add('<text class="sm" x="656" y="350">ATB</text>')
    add('<rect x="690" y="341" width="122" height="9" rx="2" fill="#0a0e2e"/>')
    atb = [(0, "transform:scaleX(0)")]
    for t in turns:
        atb += [(t["t0"], "transform:scaleX(0)"), (t["t0"] + ATB_FULL * TURN, "transform:scaleX(1)"),
                (t["hit"], "transform:scaleX(1)"), (t["hit"] + EPS, "transform:scaleX(0)")]
    atb += [(tv, "transform:scaleX(0)"), (tv + .8, "transform:scaleX(1)"), (T - .05, "transform:scaleX(1)"), (T, "transform:scaleX(0)")]
    k_atb = A.add(atb, extra="transform-box:fill-box;transform-origin:0% 50%")
    add(f'<rect class="{k_atb}" x="690" y="341" width="122" height="9" rx="2" fill="#58a6ff"/>')
    add(f'<text class="sm dim" x="656" y="374">Maior combo: {streak} dias</text>')

    # transição do loop
    k_fade = A.add([(0, "opacity:1"), (.4, "opacity:0"), (T - .4, "opacity:0"), (T, "opacity:1")])
    add(f'<rect class="{k_fade}" width="840" height="400" fill="#05060f" pointer-events="none"/>')
    add('</g>')
    add('<rect x="1" y="1" width="838" height="398" rx="12" fill="none" stroke="#30363d" stroke-width="2"/>')

    style = f"""
text{{font-family:{FONT};font-weight:700}}
.t{{font-size:15px;fill:#f2f4ff;letter-spacing:.5px}}
.sm{{font-size:13px;fill:#f2f4ff}}
.dim{{fill:#aeb8ff;font-weight:600}}
.log{{font-size:17px;fill:#ffffff;paint-order:stroke;stroke:#060a33;stroke-width:3px}}
.menu{{font-size:14px;paint-order:stroke;stroke:#060a33;stroke-width:3px}}
.pop{{font-size:30px;text-anchor:middle;paint-order:stroke;stroke:#12071a;stroke-width:5px}}
.pop.big{{font-size:38px}}
.pop.small{{font-size:16px;stroke-width:4px}}
.banner{{font-size:52px;text-anchor:middle;fill:#ffd23f;paint-order:stroke;stroke:#4a2a00;stroke-width:8px;letter-spacing:4px}}
.bob{{animation:bob 2.2s ease-in-out infinite}}
.bob2{{animation:bob2 1.1s ease-in-out infinite}}
.blink{{animation:blink .9s steps(1) infinite}}
.nudge{{animation:nudge .6s ease-in-out infinite}}
.spark{{animation:spark .7s ease-in-out infinite}}
.tw1{{animation:tw 2.4s ease-in-out infinite}}
.tw2{{animation:tw 3.1s ease-in-out infinite}}
.tw3{{animation:tw 1.7s ease-in-out infinite}}
.led1{{animation:led 1.3s steps(1) infinite}}
.led2{{animation:led 2.1s steps(1) infinite}}
.led3{{animation:led .8s steps(1) infinite}}
@keyframes bob{{0%,100%{{transform:translateY(0px)}}50%{{transform:translateY(-5px)}}}}
@keyframes bob2{{0%,100%{{transform:translateY(0px)}}50%{{transform:translateY(-2px)}}}}
@keyframes blink{{0%{{opacity:1}}50%{{opacity:0}}}}
@keyframes nudge{{0%,100%{{transform:translateX(0px)}}50%{{transform:translateX(3px)}}}}
@keyframes spark{{0%,100%{{opacity:.2}}50%{{opacity:1}}}}
@keyframes tw{{0%,100%{{opacity:.15}}50%{{opacity:1}}}}
@keyframes led{{0%{{opacity:1}}50%{{opacity:.15}}}}
"""
    style += "".join(A.css)

    title = f"Boss battle: {user} causou {total} de dano no {BOSS_NAME} com commits dos últimos 12 meses"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'shape-rendering="crispEdges" role="img" aria-label="{escape(title)}">'
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
