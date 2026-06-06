"""SQLite data layer for the Payroll System."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH      = Path(__file__).parent / "payroll.db"
SCHOOL_DB    = Path(__file__).parent.parent / "school.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id          TEXT NOT NULL,
    name        TEXT NOT NULL PRIMARY KEY,
    salary      REAL DEFAULT 0,
    pay_type    TEXT DEFAULT 'Monthly',
    weekly      REAL DEFAULT 0,
    biweekly    REAL DEFAULT 0,
    monthly     REAL DEFAULT 0,
    nib_w       REAL DEFAULT 0,
    nib_bw      REAL DEFAULT 0,
    nib_m       REAL DEFAULT 0,
    nib_y       REAL DEFAULT 0,
    enib_w      REAL DEFAULT 0,
    enib_bw     REAL DEFAULT 0,
    enib_m      REAL DEFAULT 0,
    w_r         REAL DEFAULT 0,
    bw_r        REAL DEFAULT 0,
    m_r         REAL DEFAULT 0,
    ded_m       REAL DEFAULT 0,
    ded_bw      REAL DEFAULT 0,
    ded_w       REAL DEFAULT 0,
    balance_w   REAL DEFAULT 0,
    balance_bw  REAL DEFAULT 0,
    balance_m   REAL DEFAULT 0,
    yearly      REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deductions (
    name             TEXT NOT NULL PRIMARY KEY,
    employee_id      TEXT NOT NULL DEFAULT '',
    cb               REAL DEFAULT 0,
    biccu            REAL DEFAULT 0,
    oaktree          REAL DEFAULT 0,
    furniture_plus   REAL DEFAULT 0,
    green_leaf       REAL DEFAULT 0,
    sunshine_finance REAL DEFAULT 0,
    school_loan      REAL DEFAULT 0,
    total_w          REAL DEFAULT 0,
    total_bw         REAL DEFAULT 0,
    total_m          REAL DEFAULT 0,
    total_y          REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id  TEXT    NOT NULL DEFAULT '',
    name         TEXT    NOT NULL,
    payment_date TEXT    NOT NULL,
    period       TEXT    NOT NULL,
    amount       REAL    NOT NULL,
    note         TEXT    DEFAULT '',
    year         INTEGER NOT NULL,
    timestamp    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pay_name ON payments(name);
CREATE INDEX IF NOT EXISTS idx_pay_year ON payments(year);

CREATE TABLE IF NOT EXISTS loans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_no       INTEGER DEFAULT 0,
    employee_name TEXT    NOT NULL,
    staff_id      TEXT    DEFAULT '',
    loan_date     TEXT    NOT NULL,
    principal     REAL    NOT NULL DEFAULT 0,
    pmt_amount    REAL    DEFAULT 0,
    description   TEXT    DEFAULT '',
    timestamp     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS loan_payments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pay_no        INTEGER DEFAULT 0,
    employee_name TEXT    NOT NULL,
    staff_id      TEXT    DEFAULT '',
    payment_date  TEXT    NOT NULL,
    amount        REAL    NOT NULL DEFAULT 0,
    note          TEXT    DEFAULT '',
    timestamp     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_loan_name ON loans(employee_name);
CREATE INDEX IF NOT EXISTS idx_loanpay_name ON loan_payments(employee_name);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        # Migrate old enib_* column names to enib_* if they still exist
        cols = {r[1] for r in conn.execute("PRAGMA table_info(employees)").fetchall()}
        if "enib_w" in cols:
            conn.execute("ALTER TABLE employees RENAME COLUMN enib_w  TO enib_w")
        if "enib_bw" in cols:
            conn.execute("ALTER TABLE employees RENAME COLUMN enib_bw TO enib_bw")
        if "enib_m" in cols:
            conn.execute("ALTER TABLE employees RENAME COLUMN enib_m  TO enib_m")


# ── Employees ────────────────────────────────────────────

def get_employees() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_employee(name: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM employees WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def get_employee_names() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM employees ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def upsert_employee(data: dict):
    fields = [
        "id", "name", "salary", "pay_type", "weekly", "biweekly", "monthly",
        "nib_w", "nib_bw", "nib_m", "nib_y", "enib_w", "enib_bw", "enib_m",
        "w_r", "bw_r", "m_r", "ded_m", "ded_bw", "ded_w",
        "balance_w", "balance_bw", "balance_m", "yearly",
    ]
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    vals = tuple(data.get(f, 0 if f not in ("id", "name", "pay_type") else "") for f in fields)
    with get_conn() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO employees ({cols}) VALUES ({placeholders})", vals
        )


# ── Deductions ───────────────────────────────────────────

def get_deductions(name: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM deductions WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def upsert_deductions(data: dict):
    fields = [
        "name", "employee_id", "cb", "biccu", "oaktree", "furniture_plus",
        "green_leaf", "sunshine_finance", "school_loan",
        "total_w", "total_bw", "total_m", "total_y",
    ]
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    vals = tuple(data.get(f, 0 if f not in ("name", "employee_id") else "") for f in fields)
    with get_conn() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO deductions ({cols}) VALUES ({placeholders})", vals
        )


# ── Payments ─────────────────────────────────────────────

def add_payment(
    employee_id: str, name: str, payment_date: str,
    period: str, amount: float, note: str, year: int,
) -> int:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payments "
            "(employee_id, name, payment_date, period, amount, note, year, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (employee_id, name, payment_date, period, amount, note, year, ts),
        )
    return cur.lastrowid


def get_payments(name: str, year: Optional[int] = None) -> list[dict]:
    sql = "SELECT * FROM payments WHERE name = ?"
    params: list = [name]
    if year is not None:
        sql += " AND year = ?"
        params.append(year)
    sql += " ORDER BY payment_date DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_all_payments(year: Optional[int] = None) -> list[dict]:
    sql = "SELECT * FROM payments"
    params: list = []
    if year:
        sql += " WHERE year = ?"
        params.append(year)
    sql += " ORDER BY payment_date DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_salary(name: str, new_salary: float) -> None:
    """Update base salary and recompute all dependent fields (gross, NIB, balances)."""
    emp = get_employee(name)
    if not emp or new_salary <= 0:
        return

    emp["salary"] = new_salary

    if emp.get("weekly", 0) > 0:
        old_g      = emp["weekly"]
        nib_rate   = emp.get("nib_w",      0) / old_g
        enib_rate   = emp.get("enib_w",  0) / old_g
        new_g      = new_salary / 52
        emp["weekly"]      = new_g
        emp["nib_w"]       = new_g * nib_rate
        emp["enib_w"]   = new_g * enib_rate
        emp["nib_y"]       = emp["nib_w"] * 52
        emp["w_r"]         = new_g - emp["nib_w"]
        emp["balance_w"]   = emp["w_r"] - emp.get("ded_w", 0)

    elif emp.get("biweekly", 0) > 0:
        old_g      = emp["biweekly"]
        nib_rate   = emp.get("nib_bw",     0) / old_g
        enib_rate   = emp.get("enib_bw", 0) / old_g
        new_g      = new_salary / 26
        emp["biweekly"]    = new_g
        emp["nib_bw"]      = new_g * nib_rate
        emp["enib_bw"]  = new_g * enib_rate
        emp["nib_y"]       = emp["nib_bw"] * 26
        emp["bw_r"]        = new_g - emp["nib_bw"]
        emp["balance_bw"]  = emp["bw_r"] - emp.get("ded_bw", 0)

    elif emp.get("monthly", 0) > 0:
        old_g      = emp["monthly"]
        nib_rate   = emp.get("nib_m",      0) / old_g
        enib_rate   = emp.get("enib_m",  0) / old_g
        new_g      = new_salary / 12
        emp["monthly"]     = new_g
        emp["nib_m"]       = new_g * nib_rate
        emp["enib_m"]   = new_g * enib_rate
        emp["nib_y"]       = emp["nib_m"] * 12
        emp["m_r"]         = new_g - emp["nib_m"]
        emp["balance_m"]   = emp["m_r"] - emp.get("ded_m", 0)

    upsert_employee(emp)


def save_deductions_and_recalc(name: str, entity_m: dict) -> None:
    """Save monthly amounts per entity, auto-compute period totals, recalculate employee balances."""
    total_m  = sum(entity_m.values())
    total_w  = total_m * 12 / 52
    total_bw = total_m * 12 / 26
    total_y  = total_m * 12

    existing = get_deductions(name) or {}
    upsert_deductions({
        "name":              name,
        "employee_id":       existing.get("employee_id", ""),
        **entity_m,
        "total_w":           total_w,
        "total_bw":          total_bw,
        "total_m":           total_m,
        "total_y":           total_y,
    })

    emp = get_employee(name)
    if emp:
        emp["ded_m"]      = total_m
        emp["ded_w"]      = total_w
        emp["ded_bw"]     = total_bw
        emp["balance_w"]  = emp.get("w_r",  0) - total_w
        emp["balance_bw"] = emp.get("bw_r", 0) - total_bw
        emp["balance_m"]  = emp.get("m_r",  0) - total_m
        upsert_employee(emp)


def get_ytd(name: str, year: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE name = ? AND year = ?",
            (name, year),
        ).fetchone()
    return float(row["total"])


def get_ytd_bulk(year: int) -> dict:
    """Return {name: ytd_total} for all employees in one query instead of N queries."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, COALESCE(SUM(amount), 0) AS total FROM payments WHERE year = ? GROUP BY name",
            (year,),
        ).fetchall()
    return {r["name"]: float(r["total"]) for r in rows}


def delete_payment(payment_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))


def find_duplicate_payments() -> list[dict]:
    """Return one row per duplicate group (name, payment_date, amount) with count and all IDs."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT name, payment_date, amount, COUNT(*) AS cnt,
                   GROUP_CONCAT(id ORDER BY id) AS ids
            FROM payments
            GROUP BY name, payment_date, amount
            HAVING COUNT(*) > 1
            ORDER BY name, payment_date
        """).fetchall()
    return [dict(r) for r in rows]


def remove_duplicate_payments() -> int:
    """Keep only the first (lowest id) for each (name, payment_date, amount) group.
    Returns the number of records deleted."""
    with get_conn() as conn:
        cur = conn.execute("""
            DELETE FROM payments
            WHERE id NOT IN (
                SELECT MIN(id) FROM payments GROUP BY name, payment_date, amount
            )
        """)
    return cur.rowcount


# ── Loans ─────────────────────────────────────────────────

def add_loan(employee_name: str, loan_date: str, principal: float,
             pmt_amount: float = 0, description: str = "",
             staff_id: str = "", loan_no: int = 0) -> int:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO loans (loan_no, employee_name, staff_id, loan_date, "
            "principal, pmt_amount, description, timestamp) VALUES (?,?,?,?,?,?,?,?)",
            (loan_no, employee_name, staff_id, loan_date, principal, pmt_amount, description, ts),
        )
    return cur.lastrowid


def get_loans(employee_name: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM loans"
    params: list = []
    if employee_name:
        sql += " WHERE employee_name = ?"
        params.append(employee_name)
    sql += " ORDER BY loan_date, id"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_loan_names() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT employee_name FROM loans ORDER BY employee_name"
        ).fetchall()
    return [r["employee_name"] for r in rows]


def update_loan(loan_id: int, loan_date: str, principal: float,
                pmt_amount: float, description: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE loans SET loan_date=?, principal=?, pmt_amount=?, description=? WHERE id=?",
            (loan_date, principal, pmt_amount, description, loan_id),
        )


def delete_loan(loan_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM loans WHERE id = ?", (loan_id,))


# ── Loan Payments ─────────────────────────────────────────

def add_loan_payment(employee_name: str, payment_date: str, amount: float,
                     note: str = "", staff_id: str = "", pay_no: int = 0) -> int:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO loan_payments (pay_no, employee_name, staff_id, "
            "payment_date, amount, note, timestamp) VALUES (?,?,?,?,?,?,?)",
            (pay_no, employee_name, staff_id, payment_date, amount, note, ts),
        )
    return cur.lastrowid


def get_loan_payments(employee_name: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM loan_payments"
    params: list = []
    if employee_name:
        sql += " WHERE employee_name = ?"
        params.append(employee_name)
    sql += " ORDER BY payment_date, id"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_loan_payment(pay_id: int, payment_date: str, amount: float, note: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE loan_payments SET payment_date=?, amount=?, note=? WHERE id=?",
            (payment_date, amount, note, pay_id),
        )


def delete_loan_payment(pay_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM loan_payments WHERE id = ?", (pay_id,))


def get_loan_summary(employee_name: str) -> dict:
    """Return total_loaned, total_paid, balance for an employee."""
    with get_conn() as conn:
        loaned = conn.execute(
            "SELECT COALESCE(SUM(principal),0) FROM loans WHERE employee_name=?",
            (employee_name,),
        ).fetchone()[0]
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM loan_payments WHERE employee_name=?",
            (employee_name,),
        ).fetchone()[0]
    return {"total_loaned": float(loaned), "total_paid": float(paid),
            "balance": float(loaned) - float(paid)}


def get_loan_monthly_deduction(payroll_name: str) -> float:
    """Return monthly loan repayment amount for a payroll employee (matched by staff_id).
    Returns 0 if the loan is fully paid off or the employee has no loans."""
    emp = get_employee(payroll_name)
    if not emp:
        return 0.0

    staff_id = str(emp.get("id", "")).split(".")[0]
    if not staff_id:
        return 0.0

    with get_conn() as conn:
        loans = conn.execute(
            "SELECT principal, pmt_amount FROM loans WHERE staff_id = ?",
            (staff_id,),
        ).fetchall()
        if not loans:
            return 0.0
        total_paid = float(conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM loan_payments WHERE staff_id = ?",
            (staff_id,),
        ).fetchone()[0])

    total_principal = sum(float(l["principal"]) for l in loans)
    if total_principal - total_paid <= 0:
        return 0.0

    total_pmt = sum(float(l["pmt_amount"]) for l in loans)

    # Convert periodic payment to monthly based on employee pay period
    if emp.get("weekly", 0) > 0:
        return total_pmt * 52 / 12
    elif emp.get("biweekly", 0) > 0:
        return total_pmt * 26 / 12
    return total_pmt


def clear_loans():
    with get_conn() as conn:
        conn.execute("DELETE FROM loans")
        conn.execute("DELETE FROM loan_payments")


# ── School staff sync ─────────────────────────────────────
def sync_from_school() -> tuple[int, int]:
    """Import active teachers from school.db into payroll employees.
    Only adds new staff — never overwrites existing payroll data.
    Returns (added, skipped) counts.
    """
    if not SCHOOL_DB.exists():
        return 0, 0

    school = sqlite3.connect(str(SCHOOL_DB))
    school.row_factory = sqlite3.Row
    teachers = school.execute(
        "SELECT teacher_id, first_name, last_name, salary "
        "FROM teachers WHERE status='Active' OR status IS NULL"
    ).fetchall()
    school.close()

    existing_names = {e["name"].lower() for e in get_employees()}
    added = 0
    skipped = 0

    for t in teachers:
        name = f"{t['first_name']} {t['last_name']}".strip()
        if not name:
            continue
        if name.lower() in existing_names:
            skipped += 1
            continue

        salary = float(t["salary"] or 0)
        monthly = salary / 12 if salary > 0 else 0
        nib_rate = 0.039  # standard employee NIB rate
        nib_m    = round(monthly * nib_rate, 2)
        enib  = round(monthly * 0.059, 2)   # employer NIB rate
        net_m    = round(monthly - nib_m, 2)

        upsert_employee({
            "id":         str(t["teacher_id"] or ""),
            "name":       name,
            "salary":     salary,
            "pay_type":   "Monthly",
            "monthly":    round(monthly, 2),
            "nib_m":      nib_m,
            "enib_m":  enib,
            "m_r":        net_m,
            "balance_m":  net_m,
            "nib_y":      round(nib_m * 12, 2),
            "yearly":     salary,
        })
        existing_names.add(name.lower())
        added += 1

    return added, skipped
