"""
SmartClinic+ — small real backend slice.

Flask + SQLite. Three flows are backed by a real, persistent database and
real server-side rules, not just client-side JavaScript:

  1. Login / RBAC (NFR-01)     — role is looked up server-side from the
                                  users table; templates and routes are
                                  gated on session['role'].
  2. Booking (NFR-02)          — booking a slot runs inside a SQLite
                                  transaction that locks the row first
                                  (BEGIN IMMEDIATE), so two concurrent
                                  requests for the same slot cannot both
                                  succeed. See test_concurrency.py.
  3. E-prescription (FR-05)    — the medication is checked against the
                                  patient's allergies *in the database
                                  query*, server-side, before anything is
                                  written. Bypassing the browser's JS
                                  cannot get a conflicting prescription
                                  saved.

Run with:  python3 app.py
Then open: http://127.0.0.1:5000
"""
import sqlite3
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import check_password_hash

from db import get_db, init_db, now_iso, DB_PATH

app = Flask(__name__)
app.secret_key = "smartclinic-plus-student-demo-not-for-production"

init_db()


# ---------------------------------------------------------------- helpers
def login_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if roles and session.get("role") not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


NAV = {
    "patient": [
        {"id": "book", "label": "Book Appointment", "url": "/book"},
        {"id": "prescriptions", "label": "My Prescriptions", "url": "/patient/prescriptions"},
    ],
    "doctor": [
        {"id": "dashboard", "label": "Dashboard", "url": "/doctor"},
    ],
    "manager": [
        {"id": "ops", "label": "Operational Dashboard", "url": "/manager"},
    ],
    "staff": [
        {"id": "tasks", "label": "Staff Tasks", "url": "/staff"},
    ],
}


def shell_context(active):
    role = session["role"]
    labels = {item["id"]: item["label"] for item in NAV[role]}
    return {
        "nav_items": NAV[role],
        "active": active,
        "page_title": labels.get(active, ""),
        "display_name": session["display_name"],
        "initials": "".join(w[0] for w in session["display_name"].split()[:2]).upper(),
    }


# ---------------------------------------------------------------- auth
@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid username or password.")
        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["display_name"] = user["display_name"]
        session["patient_id"] = user["patient_id"]
        session["doctor_id"] = user["doctor_id"]
        return redirect(
            {"patient": "/book", "doctor": "/doctor", "manager": "/manager", "staff": "/staff"}[user["role"]]
        )
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- patient: booking
@app.route("/book")
@login_required("patient")
def book():
    conn = get_db()
    slots = conn.execute(
        "SELECT * FROM slots WHERE slot_date = '2026-09-30' ORDER BY slot_time"
    ).fetchall()
    appointments = conn.execute(
        """SELECT s.slot_date, s.slot_time, d.name as doctor_name
           FROM appointments a
           JOIN slots s ON s.id = a.slot_id
           JOIN doctors d ON d.id = s.doctor_id
           WHERE a.patient_id = ?
           ORDER BY s.slot_date, s.slot_time""",
        (session["patient_id"],),
    ).fetchall()
    doctor = conn.execute("SELECT name FROM doctors LIMIT 1").fetchone()
    conn.close()
    return render_template(
        "book.html",
        slots=slots,
        appointments=appointments,
        doctor_name=doctor["name"],
        slot_date="2026-09-30",
        **shell_context("book"),
    )


@app.route("/book/<int:slot_id>", methods=["POST"])
@login_required("patient")
def book_slot(slot_id):
    """
    The core NFR-02 demonstration: this is a real transaction with a real
    row lock, not a check-then-write race condition.

    BEGIN IMMEDIATE grabs a write lock on the database before we even read
    the slot, so if two requests arrive for the same slot at the same
    instant, SQLite serialises them: the first to arrive gets the lock,
    reads status='open', books it and commits. The second has to wait for
    that lock, and by the time it gets in the slot already reads
    'booked' — so it is rejected with a normal flash message, never a
    double booking. test_concurrency.py fires this with real threads to
    prove it.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        slot = conn.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)).fetchone()
        if slot is None:
            conn.execute("ROLLBACK")
            flash("That slot doesn't exist.", "error")
            return redirect(url_for("book"))
        if slot["status"] != "open":
            conn.execute("ROLLBACK")
            flash(f"Sorry — the {slot['slot_time']} slot was just taken by someone else. Pick another.", "error")
            return redirect(url_for("book"))

        conn.execute("UPDATE slots SET status = 'booked' WHERE id = ?", (slot_id,))
        conn.execute(
            "INSERT INTO appointments (slot_id, patient_id, created_at) VALUES (?, ?, ?)",
            (slot_id, session["patient_id"], now_iso()),
        )
        conn.execute("COMMIT")
        flash(f"Booked {slot['slot_time']} — this slot is now locked in the database so no one else can take it.", "success")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return redirect(url_for("book"))


@app.route("/patient/prescriptions")
@login_required("patient")
def patient_prescriptions():
    conn = get_db()
    history = conn.execute(
        "SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY created_at DESC",
        (session["patient_id"],),
    ).fetchall()
    conn.close()
    ctx = shell_context("prescriptions")
    ctx["page_title"] = "My Prescriptions"
    rows = [
        {"created_at": h["created_at"], "patient_name": session["display_name"], "medication": h["medication"]}
        for h in history
    ]
    return render_template("staff_tasks.html", prescriptions=rows, **ctx)


# ---------------------------------------------------------------- doctor
@app.route("/doctor")
@login_required("doctor")
def doctor_dashboard():
    conn = get_db()
    appointments = conn.execute(
        """SELECT s.slot_time, p.id as patient_id, p.name as patient_name
           FROM appointments a
           JOIN slots s ON s.id = a.slot_id
           JOIN patients p ON p.id = a.patient_id
           WHERE s.doctor_id = ? AND s.slot_date = '2026-09-30'
           ORDER BY s.slot_time""",
        (session["doctor_id"],),
    ).fetchall()
    wilson = conn.execute("SELECT id FROM patients WHERE name = 'J. Wilson'").fetchone()
    conn.close()
    return render_template(
        "doctor_dashboard.html",
        appointments=appointments,
        slot_date="2026-09-30",
        wilson_id=wilson["id"] if wilson else None,
        **shell_context("dashboard"),
    )


@app.route("/doctor/patient/<int:patient_id>")
@login_required("doctor")
def patient_record(patient_id):
    conn = get_db()
    patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    if patient is None:
        conn.close()
        abort(404)
    notes = conn.execute(
        "SELECT * FROM consult_notes WHERE patient_id = ? ORDER BY created_at DESC", (patient_id,)
    ).fetchall()
    conn.close()
    ctx = shell_context("dashboard")
    ctx["page_title"] = f"Patient Record — {patient['name']}"
    return render_template("patient_record.html", patient=patient, notes=notes, **ctx)


@app.route("/doctor/patient/<int:patient_id>/note", methods=["POST"])
@login_required("doctor")
def add_note(patient_id):
    note = request.form.get("note", "").strip()
    if note:
        conn = get_db()
        conn.execute(
            "INSERT INTO consult_notes (patient_id, doctor_id, note, created_at) VALUES (?, ?, ?, ?)",
            (patient_id, session["doctor_id"], note, now_iso()),
        )
        conn.commit()
        conn.close()
        flash("Note added to the patient's record.", "success")
    return redirect(url_for("patient_record", patient_id=patient_id))


@app.route("/doctor/patient/<int:patient_id>/prescribe", methods=["GET", "POST"])
@login_required("doctor")
def new_prescription(patient_id):
    conn = get_db()
    patient = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    if patient is None:
        conn.close()
        abort(404)

    conflict = False
    if request.method == "POST":
        medication = request.form.get("medication", "").strip()
        dosage = request.form.get("dosage", "").strip()
        duration = request.form.get("duration", "").strip()

        # ---- FR-05, enforced server-side ----
        allergies = [a.strip().lower() for a in (patient["allergies"] or "").split(",") if a.strip()]
        med_lower = medication.lower()
        conflict = any(a in med_lower or med_lower in a for a in allergies if a)

        if medication and not conflict:
            conn.execute(
                "INSERT INTO prescriptions (patient_id, doctor_id, medication, dosage, duration, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (patient_id, session["doctor_id"], medication, dosage, duration, now_iso()),
            )
            conn.commit()
            conn.close()
            flash(f'Prescription for "{medication}" saved and sent to the pharmacy.', "success")
            return redirect(url_for("doctor_dashboard"))

    history = conn.execute(
        "SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY created_at DESC", (patient_id,)
    ).fetchall()
    conn.close()
    ctx = shell_context("dashboard")
    ctx["page_title"] = "New E-Prescription"
    return render_template("prescription.html", patient=patient, history=history, conflict=conflict, **ctx)


# ---------------------------------------------------------------- manager
@app.route("/manager")
@login_required("manager")
def manager_dashboard():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM slots WHERE slot_date = '2026-09-30'").fetchone()[0]
    booked = conn.execute("SELECT COUNT(*) FROM slots WHERE slot_date = '2026-09-30' AND status = 'booked'").fetchone()[0]
    prescriptions = conn.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
    doctor = conn.execute("SELECT name FROM doctors LIMIT 1").fetchone()
    conn.close()
    stats = {
        "total_slots": total,
        "booked_slots": booked,
        "open_slots": total - booked,
        "prescriptions": prescriptions,
        "doctor_name": doctor["name"],
        "utilisation": round((booked / total) * 100) if total else 0,
    }
    return render_template("manager_dashboard.html", stats=stats, **shell_context("ops"))


# ---------------------------------------------------------------- staff
@app.route("/staff")
@login_required("staff")
def staff_tasks():
    conn = get_db()
    rows = conn.execute(
        """SELECT pr.created_at, pr.medication, p.name as patient_name
           FROM prescriptions pr JOIN patients p ON p.id = pr.patient_id
           ORDER BY pr.created_at DESC"""
    ).fetchall()
    conn.close()
    return render_template("staff_tasks.html", prescriptions=rows, **shell_context("tasks"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
