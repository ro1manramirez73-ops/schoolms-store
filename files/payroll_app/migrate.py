"""One-time migration: reads PayrollReport_WithPayments_v3.xlsm → SQLite."""
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

import db

EXCEL_PATH = Path(__file__).parent.parent / "PayrollReport_WithPayments_v3.xlsm"

# Excel column → DB field mappings (match VBA constants exactly)
_PAYROLL_MAP = {
    "ID": "id",
    "Name": "name",
    "Salary": "salary",
    "Type": "pay_type",
    "Weekly": "weekly",
    "By-Weekly": "biweekly",
    "Monthly": "monthly",
    "NIB-W": "nib_w",
    "NIB-BW": "nib_bw",
    "NIB-M": "nib_m",
    "NIB-Y": "nib_y",
    "ENIB_W": "enib_w",
    "ENIB_BW": "enib_bw",
    "ENIB_M": "enib_m",
    "W-R": "w_r",
    "B-W R": "bw_r",
    "M-R": "m_r",
    "Deductions-M": "ded_m",
    "Deduction B-W": "ded_bw",
    "Deduction_W": "ded_w",
    "Balance-W": "balance_w",
    "Balance-B-W": "balance_bw",
    "Balance-M": "balance_m",
    "Y-R": "yearly",
}

_DEDUCTION_MAP = {
    "ID": "employee_id",
    "Name": "name",
    "CB": "cb",
    "BICCU": "biccu",
    "OakTree": "oaktree",
    "Furniture Plus": "furniture_plus",
    "Green Leaf": "green_leaf",
    "Sunshine Finance": "sunshine_finance",
    "School Loan": "school_loan",
    "Total-W": "total_w",
    "Total B-W": "total_bw",
    "Total-M": "total_m",
    "Total-Y": "total_y",
}

_PAYMENT_MAP = {
    "ID": "employee_id",
    "Name": "name",
    "Payment Date": "payment_date",
    "Period": "period",
    "Amount": "amount",
    "Note": "note",
    "Year": "year",
    "Timestamp": "timestamp",
}


def _f(val, default=0.0) -> float:
    try:
        return float(val) if pd.notna(val) else default
    except (TypeError, ValueError):
        return default


def _s(val, default="") -> str:
    if pd.isna(val) if not isinstance(val, str) else False:
        return default
    return str(val).strip()


def _read_sheet(path: Path, sheet: str, col_map: dict) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl", dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename)
        keep = list(rename.values())
        df = df[[c for c in keep if c in df.columns]]
        df = df.dropna(how="all")
        return df
    except Exception:
        return None


def migrate(excel_path: Path = EXCEL_PATH) -> tuple[int, int, int]:
    """Import all data from Excel into the SQLite database.

    Returns (employees_imported, deductions_imported, payments_imported).
    """
    db.init_db()
    emp_count = ded_count = pay_count = 0

    # ── Employees ──────────────────────────────────────────
    df = _read_sheet(excel_path, "Data", _PAYROLL_MAP)
    if df is not None and "name" in df.columns:
        for _, row in df.iterrows():
            name = _s(row.get("name"))
            if not name:
                continue
            db.upsert_employee({
                "id":         _s(row.get("id")),
                "name":       name,
                "salary":     _f(row.get("salary")),
                "pay_type":   _s(row.get("pay_type")) or "Monthly",
                "weekly":     _f(row.get("weekly")),
                "biweekly":   _f(row.get("biweekly")),
                "monthly":    _f(row.get("monthly")),
                "nib_w":      _f(row.get("nib_w")),
                "nib_bw":     _f(row.get("nib_bw")),
                "nib_m":      _f(row.get("nib_m")),
                "nib_y":      _f(row.get("nib_y")),
                "enib_w":  _f(row.get("enib_w")),
                "enib_bw": _f(row.get("enib_bw")),
                "enib_m":  _f(row.get("enib_m")),
                "w_r":        _f(row.get("w_r")),
                "bw_r":       _f(row.get("bw_r")),
                "m_r":        _f(row.get("m_r")),
                "ded_m":      _f(row.get("ded_m")),
                "ded_bw":     _f(row.get("ded_bw")),
                "ded_w":      _f(row.get("ded_w")),
                "balance_w":  _f(row.get("balance_w")),
                "balance_bw": _f(row.get("balance_bw")),
                "balance_m":  _f(row.get("balance_m")),
                "yearly":     _f(row.get("yearly")),
            })
            emp_count += 1

    # ── Deductions ─────────────────────────────────────────
    df = _read_sheet(excel_path, "Deductions", _DEDUCTION_MAP)
    if df is not None and "name" in df.columns:
        for _, row in df.iterrows():
            name = _s(row.get("name"))
            if not name:
                continue
            db.upsert_deductions({
                "name":             name,
                "employee_id":      _s(row.get("employee_id")),
                "cb":               _f(row.get("cb")),
                "biccu":            _f(row.get("biccu")),
                "oaktree":          _f(row.get("oaktree")),
                "furniture_plus":   _f(row.get("furniture_plus")),
                "green_leaf":       _f(row.get("green_leaf")),
                "sunshine_finance": _f(row.get("sunshine_finance")),
                "school_loan":      _f(row.get("school_loan")),
                "total_w":          _f(row.get("total_w")),
                "total_bw":         _f(row.get("total_bw")),
                "total_m":          _f(row.get("total_m")),
                "total_y":          _f(row.get("total_y")),
            })
            ded_count += 1

    # ── Payments ───────────────────────────────────────────
    df = _read_sheet(excel_path, "Payments", _PAYMENT_MAP)
    if df is not None and "name" in df.columns:
        for _, row in df.iterrows():
            name = _s(row.get("name"))
            raw_amt = row.get("amount")
            if not name or pd.isna(raw_amt) if not isinstance(raw_amt, str) else not raw_amt:
                continue
            amount = _f(raw_amt)
            if amount <= 0:
                continue

            # Normalise date
            pd_val = row.get("payment_date", "")
            try:
                date_str = pd.to_datetime(pd_val).strftime("%Y-%m-%d")
            except Exception:
                date_str = _s(pd_val)

            # Year
            yr_val = row.get("year")
            try:
                yr = int(_f(yr_val)) if pd.notna(yr_val) else int(date_str[:4])
            except (ValueError, TypeError):
                yr = datetime.now().year

            # Timestamp
            ts_val = row.get("timestamp", "")
            try:
                ts = pd.to_datetime(ts_val).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            db.add_payment(
                employee_id=_s(row.get("employee_id")),
                name=name,
                payment_date=date_str,
                period=_s(row.get("period")) or "M",
                amount=amount,
                note=_s(row.get("note")),
                year=yr,
            )
            pay_count += 1

    return emp_count, ded_count, pay_count


if __name__ == "__main__":
    e, d, p = migrate()
    print(f"Migrated: {e} employees, {d} deduction records, {p} payments")
