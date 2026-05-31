"""PDF generation using fpdf2."""
from datetime import datetime
from typing import Optional

from fpdf import FPDF, XPos, YPos

_BLUE_DARK  = (30, 60, 114)
_BLUE_LIGHT = (240, 244, 255)
_GREY       = (128, 128, 128)
_WHITE      = (255, 255, 255)
_YELLOW     = (255, 252, 220)


def _annual(emp: dict) -> float:
    y = emp.get("yearly") or 0
    if y:
        return y
    if emp.get("monthly"):
        return emp["monthly"] * 12
    if emp.get("biweekly"):
        return emp["biweekly"] * 26
    if emp.get("weekly"):
        return emp["weekly"] * 52
    return 0.0


def _fmt(v: float) -> str:
    return f"$ {v:>13,.2f}"


def _period_label(code: str) -> str:
    return {"W": "Weekly", "BW": "By-Weekly", "M": "Monthly"}.get(code, code)


class _PDF(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self._doc_title = title
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(auto=True, margin=18)
        self.add_page()

    def header(self):
        self.set_fill_color(*_BLUE_DARK)
        self.set_text_color(*_WHITE)
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 13, self._doc_title, align="C", fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(*_GREY)
        self.cell(0, 8,
                  f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  Page {self.page_no()}",
                  align="C")
        self.set_text_color(0, 0, 0)

    def section(self, title: str):
        self.ln(3)
        self.set_fill_color(*_BLUE_LIGHT)
        self.set_text_color(*_BLUE_DARK)
        self.set_font("Helvetica", "B", 9)
        self.cell(0, 7, f"  {title}", fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def kv(self, label: str, value: str, highlight: bool = False, bold_val: bool = False):
        fill = highlight
        self.set_fill_color(*(_YELLOW if highlight else _WHITE))
        self.set_font("Helvetica", "", 9)
        self.cell(95, 6.5, f"  {label}", fill=fill)
        self.set_font("Helvetica", "B" if bold_val else "", 9)
        self.cell(0, 6.5, value, fill=fill,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def table_head(self, cols: list[tuple[str, float]]):
        self.set_fill_color(*_BLUE_DARK)
        self.set_text_color(*_WHITE)
        self.set_font("Helvetica", "B", 8.5)
        for label, w in cols:
            self.cell(w, 7, f" {label}", fill=True, border=1)
        self.ln()
        self.set_text_color(0, 0, 0)

    def table_row(self, values: list[str], widths: list[float], even: bool = False):
        self.set_fill_color(*(  _BLUE_LIGHT if even else _WHITE))
        self.set_font("Helvetica", "", 8.5)
        for v, w in zip(values, widths):
            self.cell(w, 6.5, f" {v}", fill=True, border=1)
        self.ln()


def generate_report_pdf(emp: dict, ded: Optional[dict], ytd: float, year: int) -> bytes:
    annual  = _annual(emp)
    remain  = max(annual - ytd, 0)
    elapsed = max(datetime.now().month, 1)
    m_acc   = annual / 12
    m_paid  = ytd / elapsed
    m_rem   = max(m_acc - m_paid, 0)

    pdf = _PDF(f"Payroll Report  -  {emp['name']}  ({year})")

    # Employee info
    pdf.section("Employee Information")
    pdf.kv("Employee ID",  emp.get("id", "-"))
    pdf.kv("Name",         emp["name"])
    pdf.kv("Pay Type",     emp.get("pay_type", "-"))
    pdf.kv("Base Salary",  _fmt(emp.get("salary", 0)))

    # Gross pay
    pdf.section("Gross Pay")
    pdf.kv("Weekly",    _fmt(emp.get("weekly",   0)))
    pdf.kv("By-Weekly", _fmt(emp.get("biweekly", 0)))
    pdf.kv("Monthly",   _fmt(emp.get("monthly",  0)))
    pdf.kv("Annual (Y-R)", _fmt(annual), bold_val=True, highlight=True)

    # NIB
    pdf.section("NIB Contributions")
    cols = [("Period", 38), ("NIB", 45), ("Employer NIB", 45), ("Salary Remaining", 42)]
    pdf.table_head(cols)
    widths = [c[1] for c in cols]
    rows = [
        ("Weekly",    emp.get("nib_w",  0), emp.get("enib_w",  0), emp.get("w_r",  0)),
        ("By-Weekly", emp.get("nib_bw", 0), emp.get("enib_bw", 0), emp.get("bw_r", 0)),
        ("Monthly",   emp.get("nib_m",  0), emp.get("enib_m",  0), emp.get("m_r",  0)),
        ("Yearly",    emp.get("nib_y",  0), 0,                        0),
    ]
    for i, (period, nib, enib, rem) in enumerate(rows):
        pdf.table_row(
            [period, _fmt(nib), _fmt(enib) if enib else "-", _fmt(rem) if rem else "-"],
            widths, even=(i % 2 == 1),
        )

    # Deductions
    pdf.section("Deductions by Entity")
    if ded:
        entities = [
            ("Commonwealth Bank (CB)",  ded.get("cb",               0)),
            ("BICCU",                   ded.get("biccu",             0)),
            ("OakTree",                 ded.get("oaktree",           0)),
            ("Furniture Plus",          ded.get("furniture_plus",    0)),
            ("Green Leaf",              ded.get("green_leaf",        0)),
            ("Sunshine Finance",        ded.get("sunshine_finance",  0)),
            ("School Loan",             ded.get("school_loan",       0)),
        ]
        active = [(n, v) for n, v in entities if v > 0]
        if active:
            pdf.table_head([("Entity", 110), ("Amount", 60)])
            for i, (n, v) in enumerate(active):
                pdf.table_row([n, _fmt(v)], [110, 60], even=(i % 2 == 1))
        pdf.ln(2)
        pdf.kv("Total  W / BW / M / Y",
               f"{_fmt(ded.get('total_w',0))}  /  {_fmt(ded.get('total_bw',0))}  /  "
               f"{_fmt(ded.get('total_m',0))}  /  {_fmt(ded.get('total_y',0))}")
    else:
        pdf.kv("Deductions", "No record found")

    # Net balance
    pdf.section("Net Balance (After All Deductions)")
    pdf.kv("Balance Weekly",     _fmt(emp.get("balance_w",  0)))
    pdf.kv("Balance By-Weekly",  _fmt(emp.get("balance_bw", 0)))
    pdf.kv("Balance Monthly",    _fmt(emp.get("balance_m",  0)))

    # YTD
    pdf.section(f"Year-to-Date Summary  ({year})")
    pdf.kv("YTD Paid",                    _fmt(ytd),    bold_val=True)
    pdf.kv("Annual Salary",               _fmt(annual))
    pdf.kv("Remaining  (Annual - YTD)",   _fmt(remain), bold_val=True, highlight=True)
    pdf.ln(2)
    pdf.kv("Monthly Accrued  (Annual ÷ 12)",             _fmt(m_acc))
    pdf.kv(f"Monthly Avg Paid  (YTD ÷ {elapsed} months)", _fmt(m_paid))
    pdf.kv("Monthly Remaining",                          _fmt(m_rem))

    return bytes(pdf.output())


def generate_receipt_pdf(
    emp: dict, payment_date: str, amount: float,
    period: str, note: str, ytd: float,
) -> bytes:
    annual = _annual(emp)
    remain = max(annual - ytd, 0)
    try:
        elapsed = max(datetime.strptime(payment_date, "%Y-%m-%d").month, 1)
    except ValueError:
        elapsed = max(datetime.now().month, 1)

    pdf = _PDF(f"Payment Receipt  -  {emp['name']}")

    pdf.section("Employee")
    pdf.kv("Name",        emp["name"])
    pdf.kv("Employee ID", emp.get("id", "-"))

    pdf.section("Payment Details")
    pdf.kv("Payment Date", payment_date)
    pdf.kv("Period",       _period_label(period))
    pdf.kv("Amount Paid",  _fmt(amount), bold_val=True, highlight=True)
    if note:
        pdf.kv("Note", note)

    pdf.section("Year-to-Date")
    pdf.kv("YTD Paid (incl. this payment)", _fmt(ytd))
    pdf.kv("Annual Salary",                 _fmt(annual))
    pdf.kv("Remaining  (Annual - YTD)",     _fmt(remain), bold_val=True, highlight=True)

    pdf.section("Monthly Summary")
    pdf.kv("Monthly Accrued  (Annual ÷ 12)",              _fmt(annual / 12))
    pdf.kv(f"Monthly Avg Paid  (YTD ÷ {elapsed} months)", _fmt(ytd / elapsed))
    pdf.kv("Monthly Remaining",
           _fmt(max((annual / 12) - (ytd / elapsed), 0)))

    return bytes(pdf.output())


def generate_payslip_pdf(
    emp: dict,
    ded: Optional[dict],
    payment: dict,
    period_gross: float,
    nib_val: float,
    enib: float,
    ded_val: float,
    net_pay: float,
    ytd: float,
    annual: float,
) -> bytes:
    """Formal payslip for a single payment."""
    period      = payment.get("period", "")
    pay_date    = payment.get("payment_date", "")
    amount_paid = payment.get("amount", net_pay)
    note        = payment.get("note", "")
    remain      = max(annual - ytd, 0)
    _PERIOD     = {"W": "Weekly", "BW": "By-Weekly", "M": "Monthly"}

    pdf = _PDF(f"PAYSLIP  -  {emp['name']}")
    pdf.set_font("Helvetica", "", 9)

    # Employee / payment header
    pdf.section("Employee Information")
    pdf.kv("Name",        emp["name"])
    pdf.kv("Employee ID", emp.get("id", "-"))
    pdf.kv("Pay Type",    emp.get("pay_type", "-"))

    pdf.section("Payment Details")
    pdf.kv("Pay Date", pay_date)
    pdf.kv("Period",   _PERIOD.get(period, period))
    if note:
        pdf.kv("Note", note)

    # Earnings
    cols   = [("Description", 110), ("Amount", 60)]
    widths = [c[1] for c in cols]
    pdf.section("Earnings")
    pdf.table_head(cols)
    pdf.table_row(["Gross Pay", _fmt(period_gross)], widths)
    pdf.ln(1)

    # Deductions
    pdf.section("Deductions")
    pdf.table_head(cols)

    ded_rows: list[tuple[str, float]] = []
    if nib_val: ded_rows.append(("NIB", nib_val))
    if enib: ded_rows.append(("Employer NIB", enib))
    if ded:
        for label, field in [
            ("Commonwealth Bank (CB)",  "cb"),
            ("BICCU",                   "biccu"),
            ("OakTree",                 "oaktree"),
            ("Furniture Plus",          "furniture_plus"),
            ("Green Leaf",              "green_leaf"),
            ("Sunshine Finance",        "sunshine_finance"),
            ("School Loan",             "school_loan"),
        ]:
            v = ded.get(field, 0)
            if v:
                ded_rows.append((label, v))

    total_ded = sum(v for _, v in ded_rows)
    for i, (label, val) in enumerate(ded_rows):
        pdf.table_row([label, _fmt(val)], widths, even=(i % 2 == 1))
    pdf.ln(1)
    pdf.kv("Total Deductions", _fmt(total_ded), bold_val=True)

    # Net pay — highlighted banner
    pdf.ln(3)
    pdf.set_fill_color(30, 60, 114)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 11, f"  NET PAY:   {_fmt(net_pay)}",
             fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

    # YTD summary
    pdf.section("Year-to-Date Summary")
    pdf.set_font("Helvetica", "", 9)
    pdf.kv("Amount Paid This Period",  _fmt(amount_paid))
    pdf.kv("YTD Total Paid",           _fmt(ytd),    bold_val=True)
    pdf.kv("Annual Salary",            _fmt(annual))
    pdf.kv("Remaining (Annual - YTD)", _fmt(remain), bold_val=True, highlight=True)

    return bytes(pdf.output())


_DED_ENTITIES = [
    ("cb",               "CB"),
    ("biccu",            "BICCU"),
    ("oaktree",          "OakTree"),
    ("furniture_plus",   "Furn+"),
    ("green_leaf",       "Green"),
    ("sunshine_finance", "Sunshine"),
    ("school_loan",      "School"),
]


def generate_monthly_report_pdf(rows: list[dict], month_label: str) -> bytes:
    """Monthly payroll summary: gross/NIB/deductions/net + deduction entity breakdown."""
    def _f(v: float) -> str:
        return f"${v:,.2f}"

    pdf = _PDF(f"Monthly Payroll Report  -  {month_label}")
    pdf.set_font("Helvetica", "", 8.5)

    # ── Section 1: Payroll Summary ────────────────────────────────────────────
    sum_cols = [
        ("Employee Name", 46),
        ("Gross Pay",     24),
        ("Emp NIB",       22),
        ("Employer NIB",       22),
        ("Deductions",    24),
        ("Net Pay",       32),
    ]
    sum_widths = [c[1] for c in sum_cols]

    pdf.section(f"Payroll Summary  -  {month_label}")
    pdf.table_head(sum_cols)

    tot_gross = tot_nib = tot_enib = tot_ded = tot_net = 0.0

    for i, row in enumerate(rows):
        g   = row["Gross"]
        n   = row["Emp NIB"]
        b   = row["Employer NIB"]
        d   = row["Deductions"]
        net = row["Net Pay"]
        tot_gross += g; tot_nib += n; tot_enib += b; tot_ded += d; tot_net += net
        pdf.table_row([row["Name"], _f(g), _f(n), _f(b), _f(d), _f(net)],
                      sum_widths, even=(i % 2 == 1))

    pdf.ln(1)
    pdf.set_fill_color(*_BLUE_DARK)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 8.5)
    for v, w in zip(
        ["TOTALS", _f(tot_gross), _f(tot_nib), _f(tot_enib), _f(tot_ded), _f(tot_net)],
        sum_widths,
    ):
        pdf.cell(w, 7, f" {v}", fill=True, border=1)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)

    # Balance verification line
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*_GREY)
    pdf.cell(0, 5,
             f"  Balance check:  Gross {_f(tot_gross)}  -  NIB {_f(tot_nib)}"
             f"  -  Deductions {_f(tot_ded)}  =  Net {_f(tot_gross - tot_nib - tot_ded)}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

    # ── Section 2: Deduction Entity Breakdown ─────────────────────────────────
    # Only include entities that have at least one non-zero value
    active_entities = [
        (field, label) for field, label in _DED_ENTITIES
        if any(row.get(field, 0) for row in rows)
    ]

    if active_entities:
        name_w = 46
        ent_w  = min(18, int(124 / max(len(active_entities), 1)))
        total_w_col = 170 - name_w - ent_w * len(active_entities)
        total_w_col = max(total_w_col, 14)

        ded_cols = [("Employee", name_w)] + [(lbl, ent_w) for _, lbl in active_entities] \
                   + [("Total", total_w_col)]
        ded_widths = [c[1] for c in ded_cols]

        pdf.section("Deduction Breakdown by Entity  (Monthly Amounts)")
        pdf.table_head(ded_cols)

        ent_totals = {field: 0.0 for field, _ in active_entities}

        for i, row in enumerate(rows):
            row_total = sum(row.get(f, 0) for f, _ in active_entities)
            if row_total == 0:
                continue
            vals = [row["Name"]] + [_f(row.get(f, 0)) for f, _ in active_entities] \
                   + [_f(row_total)]
            pdf.table_row(vals, ded_widths, even=(i % 2 == 1))
            for field, _ in active_entities:
                ent_totals[field] += row.get(field, 0)

        pdf.ln(1)
        pdf.set_fill_color(*_BLUE_DARK)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 8.5)
        grand_ded = sum(ent_totals.values())
        tot_vals = ["TOTALS"] + [_f(ent_totals[f]) for f, _ in active_entities] + [_f(grand_ded)]
        for v, w in zip(tot_vals, ded_widths):
            pdf.cell(w, 7, f" {v}", fill=True, border=1)
        pdf.ln()
        pdf.set_text_color(0, 0, 0)

    # ── Section 3: Payroll Summary Metrics ────────────────────────────────────
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_BLUE_LIGHT)
    pdf.set_text_color(*_BLUE_DARK)
    pdf.cell(0, 7, "  Totals", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 9)
    pdf.kv("Total Employees",           str(len(rows)))
    pdf.kv("Total Gross Payroll",       _f(tot_gross))
    pdf.kv("Total Employee NIB",        _f(tot_nib))
    pdf.kv("Total Employer NIB (Employer)",  _f(tot_enib))
    pdf.kv("Total Other Deductions",    _f(tot_ded))
    pdf.kv("Net = Gross - NIB - Ded",   _f(tot_gross - tot_nib - tot_ded))
    pdf.kv("Total Net Pay (Stored)",     _f(tot_net), bold_val=True, highlight=True)

    return bytes(pdf.output())
