#!/usr/bin/env python3
"""
School Management System — User Manual Generator  (revamped)
Run from the project root: python generate_manual.py
Output: SchoolMS_User_Manual.pdf
"""

import io
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, Flowable, HRFlowable,
)
from reportlab.graphics.shapes import (
    Drawing, Rect, String, Line, Circle, Polygon, Group,
    PolyLine, Path,
)
from reportlab.graphics import renderPDF

# ── Palette ───────────────────────────────────────────────
INDIGO    = colors.HexColor('#4f46e5')
INDIGO_L  = colors.HexColor('#eef2ff')
DARK_BG   = colors.HexColor('#0f172a')
DARK      = colors.HexColor('#1e293b')
SLATE     = colors.HexColor('#334155')
MUTED     = colors.HexColor('#64748b')
BORDER    = colors.HexColor('#e2e8f0')
LIGHT     = colors.HexColor('#f8fafc')
GREEN     = colors.HexColor('#10b981')
GREEN_L   = colors.HexColor('#ecfdf5')
AMBER     = colors.HexColor('#f59e0b')
AMBER_L   = colors.HexColor('#fffbeb')
RED       = colors.HexColor('#ef4444')
RED_L     = colors.HexColor('#fef2f2')
CYAN      = colors.HexColor('#0891b2')
W         = colors.white

ADMIN_C   = colors.HexColor('#6d28d9')
TEACHER_C = colors.HexColor('#0369a1')
PARENT_C  = colors.HexColor('#047857')
STUDENT_C = colors.HexColor('#b45309')
QB_C      = colors.HexColor('#166534')
ACCT_C    = colors.HexColor('#0f766e')
FRONT_C   = colors.HexColor('#0369a1')

PW = 6.5 * inch


# ── Canvas callbacks ───────────────────────────────────────
def _cover_bg(canvas, doc):
    canvas.saveState()
    W_pt, H_pt = letter
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, W_pt, H_pt, fill=1, stroke=0)
    # decorative circles
    canvas.setFillColor(colors.HexColor('#1e3a8a'))
    canvas.circle(W_pt * 0.85, H_pt * 0.8, 120, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor('#1e1b4b'))
    canvas.circle(W_pt * 0.1, H_pt * 0.15, 90, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor('#312e81'))
    canvas.circle(W_pt * 0.5, H_pt * 0.03, 60, fill=1, stroke=0)
    # bottom accent bar
    canvas.setFillColor(INDIGO)
    canvas.rect(0, 0, W_pt, 6, fill=1, stroke=0)
    canvas.restoreState()


def _hf(canvas, doc):
    canvas.saveState()
    W_pt = letter[0]
    canvas.setFillColor(INDIGO)
    canvas.rect(0, letter[1] - 0.45 * inch, W_pt, 0.45 * inch, fill=1, stroke=0)
    canvas.setFont('Helvetica-Bold', 7.5)
    canvas.setFillColor(W)
    canvas.drawString(0.75 * inch, letter[1] - 0.28 * inch,
                      'School Management System  —  User Manual')
    canvas.drawRightString(W_pt - 0.75 * inch, letter[1] - 0.28 * inch,
                           f'Version 2.0  ·  {date.today().year}')
    canvas.setFillColor(BORDER)
    canvas.rect(0, 0, W_pt, 0.38 * inch, fill=1, stroke=0)
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(SLATE)
    canvas.drawCentredString(W_pt / 2, 0.13 * inch, f'Page {doc.page}')
    canvas.restoreState()


# ── Style factory ──────────────────────────────────────────
def _s(name, **kw):
    defaults = dict(fontName='Helvetica', fontSize=10, textColor=SLATE,
                    leading=15, spaceAfter=4)
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)


S = {
    'cov_title': _s('cov_t', fontSize=38, fontName='Helvetica-Bold',
                    textColor=W, alignment=TA_CENTER, leading=44, spaceAfter=6),
    'cov_sub':   _s('cov_s', fontSize=14, textColor=colors.HexColor('#c7d2fe'),
                    alignment=TA_CENTER, spaceAfter=4),
    'cov_meta':  _s('cov_m', fontSize=10, textColor=colors.HexColor('#94a3b8'),
                    alignment=TA_CENTER, spaceAfter=3),
    'chap':      _s('chap', fontSize=24, fontName='Helvetica-Bold', textColor=W,
                    alignment=TA_CENTER, leading=30, spaceAfter=4),
    'chap_sub':  _s('chap_s', fontSize=11, textColor=colors.HexColor('#e0e7ff'),
                    alignment=TA_CENTER, leading=15),
    'h1':  _s('h1',  fontSize=18, fontName='Helvetica-Bold', textColor=DARK,
               spaceBefore=14, spaceAfter=6, leading=22),
    'h2':  _s('h2',  fontSize=13, fontName='Helvetica-Bold', textColor=INDIGO,
               spaceBefore=12, spaceAfter=5, leading=17),
    'h3':  _s('h3',  fontSize=11, fontName='Helvetica-Bold', textColor=DARK,
               spaceBefore=8, spaceAfter=4, leading=14),
    'body': _s('body', fontSize=10, textColor=SLATE, spaceAfter=5, leading=16),
    'sm':   _s('sm',   fontSize=9,  textColor=SLATE, spaceAfter=3, leading=13),
    'bul':  _s('bul',  fontSize=10, textColor=SLATE, spaceAfter=3, leading=15,
                leftIndent=14),
    'step': _s('step', fontSize=10, textColor=DARK, spaceAfter=4, leading=14),
    'note': _s('note', fontSize=9,  textColor=SLATE, leading=14),
    'toc_h': _s('toc_h', fontSize=11, fontName='Helvetica-Bold', textColor=W,
                 spaceAfter=2, spaceBefore=6),
    'toc_i': _s('toc_i', fontSize=9.5, textColor=MUTED, spaceAfter=1, leftIndent=16),
    'caption': _s('caption', fontSize=8, textColor=MUTED, alignment=TA_CENTER,
                   spaceAfter=6, fontName='Helvetica-Oblique'),
    'tag':  _s('tag', fontSize=8, fontName='Helvetica-Bold', textColor=W,
                alignment=TA_CENTER),
    'centered': _s('centered', fontSize=10, textColor=SLATE, alignment=TA_CENTER),
}


# ── Basic helpers ──────────────────────────────────────────
def P(text, style='body'):
    if isinstance(style, ParagraphStyle):
        return Paragraph(text, style)
    return Paragraph(text, S[style])

def SP(h=0.12):
    return Spacer(1, h * inch)

def HR(color=BORDER, w=1):
    return HRFlowable(width='100%', thickness=w, color=color, spaceAfter=4)


# ── Callout boxes ──────────────────────────────────────────
def _callout(icon, label, text, accent, bg):
    content = Paragraph(f'<b>{icon} {label}</b>  {text}', S['note'])
    t = Table([[content]], colWidths=[PW])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), bg),
        ('TOPPADDING',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('LINEBEFORE',    (0, 0), (0,  -1), 4, accent),
    ]))
    return t

def tip(text):
    return _callout('*', 'Tip:', text, INDIGO, INDIGO_L)

def warn(text):
    return _callout('!', 'Note:', text, AMBER, AMBER_L)

def danger(text):
    return _callout('X', 'Warning:', text, RED, RED_L)

def success(text):
    return _callout('OK', 'Done:', text, GREEN, GREEN_L)


# ── Numbered steps (visual cards) ─────────────────────────
def steps(*txts, color=INDIGO):
    els = []
    for i, t in enumerate(txts, 1):
        num_cell = Table(
            [[P(str(i), ParagraphStyle('snum', fontSize=11, fontName='Helvetica-Bold',
                                        textColor=W, alignment=TA_CENTER))]],
            colWidths=[0.32 * inch], rowHeights=[0.32 * inch],
        )
        num_cell.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), color),
            ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('ROUNDEDCORNERS', [4]),
        ]))
        row = Table([[num_cell, P(t, 'step')]], colWidths=[0.42 * inch, PW - 0.42 * inch])
        row.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',   (0, 0), (-1, -1), 2),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
            ('TOPPADDING',    (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        els.append(row)
    return els


def bul(*txts):
    return [P(f'<font color="#4f46e5">&#x2022;</font>  {t}', 'bul') for t in txts]


# ── Feature table ──────────────────────────────────────────
def feat(rows, hdr_color):
    data = [[P('<b>Feature</b>', 'sm'), P('<b>Description</b>', 'sm')]]
    data += [[P(f'<b>{r[0]}</b>', 'sm'), P(r[1], 'sm')] for r in rows]
    t = Table(data, colWidths=[1.9 * inch, 4.6 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1,  0), hdr_color),
        ('TEXTCOLOR',     (0, 0), (-1,  0), W),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [W, LIGHT]),
        ('GRID',          (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


# ── Chapter banner ─────────────────────────────────────────
def chap_banner(title, subtitle, color):
    tbl = Table(
        [[P(title, 'chap')], [P(subtitle, 'chap_sub')]],
        colWidths=[PW],
    )
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), color),
        ('TOPPADDING',    (0, 0), (-1, -1), 28),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 28),
        ('LEFTPADDING',   (0, 0), (-1, -1), 20),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 20),
    ]))
    return tbl


# ══════════════════════════════════════════════════════════
# GRAPHIC COMPONENTS (ReportLab Drawing API)
# ══════════════════════════════════════════════════════════

class DrawingFlowable(Flowable):
    """Wraps a reportlab Drawing so it can live inside a Platypus story."""
    def __init__(self, drawing):
        Flowable.__init__(self)
        self.drawing = drawing
        self.width  = drawing.width
        self.height = drawing.height

    def draw(self):
        renderPDF.draw(self.drawing, self.canv, 0, 0)


def _hex(c):
    """Return a hex string from a reportlab color for Drawing String fill."""
    return c.hexval() if hasattr(c, 'hexval') else '#000000'


# ── Flow Chart ────────────────────────────────────────────
def flow_chart(steps_list, color=INDIGO, w=None):
    """
    Horizontal flow chart with boxes and arrows.
    steps_list: list of short label strings (max ~5 items look best).
    """
    n = len(steps_list)
    box_w = 90
    box_h = 38
    arrow_w = 22
    pad = 10
    total_w = n * box_w + (n - 1) * arrow_w + 2 * pad
    total_h = box_h + 2 * pad + 18   # +18 for caption row

    d = Drawing(total_w, total_h)

    for i, label in enumerate(steps_list):
        x = pad + i * (box_w + arrow_w)
        y = pad + 18
        # box
        d.add(Rect(x, y, box_w, box_h,
                   fillColor=color if i == 0 or i == n - 1 else colors.HexColor('#e0e7ff'),
                   strokeColor=color, strokeWidth=1.5,
                   rx=6, ry=6))
        # label
        txt = String(x + box_w / 2, y + box_h / 2 - 4, label,
                     fontSize=8.5,
                     fillColor=W if (i == 0 or i == n - 1) else color,
                     fontName='Helvetica-Bold',
                     textAnchor='middle')
        d.add(txt)
        # arrow
        if i < n - 1:
            ax = x + box_w
            ay = y + box_h / 2
            d.add(Line(ax, ay, ax + arrow_w - 4, ay,
                       strokeColor=color, strokeWidth=1.5))
            # arrowhead
            d.add(Polygon([ax + arrow_w - 4, ay + 5,
                            ax + arrow_w,     ay,
                            ax + arrow_w - 4, ay - 5],
                           fillColor=color, strokeColor=color))

    return DrawingFlowable(d)


# ── Role Cards Grid ───────────────────────────────────────
def role_grid(roles):
    """
    roles: list of (name, color, description) — displayed as 3-column card grid.
    """
    cards_per_row = 3
    card_w = PW / cards_per_row - 4
    rows_data = []
    row = []
    for i, (name, color, desc) in enumerate(roles):
        inner = Table(
            [[P(f'<b>{name}</b>',
                ParagraphStyle('rn', fontSize=10, fontName='Helvetica-Bold',
                                textColor=W, alignment=TA_CENTER))],
             [P(desc,
                ParagraphStyle('rd', fontSize=8, textColor=SLATE, leading=12))]],
            colWidths=[card_w],
        )
        inner.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (0, 0), color),
            ('BACKGROUND',    (0, 1), (0, 1), LIGHT),
            ('TOPPADDING',    (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ('BOX',           (0, 0), (-1, -1), 1, color),
        ]))
        row.append(inner)
        if len(row) == cards_per_row:
            rows_data.append(row)
            row = []
    if row:
        while len(row) < cards_per_row:
            row.append(Paragraph('', S['sm']))
        rows_data.append(row)

    t = Table(rows_data, colWidths=[card_w] * cards_per_row,
              hAlign='LEFT')
    t.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


# ── Stat Cards Row ────────────────────────────────────────
def stat_row(stats, color=INDIGO):
    """
    stats: list of (value, label) shown as colored stat cards.
    """
    n = len(stats)
    cw = PW / n - 4
    cells = []
    for val, label in stats:
        card = Table(
            [[P(str(val),
                ParagraphStyle('sv', fontSize=22, fontName='Helvetica-Bold',
                                textColor=color, alignment=TA_CENTER))],
             [P(label,
                ParagraphStyle('sl', fontSize=8.5, textColor=MUTED,
                                alignment=TA_CENTER))]],
            colWidths=[cw],
        )
        card.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), W),
            ('BOX',           (0, 0), (-1, -1), 1.5, BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LINEABOVE',     (0, 0), (-1, 0),  3, color),
        ]))
        cells.append(card)

    t = Table([cells], colWidths=[cw] * n)
    t.setStyle(TableStyle([
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


# ── Sidebar Diagram ───────────────────────────────────────
def sidebar_diagram():
    """A simplified visual of the sidebar navigation."""
    W_d, H_d = 220, 340
    d = Drawing(W_d, H_d)

    # sidebar background
    d.add(Rect(0, 0, 90, H_d, fillColor=DARK_BG, strokeColor=colors.transparent))

    # brand area
    d.add(Rect(0, H_d - 40, 90, 40, fillColor=DARK, strokeColor=colors.transparent))
    d.add(String(45, H_d - 25, 'SchoolMS', fontSize=8, fontName='Helvetica-Bold',
                 fillColor=W, textAnchor='middle'))

    # nav items
    items = [
        ('Dashboard',   INDIGO,   True),
        ('Students',    colors.transparent, False),
        ('Staff',       colors.transparent, False),
        ('Attendance',  colors.transparent, False),
        ('Grades',      colors.transparent, False),
        ('Finances',    colors.transparent, False),
        ('Reports',     colors.transparent, False),
        ('Payroll',     colors.transparent, False),
        ('Settings',    colors.transparent, False),
    ]
    y = H_d - 55
    for label, bg, active in items:
        d.add(Rect(5, y - 2, 80, 20, fillColor=bg,
                   strokeColor=colors.transparent, rx=4, ry=4))
        d.add(String(12, y + 4, label, fontSize=7,
                     fillColor=W if active else colors.HexColor('#94a3b8'),
                     fontName='Helvetica-Bold' if active else 'Helvetica',
                     textAnchor='start'))
        y -= 26

    # user section
    d.add(Rect(0, 0, 90, 36, fillColor=colors.HexColor('#1e293b'),
               strokeColor=colors.transparent))
    d.add(Circle(14, 18, 10, fillColor=INDIGO, strokeColor=colors.transparent))
    d.add(String(14, 14, 'A', fontSize=9, fontName='Helvetica-Bold',
                 fillColor=W, textAnchor='middle'))
    d.add(String(30, 22, 'Admin User', fontSize=7, fontName='Helvetica-Bold',
                 fillColor=W, textAnchor='start'))
    d.add(String(30, 12, 'administrator', fontSize=6,
                 fillColor=colors.HexColor('#64748b'), textAnchor='start'))

    # main content area
    d.add(Rect(95, 0, W_d - 95, H_d, fillColor=colors.HexColor('#f1f5f9'),
               strokeColor=colors.transparent))

    # topbar
    d.add(Rect(95, H_d - 30, W_d - 95, 30, fillColor=W,
               strokeColor=BORDER, strokeWidth=0.5))
    d.add(String(110, H_d - 19, 'Dashboard', fontSize=9, fontName='Helvetica-Bold',
                 fillColor=DARK, textAnchor='start'))

    # stat cards
    for i, (v, lbl, c) in enumerate([('142', 'Students', INDIGO),
                                      ('18', 'Staff', TEACHER_C),
                                      ('$24k', 'Fees', GREEN)]):
        cx = 100 + i * 39
        d.add(Rect(cx, H_d - 80, 36, 44, fillColor=W,
                   strokeColor=BORDER, strokeWidth=0.5, rx=3, ry=3))
        d.add(Rect(cx, H_d - 36, 36, 3, fillColor=c,
                   strokeColor=colors.transparent))
        d.add(String(cx + 18, H_d - 58, v, fontSize=10, fontName='Helvetica-Bold',
                     fillColor=c, textAnchor='middle'))
        d.add(String(cx + 18, H_d - 72, lbl, fontSize=6,
                     fillColor=MUTED, textAnchor='middle'))

    # table rows
    for j in range(5):
        ry = H_d - 105 - j * 22
        d.add(Rect(100, ry, W_d - 104, 18,
                   fillColor=W if j % 2 == 0 else LIGHT,
                   strokeColor=colors.transparent))
        d.add(String(106, ry + 5, f'Student Row {j + 1}', fontSize=6.5,
                     fillColor=SLATE, textAnchor='start'))

    return DrawingFlowable(d)


# ── Login Flow Graphic ─────────────────────────────────────
def login_flow():
    return flow_chart(
        ['Open Browser', 'Go to URL', 'Click Sign In', 'Enter Credentials', 'Dashboard'],
        color=INDIGO,
    )


# ── Fee Payment Flow ───────────────────────────────────────
def fee_flow():
    return flow_chart(
        ['Open Student', 'Fees Tab', 'Enter Amount', 'Choose Method', 'Confirm'],
        color=GREEN,
    )


# ── Attendance Flow ────────────────────────────────────────
def attendance_flow():
    return flow_chart(
        ['Attendance', 'Select Class', 'Choose Date', 'Mark Students', 'Save'],
        color=TEACHER_C,
    )


# ── Key + Value pill row ───────────────────────────────────
def kv_row(pairs, key_color=INDIGO):
    """pairs: list of (key, value) shown as a 2-col table row."""
    data = [[P(f'<b>{k}</b>', 'sm'), P(v, 'sm')] for k, v in pairs]
    t = Table(data, colWidths=[1.8 * inch, 4.7 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, -1), INDIGO_L),
        ('TEXTCOLOR',     (0, 0), (0, -1), key_color),
        ('GRID',          (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


# ══════════════════════════════════════════════════════════
#  SECTIONS
# ══════════════════════════════════════════════════════════

# ── Cover ─────────────────────────────────────────────────
def sec_cover():
    el = []
    el.append(SP(1.8))

    # Logo mark
    logo_t = Table(
        [[P('SMS', ParagraphStyle('logo', fontSize=26, fontName='Helvetica-Bold',
                                   textColor=W, alignment=TA_CENTER))]],
        colWidths=[1.0 * inch], rowHeights=[1.0 * inch],
    )
    logo_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), INDIGO),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('ROUNDEDCORNERS', [12]),
    ]))
    center = Table([[logo_t]], colWidths=[PW])
    center.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
    el.append(center)
    el.append(SP(0.3))

    el.append(P('SCHOOL MANAGEMENT', 'cov_title'))
    el.append(P('SYSTEM', ParagraphStyle('cov_t2', fontSize=38,
               fontName='Helvetica-Bold', textColor=colors.HexColor('#818cf8'),
               alignment=TA_CENTER, leading=44, spaceAfter=10)))

    el.append(HR(colors.HexColor('#312e81'), 2))
    el.append(SP(0.2))
    el.append(P('User Manual', ParagraphStyle('man_t', fontSize=20,
               fontName='Helvetica-Bold', textColor=colors.HexColor('#c7d2fe'),
               alignment=TA_CENTER)))
    el.append(SP(0.12))
    el.append(P('Administrators  ·  Teachers  ·  Parents  ·  Students', 'cov_sub'))
    el.append(SP(0.45))

    # role badges row on cover
    badge_data = []
    for lbl, c in [('Admin', ADMIN_C), ('Teacher', TEACHER_C),
                   ('Parent', PARENT_C), ('Student', STUDENT_C)]:
        b = Table([[P(f'<b>{lbl}</b>',
                      ParagraphStyle('cb', fontSize=9, fontName='Helvetica-Bold',
                                      textColor=W, alignment=TA_CENTER))]],
                  colWidths=[1.2 * inch], rowHeights=[0.32 * inch])
        b.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, -1), c),
            ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
            ('ROUNDEDCORNERS', [6]),
        ]))
        badge_data.append(b)
    br = Table([badge_data], colWidths=[1.3 * inch] * 4, hAlign='CENTER')
    br.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    centered_br = Table([[br]], colWidths=[PW])
    centered_br.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
    el.append(centered_br)

    el.append(SP(0.5))
    el.append(P(f'Version 2.0  ·  {date.today().strftime("%B %Y")}', 'cov_meta'))
    el.append(SP(0.1))
    el.append(P('School Management System', 'cov_meta'))
    el.append(PageBreak())
    return el


# ── Table of Contents ─────────────────────────────────────
def sec_toc():
    el = []
    el.append(P('Table of Contents', 'h1'))
    el.append(HR(INDIGO, 2))
    el.append(SP(0.15))

    sections = [
        ('1.  Getting Started',        INDIGO,
         ['System overview', 'Accessing the system', 'Logging in', 'User roles',
          'Navigation & sidebar', 'Session timeout', 'Remote access']),
        ('2.  Admin Guide',            ADMIN_C,
         ['Dashboard overview', 'User management', 'Student management',
          'Teacher & staff management', 'Classes & subjects', 'Attendance',
          'Grades & assignments', 'Finances & fees', 'Payment plans',
          'Walk-in Clients', 'Announcements', 'Calendar', 'Reports & PDFs',
          'Admissions', 'Payroll', 'School settings']),
        ('3.  Teacher Guide',          TEACHER_C,
         ['Teacher dashboard', 'Taking attendance', 'Entering grades',
          'Managing assignments', 'Timetable', 'Announcements & calendar']),
        ('4.  Parent Guide',           PARENT_C,
         ['Registering your account', 'Parent portal', 'Fees & payment status',
          'Grades & attendance', 'Messages']),
        ('5.  Student Guide',          STUDENT_C,
         ['Student portal', 'Grades', 'Attendance record', 'Assignments']),
        ('6.  QuickBooks & Web Connector', QB_C,
         ['Sync overview', 'Manual IIF export', 'Web Connector setup',
          'Required QB accounts', 'Troubleshooting']),
    ]

    for title, color, items in sections:
        hdr = Table([[P(f'<b>{title}</b>',
                        ParagraphStyle('th', fontSize=10, fontName='Helvetica-Bold',
                                        textColor=W))]],
                    colWidths=[PW])
        hdr.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), color),
            ('TOPPADDING',    (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ]))
        el.append(hdr)

        # items in 2 columns
        mid = (len(items) + 1) // 2
        col1 = [P(f'•  {x}', 'toc_i') for x in items[:mid]]
        col2 = [P(f'•  {x}', 'toc_i') for x in items[mid:]]
        while len(col2) < len(col1):
            col2.append(P('', 'toc_i'))
        item_rows = list(zip(col1, col2))
        item_tbl = Table(item_rows, colWidths=[PW / 2, PW / 2])
        item_tbl.setStyle(TableStyle([
            ('TOPPADDING',    (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ]))
        el.append(item_tbl)
        el.append(SP(0.08))

    el.append(PageBreak())
    return el


# ── Getting Started ────────────────────────────────────────
def sec_getting_started():
    el = []
    el.append(P('1.  Getting Started', 'h1'))
    el.append(HR(INDIGO, 2))
    el.append(SP(0.1))

    el.append(P('System Overview', 'h2'))
    el.append(P('School Management System (SMS) is a web-based platform that centralises '
                'student records, academic tracking, fee management, and parent communication '
                'in one place. It runs on a local school server and is accessed from any '
                'device through a web browser — no installation required.', 'body'))

    # overview stat row
    el.append(stat_row([
        ('6', 'User Roles'),
        ('10+', 'Modules'),
        ('Any Browser', 'Access'),
        ('HTTPS', 'Secure'),
    ]))
    el.append(SP(0.12))

    el.append(P('Accessing the System', 'h2'))
    el.append(kv_row([
        ('Remote (recommended)', 'https://school.yourdomain.com  —  works anywhere with internet'),
        ('On-site only',         'http://127.0.0.1:5000  —  school network only'),
    ]))
    el.append(SP(0.1))

    el.append(P('Logging In', 'h2'))
    el.append(P('Follow these steps to sign in:', 'body'))
    el.append(login_flow())
    el.append(P('Login flow — from browser to your dashboard', 'caption'))
    el.append(SP(0.08))
    el += steps(
        'Open any web browser (Chrome, Edge, Firefox, Safari) on any device.',
        'Navigate to <b>https://school.yourdomain.com</b> (or the school\'s local IP).',
        'Click <b>Sign In</b> in the top-right corner of the homepage.',
        'Enter your <b>Username</b> and <b>Password</b> — then click <b>Sign In</b>.',
        'You are redirected to your role-specific dashboard automatically.',
    )
    el.append(SP(0.08))
    el.append(tip('Bookmark the URL for quick daily access. The system works on phones, '
                  'tablets, and computers — no app to download.'))

    el.append(P('User Roles', 'h2'))
    el.append(P('Every account has exactly one role. The role controls which pages and '
                'actions are available across the whole system.', 'body'))
    el.append(SP(0.06))
    el.append(role_grid([
        ('Admin',      ADMIN_C,
         'Full access: all modules, user management, financial reports, system settings, admissions.'),
        ('Teacher',    TEACHER_C,
         'Attendance, grades, assignments, timetable, curriculum sharing with parents.'),
        ('Accountant', ACCT_C,
         'Finances, fees, payment plans, QuickBooks sync, read-only student records.'),
        ('Frontdesk',  FRONT_C,
         'Student records, fee entry and payments, basic finance view.'),
        ('Parent',     PARENT_C,
         'Read-only portal: child\'s grades, attendance, fees, and announcements.'),
        ('Student',    STUDENT_C,
         'Read-only portal: own grades, attendance, assignments, announcements.'),
        ('Viewer',     MUTED,
         'Read-only access to dashboard, students, grades, timetable, and finances.'),
    ]))
    el.append(SP(0.08))

    el.append(P('Navigation & Sidebar', 'h2'))
    el.append(P('The left sidebar is your main navigation panel. Here is a preview:', 'body'))
    el.append(SP(0.06))

    # sidebar diagram + description side by side
    sb = sidebar_diagram()
    desc_items = [
        P('The <b>sidebar</b> shows links based on your role.', 'sm'),
        SP(0.04),
        P('<b>Dashboard</b> — Stats and quick actions', 'sm'),
        P('<b>Students</b> — Full roster and profiles', 'sm'),
        P('<b>Attendance</b> — Daily entry by class', 'sm'),
        P('<b>Grades</b> — Grade book and report cards', 'sm'),
        P('<b>Finances</b> — Fees, payments, invoices', 'sm'),
        P('<b>Payroll</b> — Staff payroll (Admin only)', 'sm'),
        SP(0.06),
        tip('Click the <b>‹</b> button at the top to collapse the sidebar to icons only.'),
    ]
    desc_table_rows = [[item] for item in desc_items]
    desc_tbl = Table(desc_table_rows, colWidths=[PW - 2.6 * inch - 0.2 * inch])
    desc_tbl.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
    ]))
    side_row = Table([[sb, desc_tbl]],
                     colWidths=[2.6 * inch, PW - 2.6 * inch - 0.2 * inch])
    side_row.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
    ]))
    el.append(side_row)
    el.append(SP(0.06))
    el.append(warn('If a menu item is missing, your role may not have permission. '
                   'Contact your Administrator to adjust access.'))

    el.append(P('Session Timeout', 'h2'))
    el.append(P('For security, the system signs you out automatically after a period '
                'of inactivity.', 'body'))
    el += bul(
        'A warning overlay appears with a countdown before sign-out.',
        'Click <b>Stay Signed In</b> to reset the timer.',
        'Always click <b>Sign Out</b> when leaving your workstation.',
    )
    el.append(SP(0.06))
    el.append(tip('Move your mouse or press any key to reset the inactivity timer.'))

    el.append(P('Remote Access', 'h2'))
    el.append(P('The system uses a secure <b>Cloudflare tunnel</b> to provide a permanent '
                'HTTPS web address accessible from anywhere in the world.', 'body'))
    el += bul(
        'Works on any device: phone, tablet, laptop, or desktop.',
        'No VPN, no app, no special software required.',
        'All connections are encrypted end-to-end (HTTPS).',
    )
    el.append(SP(0.06))
    el.append(warn('The school server must be <b>powered on</b> and the SMS service must be '
                   'running for the URL to respond. If the site is unavailable, check the '
                   'server computer and restart the service if needed.'))
    el.append(PageBreak())
    return el


# ── Admin Guide ────────────────────────────────────────────
def sec_admin():
    el = []
    el.append(chap_banner('Admin Guide',
                           'Complete system management for administrators', ADMIN_C))
    el.append(SP(0.25))

    el.append(P('1.  Dashboard', 'h2'))
    el.append(P('The Admin dashboard is the first screen after login — a real-time '
                'snapshot of the school.', 'body'))
    el.append(stat_row([
        ('Active Students', 'Total enrolled'),
        ('Total Staff',     'Active teachers'),
        ('Fees Collected',  'All-time income'),
        ('Outstanding',     'Fees still owed'),
    ], color=ADMIN_C))
    el.append(SP(0.08))
    el.append(feat([
        ('Recent Activity', 'Latest system actions — grades entered, payments received, logins.'),
        ('Quick Links',     'One-click shortcuts to common tasks: Add Student, Record Fee, etc.'),
        ('Attendance Chart','Visual attendance summary across classes for the current week.'),
        ('Overdue Fees',    'Students with unpaid fees highlighted at the top.'),
    ], ADMIN_C))

    el.append(P('2.  User Management', 'h2'))
    el.append(P('Go to <b>Users</b> in the sidebar to manage all system accounts.', 'body'))
    el.append(P('Adding a New User', 'h3'))
    el += steps(
        'Click <b>Add User</b> (top-right of the Users page).',
        'Enter full name, username, email address, and choose a role.',
        'Set an initial password — the user should change it on first login.',
        'For <b>Teacher</b> roles: set <b>Linked Record</b> to their Teachers table entry.',
        'For <b>Parent / Student</b> roles: select the linked student record.',
        'Click <b>Save</b>. The account is active immediately.',
    )
    el.append(SP(0.06))
    el.append(danger('<b>Teacher accounts require a Linked Record.</b> Without this link '
                     'the teacher will see no students or classes after login. Set it in '
                     'the Edit User form (Linked ID field).'))
    el.append(SP(0.06))
    el.append(tip('Parents can self-register at <b>/parent/register</b> using the Student ID '
                  'and the parent email stored in the student record. No admin action needed.'))

    el.append(P('3.  Student Management', 'h2'))
    el.append(P('Go to <b>Students</b> to view, add, and manage all student records.', 'body'))
    el.append(P('Adding a Student', 'h3'))
    el += steps(
        'Click <b>Add Student</b>.',
        'The Student ID is auto-generated as a unique 10-digit number.',
        'Fill in personal details: first/last name, date of birth, gender, address.',
        'Assign a <b>Class</b> and set the <b>Enrollment Date</b>.',
        'Enter parent/guardian name, email, and phone.',
        'Click <b>Save</b>.',
    )
    el.append(SP(0.06))
    el.append(tip('Student IDs are unique 10-digit numbers — no duplicates possible. '
                  'You can also type a custom ID if needed.'))
    el.append(SP(0.06))
    el.append(P('Student Detail Page', 'h3'))
    el.append(P('Click any student name to open their full profile:', 'body'))
    el += bul(
        'View grades, attendance, fees, and payment plans',
        'Download <b>Report Card PDF</b> (select term and year)',
        'Download <b>Fee Statement PDF</b> and <b>Progress Report PDF</b>',
        'Edit student info including date of birth and graduation date',
        'Upload a student photo',
    )

    el.append(P('4.  Staff Management', 'h2'))
    el.append(P('Go to <b>Staff</b> in the sidebar to manage teacher and staff records.', 'body'))
    el += steps(
        'Click <b>Add Staff</b>.',
        'Staff ID is auto-generated — or type a custom one.',
        'Fill in name, job title, qualifications, hire date, and salary.',
        'Click <b>Save</b>.',
    )
    el.append(SP(0.06))
    el.append(warn('After adding a staff member, go to <b>Users</b> and create a login '
                   'account — then link it to this staff record via the Linked ID field.'))

    el.append(P('5.  Classes & Subjects', 'h2'))
    el.append(feat([
        ('Add Class',   'Create a named class, assign a homeroom teacher, set room and capacity.'),
        ('Add Subject', 'Add a subject linked to a class and teacher — used for grades and timetable.'),
        ('Enroll',      'Assign students to classes from the Students page (Class field).'),
    ], ADMIN_C))

    el.append(P('6.  Attendance', 'h2'))
    el.append(P('Attendance is taken per class per day. Here is the full flow:', 'body'))
    el.append(attendance_flow())
    el.append(P('Attendance workflow — select class, date, mark each student, save', 'caption'))
    el.append(SP(0.08))
    el += bul(
        'Admin can view attendance for any class on any date.',
        'Teachers can only take attendance for their own classes.',
        'Attendance is shown per student on their detail page.',
        'Monthly attendance summary is included in the Progress Report PDF.',
    )

    el.append(P('7.  Grades & Assignments', 'h2'))
    el.append(feat([
        ('Enter Grades',    'Go to Grades → select class and subject → enter scores per student.'),
        ('Exam Types',      'Supports: Quiz, Test, Midterm, Final, Assignment, Project, Participation.'),
        ('Assignments',     'Create assignments with due dates and max scores per class.'),
        ('Report Cards',    'Generate and download PDF report cards per student per term.'),
        ('Progress Reports','Full academic report combining grades, attendance, and fee balance.'),
    ], ADMIN_C))

    el.append(P('8.  Finances & Fees', 'h2'))
    el.append(P('All financial activity is managed from the <b>Finances</b> section.', 'body'))
    el.append(P('Recording a Fee Payment', 'h3'))
    el.append(fee_flow())
    el.append(P('Fee payment flow — open student → fees tab → enter amount → confirm', 'caption'))
    el.append(SP(0.08))
    el += steps(
        'Open the student\'s profile page.',
        'Click the <b>Fees</b> tab.',
        'Click <b>Add Fee</b> or select an existing outstanding fee.',
        'Enter the amount and choose the payment method.',
        'Click <b>Confirm</b> — a receipt PDF is generated automatically.',
    )
    el.append(SP(0.06))
    el.append(tip('Student credits (overpayments) are stored and applied automatically '
                  'to future fees.'))

    el.append(P('9.  Payment Plans', 'h2'))
    el.append(P('For students who cannot pay the full amount at once:', 'body'))
    el += steps(
        'Open the student\'s profile → <b>Payment Plans</b> tab.',
        'Click <b>Create Plan</b>.',
        'Enter the total amount, description, and number of installments.',
        'The system calculates the per-installment amount automatically.',
        'Each installment can be paid independently as it comes due.',
    )

    el.append(P('10.  Walk-in Clients', 'h2'))
    el.append(P('Walk-in clients are external students or drop-in session participants '
                'who are not enrolled in a full programme.', 'body'))
    el += bul(
        'A 10-digit unique ID is generated automatically at check-in.',
        'Basic contact info and session notes are recorded.',
        'Fees can be charged per session.',
        'Walk-in records appear separately from regular enrolled students.',
    )

    el.append(P('11.  Announcements & Calendar', 'h2'))
    el.append(feat([
        ('Announcements', 'Post notices to all users or a specific role group (teachers, parents, etc.).'),
        ('Calendar',      'Add school events, holidays, exam dates — visible to all logged-in users.'),
        ('Notifications', 'Bell icon in the sidebar shows unread announcements for the current user.'),
    ], ADMIN_C))

    el.append(P('12.  Reports & PDFs', 'h2'))
    el.append(feat([
        ('Student List',       'Export the full student roster to CSV or PDF.'),
        ('Attendance Report',  'Daily, weekly, or monthly attendance by class.'),
        ('Fee Statement',      'Itemised payment history per student as a PDF.'),
        ('Financial Summary',  'Total income, outstanding balance, payment method breakdown.'),
        ('Report Card',        'Per-student academic report by term and year.'),
        ('Progress Report',    'Comprehensive PDF: grades + attendance + fee balance.'),
        ('Payroll Summary',    'Monthly payroll totals and individual payslips.'),
    ], ADMIN_C))

    el.append(P('13.  Payroll', 'h2'))
    el.append(P('The Payroll module manages staff salary, NIB contributions, and '
                'deductions. It is accessible only to Admins.', 'body'))
    el += bul(
        'Staff are synced automatically from the Teachers table.',
        'Set pay type (Weekly, Bi-Weekly, Monthly) and gross salary.',
        'Employee NIB (3.9%) and Employer NIB (5.9%) are calculated automatically.',
        'Add deductions per entity (loan, BICCU, school loan, etc.).',
        'Generate payslip PDFs and monthly payroll summary reports.',
    )

    el.append(P('14.  School Settings', 'h2'))
    el.append(feat([
        ('School Name / Logo', 'Appears on all PDF reports and the login page.'),
        ('Language',           'Switch the system UI between English and Spanish.'),
        ('Session Timeout',    'Set how long before inactive users are signed out.'),
        ('Server Mode',        'LAN (local only) or Online (Cloudflare tunnel).'),
    ], ADMIN_C))
    el.append(SP(0.1))
    el.append(PageBreak())
    return el


# ── Teacher Guide ──────────────────────────────────────────
def sec_teacher():
    el = []
    el.append(chap_banner('Teacher Guide',
                           'Attendance, grades, assignments and more', TEACHER_C))
    el.append(SP(0.25))

    el.append(P('Teacher Dashboard', 'h2'))
    el.append(P('After login you see your personalised dashboard showing only your '
                'classes and students.', 'body'))
    el.append(stat_row([
        ('My Classes',   'Assigned to you'),
        ('My Students',  'Across all classes'),
        ('Due Today',    'Assignments'),
        ('Attendance',   'This week %'),
    ], color=TEACHER_C))
    el.append(SP(0.08))

    el.append(P('Taking Attendance', 'h2'))
    el.append(attendance_flow())
    el.append(P('Attendance workflow for teachers', 'caption'))
    el.append(SP(0.08))
    el += steps(
        'Click <b>Attendance</b> in the sidebar.',
        'Select your <b>Class</b> from the dropdown.',
        'The date defaults to today — change it if entering past records.',
        'For each student, click <b>Present</b>, <b>Absent</b>, or <b>Late</b>.',
        'Click <b>Save Attendance</b>. The records are saved instantly.',
    )
    el.append(SP(0.06))
    el.append(tip('You can edit a past attendance record by choosing an earlier date '
                  'and re-saving. Only records for your own classes are accessible.'))

    el.append(P('Entering Grades', 'h2'))
    el += steps(
        'Click <b>Grades</b> in the sidebar.',
        'Select a <b>Class</b> and <b>Subject</b>.',
        'Click <b>Add Grade</b> or click a student row to enter a score.',
        'Choose the <b>Exam Type</b> (Quiz, Test, Midterm, Final, etc.).',
        'Enter the <b>Score</b> and <b>Max Score</b> — the system calculates the percentage.',
        'Click <b>Save</b>.',
    )
    el.append(SP(0.06))
    el.append(feat([
        ('Quiz',          'Short in-class quiz.'),
        ('Test',          'Chapter or unit test.'),
        ('Midterm',       'Mid-semester examination.'),
        ('Final',         'End-of-semester examination.'),
        ('Assignment',    'Graded homework or project.'),
        ('Participation', 'Daily participation score.'),
    ], TEACHER_C))

    el.append(P('Managing Assignments', 'h2'))
    el += steps(
        'Click <b>Assignments</b> in the sidebar.',
        'Click <b>New Assignment</b>.',
        'Enter title, description, select class and subject, set a due date and max score.',
        'Click <b>Save</b>. Students see the assignment in their portal immediately.',
    )
    el.append(SP(0.06))
    el.append(tip('Students can view assignment details and due dates in their Student Portal.'))

    el.append(P('Timetable', 'h2'))
    el.append(P('The timetable shows your weekly class schedule.', 'body'))
    el += bul(
        'Admins create timetable entries (class, subject, day, time, room).',
        'Teachers see their own schedule only.',
        'The weekly view shows all periods in a grid by day.',
    )

    el.append(P('Announcements & Calendar', 'h2'))
    el += bul(
        'Post announcements to your class or all users via <b>Announcements</b>.',
        'View school events in the <b>Calendar</b>.',
        'Unread notifications appear as a badge on the bell icon in the sidebar.',
    )
    el.append(PageBreak())
    return el


# ── Parent Guide ───────────────────────────────────────────
def sec_parent():
    el = []
    el.append(chap_banner('Parent Guide',
                           'Monitor your child\'s progress from anywhere', PARENT_C))
    el.append(SP(0.25))

    el.append(P('Registering Your Account', 'h2'))
    el.append(P('Parents self-register — no admin action is needed. You will need '
                'two pieces of information from the school:', 'body'))
    el.append(kv_row([
        ('Student ID',    'The 10-digit number assigned to your child (provided by the school).'),
        ('Parent Email',  'The email address the school has on file for your family.'),
    ], key_color=PARENT_C))
    el.append(SP(0.08))
    el += steps(
        'Go to the school\'s website and click <b>Sign In</b>.',
        'On the login page click <b>"Register your account here"</b>.',
        'Enter your child\'s <b>Student ID</b> and your <b>Parent Email</b>.',
        'Choose a username and password for your new account.',
        'Click <b>Register</b>. You are logged in immediately.',
    )
    el.append(SP(0.06))
    el.append(tip('If registration fails, contact the school to confirm the Student ID '
                  'and the email address they have on file for you.'))

    el.append(P('Parent Portal Overview', 'h2'))
    el.append(P('After login you see your child\'s summary dashboard:', 'body'))
    el.append(feat([
        ('Grades',        'All recorded grades by subject and exam type.'),
        ('Attendance',    'Daily attendance record — present, absent, or late.'),
        ('Fees',          'Current balance, payment history, and due dates.'),
        ('Fee Statement', 'Download a PDF itemised fee statement.'),
        ('Announcements', 'School and class notices posted by staff.'),
        ('Assignments',   'List of upcoming and past assignments with due dates.'),
    ], PARENT_C))
    el.append(SP(0.06))
    el.append(warn('The Parent Portal is <b>read-only</b>. You cannot edit student information '
                   'or make payments directly through the portal. Contact the school for changes.'))

    el.append(P('Viewing Fees & Payment Status', 'h2'))
    el += bul(
        'The <b>Fees</b> section shows all charges with their due dates and paid amounts.',
        'Outstanding balances are highlighted in red.',
        'Click <b>Download Fee Statement</b> for a printable PDF receipt history.',
    )
    el.append(PageBreak())
    return el


# ── Student Guide ──────────────────────────────────────────
def sec_student():
    el = []
    el.append(chap_banner('Student Guide',
                           'Your academic record at a glance', STUDENT_C))
    el.append(SP(0.25))

    el.append(P('Student Portal Overview', 'h2'))
    el.append(P('The student portal is a read-only view of your own academic record. '
                'Your school will give you a username and password to log in.', 'body'))
    el.append(feat([
        ('Grades',      'All your grades by subject, exam type, and term.'),
        ('Attendance',  'Your attendance record — present, absent, late.'),
        ('Assignments', 'Upcoming and past assignments with due dates.'),
        ('Fees',        'Your fee balance and payment status.'),
        ('Announcements','School-wide and class-specific notices.'),
    ], STUDENT_C))
    el.append(SP(0.06))

    el.append(P('Viewing Your Grades', 'h2'))
    el += bul(
        'Click <b>Grades</b> in the sidebar to see all recorded scores.',
        'Grades are sorted by subject, then by date.',
        'Your average score per subject is shown at the top.',
        'Percentage and letter grade are calculated automatically.',
    )

    el.append(P('Attendance Record', 'h2'))
    el += bul(
        'Click <b>Attendance</b> to see your daily record.',
        'Days marked <b>Absent</b> or <b>Late</b> are highlighted.',
        'Your overall attendance percentage is shown at the top.',
    )

    el.append(P('Assignments', 'h2'))
    el += bul(
        'All assignments posted by your teachers appear here.',
        'Upcoming due dates are shown — plan ahead!',
        'Past assignments are archived and still viewable.',
    )
    el.append(PageBreak())
    return el


# ── QuickBooks Guide ───────────────────────────────────────
def sec_qb():
    el = []
    el.append(chap_banner('QuickBooks & Web Connector',
                           'Sync financial data with QuickBooks Desktop', QB_C))
    el.append(SP(0.25))

    el.append(P('Sync Overview', 'h2'))
    el.append(P('SMS can export financial transactions to QuickBooks Desktop in two ways:', 'body'))
    el.append(flow_chart(
        ['SMS Finances', 'QB Sync Page', 'IIF Export', 'Import to QB'],
        color=QB_C,
    ))
    el.append(P('Manual IIF export flow — from SMS to QuickBooks', 'caption'))
    el.append(SP(0.08))

    el.append(kv_row([
        ('Manual Export',   'Download an IIF file from QB Sync → import it into QuickBooks manually.'),
        ('Web Connector',   'Automatic sync via the QuickBooks Web Connector app (recommended).'),
    ], key_color=QB_C))
    el.append(SP(0.1))

    el.append(P('Manual IIF Export', 'h2'))
    el += steps(
        'Go to <b>QB Sync</b> in the sidebar.',
        'Select the date range for the export.',
        'Click <b>Download IIF</b>.',
        'In QuickBooks Desktop: File → Utilities → Import → IIF Files.',
        'Select the downloaded file and click <b>Open</b>.',
    )

    el.append(P('Web Connector Auto-Sync Setup', 'h2'))
    el += steps(
        'Download the <b>QWC file</b> from the QB Sync page in SMS.',
        'Open QuickBooks Web Connector (installed with QuickBooks Desktop).',
        'Click <b>Add an Application</b> and select the QWC file.',
        'Set a <b>password</b> when prompted — save this.',
        'Set the <b>sync interval</b> (e.g. every 60 minutes).',
        'Click <b>Update Selected</b> to run the first sync.',
    )
    el.append(SP(0.06))
    el.append(tip('The Web Connector must be running on the same computer as QuickBooks '
                  'Desktop. It can run minimised in the background.'))

    el.append(P('Required QuickBooks Accounts', 'h2'))
    el.append(feat([
        ('Tuition Income',      'Income account for regular tuition fee payments.'),
        ('Other School Income', 'Income account for miscellaneous school fees.'),
        ('Undeposited Funds',   'Asset account used as the payment clearing account.'),
        ('Accounts Receivable', 'Asset account for outstanding student fee balances.'),
    ], QB_C))
    el.append(SP(0.06))
    el.append(warn('The account names in QuickBooks must match exactly what SMS expects. '
                   'If the import fails, check that these accounts exist and are not renamed.'))

    el.append(P('Troubleshooting', 'h2'))
    el.append(feat([
        ('IIF import fails',       'Check that all required QB accounts exist with exact names.'),
        ('Web Connector error',    'Confirm the SMS server is running and the QB Sync password is correct.'),
        ('Duplicate transactions', 'Do not import the same IIF file twice — use the date range filter.'),
        ('Wrong amounts',          'Verify the date range matches the transactions you expect to sync.'),
    ], QB_C))
    return el


# ══════════════════════════════════════════════════════════
#  BUILD
# ══════════════════════════════════════════════════════════

_ROLE_SECTIONS = {
    'admin':      [sec_getting_started, sec_admin, sec_teacher, sec_parent, sec_student, sec_qb],
    'teacher':    [sec_getting_started, sec_teacher],
    'accountant': [sec_getting_started, sec_admin],
    'frontdesk':  [sec_getting_started, sec_admin],
    'parent':     [sec_getting_started, sec_parent],
    'student':    [sec_getting_started, sec_student],
    'viewer':     [sec_getting_started],
}

_ROLE_LABELS = {
    'admin':      'Administrator',
    'teacher':    'Teacher',
    'accountant': 'Accountant',
    'frontdesk':  'Front Desk',
    'parent':     'Parent',
    'student':    'Student',
    'viewer':     'Viewer',
}


def _build_doc(dest, role='admin'):
    """Build the PDF story and write to dest (filename or file-like object)."""
    doc = SimpleDocTemplate(
        dest,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.6 * inch,
    )

    story = list(sec_cover())
    for fn in _ROLE_SECTIONS.get(role, [sec_getting_started]):
        story += fn()

    def _page_template(canvas, doc):
        if doc.page == 1:
            _cover_bg(canvas, doc)
        else:
            _hf(canvas, doc)

    doc.build(story, onFirstPage=_page_template, onLaterPages=_page_template)
    return doc.page


def build(output='SchoolMS_User_Manual.pdf'):
    pages = _build_doc(output, role='admin')
    print(f'Manual generated: {output}  ({pages} pages)')


def build_for_role(role: str) -> bytes:
    """Generate a role-specific manual and return raw PDF bytes."""
    buf = io.BytesIO()
    _build_doc(buf, role=role)
    return buf.getvalue()


if __name__ == '__main__':
    build()
