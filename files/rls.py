"""
Row-Level Security helpers for SchoolMS.

All checks return True for admin (unrestricted).
teacher_linked_id is session['linked_id'] — the teachers.id for that user.
"""

from flask import session, render_template
import logging

log = logging.getLogger(__name__)


def _is_admin() -> bool:
    return session.get('role') == 'admin'


def teacher_owns_class(conn, class_id: int, teacher_linked_id) -> bool:
    """True if the class belongs to this teacher (or user is admin)."""
    if _is_admin():
        return True
    if not teacher_linked_id or not class_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM classes WHERE id=? AND teacher_id=?",
        (int(class_id), int(teacher_linked_id))
    ).fetchone()
    return row is not None


def teacher_owns_student(conn, student_id: int, teacher_linked_id) -> bool:
    """True if the student is in one of this teacher's classes (or user is admin)."""
    if _is_admin():
        return True
    if not teacher_linked_id or not student_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM students WHERE id=? "
        "AND class_id IN (SELECT id FROM classes WHERE teacher_id=?)",
        (int(student_id), int(teacher_linked_id))
    ).fetchone()
    return row is not None


def teacher_class_ids(conn, teacher_linked_id) -> list[int]:
    """Return all class IDs assigned to this teacher."""
    if not teacher_linked_id:
        return []
    rows = conn.execute(
        "SELECT id FROM classes WHERE teacher_id=?", (int(teacher_linked_id),)
    ).fetchall()
    return [r['id'] for r in rows]


def teacher_student_ids(conn, teacher_linked_id) -> list[int]:
    """Return all student IDs in this teacher's classes."""
    class_ids = teacher_class_ids(conn, teacher_linked_id)
    if not class_ids:
        return []
    placeholders = ','.join('?' * len(class_ids))
    rows = conn.execute(
        f"SELECT id FROM students WHERE class_id IN ({placeholders})", class_ids
    ).fetchall()
    return [r['id'] for r in rows]


def forbidden(message: str = "Access denied."):
    """Return a 403 response."""
    return render_template('error.html', message=message), 403
