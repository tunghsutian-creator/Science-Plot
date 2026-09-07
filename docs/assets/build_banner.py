"""Compose native showcase exports into the GitHub cover; never redraw data.

Run from the repository root:
QT_QPA_PLATFORM=offscreen .venv/bin/python docs/assets/build_banner.py
The SVG embeds complete PNG pages; the PNG is a rasterization of that SVG.
"""

import base64
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parent


def chart(path, x, y, width, height, angle, accent):
    content = base64.b64encode((ROOT / path).read_bytes()).decode("ascii")
    return f'''
    <g transform="translate({x} {y}) rotate({angle} {width / 2} {height / 2})">
      <rect x="-10" y="2" width="{width + 20}" height="{height + 20}" rx="14" fill="#030817" opacity=".45"/>
      <rect x="-10" y="-10" width="{width + 20}" height="{height + 20}" rx="14" fill="#FFFFFF"/>
      <rect x="10" y="-10" width="68" height="5" rx="2" fill="{accent}"/>
      <image x="0" y="0" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet"
        xlink:href="data:image/png;base64,{content}"/>
    </g>'''


def build():
    cards = "\n".join(
        [
            chart(
                "showcase/v2/spectra/spectra-rich.png",
                790,
                91,
                330,
                302.5,
                -7,
                "#31EBC3",
            ),
            chart(
                "showcase/v2/distributions/replicate-distributions.png",
                1170,
                117,
                320,
                293.3,
                8,
                "#F768A1",
            ),
            chart(
                "showcase/v2/performance/performance-scatter-rich.png",
                770,
                441,
                750,
                344,
                -3,
                "#8D7AFF",
            ),
        ]
    )
    stars = "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" opacity=".7"/>'
        for x, y, r, color in [
            (685, 165, 3, "#41EBC4"),
            (1460, 63, 4, "#FCBC4A"),
            (720, 510, 4, "#F770B3"),
            (1250, 430, 3, "#41EBC4"),
            (1560, 390, 4, "#8D7AFF"),
            (652, 695, 3, "#FCBC4A"),
            (72, 634, 3, "#41EBC4"),
            (1515, 825, 2, "#F770B3"),
        ]
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
      width="1600" height="850" viewBox="0 0 1600 850" role="img" aria-labelledby="title desc">
    <title id="title">SciPlot — 让数据，成为好图。</title>
    <desc id="desc">鲜艳的五样品光谱、五组重复分布与十六样品性能散点，均来自 SciPlot 原生渲染的合成演示数据。面向外部 AI 的本地科研绘图工具。</desc>
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop stop-color="#080F20"/><stop offset=".6" stop-color="#151B3D"/><stop offset="1" stop-color="#312958"/>
      </linearGradient>
      <radialGradient id="aura"><stop stop-color="#704DE3" stop-opacity=".45"/><stop offset="1" stop-color="#704DE3" stop-opacity="0"/></radialGradient>
      <linearGradient id="spectrum"><stop stop-color="#27E6BE"/><stop offset=".32" stop-color="#4299FF"/><stop offset=".64" stop-color="#B879F9"/><stop offset="1" stop-color="#F877A0"/></linearGradient>
    </defs>
    <rect width="1600" height="850" rx="26" fill="url(#bg)"/>
    <ellipse cx="1180" cy="470" rx="610" ry="490" fill="url(#aura)"/>
    <g fill="none" stroke="#9D90F3" opacity=".13">
      <ellipse cx="1200" cy="450" rx="570" ry="300" transform="rotate(-24 1200 450)"/>
      <ellipse cx="1200" cy="450" rx="650" ry="390" transform="rotate(-24 1200 450)"/>
      <ellipse cx="1200" cy="450" rx="720" ry="470" transform="rotate(-24 1200 450)"/>
    </g>
    {stars}
    <g font-family="Arial">
      <rect x="72" y="70" width="7" height="20" rx="2" fill="#39E7C1"/>
      <rect x="85" y="60" width="7" height="30" rx="2" fill="#7C86FF"/>
      <rect x="98" y="49" width="7" height="41" rx="2" fill="#F27CB9"/>
      <text x="126" y="80" font-size="20" font-weight="600" letter-spacing="3" fill="#B7C4E1">SCIENTIFIC FIGURES, WITH AI</text>
      <text x="66" y="268" font-size="164" font-weight="700" letter-spacing="-8" fill="#FFFFFF">SciPlot<tspan fill="#3DEAC1">.</tspan></text>
      <rect x="76" y="292" width="495" height="6" rx="3" fill="url(#spectrum)"/>
    </g>
    <g font-family="PingFang SC">
      <text x="73" y="407" font-size="64" font-weight="600" fill="#FFFFFF">让数据，成为好图。</text>
      <text x="76" y="475" font-size="28" fill="#C4CCE4">AI 理解任务 · 本地忠实成图</text>
      <text x="76" y="525" font-size="25" fill="#C4CCE4">可编辑 · 可追溯 · 可继续修改</text>
      <text x="76" y="633" font-size="21" fill="#B5C1DF">实验数据</text>
      <text x="212" y="633" font-size="24" fill="#736FBA">→</text>
      <text x="265" y="633" font-size="21" fill="#B5C1DF">原生图稿</text>
      <text x="400" y="633" font-size="24" fill="#736FBA">→</text>
      <text x="453" y="633" font-size="21" fill="#B5C1DF">审阅与交付</text>
    </g>
    <g font-family="Arial" font-size="20" font-weight="600" letter-spacing="2">
      <text x="76" y="738" fill="#48E6C7">VSZ</text>
      <text x="170" y="738" fill="#94ADFF">PDF</text>
      <text x="267" y="738" fill="#D8A1FA">TIFF</text>
      <text x="378" y="738" fill="#FA96BC">CSV</text>
      <text x="78" y="794" font-size="14" letter-spacing="3" fill="#828FAA">LOCAL EXECUTION. EDITABLE SCIENCE.</text>
    </g>
    {cards}
    <text x="1126" y="832" font-family="Arial" font-size="13" letter-spacing="1.6" fill="#B4B9D1">NATIVE RENDERS · SYNTHETIC DEMO DATA</text>
    </svg>"""
    target = ROOT / "sciplot-banner.svg"
    target.write_text(
        "\n".join(line.rstrip() for line in svg.splitlines()) + "\n", encoding="utf-8"
    )
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(target))
    assert renderer.isValid()
    bitmap = QImage(renderer.defaultSize(), QImage.Format.Format_ARGB32)
    bitmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(bitmap)
    renderer.render(painter)
    painter.end()
    assert bitmap.save(str(ROOT / "sciplot-banner.png"))
    return app


if __name__ == "__main__":
    build()
