"""Payroll — native Flask blueprint (replaces the Streamlit iframe)."""
from __future__ import annotations

import io
import sys
import os
import zipfile
import tempfile
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, send_file, abort, session, jsonify,
)

# ── import payroll data layer ──────────────────────────────────────────────────
_PAYROLL_DIR = Path(__file__).parent / "payroll_app"
if str(_PAYROLL_DIR) not in sys.path:
    sys.path.insert(0, str(_PAYROLL_DIR))

import db as _db
import pdf_gen as _pdf

_db.init_db()

payroll_bp = Blueprint("payroll_bp", __name__, url_prefix="/payroll")

_DELETE_PWD = os.environ.get("PAYROLL_DELETE_PWD", "changeme")

_ENTITY_FIELDS = [
    ("cb",               "Commonwealth Bank (CB)"),
    ("biccu",            "BICCU"),
    ("oaktree",          "OakTree"),
    ("furniture_plus",   "Furniture Plus"),
    ("green_leaf",       "Green Leaf"),
    ("sunshine_finance", "Sunshine Finance"),
    ("school_loan",      "School Loan"),
]

# ── helpers ────────────────────────────────────────────────────────────────────

def _login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapped


def _annual(emp: dict) -> float:
    if emp.get("salary"):   return float(emp["salary"])
    if emp.get("monthly"):  return float(emp["monthly"]) * 12
    if emp.get("biweekly"): return float(emp["biweekly"]) * 26
    if emp.get("weekly"):   return float(emp["weekly"]) * 52
    return 0.0


def _annual_net(emp: dict) -> float:
    if emp.get("balance_m"):  return float(emp["balance_m"]) * 12
    if emp.get("balance_bw"): return float(emp["balance_bw"]) * 26
    if emp.get("balance_w"):  return float(emp["balance_w"]) * 52
    return _annual(emp)


def _period_label(code: str) -> str:
    return {"W": "Weekly", "BW": "Bi-Weekly", "M": "Monthly"}.get(code, code)


def _mv(m, w=0.0, bw=0.0) -> float:
    _W2M, _B2M = 52 / 12, 26 / 12
    return float(m or (float(w) * _W2M) or (float(bw) * _B2M))


def _monthly_figures(emp: dict) -> dict:
    """Return monthly gross/nib/employer_nib/ded/net for an employee."""
    return {
        "gross": _mv(emp.get("monthly", 0), emp.get("weekly", 0), emp.get("biweekly", 0)),
        "nib":   _mv(emp.get("nib_m", 0),   emp.get("nib_w", 0), emp.get("nib_bw", 0)),
        "enib":  _mv(emp.get("enib_m", 0), emp.get("enib_w", 0), emp.get("enib_bw", 0)),
        "ded":   _mv(emp.get("ded_m", 0),   emp.get("ded_w", 0), emp.get("ded_bw", 0)),
        "net":   _mv(emp.get("balance_m", 0), emp.get("balance_w", 0), emp.get("balance_bw", 0)),
    }


def _year_range():
    y = datetime.now().year
    return list(range(y - 3, y + 2))


def _months():
    return [(i, datetime(2000, i, 1).strftime("%B")) for i in range(1, 13)]


# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@payroll_bp.route("/")
@_login_required
def dashboard():
    year = int(request.args.get("year", datetime.now().year))
    employees = _db.get_employees()

    rows = []
    for e in employees:
        annual     = _annual(e)
        annual_net = _annual_net(e)
        ytd        = _db.get_ytd(e["name"], year)
        fig        = _monthly_figures(e)
        rows.append({
            "id":           e["id"],
            "name":         e["name"],
            "pay_type":     e.get("pay_type", "—"),
            "gross_annual": annual,
            "net_annual":   annual_net,
            "ytd":          ytd,
            "remaining":    max(annual_net - ytd, 0),
            "progress":     round((ytd / annual_net * 100) if annual_net > 0 else 0, 1),
            "ded_m":        fig["ded"],
            "net_m":        fig["net"],
        })

    return render_template(
        "payroll/dashboard.html",
        active_tab="dashboard",
        year=year,
        rows=rows,
        total_gross=sum(r["gross_annual"] for r in rows),
        total_net=sum(r["net_annual"] for r in rows),
        total_ytd=sum(r["ytd"] for r in rows),
        total_remain=sum(r["remaining"] for r in rows),
        total_net_m=sum(r["net_m"] for r in rows),
        num_employees=len(employees),
        years=_year_range(),
    )


@payroll_bp.route("/api/chart")
@_login_required
def api_chart():
    year = int(request.args.get("year", datetime.now().year))
    employees = _db.get_employees()
    names, net_annual, ytd_vals = [], [], []
    for e in employees:
        names.append(e["name"])
        net_annual.append(_annual_net(e))
        ytd_vals.append(_db.get_ytd(e["name"], year))
    return jsonify({"names": names, "net_annual": net_annual, "ytd": ytd_vals})


# ── SYNC ──────────────────────────────────────────────────────────────────────

@payroll_bp.route("/sync", methods=["POST"])
@_login_required
def sync_staff():
    added, skipped = _db.sync_from_school()
    if added:
        flash(f"{added} staff member(s) imported from school.", "success")
    else:
        flash(f"All staff already in payroll ({skipped} existing).", "info")
    return redirect(url_for("payroll_bp.dashboard"))


# ── EMPLOYEE LIST ─────────────────────────────────────────────────────────────

@payroll_bp.route("/employees")
@_login_required
def employees():
    emps = _db.get_employees()
    return render_template("payroll/employees.html",
        active_tab="employees", employees=emps)


@payroll_bp.route("/employees/add", methods=["POST"])
@_login_required
def add_employee():
    name   = request.form.get("name", "").strip()
    emp_id = request.form.get("emp_id", "").strip()
    salary = float(request.form.get("salary") or 0)
    pay_type = request.form.get("pay_type", "Monthly")
    if not name:
        flash("Employee name is required.", "danger")
        return redirect(url_for("payroll_bp.employees"))
    monthly  = salary / 12 if salary > 0 else 0
    nib_m    = round(monthly * 0.039, 2)
    enib  = round(monthly * 0.059, 2)
    net_m    = round(monthly - nib_m, 2)
    _db.upsert_employee({
        "id":        emp_id,
        "name":      name,
        "salary":    salary,
        "pay_type":  pay_type,
        "monthly":   round(monthly, 2),
        "nib_m":     nib_m,
        "enib_m": enib,
        "m_r":       net_m,
        "balance_m": net_m,
        "nib_y":     round(nib_m * 12, 2),
        "yearly":    salary,
    })
    flash(f"Employee '{name}' added.", "success")
    return redirect(url_for("payroll_bp.employees"))


@payroll_bp.route("/employees/delete/<name>", methods=["POST"])
@_login_required
def delete_employee(name):
    pwd = request.form.get("pwd", "")
    if pwd != _DELETE_PWD:
        flash("Incorrect password.", "danger")
        return redirect(url_for("payroll_bp.employees"))
    with _db.get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE name = ?", (name,))
        conn.execute("DELETE FROM deductions WHERE name = ?", (name,))
    flash(f"Employee '{name}' deleted.", "success")
    return redirect(url_for("payroll_bp.employees"))


# ── EMPLOYEE REPORT ───────────────────────────────────────────────────────────

@payroll_bp.route("/employee/<path:name>")
@_login_required
def employee_report(name):
    emp = _db.get_employee(name)
    if not emp:
        abort(404)
    year    = int(request.args.get("year", datetime.now().year))
    ded     = _db.get_deductions(name) or {}
    ytd     = _db.get_ytd(name, year)
    annual  = _annual(emp)
    remain  = max(annual - ytd, 0)
    elapsed = max(datetime.now().month, 1)
    pct     = (ytd / annual * 100) if annual else 0

    return render_template(
        "payroll/employee_report.html",
        active_tab="report",
        emp=emp,
        ded=ded,
        ytd=ytd,
        annual=annual,
        remain=remain,
        elapsed=elapsed,
        pct=round(pct, 1),
        year=year,
        employees=_db.get_employee_names(),
        entities=_ENTITY_FIELDS,
        years=_year_range(),
    )


@payroll_bp.route("/employee/<path:name>/salary", methods=["POST"])
@_login_required
def update_salary(name):
    new_salary = float(request.form.get("salary") or 0)
    year = request.form.get("year", datetime.now().year)
    if new_salary > 0:
        _db.update_salary(name, new_salary)
        flash(f"Salary updated to ${new_salary:,.2f}", "success")
    return redirect(url_for("payroll_bp.employee_report", name=name, year=year))


@payroll_bp.route("/employee/<path:name>/deductions", methods=["POST"])
@_login_required
def save_deductions(name):
    entity_m = {f: float(request.form.get(f) or 0) for f, _ in _ENTITY_FIELDS}
    _db.save_deductions_and_recalc(name, entity_m)
    flash("Deductions saved and balances recalculated.", "success")
    year = request.form.get("year", datetime.now().year)
    return redirect(url_for("payroll_bp.employee_report", name=name, year=year))


# ── REGISTER PAYMENT ──────────────────────────────────────────────────────────

@payroll_bp.route("/register", methods=["GET", "POST"])
@_login_required
def register_payment():
    employees = _db.get_employee_names()
    selected  = request.args.get("emp") or (employees[0] if employees else None)
    year      = int(request.args.get("year", datetime.now().year))
    emp       = _db.get_employee(selected) if selected else None
    ytd       = _db.get_ytd(selected, datetime.now().year) if selected else 0
    annual_net = _annual_net(emp) if emp else 0

    if request.method == "POST":
        emp_name = request.form.get("emp", "")
        pay_date = request.form.get("pay_date", date.today().isoformat())
        period   = request.form.get("period", "M")
        amount   = float(request.form.get("amount") or 0)
        note     = request.form.get("note", "")
        emp_obj  = _db.get_employee(emp_name)
        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
        elif emp_obj:
            _db.add_payment(
                employee_id  = emp_obj.get("id", ""),
                name         = emp_name,
                payment_date = pay_date,
                period       = period,
                amount       = amount,
                note         = note,
                year         = int(pay_date[:4]),
            )
            flash(f"${amount:,.2f} registered for {emp_name}.", "success")
            return redirect(url_for("payroll_bp.register_payment", emp=emp_name))

    return render_template(
        "payroll/register_payment.html",
        active_tab="register",
        employees=employees,
        selected=selected,
        emp=emp,
        ytd=ytd,
        annual_net=annual_net,
        today=date.today().isoformat(),
        year=year,
        period_label=_period_label,
    )


# ── PAYMENT HISTORY ───────────────────────────────────────────────────────────

@payroll_bp.route("/history")
@_login_required
def payment_history():
    employees = _db.get_employee_names()
    selected  = request.args.get("emp") or (employees[0] if employees else None)
    year      = int(request.args.get("year", datetime.now().year))
    payments  = _db.get_payments(selected, year) if selected else []
    total_paid = sum(p["amount"] for p in payments)
    duplicates = _db.find_duplicate_payments()

    return render_template(
        "payroll/payment_history.html",
        active_tab="history",
        employees=employees,
        selected=selected,
        year=year,
        payments=payments,
        total_paid=total_paid,
        duplicates=duplicates,
        period_label=_period_label,
        years=_year_range(),
    )


@payroll_bp.route("/payment/delete/<int:pid>", methods=["POST"])
@_login_required
def delete_payment(pid):
    pwd  = request.form.get("pwd", "")
    emp  = request.form.get("emp", "")
    year = request.form.get("year", datetime.now().year)
    if pwd == _DELETE_PWD:
        _db.delete_payment(pid)
        flash("Payment deleted.", "success")
    else:
        flash("Incorrect password.", "danger")
    return redirect(url_for("payroll_bp.payment_history", emp=emp, year=year))


@payroll_bp.route("/duplicates/remove", methods=["POST"])
@_login_required
def remove_duplicates():
    pwd = request.form.get("pwd", "")
    if pwd == _DELETE_PWD:
        n = _db.remove_duplicate_payments()
        flash(f"Removed {n} duplicate payment(s).", "success")
    else:
        flash("Incorrect password.", "danger")
    return redirect(url_for("payroll_bp.payment_history"))


# ── LOANS ─────────────────────────────────────────────────────────────────────

@payroll_bp.route("/loans")
@_login_required
def loans():
    employees  = _db.get_employee_names()
    loan_names = _db.get_loan_names()
    all_names  = sorted(set(employees + loan_names))
    selected   = request.args.get("emp") or (all_names[0] if all_names else None)

    summary_rows = [{"name": n, **_db.get_loan_summary(n)} for n in loan_names]
    totals = {
        "total_loaned": sum(r["total_loaned"] for r in summary_rows),
        "total_paid":   sum(r["total_paid"]   for r in summary_rows),
        "balance":      sum(r["balance"]       for r in summary_rows),
    }

    emp_loans    = _db.get_loans(selected) if selected else []
    emp_payments = _db.get_loan_payments(selected) if selected else []
    emp_summary  = _db.get_loan_summary(selected) if selected else {"total_loaned": 0, "total_paid": 0, "balance": 0}

    return render_template(
        "payroll/loans.html",
        active_tab="loans",
        all_names=all_names,
        selected=selected,
        summary_rows=summary_rows,
        totals=totals,
        emp_loans=emp_loans,
        emp_payments=emp_payments,
        emp_summary=emp_summary,
        today=date.today().isoformat(),
    )


@payroll_bp.route("/loan/add", methods=["POST"])
@_login_required
def add_loan():
    emp       = request.form.get("emp", "")
    principal = float(request.form.get("principal") or 0)
    if principal > 0:
        _db.add_loan(
            employee_name = emp,
            loan_date     = request.form.get("loan_date", date.today().isoformat()),
            principal     = principal,
            pmt_amount    = float(request.form.get("pmt_amount") or 0),
            description   = request.form.get("description", ""),
        )
        flash(f"Loan of ${principal:,.2f} added.", "success")
    return redirect(url_for("payroll_bp.loans", emp=emp))


@payroll_bp.route("/loan/edit/<int:lid>", methods=["POST"])
@_login_required
def edit_loan(lid):
    emp = request.form.get("emp", "")
    _db.update_loan(
        lid,
        request.form.get("loan_date", date.today().isoformat()),
        float(request.form.get("principal") or 0),
        float(request.form.get("pmt_amount") or 0),
        request.form.get("description", ""),
    )
    flash("Loan updated.", "success")
    return redirect(url_for("payroll_bp.loans", emp=emp))


@payroll_bp.route("/loan/delete/<int:lid>", methods=["POST"])
@_login_required
def delete_loan(lid):
    emp = request.form.get("emp", "")
    if request.form.get("pwd", "") == _DELETE_PWD:
        _db.delete_loan(lid)
        flash("Loan deleted.", "success")
    else:
        flash("Incorrect password.", "danger")
    return redirect(url_for("payroll_bp.loans", emp=emp))


@payroll_bp.route("/loan/payment/add", methods=["POST"])
@_login_required
def add_loan_payment():
    emp    = request.form.get("emp", "")
    amount = float(request.form.get("amount") or 0)
    if amount > 0:
        _db.add_loan_payment(
            employee_name = emp,
            payment_date  = request.form.get("pay_date", date.today().isoformat()),
            amount        = amount,
            note          = request.form.get("note", ""),
        )
        flash(f"Payment of ${amount:,.2f} recorded.", "success")
    return redirect(url_for("payroll_bp.loans", emp=emp))


@payroll_bp.route("/loan/payment/edit/<int:pid>", methods=["POST"])
@_login_required
def edit_loan_payment(pid):
    emp = request.form.get("emp", "")
    _db.update_loan_payment(
        pid,
        request.form.get("pay_date", date.today().isoformat()),
        float(request.form.get("amount") or 0),
        request.form.get("note", ""),
    )
    flash("Payment updated.", "success")
    return redirect(url_for("payroll_bp.loans", emp=emp))


@payroll_bp.route("/loan/payment/delete/<int:pid>", methods=["POST"])
@_login_required
def delete_loan_payment(pid):
    emp = request.form.get("emp", "")
    if request.form.get("pwd", "") == _DELETE_PWD:
        _db.delete_loan_payment(pid)
        flash("Payment deleted.", "success")
    else:
        flash("Incorrect password.", "danger")
    return redirect(url_for("payroll_bp.loans", emp=emp))


# ── PAYSLIP ───────────────────────────────────────────────────────────────────

def _build_slip_data(emp: dict, ded: dict | None, selected: str, year: int) -> dict | None:
    payments = _db.get_payments(selected, year)
    if not payments:
        return None
    pay = payments[0]
    _W2M, _B2M = 52 / 12, 26 / 12
    def _m(m, w=0, bw=0):
        return float(m or (float(w) * _W2M) or (float(bw) * _B2M))

    period_gross = _m(emp.get("monthly", 0), emp.get("weekly", 0), emp.get("biweekly", 0))
    nib_val  = _m(emp.get("nib_m", 0),     emp.get("nib_w", 0),     emp.get("nib_bw", 0))
    enib  = _m(emp.get("enib_m", 0), emp.get("enib_w", 0), emp.get("enib_bw", 0))
    ded_val  = _m(emp.get("ded_m", 0),     emp.get("ded_w", 0),     emp.get("ded_bw", 0))
    loan_ded = _db.get_loan_monthly_deduction(selected)
    net_pay  = (_m(emp.get("balance_m", 0), emp.get("balance_w", 0), emp.get("balance_bw", 0))
                or (period_gross - nib_val - ded_val)) - loan_ded
    annual_net = _annual_net(emp)
    ytd = _db.get_ytd(selected, year)

    ded_rows = [("NIB", nib_val), ("Employer NIB", enib)]
    if ded:
        for label, field in [
            ("CB", "cb"), ("BICCU", "biccu"), ("OakTree", "oaktree"),
            ("Furniture Plus", "furniture_plus"), ("Green Leaf", "green_leaf"),
            ("Sunshine Finance", "sunshine_finance"), ("School Loan", "school_loan"),
        ]:
            v = ded.get(field, 0)
            if v > 0:
                ded_rows.append((label, float(v)))
    if loan_ded > 0:
        ded_rows.append(("Loan Repayment", loan_ded))

    return {
        "payments":     payments,
        "pay":          pay,
        "period_gross": period_gross,
        "nib_val":      nib_val,
        "enib":      enib,
        "ded_val":      ded_val,
        "net_pay":      net_pay,
        "annual_net":   annual_net,
        "ytd":          ytd,
        "ded_rows":     [(l, v) for l, v in ded_rows if v > 0],
    }


@payroll_bp.route("/payslip")
@_login_required
def payslip():
    employees = _db.get_employee_names()
    selected  = request.args.get("emp") or (employees[0] if employees else None)
    year      = int(request.args.get("year", datetime.now().year))
    pay_id    = request.args.get("pay_id", type=int)
    emp       = _db.get_employee(selected) if selected else None
    ded       = _db.get_deductions(selected) if selected else None
    slip      = None

    if emp:
        slip = _build_slip_data(emp, ded, selected, year)
        if slip and pay_id:
            slip["pay"] = next((p for p in slip["payments"] if p["id"] == pay_id), slip["payments"][0])

    return render_template(
        "payroll/payslip.html",
        active_tab="payslip",
        employees=employees,
        selected=selected,
        year=year,
        emp=emp,
        slip=slip,
        period_label=_period_label,
        years=_year_range(),
    )


@payroll_bp.route("/payslip/pdf")
@_login_required
def payslip_pdf():
    emp_name = request.args.get("emp", "")
    pay_id   = request.args.get("pay_id", type=int)
    year     = int(request.args.get("year", datetime.now().year))
    emp      = _db.get_employee(emp_name)
    ded      = _db.get_deductions(emp_name)
    if not emp:
        abort(404)
    slip = _build_slip_data(emp, ded, emp_name, year)
    if not slip:
        abort(404)
    pay = next((p for p in slip["payments"] if p["id"] == pay_id), slip["payments"][0]) if pay_id else slip["pay"]
    pdf_bytes = _pdf.generate_payslip_pdf(
        emp=emp, ded=ded, payment=pay,
        period_gross=slip["period_gross"], nib_val=slip["nib_val"],
        enib=slip["enib"], ded_val=slip["ded_val"],
        net_pay=slip["net_pay"], ytd=slip["ytd"], annual=slip["annual_net"],
    )
    safe = emp_name.replace(" ", "_")
    return send_file(io.BytesIO(pdf_bytes),
                     download_name=f"Payslip_{safe}_{pay['payment_date']}.pdf",
                     mimetype="application/pdf")


# ── EXPORT ────────────────────────────────────────────────────────────────────

@payroll_bp.route("/export")
@_login_required
def export():
    employees = _db.get_employee_names()
    selected  = request.args.get("emp") or (employees[0] if employees else None)
    year      = int(request.args.get("year", datetime.now().year))
    emp       = _db.get_employee(selected) if selected else None
    payments  = _db.get_payments(selected, year) if selected else []
    ytd       = _db.get_ytd(selected, year) if selected else 0

    # Monthly report data
    all_emps  = _db.get_employees()
    rpt_rows  = []
    for e in all_emps:
        if not (e.get("salary") or e.get("weekly") or e.get("monthly") or e.get("biweekly")):
            continue
        f = _monthly_figures(e)
        dr = _db.get_deductions(e["name"]) or {}
        rpt_rows.append({
            "Name": e["name"], "Gross": f["gross"],
            "Emp NIB": f["nib"], "Employer NIB": f["enib"],
            "Deductions": f["ded"], "Net Pay": f["net"],
            **{field: float(dr.get(field, 0)) for field, _ in _ENTITY_FIELDS},
        })

    return render_template(
        "payroll/export.html",
        active_tab="export",
        employees=employees,
        selected=selected,
        year=year,
        emp=emp,
        payments=payments,
        ytd=ytd,
        annual_net=_annual_net(emp) if emp else 0,
        rpt_rows=rpt_rows,
        months=_months(),
        current_month=datetime.now().month,
        years=_year_range(),
    )


@payroll_bp.route("/export/report.pdf")
@_login_required
def export_report_pdf():
    name = request.args.get("emp", "")
    year = int(request.args.get("year", datetime.now().year))
    emp  = _db.get_employee(name)
    if not emp:
        abort(404)
    ded  = _db.get_deductions(name)
    ytd  = _db.get_ytd(name, year)
    data = _pdf.generate_report_pdf(emp, ded, ytd, year)
    safe = name.replace(" ", "_").replace("/", "_")
    return send_file(io.BytesIO(data),
                     download_name=f"Reporte_{safe}_{year}.pdf",
                     mimetype="application/pdf")


@payroll_bp.route("/export/receipt.pdf")
@_login_required
def export_receipt_pdf():
    name = request.args.get("emp", "")
    year = int(request.args.get("year", datetime.now().year))
    emp  = _db.get_employee(name)
    if not emp:
        abort(404)
    ytd      = _db.get_ytd(name, year)
    payments = _db.get_payments(name, year)
    if not payments:
        abort(404)
    last = payments[0]
    data = _pdf.generate_receipt_pdf(emp, last["payment_date"], last["amount"],
                                     last["period"], last.get("note", ""), ytd)
    safe = name.replace(" ", "_").replace("/", "_")
    return send_file(io.BytesIO(data),
                     download_name=f"Receipt_{safe}_{last['payment_date']}.pdf",
                     mimetype="application/pdf")


@payroll_bp.route("/export/bulk.zip")
@_login_required
def export_bulk_zip():
    year = int(request.args.get("year", datetime.now().year))
    buf  = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in _db.get_employees():
            ed   = _db.get_deductions(e["name"])
            eytd = _db.get_ytd(e["name"], year)
            data = _pdf.generate_report_pdf(e, ed, eytd, year)
            safe = e["name"].replace(" ", "_").replace("/", "_")
            zf.writestr(f"Reporte_{safe}_{year}.pdf", data)
    buf.seek(0)
    return send_file(buf, download_name=f"Payroll_Reports_{year}.zip",
                     mimetype="application/zip")


@payroll_bp.route("/export/monthly.pdf")
@_login_required
def export_monthly_pdf():
    year  = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    label = datetime(year, month, 1).strftime("%B %Y")

    rpt_rows = []
    for e in _db.get_employees():
        if not (e.get("salary") or e.get("weekly") or e.get("monthly") or e.get("biweekly")):
            continue
        f  = _monthly_figures(e)
        dr = _db.get_deductions(e["name"]) or {}
        rpt_rows.append({
            "Name": e["name"], "Gross": f["gross"],
            "Emp NIB": f["nib"], "Employer NIB": f["enib"],
            "Deductions": f["ded"], "Net Pay": f["net"],
            **{field: float(dr.get(field, 0)) for field, _ in _ENTITY_FIELDS},
        })

    data = _pdf.generate_monthly_report_pdf(rpt_rows, label)
    return send_file(io.BytesIO(data),
                     download_name=f"Monthly_Payroll_{label.replace(' ','_')}.pdf",
                     mimetype="application/pdf")


# ── SETTINGS ──────────────────────────────────────────────────────────────────

@payroll_bp.route("/settings")
@_login_required
def settings():
    all_emp = _db.get_employees()
    all_pay = _db.get_all_payments()
    return render_template(
        "payroll/settings.html",
        active_tab="settings",
        num_employees=len(all_emp),
        num_payments=len(all_pay),
        years_in_db=len({p["year"] for p in all_pay}) if all_pay else 0,
        db_path=str(_db.DB_PATH),
        employees=all_emp,
    )


@payroll_bp.route("/settings/import", methods=["POST"])
@_login_required
def import_excel():
    if str(_PAYROLL_DIR) not in sys.path:
        sys.path.insert(0, str(_PAYROLL_DIR))
    from migrate import migrate, EXCEL_PATH  # type: ignore

    uploaded = request.files.get("excel_file")
    try:
        if uploaded and uploaded.filename:
            tmp = Path(tempfile.mktemp(suffix=Path(uploaded.filename).suffix or ".xlsx"))
            uploaded.save(str(tmp))
            e, d, p = migrate(tmp)
            tmp.unlink(missing_ok=True)
        elif EXCEL_PATH.exists():
            e, d, p = migrate(EXCEL_PATH)
        else:
            flash("No Excel file provided or found.", "danger")
            return redirect(url_for("payroll_bp.settings"))
        flash(f"Import complete — {e} employees · {d} deduction records · {p} payments", "success")
    except Exception as exc:
        flash(f"Import failed: {exc}", "danger")
    return redirect(url_for("payroll_bp.settings"))


@payroll_bp.route("/settings/clear", methods=["POST"])
@_login_required
def clear_database():
    pwd = request.form.get("pwd", "")
    if pwd == _DELETE_PWD:
        _db.DB_PATH.unlink(missing_ok=True)
        _db.init_db()
        flash("Payroll database cleared.", "success")
    else:
        flash("Incorrect password.", "danger")
    return redirect(url_for("payroll_bp.settings"))
