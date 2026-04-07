from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


def wrap_text(text: str, font_name: str, font_size: int, max_width: float) -> List[str]:
    if not text:
        return [""]

    words = text.split()
    if not words:
        return [""]

    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def build_pdf(source: Path, output: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Manual source not found: {source}")

    output.parent.mkdir(parents=True, exist_ok=True)

    page_width, page_height = A4
    left = 45
    right = 45
    top = 50
    bottom = 50
    max_width = page_width - left - right

    c = canvas.Canvas(str(output), pagesize=A4)
    page = 1
    y = page_height - top

    def draw_footer(page_number: int) -> None:
        c.setStrokeColor(colors.lightgrey)
        c.line(left, bottom - 10, page_width - right, bottom - 10)
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 9)
        c.drawString(left, bottom - 25, "TradingBot - Manual do Cliente")
        c.drawRightString(page_width - right, bottom - 25, f"Pagina {page_number}")

    def new_page() -> None:
        nonlocal page, y
        draw_footer(page)
        c.showPage()
        page += 1
        y = page_height - top

    def draw_line(text: str, font_name: str, font_size: int, indent: int = 0, color=colors.black) -> None:
        nonlocal y
        wrapped = wrap_text(text, font_name, font_size, max_width - indent)
        for chunk in wrapped:
            if y < bottom + 20:
                new_page()
            c.setFillColor(color)
            c.setFont(font_name, font_size)
            c.drawString(left + indent, y, chunk)
            y -= font_size + 4

    lines = source.read_text(encoding="utf-8").splitlines()

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("MANUAL DO CLIENTE"):
            draw_line(stripped, "Helvetica-Bold", 16, 0, colors.darkblue)
            y -= 2
            continue

        if stripped.startswith("Versao") or stripped.startswith("Data do manual") or stripped.startswith("Plataforma"):
            draw_line(stripped, "Helvetica", 10, 0, colors.black)
            continue

        if stripped.startswith("================================================================="):
            if y < bottom + 30:
                new_page()
            c.setStrokeColor(colors.lightgrey)
            c.line(left, y, page_width - right, y)
            y -= 10
            continue

        if not stripped:
            y -= 6
            if y < bottom + 20:
                new_page()
            continue

        if re.match(r"^\d+\)", stripped):
            y -= 2
            draw_line(stripped, "Helvetica-Bold", 12, 0, colors.darkblue)
            continue

        if re.match(r"^\d+\.\d+", stripped):
            draw_line(stripped, "Helvetica-Bold", 11, 0, colors.black)
            continue

        if stripped.startswith("- "):
            draw_line(stripped, "Helvetica", 10, 10, colors.black)
            continue

        if re.match(r"^\d+\.", stripped):
            draw_line(stripped, "Helvetica", 10, 10, colors.black)
            continue

        draw_line(stripped, "Helvetica", 10, 0, colors.black)

    draw_footer(page)
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate client manual PDF for TradingBot.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("docs/MANUAL_CLIENTE_TRADINGBOT.txt"),
        help="Path to source TXT manual",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/MANUAL_CLIENTE_TRADINGBOT.pdf"),
        help="Path to output PDF file",
    )
    args = parser.parse_args()

    build_pdf(args.source, args.output)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] PDF generated: {args.output}")


if __name__ == "__main__":
    main()
