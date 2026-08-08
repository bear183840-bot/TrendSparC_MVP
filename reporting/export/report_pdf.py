"""Turn a finished run into a PDF someone can file or forward.

A dashboard answers "what does this say"; a PDF answers "what did it say on
the day we decided". Those are different jobs, and the second one is why this
exists: a report that only lives in a browser session can't be attached to a
decision.

Korean is the whole difficulty. ReportLab's built-in fonts have no Hangul
glyphs, so an unregistered font renders every Korean character as a black
box - which looks like a broken export rather than a missing font. The fix is
to find a real CJK font on the machine and register it; where none exists,
`pdf_font_available()` says so and the caller offers HTML instead of shipping
a page of boxes.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

# Imported at module scope but guarded: a missing reportlab must degrade the
# download to JSON, never take the dashboard down with an ImportError at
# startup. Streamlit Cloud installs from requirements.txt, a local venv may
# not have caught up yet, and neither case is worth a blank page.
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        HRFlowable,
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:  # pragma: no cover - exercised only where the dep is absent
    _REPORTLAB_AVAILABLE = False
else:
    _REPORTLAB_AVAILABLE = True

# Ordered by how likely each is to be the one present: Windows first (where
# this is developed), then macOS, then the two families a Linux host running
# Streamlit is most likely to have.
_FONT_CANDIDATES = (
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", None),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", None),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", None),
)

_FONT_NAME = "TrendSparcKR"
_FONT_BOLD = "TrendSparcKR-Bold"
_ACCENT = colors.HexColor("#f24503") if _REPORTLAB_AVAILABLE else None
_INK = colors.HexColor("#161616") if _REPORTLAB_AVAILABLE else None
_MUTED = colors.HexColor("#77736e") if _REPORTLAB_AVAILABLE else None
_LINE = colors.HexColor("#d9d6d2") if _REPORTLAB_AVAILABLE else None

_registered: bool | None = None


def _register_font() -> bool:
    global _registered
    if not _REPORTLAB_AVAILABLE:
        return False
    if _registered is not None:
        return _registered
    _registered = False
    for regular, bold in _FONT_CANDIDATES:
        if not Path(regular).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(_FONT_NAME, regular))
            pdfmetrics.registerFont(TTFont(_FONT_BOLD, bold if bold and Path(bold).exists() else regular))
        except Exception:  # noqa: BLE001  - a font that won't load is the same as absent
            continue
        _registered = True
        break
    return _registered


def pdf_font_available() -> bool:
    """Whether a PDF can actually be produced here - reportlab installed and a
    Hangul-capable font present. False means offer the JSON instead."""
    return _register_font()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "title": ParagraphStyle("ts-title", parent=base, fontName=_FONT_BOLD, fontSize=17,
                                leading=23, textColor=_INK, spaceAfter=2),
        "meta": ParagraphStyle("ts-meta", parent=base, fontName=_FONT_NAME, fontSize=8.5,
                               leading=13, textColor=_MUTED, spaceAfter=10),
        "section": ParagraphStyle("ts-section", parent=base, fontName=_FONT_BOLD, fontSize=11.5,
                                  leading=16, textColor=_INK, spaceBefore=13, spaceAfter=4),
        "body": ParagraphStyle("ts-body", parent=base, fontName=_FONT_NAME, fontSize=9.5,
                               leading=15, textColor=_INK, alignment=TA_LEFT),
        "small": ParagraphStyle("ts-small", parent=base, fontName=_FONT_NAME, fontSize=8.5,
                                leading=13, textColor=_MUTED),
    }


def _escape(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bullets(values: list[str], style: ParagraphStyle) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_escape(value), style), leftIndent=10) for value in values],
        bulletType="bullet", bulletColor=_ACCENT, bulletFontSize=6, start="circle",
        leftIndent=12, spaceBefore=1, spaceAfter=4,
    )


def _metric_table(points: list[Any], styles: dict[str, ParagraphStyle]) -> Table:
    """Figures as a table, because a PDF has no hover and no tooltip: every
    number has to arrive with its subject, period and unit visible."""
    rows = [["지표", "대상", "시점", "값"]]
    for point in points[:14]:
        rows.append([
            point.label or "",
            getattr(point, "subject", None) or "-",
            point.period or "-",
            f"{point.value:,.10g}{point.unit or ''}" + (" (전망)" if getattr(point, "is_forecast", False) else ""),
        ])
    table = Table(rows, colWidths=[58 * mm, 32 * mm, 34 * mm, 36 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, _LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_report_pdf(result: Any, question: str) -> bytes:
    """The finished report as PDF bytes.

    Sections come from the generated report, so the PDF says exactly what the
    dashboard said - it is a second rendering of one result, never a second
    summarisation of it. Sources are listed last with their URLs spelled out,
    since a printed page can't be clicked.
    """
    if not _register_font():
        raise RuntimeError("no Hangul-capable font found for PDF export")
    styles = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=question or "TrendSparC 리포트", author="TrendSparC",
    )
    report = getattr(result, "generated_report", None)
    synthesis = getattr(result, "synthesis", None)
    story: list[Any] = [
        Paragraph(_escape((report.title if report else None) or question or "분석 결과"), styles["title"]),
    ]
    meta = " · ".join(
        part for part in (
            f"질문: {question}" if question else "",
            f"섹터: {getattr(result.sector_route, 'sector_id', '')}" if getattr(result, "sector_route", None) else "",
            f"청중: {report.audience_id}" if report else "",
            f"목적: {report.purpose_id}" if report and report.purpose_id else "",
            f"출처 {synthesis.unique_source_count}곳 / 문서 {synthesis.source_count}건" if synthesis else "",
        ) if part
    )
    story += [Paragraph(_escape(meta), styles["meta"]),
              HRFlowable(width="100%", thickness=0.6, color=_LINE, spaceAfter=6)]

    if report and report.executive_summary:
        story += [Paragraph("핵심 요약", styles["section"]),
                  Paragraph(_escape(report.executive_summary), styles["body"])]

    for section in (report.sections if report else []):
        story.append(Paragraph(_escape(section.title or section.section_id), styles["section"]))
        if section.summary:
            story.append(Paragraph(_escape(section.summary), styles["body"]))
        for label, values in (
            ("핵심", section.key_points), ("위험", section.risks),
            ("기회", section.opportunities), ("조치", section.actions),
        ):
            if values:
                story.append(Paragraph(f"<b>{label}</b>", styles["small"]))
                story.append(_bullets(values, styles["body"]))

    if synthesis and synthesis.metric_series:
        story += [Paragraph("확인된 수치", styles["section"]), _metric_table(synthesis.metric_series, styles)]

    if report and report.limitations:
        story += [Paragraph("한계", styles["section"]), _bullets(report.limitations, styles["small"])]

    sources = getattr(synthesis, "doc_url_map", {}) or {}
    if sources:
        story.append(Paragraph("출처", styles["section"]))
        story.append(_bullets(
            [f"{doc_id} — {url}" for doc_id, url in list(sources.items())[:20]], styles["small"]
        ))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "이 리포트의 모든 수치와 주장은 수집된 근거 문서에서 확인된 것만 포함합니다.", styles["small"]
    ))
    document.build(story)
    return buffer.getvalue()
