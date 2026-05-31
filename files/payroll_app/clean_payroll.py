#!/usr/bin/env python
"""
Clean payroll database - remove all staff and payment data
"""
import sqlite3
import os

DB = "payroll.db"

try:
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    # Delete all data from tables (keeping schema)
    tables_to_clear = ['employees', 'deductions', 'payments', 'loans', 'loan_payments']
    
    for table in tables_to_clear:
        c.execute(f"DELETE FROM {table}")
        count = conn.execute("SELECT changes()").fetchone()[0]
        print(f"[✓] Cleared {table}: deleted {count} rows")
    
    # Reset auto-increment counters
    c.execute("DELETE FROM sqlite_sequence")
    print("[✓] Reset auto-increment counters")
    
    conn.commit()
    print(f"\n✅ Payroll database cleaned: {DB}")
    print("   Ready for new staff data")
    
except Exception as e:
    conn.rollback()
    print(f"❌ Error: {e}")
    raise
finally:
    conn.close()
