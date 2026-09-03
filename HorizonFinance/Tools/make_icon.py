#!/usr/bin/env python3
"""Генерирует иконку приложения (Resources/icon.png) без внешних зависимостей.

Рисуем через знаковые функции расстояния — так края получаются сглаженными
без суперсэмплинга. Запуск: python3 Tools/make_icon.py
"""

import math
import os
import struct
import zlib

SIZE = 1024


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def mix(a, b, t):
    t = clamp(t)
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def sd_round_rect(px, py, cx, cy, half_w, half_h, radius):
    dx = abs(px - cx) - (half_w - radius)
    dy = abs(py - cy) - (half_h - radius)
    ax, ay = max(dx, 0.0), max(dy, 0.0)
    return math.hypot(ax, ay) + min(max(dx, dy), 0.0) - radius


def sd_segment(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0 else clamp((wx * vx + wy * vy) / denom)
    return math.hypot(wx - vx * t, wy - vy * t)


def coverage(distance):
    """Расстояние в пикселях → покрытие 0..1 с мягким краем в один пиксель."""
    return clamp(0.5 - distance)


BG_TOP = (0.31, 0.55, 0.97)      # #4F8DF7
BG_BOTTOM = (0.07, 0.69, 0.63)   # #12B0A0
WHITE = (1.0, 1.0, 1.0)

# Ломаная «рост накоплений» в координатах 0..1024
LINE = [(250, 720), (410, 640), (560, 470), (700, 500), (830, 280)]

# Столбики под линией: (центр по x, высота)
BARS = [(300, 150), (430, 230), (560, 330), (690, 300), (820, 470)]


def render():
    rows = []
    margin = 62
    half = (SIZE - 2 * margin) / 2
    cx = cy = SIZE / 2
    radius = 226

    for y in range(SIZE):
        row = bytearray()
        py = y + 0.5
        for x in range(SIZE):
            px = x + 0.5

            bg_cov = coverage(sd_round_rect(px, py, cx, cy, half, half, radius))
            if bg_cov <= 0.0:
                row += b"\x00\x00\x00\x00"
                continue

            base = mix(BG_TOP, BG_BOTTOM, (px / SIZE) * 0.35 + (py / SIZE) * 0.75)

            # Столбики
            bar_cov = 0.0
            for bx, bh in BARS:
                d = sd_round_rect(px, py, bx, 760 - bh / 2, 34, bh / 2, 30)
                bar_cov = max(bar_cov, coverage(d))
            color = mix(base, WHITE, bar_cov * 0.30)

            # Линия роста
            line_d = min(
                sd_segment(px, py, LINE[i][0], LINE[i][1], LINE[i + 1][0], LINE[i + 1][1])
                for i in range(len(LINE) - 1)
            )
            line_cov = coverage(line_d - 21)
            color = mix(color, WHITE, line_cov)

            # Точка на конце линии — «цель»
            dot = coverage(math.hypot(px - LINE[-1][0], py - LINE[-1][1]) - 44)
            color = mix(color, WHITE, dot)

            alpha = int(round(bg_cov * 255))
            row += bytes(
                (
                    int(round(clamp(color[0]) * 255)),
                    int(round(clamp(color[1]) * 255)),
                    int(round(clamp(color[2]) * 255)),
                    alpha,
                )
            )
        rows.append(bytes(row))
    return rows


def write_png(path, rows):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(png)


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(here, "Resources", "icon.png")
    write_png(target, render())
    print("Иконка записана:", target)
