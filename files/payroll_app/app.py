"""Payroll System — Streamlit web app."""
from __future__ import annotations

import io
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import db
import pdf_gen
from migrate import EXCEL_PATH, migrate

# ── Bootstrap ────────────────────────────────────────────────────────────────
db.init_db()

# Auto-sync staff from school.db on first load each session
if "school_synced" not in st.session_state:
    _added, _ = db.sync_from_school()
    st.session_state["school_synced"] = True
    if _added:
        st.session_state["sync_msg"] = f"{_added} staff member(s) imported from school."

_DELETE_PWD = os.environ.get("PAYROLL_DELETE_PWD", "changeme")

st.set_page_config(
    page_title="Payroll System",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Cached DB helpers ────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def _get_employees():
    return db.get_employees()

@st.cache_data(ttl=60)
def _get_employee_names():
    return db.get_employee_names()

@st.cache_data(ttl=60)
def _get_loan_names():
    return db.get_loan_names()

@st.cache_data(ttl=30)
def _get_ytd(name: str, year: int):
    return db.get_ytd(name, year)

def _clear_caches():
    _get_employees.clear()
    _get_employee_names.clear()
    _get_loan_names.clear()
    _get_ytd.clear()


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Payroll System")
    st.markdown("---")

    names = _get_employee_names()
    if names:
        selected = st.selectbox("Employee", names, key="sel_emp")
    else:
        selected = None
        st.warning("No employees found.\nGo to **⚙ Settings** to import data.")

    st.markdown("---")
    year_sel = st.number_input(
        "Year", min_value=2000, max_value=2100,
        value=datetime.now().year, step=1, key="sel_year",
    )
    st.markdown("---")
    if st.button("🔄 Sync Staff from School", use_container_width=True):
        _added, _skipped = db.sync_from_school()
        _clear_caches()
        if _added:
            st.success(f"{_added} staff member(s) imported.")
        else:
            st.info("All staff already in payroll.")

    if st.session_state.get("sync_msg"):
        st.success(st.session_state.pop("sync_msg"))

    st.markdown("---")
    st.caption("Data stored in `payroll.db`")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _annual(emp: dict) -> float:
    if emp.get("salary"):   return float(emp["salary"])
    if emp.get("monthly"):  return emp["monthly"]  * 12
    if emp.get("biweekly"): return emp["biweekly"] * 26
    if emp.get("weekly"):   return emp["weekly"]   * 52
    return 0.0


def _annual_net(emp: dict) -> float:
    """Annual take-home after NIB and deductions — matches what gets registered as payments."""
    if emp.get("balance_m"):  return float(emp["balance_m"]) * 12
    if emp.get("balance_bw"): return float(emp["balance_bw"]) * 26
    if emp.get("balance_w"):  return float(emp["balance_w"]) * 52
    return _annual(emp)


def _period_label(code: str) -> str:
    return {"W": "Weekly", "BW": "By-Weekly", "M": "Monthly"}.get(code, code)


# ── Shared table CSS ──────────────────────────────────────────────────────────
_TABLE_STYLES = [
    {"selector": "thead th", "props": "background-color:#1E3C72; color:white; font-weight:bold; text-align:center;"},
    {"selector": "tbody tr:nth-child(even)", "props": "background-color:#F0F4FF;"},
    {"selector": "tbody tr:hover", "props": "background-color:#D6E4FF;"},
    {"selector": "td", "props": "text-align:right; padding:4px 10px;"},
    {"selector": "th.row_heading", "props": "text-align:left; padding:4px 8px;"},
    {"selector": "", "props": "border-collapse:collapse; width:100%;"},
]

_MONEY_FMT  = "${:,.2f}"
_PCT_FMT    = "{:.1f}%"


def _base(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Return a Styler with shared table CSS pre-applied."""
    return df.style.set_table_styles(_TABLE_STYLES)


def _money_cols(df: pd.DataFrame, cols: list[str]) -> dict:
    return {c: _MONEY_FMT for c in cols if c in df.columns}


def style_dashboard(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Dashboard summary: gradient on Remaining, bar on Progress %."""
    money = _money_cols(df, ["Gross Annual", "Net Annual", "YTD Paid", "Remaining", "Deductions/mo", "Net/mo"])
    s = (
        _base(df)
        .format({**money, "Progress %": _PCT_FMT})
        .background_gradient(subset=["Remaining"], cmap="RdYlGn", vmin=0)
        .background_gradient(subset=["YTD Paid"],  cmap="Blues",  vmin=0)
        .bar(subset=["Progress %"], color=["#ff4b4b", "#1E3C72"], vmin=0, vmax=100)
        .highlight_max(subset=["Net Annual", "Remaining"], color="#D6FFE8")
        .highlight_min(subset=["Remaining"],               color="#FFE0E0")
    )
    if "Deductions/mo" in df.columns and df["Deductions/mo"].sum() > 0:
        s = s.background_gradient(subset=["Deductions/mo"], cmap="Oranges", vmin=0)
    if "Net/mo" in df.columns and df["Net/mo"].sum() > 0:
        s = s.background_gradient(subset=["Net/mo"], cmap="Greens", vmin=0)
    return s


def style_simple(df: pd.DataFrame, money_cols: list[str]) -> pd.io.formats.style.Styler:
    """Generic money table with shared CSS."""
    return _base(df).format(_money_cols(df, money_cols))


def style_nib(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """NIB table: gradient on each money column."""
    money = ["NIB", "Employer NIB", "Remaining"]
    s = _base(df).format(_money_cols(df, money))
    for col in money:
        if col in df.columns and df[col].sum() > 0:
            s = s.background_gradient(subset=[col], cmap="Blues", vmin=0)
    return s


def style_deductions(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Deductions entity table: bar on Amount, highlight max."""
    return (
        _base(df)
        .format({"Amount": _MONEY_FMT})
        .bar(subset=["Amount"], color="#1E3C72", vmin=0)
        .highlight_max(subset=["Amount"], color="#FFE0B2")
    )


def style_ytd(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """YTD summary: highlight the Remaining row in amber."""
    def _mark_remaining(row):
        return ["background-color:#FFF8E1; font-weight:bold"
                if "Remaining" in str(row["Metric"]) else "" for _ in row]
    return (
        _base(df)
        .format({"Amount": _MONEY_FMT})
        .apply(_mark_remaining, axis=1)
    )


def style_history(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Payment history: gradient on Amount, color-code Period."""
    _PERIOD_COLORS = {
        "Weekly":    "background-color:#E3F2FD; color:#0D47A1;",
        "By-Weekly": "background-color:#E8F5E9; color:#1B5E20;",
        "Monthly":   "background-color:#FFF3E0; color:#E65100;",
    }

    def _color_period(val):
        return _PERIOD_COLORS.get(str(val), "")

    s = _base(df).format({"Amount": _MONEY_FMT})
    if "Amount" in df.columns and df["Amount"].sum() > 0:
        s = s.background_gradient(subset=["Amount"], cmap="YlGn", vmin=0)
    if "Period" in df.columns:
        s = s.map(_color_period, subset=["Period"])
    if "Amount" in df.columns:
        s = s.highlight_max(subset=["Amount"], color="#B9F6CA")
    return s


# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_dash, tab_report, tab_pay, tab_hist, tab_loans, tab_slip, tab_export, tab_settings = st.tabs([
    "📊 Dashboard",
    "👤 Report",
    "💳 Register Payment",
    "📋 History",
    "🏦 Loans",
    "🧾 Payslip",
    "📄 Export PDF",
    "⚙ Settings",
])


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.header(f"Dashboard  —  {int(year_sel)}")

    employees = _get_employees()
    if not employees:
        st.info("No data yet. Go to **⚙ Settings** to import from Excel.")
        st.stop()

    # Compute per-employee summary
    _W2M_d, _B2M_d = 52 / 12, 26 / 12

    def _mv(m, w=0.0, bw=0.0):
        return float(m or (w * _W2M_d) or (bw * _B2M_d))

    rows = []
    for e in employees:
        annual     = _annual(e)
        annual_net = _annual_net(e)
        ytd        = _get_ytd(e["name"], int(year_sel))
        ded_m      = _mv(e.get("ded_m", 0), e.get("ded_w", 0), e.get("ded_bw", 0))
        net_m      = _mv(e.get("balance_m", 0), e.get("balance_w", 0), e.get("balance_bw", 0))
        rows.append({
            "ID":            e["id"],
            "Name":          e["name"],
            "Pay Type":      e.get("pay_type", "—"),
            "Gross Annual":  annual,
            "Net Annual":    annual_net,
            "YTD Paid":      ytd,
            "Remaining":     max(annual_net - ytd, 0),
            "Progress %":    round((ytd / annual_net * 100) if annual_net > 0 else 0, 1),
            "Deductions/mo": ded_m,
            "Net/mo":        net_m,
        })
    summary_df = pd.DataFrame(rows)

    # KPI strip
    total_gross   = summary_df["Gross Annual"].sum()
    total_net_ann = summary_df["Net Annual"].sum()
    total_ytd     = summary_df["YTD Paid"].sum()
    total_remain  = summary_df["Remaining"].sum()
    total_ded     = summary_df["Deductions/mo"].sum()
    total_net_m   = summary_df["Net/mo"].sum()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Employees",            len(employees))
    c2.metric("Gross Annual Payroll", f"${total_gross:,.2f}")
    c3.metric("Net Annual Payroll",   f"${total_net_ann:,.2f}")
    c4.metric(f"YTD Paid ({int(year_sel)})", f"${total_ytd:,.2f}")
    c5.metric("Remaining",            f"${total_remain:,.2f}")
    c6.metric("Total Net/mo",         f"${total_net_m:,.2f}")

    st.markdown("---")

    # Bar chart: Net Annual vs YTD
    fig = go.Figure()
    fig.add_bar(
        name="Net Annual",
        x=summary_df["Name"],
        y=summary_df["Net Annual"],
        marker_color="rgba(30,60,114,0.3)",
    )
    fig.add_bar(
        name="YTD Paid",
        x=summary_df["Name"],
        y=summary_df["YTD Paid"],
        marker_color="rgba(30,60,114,0.9)",
    )
    fig.update_layout(
        barmode="overlay",
        title=f"Net Annual vs YTD Paid  ({int(year_sel)})",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=50, b=10),
        height=320,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    display = summary_df[["Name", "Pay Type", "Gross Annual", "Net Annual", "YTD Paid", "Remaining", "Progress %", "Deductions/mo", "Net/mo"]].copy()
    st.dataframe(
        style_dashboard(display),
        use_container_width=True,
        hide_index=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# EMPLOYEE REPORT
# ═══════════════════════════════════════════════════════════════════════════════
with tab_report:
    st.header("Employee Report")

    if not selected:
        st.info("Select an employee in the sidebar.")
    else:
        emp  = db.get_employee(selected)
        ded  = db.get_deductions(selected)
        ytd  = db.get_ytd(selected, int(year_sel))
        annual  = _annual(emp)
        remain  = max(annual - ytd, 0)
        elapsed = max(datetime.now().month, 1)
        pct     = (ytd / annual * 100) if annual else 0

        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Annual Salary",          f"${annual:,.2f}")
        k2.metric(f"YTD Paid ({int(year_sel)})", f"${ytd:,.2f}")
        k3.metric("Remaining",              f"${remain:,.2f}")
        k4.metric("YTD Progress",           f"{pct:.1f}%")

        st.progress(min(pct / 100, 1.0))
        st.markdown("---")

        col_l, col_r = st.columns(2)

        with col_l:
            st.subheader("Employee Info")
            st.write(f"**ID:** {emp.get('id', '—')}")
            st.write(f"**Pay Type:** {emp.get('pay_type', '—')}")
            st.write(f"**Base Salary:** ${emp.get('salary', 0):,.2f}")

            st.subheader("Gross Pay")
            gp_df = pd.DataFrame({
                "Period":  ["Weekly",                "By-Weekly",             "Monthly"],
                "Amount":  [emp.get("weekly",   0), emp.get("biweekly", 0), emp.get("monthly", 0)],
            })
            st.dataframe(
                _base(gp_df).format({"Amount": _MONEY_FMT})
                .bar(subset=["Amount"], color="#1E3C72", vmin=0),
                hide_index=True, use_container_width=True,
            )

            st.subheader("NIB Contributions")
            nib_df = pd.DataFrame({
                "Period":    ["Weekly",               "By-Weekly",              "Monthly",             "Yearly"],
                "NIB":       [emp.get("nib_w",   0), emp.get("nib_bw",  0), emp.get("nib_m",  0), emp.get("nib_y", 0)],
                "Employer NIB":   [emp.get("enib_w",0), emp.get("enib_bw",0), emp.get("enib_m",0), 0],
                "Remaining": [emp.get("w_r",     0), emp.get("bw_r",    0), emp.get("m_r",    0), 0],
            })
            st.dataframe(
                style_nib(nib_df),
                hide_index=True, use_container_width=True,
            )

        with col_r:
            st.subheader("Deductions")
            if ded:
                ded_items = [
                    ("Commonwealth Bank (CB)",  ded.get("cb",               0)),
                    ("BICCU",                   ded.get("biccu",             0)),
                    ("OakTree",                 ded.get("oaktree",           0)),
                    ("Furniture Plus",          ded.get("furniture_plus",    0)),
                    ("Green Leaf",              ded.get("green_leaf",        0)),
                    ("Sunshine Finance",        ded.get("sunshine_finance",  0)),
                    ("School Loan",             ded.get("school_loan",       0)),
                ]
                ded_df = pd.DataFrame(
                    [r for r in ded_items if r[1] > 0], columns=["Entity", "Amount"]
                )
                if not ded_df.empty:
                    st.dataframe(
                        style_deductions(ded_df),
                        hide_index=True, use_container_width=True,
                    )
                totals_df = pd.DataFrame({
                    "Period":  ["Weekly", "By-Weekly", "Monthly", "Yearly"],
                    "Total":   [ded.get("total_w", 0), ded.get("total_bw", 0),
                                ded.get("total_m", 0), ded.get("total_y",  0)],
                })
                st.dataframe(
                    _base(totals_df).format({"Total": _MONEY_FMT})
                    .bar(subset=["Total"], color="#E57373", vmin=0),
                    hide_index=True, use_container_width=True,
                )
            else:
                st.info("No deduction record found.")

            st.subheader("Net Balance (After Deductions)")
            bal_df = pd.DataFrame({
                "Period":  ["Weekly",              "By-Weekly",               "Monthly"],
                "Balance": [emp.get("balance_w",0), emp.get("balance_bw",0), emp.get("balance_m",0)],
            })
            st.dataframe(
                _base(bal_df).format({"Balance": _MONEY_FMT})
                .background_gradient(subset=["Balance"], cmap="RdYlGn", vmin=0),
                hide_index=True, use_container_width=True,
            )

            st.subheader(f"Year-to-Date  ({int(year_sel)})")
            ytd_df = pd.DataFrame({
                "Metric": [
                    "YTD Paid", "Annual Salary", "Remaining",
                    "Monthly Accrued (Annual÷12)",
                    f"Monthly Avg Paid (YTD÷{elapsed}mo)",
                    "Monthly Remaining",
                ],
                "Amount": [
                    ytd, annual, remain,
                    annual / 12,
                    ytd / elapsed,
                    max((annual / 12) - (ytd / elapsed), 0),
                ],
            })
            st.dataframe(style_ytd(ytd_df), hide_index=True, use_container_width=True)

        # ── Deduction Editor ────────────────────────────────────────────────
        st.markdown("---")
        with st.expander("✏️ Edit Deductions  (enter monthly amounts — all periods auto-calculate)"):
            _ENTITIES = [
                ("cb",               "Commonwealth Bank (CB)"),
                ("biccu",            "BICCU"),
                ("oaktree",          "OakTree"),
                ("furniture_plus",   "Furniture Plus"),
                ("green_leaf",       "Green Leaf"),
                ("sunshine_finance", "Sunshine Finance"),
                ("school_loan",      "School Loan"),
            ]
            ded_cur = db.get_deductions(selected) or {}

            with st.form("ded_edit_form"):
                cols_e = st.columns(2)
                entity_vals: dict[str, float] = {}
                for i, (field, label) in enumerate(_ENTITIES):
                    with cols_e[i % 2]:
                        entity_vals[field] = st.number_input(
                            f"{label}",
                            value=float(ded_cur.get(field, 0)),
                            min_value=0.0, step=1.0, format="%.2f",
                            key=f"ded_{field}",
                        )

                total_m_edit  = sum(entity_vals.values())
                total_w_edit  = total_m_edit * 12 / 52
                total_bw_edit = total_m_edit * 12 / 26
                total_y_edit  = total_m_edit * 12

                st.markdown("**Auto-calculated totals:**")
                ca, cb_, cc, cd = st.columns(4)
                ca.metric("Weekly",    f"${total_w_edit:,.2f}")
                cb_.metric("Bi-Weekly", f"${total_bw_edit:,.2f}")
                cc.metric("Monthly",   f"${total_m_edit:,.2f}")
                cd.metric("Yearly",    f"${total_y_edit:,.2f}")

                if st.form_submit_button("💾 Save & Recalculate Balances", type="primary"):
                    db.save_deductions_and_recalc(selected, entity_vals)
                    st.success("Deductions saved — weekly/bi-weekly/yearly and all balances updated.")
                    _clear_caches(); st.rerun()

        # ── Salary Editor ───────────────────────────────────────────────────
        with st.expander("💰 Edit Base Salary"):
            emp_cur = db.get_employee(selected)
            cur_salary = float(emp_cur.get("salary", 0))

            with st.form("salary_edit_form"):
                new_salary = st.number_input(
                    "Base Salary (Annual)",
                    value=cur_salary,
                    min_value=0.0, step=100.0, format="%.2f",
                )

                # Live preview
                if new_salary > 0:
                    st.markdown("**Auto-calculated gross pay:**")
                    p1, p2, p3 = st.columns(3)
                    p1.metric("Weekly",    f"${new_salary/52:,.2f}")
                    p2.metric("Bi-Weekly", f"${new_salary/26:,.2f}")
                    p3.metric("Monthly",   f"${new_salary/12:,.2f}")

                if st.form_submit_button("💾 Save Salary & Recalculate All", type="primary"):
                    if new_salary != cur_salary:
                        db.update_salary(selected, new_salary)
                        st.success(f"Salary updated to ${new_salary:,.2f} — gross, NIB and balances recalculated.")
                        _clear_caches(); st.rerun()
                    else:
                        st.info("No change.")


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTER PAYMENT
# ═══════════════════════════════════════════════════════════════════════════════
with tab_pay:
    st.header("Register Payment")

    if not selected:
        st.info("Select an employee in the sidebar.")
    else:
        emp = db.get_employee(selected)
        ytd = db.get_ytd(selected, datetime.now().year)
        st.write(f"Recording a payment for **{selected}**")

        col_a, col_b = st.columns([2, 1])
        with col_a:
            with st.form("form_payment", clear_on_submit=True):
                fc1, fc2 = st.columns(2)
                with fc1:
                    pay_date = st.date_input("Payment Date", value=date.today())
                    period   = st.selectbox(
                        "Period", ["W", "BW", "M"],
                        format_func=_period_label,
                    )
                with fc2:
                    amount = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f")
                    note   = st.text_input("Note (optional)")

                submitted = st.form_submit_button("✔ Register Payment", type="primary", use_container_width=True)

            if submitted:
                if amount <= 0:
                    st.error("Amount must be greater than zero.")
                else:
                    db.add_payment(
                        employee_id  = emp.get("id", ""),
                        name         = selected,
                        payment_date = pay_date.strftime("%Y-%m-%d"),
                        period       = period,
                        amount       = float(amount),
                        note         = note,
                        year         = pay_date.year,
                    )
                    st.success(f"${amount:,.2f} registered for {selected} on {pay_date}.")
                    _clear_caches(); st.rerun()

        with col_b:
            annual_net = _annual_net(emp)
            st.markdown("#### Current Status")
            st.metric("Annual Net Pay",  f"${annual_net:,.2f}")
            st.metric(f"YTD {datetime.now().year}", f"${ytd:,.2f}")
            st.metric("Remaining",       f"${max(annual_net-ytd,0):,.2f}")
            if annual_net > 0:
                st.progress(min(ytd / annual_net, 1.0))


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT HISTORY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_hist:
    st.header("Payment History")

    if not selected:
        st.info("Select an employee in the sidebar.")
    else:
        payments = db.get_payments(selected, int(year_sel))

        if not payments:
            st.info(f"No payments found for **{selected}** in {int(year_sel)}.")
        else:
            total_paid = sum(p["amount"] for p in payments)
            h1, h2, h3 = st.columns(3)
            h1.metric(f"Total Paid ({int(year_sel)})", f"${total_paid:,.2f}")
            h2.metric("Number of Payments",            len(payments))
            h3.metric("Average Payment",               f"${total_paid/len(payments):,.2f}")

            df = pd.DataFrame(payments)
            df["period"] = df["period"].map(_period_label)
            df = df.rename(columns={
                "payment_date": "Date",
                "period":       "Period",
                "amount":       "Amount",
                "note":         "Note",
                "timestamp":    "Recorded At",
            })
            show_cols = ["Date", "Period", "Amount", "Note", "Recorded At"]
            df = df[[c for c in show_cols if c in df.columns]]

            st.dataframe(
                style_history(df),
                use_container_width=True,
                hide_index=True,
            )

            # Delete a payment
            with st.expander("Delete a payment"):
                ids = [p["id"] for p in payments]
                del_id = st.selectbox(
                    "Select payment ID to delete",
                    ids,
                    format_func=lambda i: next(
                        f"#{i}  {p['payment_date']}  ${p['amount']:,.2f}" for p in payments if p["id"] == i
                    ),
                )
                dp_pwd = st.text_input("Password", type="password", key="del_pay_pwd")
                if st.button("Delete", type="secondary"):
                    if dp_pwd == _DELETE_PWD:
                        db.delete_payment(del_id)
                        st.success(f"Payment #{del_id} deleted.")
                        _clear_caches(); st.rerun()
                    else:
                        st.error("Incorrect password.")

        # ── Duplicate finder (all employees, selected year) ──────────────────
        st.markdown("---")
        with st.expander("🔍 Find & Remove Duplicate Payments"):
            dupes = db.find_duplicate_payments()
            if not dupes:
                st.success("No duplicate payments found.")
            else:
                st.warning(f"Found **{len(dupes)}** duplicate group(s).")
                dupe_df = pd.DataFrame([{
                    "Employee":     d["name"],
                    "Date":         d["payment_date"],
                    "Amount":       d["amount"],
                    "Copies":       d["cnt"],
                    "IDs (keep first)": d["ids"],
                } for d in dupes])
                st.dataframe(
                    style_simple(dupe_df, ["Amount"]),
                    hide_index=True, use_container_width=True,
                )
                st.caption("The first (lowest) ID in each group is kept; all others are deleted.")
                dup_pwd = st.text_input("Password", type="password", key="dup_pwd")
                if st.button("🗑 Remove All Duplicates", type="primary"):
                    if dup_pwd == _DELETE_PWD:
                        n = db.remove_duplicate_payments()
                        st.success(f"Deleted {n} duplicate payment(s).")
                        _clear_caches(); st.rerun()
                    else:
                        st.error("Incorrect password.")


# ═══════════════════════════════════════════════════════════════════════════════
# LOANS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_loans:
    import import_loans as _il

    st.header("Loan Records & Payments")

    # ── Summary table (all employees) ────────────────────────────────────────
    loan_names = _get_loan_names()

    if loan_names:
        sum_rows = []
        for n in loan_names:
            s = db.get_loan_summary(n)
            sum_rows.append({
                "Employee":      n,
                "Total Loaned":  s["total_loaned"],
                "Total Paid":    s["total_paid"],
                "Balance":       s["balance"],
            })
        sum_df = pd.DataFrame(sum_rows)
        totals = sum_df[["Total Loaned", "Total Paid", "Balance"]].sum()
        st.dataframe(
            style_simple(sum_df, ["Total Loaned", "Total Paid", "Balance"]),
            hide_index=True, use_container_width=True,
        )
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Total Loaned", f"${totals['Total Loaned']:,.2f}")
        sc2.metric("Total Paid",   f"${totals['Total Paid']:,.2f}")
        sc3.metric("Balance Due",  f"${totals['Balance']:,.2f}")
    else:
        st.info("No loan records yet. Import from Excel or add manually below.")

    st.markdown("---")

    # ── Employee selector ────────────────────────────────────────────────────
    all_names_for_loans = sorted(set(_get_employee_names() + loan_names))
    loan_emp = st.selectbox("Select Employee", all_names_for_loans, key="loan_emp_sel")

    if loan_emp:
        summary = db.get_loan_summary(loan_emp)
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Loaned", f"${summary['total_loaned']:,.2f}")
        k2.metric("Total Paid",   f"${summary['total_paid']:,.2f}")
        k3.metric("Balance",      f"${summary['balance']:,.2f}",
                  delta=f"-${summary['balance']:,.2f}" if summary['balance'] > 0 else "Paid off",
                  delta_color="inverse")

        col_loans, col_pays = st.columns(2)

        with col_loans:
            st.subheader("Loans")
            emp_loans = db.get_loans(loan_emp)
            if emp_loans:
                ldf = pd.DataFrame([{
                    "ID":        l["id"],
                    "Loan #":    l["loan_no"] or l["id"],
                    "Date":      l["loan_date"],
                    "Principal": l["principal"],
                    "Pmt/Period":l["pmt_amount"],
                    "Note":      l["description"],
                } for l in emp_loans])
                st.dataframe(
                    style_simple(ldf[["Loan #","Date","Principal","Pmt/Period","Note"]],
                                 ["Principal", "Pmt/Period"]),
                    hide_index=True, use_container_width=True,
                )
            else:
                st.info("No loans recorded.")

            with st.expander("➕ Add New Loan"):
                with st.form("add_loan_form"):
                    l_date = st.date_input("Loan Date", value=date.today(), key="l_date")
                    l_amt  = st.number_input("Principal Amount", min_value=0.0,
                                             step=50.0, format="%.2f", key="l_amt")
                    l_pmt  = st.number_input("Expected Payment / Period",
                                             min_value=0.0, step=10.0, format="%.2f", key="l_pmt")
                    l_desc = st.text_input("Description (optional)", key="l_desc")
                    if st.form_submit_button("💾 Save Loan", type="primary"):
                        if l_amt > 0:
                            db.add_loan(loan_emp, str(l_date), l_amt, l_pmt, l_desc)
                            st.success(f"Loan of ${l_amt:,.2f} added.")
                            _clear_caches(); st.rerun()
                        else:
                            st.warning("Enter an amount greater than 0.")

            if emp_loans:
                with st.expander("✏️ Edit / Delete Loan"):
                    sel_loan = st.selectbox(
                        "Select loan",
                        emp_loans,
                        format_func=lambda l: f"#{l['loan_no'] or l['id']}  {l['loan_date']}  ${l['principal']:,.2f}",
                        key="edit_loan_sel",
                    )
                    with st.form("edit_loan_form"):
                        el_date = st.date_input(
                            "Loan Date",
                            value=date.fromisoformat(sel_loan["loan_date"]),
                            key="el_date",
                        )
                        el_amt  = st.number_input("Principal", value=float(sel_loan["principal"]),
                                                  min_value=0.0, step=50.0, format="%.2f", key="el_amt")
                        el_pmt  = st.number_input("Pmt / Period", value=float(sel_loan["pmt_amount"]),
                                                  min_value=0.0, step=10.0, format="%.2f", key="el_pmt")
                        el_desc = st.text_input("Description", value=sel_loan["description"] or "",
                                                key="el_desc")
                        el_pwd  = st.text_input("Password (required to delete)", type="password", key="el_pwd")
                        ec1, ec2 = st.columns(2)
                        save_loan = ec1.form_submit_button("💾 Save Changes", type="primary")
                        del_loan  = ec2.form_submit_button("🗑 Delete Loan",  type="secondary")
                    if save_loan:
                        db.update_loan(sel_loan["id"], str(el_date), el_amt, el_pmt, el_desc)
                        st.success("Loan updated.")
                        _clear_caches(); st.rerun()
                    if del_loan:
                        if el_pwd == _DELETE_PWD:
                            db.delete_loan(sel_loan["id"])
                            st.success("Loan deleted.")
                            _clear_caches(); st.rerun()
                        else:
                            st.error("Incorrect password.")

        with col_pays:
            st.subheader("Payment History")
            emp_pays = db.get_loan_payments(loan_emp)
            if emp_pays:
                pdf_data = pd.DataFrame([{
                    "ID":     p["id"],
                    "Pay #":  p["pay_no"] or p["id"],
                    "Date":   p["payment_date"],
                    "Amount": p["amount"],
                    "Note":   p["note"],
                } for p in emp_pays])
                st.dataframe(
                    style_simple(pdf_data[["Pay #","Date","Amount","Note"]], ["Amount"]),
                    hide_index=True, use_container_width=True,
                )
            else:
                st.info("No payments recorded.")

            with st.expander("➕ Register Payment"):
                with st.form("add_loan_pay_form"):
                    p_date = st.date_input("Payment Date", value=date.today(), key="p_date")
                    p_amt  = st.number_input("Amount", min_value=0.0,
                                             step=10.0, format="%.2f", key="p_amt")
                    p_note = st.text_input("Note (optional)", key="p_note")
                    if st.form_submit_button("💾 Save Payment", type="primary"):
                        if p_amt > 0:
                            db.add_loan_payment(loan_emp, str(p_date), p_amt, p_note)
                            st.success(f"Payment of ${p_amt:,.2f} recorded.")
                            _clear_caches(); st.rerun()
                        else:
                            st.warning("Enter an amount greater than 0.")

            if emp_pays:
                with st.expander("✏️ Edit / Delete Payment"):
                    sel_pay = st.selectbox(
                        "Select payment",
                        emp_pays,
                        format_func=lambda p: f"#{p['pay_no'] or p['id']}  {p['payment_date']}  ${p['amount']:,.2f}",
                        key="edit_pay_sel",
                    )
                    with st.form("edit_pay_form"):
                        ep_date = st.date_input(
                            "Payment Date",
                            value=date.fromisoformat(sel_pay["payment_date"]),
                            key="ep_date",
                        )
                        ep_amt  = st.number_input("Amount", value=float(sel_pay["amount"]),
                                                  min_value=0.0, step=10.0, format="%.2f", key="ep_amt")
                        ep_note = st.text_input("Note", value=sel_pay["note"] or "", key="ep_note")
                        ep_pwd  = st.text_input("Password (required to delete)", type="password", key="ep_pwd")
                        pc1, pc2 = st.columns(2)
                        save_pay = pc1.form_submit_button("💾 Save Changes", type="primary")
                        del_pay  = pc2.form_submit_button("🗑 Delete Payment", type="secondary")
                    if save_pay:
                        db.update_loan_payment(sel_pay["id"], str(ep_date), ep_amt, ep_note)
                        st.success("Payment updated.")
                        _clear_caches(); st.rerun()
                    if del_pay:
                        if ep_pwd == _DELETE_PWD:
                            db.delete_loan_payment(sel_pay["id"])
                            st.success("Payment deleted.")
                            _clear_caches(); st.rerun()
                        else:
                            st.error("Incorrect password.")

    st.markdown("---")

    # ── Import / Re-import ───────────────────────────────────────────────────
    st.subheader("Import from Excel")
    st.caption(f"Default file: `{_il.LOANS_EXCEL}`")

    up_col, btn_col = st.columns([3, 1])
    with up_col:
        loan_upload = st.file_uploader(
            "Upload Loans Excel (.xlsx)", type=["xlsx", "xlsm"], key="loan_upload"
        )
    with btn_col:
        st.write("")
        st.write("")
        use_default = st.button("Import Default File", type="secondary")

    if loan_upload or use_default:
        reimport_pwd = st.text_input("Password to clear & re-import", type="password", key="reimport_pwd")
        if st.button("⚠️ Clear existing & re-import", type="primary"):
            if reimport_pwd != _DELETE_PWD:
                st.error("Incorrect password.")
            else:
                if loan_upload:
                    import tempfile
                    tmp = Path(tempfile.mktemp(suffix=".xlsx"))
                    tmp.write_bytes(loan_upload.read())
                    src = tmp
                else:
                    src = _il.LOANS_EXCEL
                with st.spinner("Importing…"):
                    db.clear_loans()
                    n_l, n_p = _il.import_loans(src)
                    if loan_upload:
                        tmp.unlink(missing_ok=True)
                st.success(f"Imported {n_l} loans and {n_p} payments.")
                _clear_caches(); st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAYSLIP
# ═══════════════════════════════════════════════════════════════════════════════
with tab_slip:
    st.header("Payslip")

    if not selected:
        st.info("Select an employee in the sidebar.")
    else:
        emp = db.get_employee(selected)
        ded = db.get_deductions(selected)

        payments = db.get_payments(selected, int(year_sel))
        if not payments:
            st.info(f"No payments found for **{selected}** in {int(year_sel)}.")
        else:
            # Payment picker
            def _pay_label(p: dict) -> str:
                return f"{p['payment_date']}  |  {_period_label(p['period'])}  |  ${p['amount']:,.2f}"

            pay_options = {_pay_label(p): p for p in payments}
            chosen_label = st.selectbox("Select payment", list(pay_options.keys()))
            pay = pay_options[chosen_label]

            # Monthly equivalents for all pay types (weekly × 52/12, biweekly × 26/12)
            _W2M = 52 / 12
            _B2M = 26 / 12
            def _monthly(m, w=0, bw=0):
                return m or (w * _W2M) or (bw * _B2M)

            period_gross = _monthly(emp.get("monthly",    0), emp.get("weekly",     0), emp.get("biweekly",    0))
            nib_val      = _monthly(emp.get("nib_m",      0), emp.get("nib_w",      0), emp.get("nib_bw",      0))
            enib      = _monthly(emp.get("enib_m",  0), emp.get("enib_w",  0), emp.get("enib_bw",  0))
            ded_val      = _monthly(emp.get("ded_m",       0), emp.get("ded_w",       0), emp.get("ded_bw",       0))
            loan_ded     = db.get_loan_monthly_deduction(selected)
            net_pay      = (_monthly(emp.get("balance_m",  0), emp.get("balance_w",   0), emp.get("balance_bw",  0))
                           or (period_gross - nib_val - ded_val)) - loan_ded

            annual_net = _annual_net(emp)
            ytd        = db.get_ytd(selected, int(year_sel))

            st.markdown("---")

            # ── On-screen payslip preview ─────────────────────────────────────
            col_info, col_pay = st.columns(2)

            with col_info:
                st.markdown("##### Employee")
                st.write(f"**Name:** {emp['name']}")
                st.write(f"**ID:** {emp.get('id', '-')}")
                st.write(f"**Pay Type:** {emp.get('pay_type', '-')}")

                st.markdown("##### Payment")
                st.write(f"**Date:** {pay['payment_date']}")
                st.write(f"**Period:** {_period_label(pay['period'])}")
                if pay.get("note"):
                    st.write(f"**Note:** {pay['note']}")

            with col_pay:
                st.markdown("##### Earnings")
                earn_df = pd.DataFrame({
                    "Item":   ["Gross Pay"],
                    "Amount": [period_gross],
                })
                st.dataframe(
                    _base(earn_df).format({"Amount": _MONEY_FMT}),
                    hide_index=True, use_container_width=True,
                )

                st.markdown("##### Deductions")
                ded_rows = [("NIB", nib_val), ("Employer NIB", enib)]
                if ded:
                    for label, field in [
                        ("CB",               "cb"),
                        ("BICCU",            "biccu"),
                        ("OakTree",          "oaktree"),
                        ("Furniture Plus",   "furniture_plus"),
                        ("Green Leaf",       "green_leaf"),
                        ("Sunshine Finance", "sunshine_finance"),
                        ("School Loan",      "school_loan"),
                    ]:
                        v = ded.get(field, 0)
                        if v > 0:
                            ded_rows.append((label, v))
                if loan_ded > 0:
                    ded_rows.append(("Loan Repayment", loan_ded))

                ded_df = pd.DataFrame(
                    [(k, v) for k, v in ded_rows if v > 0],
                    columns=["Item", "Amount"],
                )
                if not ded_df.empty:
                    st.dataframe(
                        style_deductions(ded_df),
                        hide_index=True, use_container_width=True,
                    )

            st.markdown("---")
            n1, n2, n3 = st.columns(3)
            n1.metric("Net Pay",       f"${net_pay:,.2f}")
            n2.metric("YTD Paid",      f"${ytd:,.2f}")
            n3.metric("Remaining",     f"${max(annual_net - ytd, 0):,.2f}")

            st.markdown("---")

            # ── PDF download ──────────────────────────────────────────────────
            slip_bytes = pdf_gen.generate_payslip_pdf(
                emp=emp,
                ded=ded,
                payment=pay,
                period_gross=period_gross,
                nib_val=nib_val,
                enib=enib,
                ded_val=ded_val,
                net_pay=net_pay,
                ytd=ytd,
                annual=annual_net,
            )
            safe = emp["name"].replace(" ", "_")
            st.download_button(
                label="Download Payslip PDF",
                data=slip_bytes,
                file_name=f"Payslip_{safe}_{pay['payment_date']}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT PDF
# ═══════════════════════════════════════════════════════════════════════════════
with tab_export:
    st.header("Export PDF")

    if not selected:
        st.info("Select an employee in the sidebar.")
    else:
        emp        = db.get_employee(selected)
        ded        = db.get_deductions(selected)
        ytd        = db.get_ytd(selected, int(year_sel))
        annual_net = _annual_net(emp)

        col_x, col_y = st.columns(2)

        with col_x:
            st.subheader("Full Payroll Report")
            st.write(f"Complete breakdown for **{selected}** — {int(year_sel)}")
            report_bytes = pdf_gen.generate_report_pdf(emp, ded, ytd, int(year_sel))
            safe_name = selected.replace(" ", "_").replace("/", "_")
            st.download_button(
                label="⬇ Download Report PDF",
                data=report_bytes,
                file_name=f"Reporte_{safe_name}_{int(year_sel)}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )

        with col_y:
            st.subheader("Payment Receipt")
            payments = db.get_payments(selected, int(year_sel))
            if payments:
                last = payments[0]
                st.write(
                    f"**Last:** ${last['amount']:,.2f} · {last['payment_date']} · "
                    f"{_period_label(last['period'])}"
                )
                receipt_bytes = pdf_gen.generate_receipt_pdf(
                    emp,
                    last["payment_date"],
                    last["amount"],
                    last["period"],
                    last.get("note", ""),
                    ytd,
                )
                st.download_button(
                    label="⬇ Download Receipt PDF",
                    data=receipt_bytes,
                    file_name=f"Receipt_{safe_name}_{last['payment_date']}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.info(f"No payments in {int(year_sel)} to generate a receipt.")

        st.markdown("---")
        st.subheader("Bulk Export")
        st.write("Download reports for every employee as a single ZIP file.")
        if st.button("Generate All Reports → ZIP"):
            buf = io.BytesIO()
            employees = db.get_employees()
            progress  = st.progress(0.0)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, e in enumerate(employees):
                    ed   = db.get_deductions(e["name"])
                    eytd = db.get_ytd(e["name"], int(year_sel))
                    data = pdf_gen.generate_report_pdf(e, ed, eytd, int(year_sel))
                    safe = e["name"].replace(" ", "_").replace("/", "_")
                    zf.writestr(f"Reporte_{safe}_{int(year_sel)}.pdf", data)
                    progress.progress((i + 1) / len(employees))
            buf.seek(0)
            st.download_button(
                label="⬇ Download ZIP",
                data=buf.getvalue(),
                file_name=f"Payroll_Reports_{int(year_sel)}.zip",
                mime="application/zip",
                type="primary",
            )

    # ── Monthly Payroll Report ───────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📅 Monthly Payroll Report")

    col_m, _ = st.columns([1, 4])
    with col_m:
        month_sel = st.selectbox(
            "Month",
            range(1, 13),
            format_func=lambda m: datetime(2000, m, 1).strftime("%B"),
            index=datetime.now().month - 1,
            key="rpt_month",
        )

    _W2M, _B2M = 52 / 12, 26 / 12

    def _mfig(e: dict) -> tuple:
        def mv(m, w=0.0, bw=0.0):
            return float(m or (w * _W2M) or (bw * _B2M))
        gross = mv(e.get("monthly", 0),    e.get("weekly", 0),     e.get("biweekly", 0))
        nib   = mv(e.get("nib_m", 0),      e.get("nib_w", 0),      e.get("nib_bw", 0))
        enib  = mv(e.get("enib_m", 0),  e.get("enib_w", 0),  e.get("enib_bw", 0))
        ded   = mv(e.get("ded_m", 0),      e.get("ded_w", 0),      e.get("ded_bw", 0))
        net   = mv(e.get("balance_m", 0),  e.get("balance_w", 0),  e.get("balance_bw", 0)) \
                or (gross - nib - ded)
        return gross, nib, enib, ded, net

    all_employees = _get_employees()
    rpt_rows: list[dict] = []
    for e in all_employees:
        if not (e.get("salary") or e.get("weekly") or e.get("monthly") or e.get("biweekly")):
            continue
        g, n, b, d, net = _mfig(e)
        ded_rec = db.get_deductions(e["name"]) or {}
        rpt_rows.append({
            "Name":             e["name"],
            "Gross":            g,
            "Emp NIB":          n,
            "Employer NIB":          b,
            "Deductions":       d,
            "Net Pay":          net,
            "cb":               ded_rec.get("cb",               0),
            "biccu":            ded_rec.get("biccu",             0),
            "oaktree":          ded_rec.get("oaktree",           0),
            "furniture_plus":   ded_rec.get("furniture_plus",    0),
            "green_leaf":       ded_rec.get("green_leaf",        0),
            "sunshine_finance": ded_rec.get("sunshine_finance",  0),
            "school_loan":      ded_rec.get("school_loan",       0),
        })

    _MONEY_COLS_RPT = ["Gross", "Emp NIB", "Employer NIB", "Deductions", "Net Pay"]
    rpt_df = pd.DataFrame(rpt_rows)

    st.dataframe(
        style_simple(rpt_df, _MONEY_COLS_RPT),
        hide_index=True, use_container_width=True,
    )

    tot = rpt_df[_MONEY_COLS_RPT].sum()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Gross",       f"${tot['Gross']:,.2f}")
    c2.metric("Total Emp NIB",     f"${tot['Emp NIB']:,.2f}")
    c3.metric("Total Employer NIB",     f"${tot['Employer NIB']:,.2f}")
    c4.metric("Total Deductions",  f"${tot['Deductions']:,.2f}")
    c5.metric("Total Net Pay",     f"${tot['Net Pay']:,.2f}")

    month_label = datetime(int(year_sel), int(month_sel), 1).strftime("%B %Y")
    rpt_pdf_bytes = pdf_gen.generate_monthly_report_pdf(rpt_rows, month_label)
    st.download_button(
        label="⬇ Download Monthly Report PDF",
        data=rpt_pdf_bytes,
        file_name=f"Monthly_Payroll_{month_label.replace(' ', '_')}.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_settings:
    st.header("Settings & Data Import")

    # ── Import ──────────────────────────────────────────────────────────────
    st.subheader("Import from Excel")

    def _run_migration(path: Path):
        with st.spinner("Importing data…"):
            try:
                e, d, p = migrate(path)
                st.success(
                    f"Import complete — "
                    f"**{e}** employees · **{d}** deduction records · **{p}** payments"
                )
                _clear_caches(); st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")

    if EXCEL_PATH.exists():
        st.write(f"Found `{EXCEL_PATH.name}` in the parent folder.")
        if st.button("Import from Excel file", type="primary"):
            _run_migration(EXCEL_PATH)
    else:
        st.info(f"`{EXCEL_PATH.name}` not found next to this app.")

    uploaded = st.file_uploader(
        "Or upload an Excel file (.xlsx / .xlsm)",
        type=["xlsx", "xlsm"],
    )
    if uploaded:
        if st.button("Import uploaded file"):
            tmp = Path(tempfile.mktemp(suffix=Path(uploaded.name).suffix))
            tmp.write_bytes(uploaded.read())
            _run_migration(tmp)
            tmp.unlink(missing_ok=True)

    # ── Database info ────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Database")
    st.code(str(db.DB_PATH), language=None)

    all_emp  = _get_employees()
    all_pay  = db.get_all_payments()
    i1, i2, i3 = st.columns(3)
    i1.metric("Employees",       len(all_emp))
    i2.metric("Payment Records", len(all_pay))
    i3.metric("Years in DB",
              len({p["year"] for p in all_pay}) if all_pay else 0)

    # ── Raw data viewers ─────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Raw Data")

    with st.expander("Employees table"):
        if all_emp:
            st.dataframe(pd.DataFrame(all_emp), use_container_width=True)
        else:
            st.write("Empty.")

    with st.expander("Deductions table"):
        names_list = db.get_employee_names()
        deds = [db.get_deductions(n) for n in names_list if db.get_deductions(n)]
        if deds:
            st.dataframe(pd.DataFrame(deds), use_container_width=True)
        else:
            st.write("Empty.")

    with st.expander(f"Payments  ({int(year_sel)})"):
        year_pays = db.get_all_payments(int(year_sel))
        if year_pays:
            st.dataframe(pd.DataFrame(year_pays), use_container_width=True)
        else:
            st.write("No payments for this year.")

    # ── Danger zone ──────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("⚠ Danger Zone"):
        st.warning("These actions cannot be undone.")
        dz_pwd = st.text_input("Password", type="password", key="dz_pwd")
        if st.button("Clear ALL data (wipe database)", type="secondary"):
            if dz_pwd != _DELETE_PWD:
                st.error("Incorrect password.")
            else:
                db.DB_PATH.unlink(missing_ok=True)
                db.init_db()
                st.success("Database cleared.")
                _clear_caches(); st.rerun()
