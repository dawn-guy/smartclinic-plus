"""
Unit tests for the SmartClinic+ Flask backend, using Flask's built-in test
client (no live server, no extra dependencies beyond Flask itself).

Run with:  python3 -m unittest test_app.py -v

Covers the three requirements this backend demo exists to prove:
  - NFR-01: role-based access (wrong/no login can't reach a role's pages)
  - NFR-02: a slot that's already booked cannot be booked again
  - FR-05:  a prescription that conflicts with a recorded allergy is
            rejected and never written to the database
"""
import os
import tempfile
import unittest

# Point the app at a throwaway database before importing it, so tests never
# touch the real smartclinic.db used for manual demos.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SMARTCLINIC_DB_PATH"] = _tmp_db.name

import db  # noqa: E402
db.init_db(reset=True)

import app as flask_app_module  # noqa: E402


class SmartClinicTests(unittest.TestCase):
    def setUp(self):
        self.app = flask_app_module.app.test_client()

    def login(self, username, password):
        return self.app.post(
            "/login", data={"username": username, "password": password}, follow_redirects=True
        )

    # ---- NFR-01: role-based access ----
    def test_wrong_password_rejected(self):
        resp = self.login("patient1", "wrong-password")
        self.assertIn(b"Invalid username or password", resp.data)

    def test_patient_cannot_open_manager_dashboard(self):
        self.login("patient1", "patient123")
        resp = self.app.get("/manager")
        self.assertEqual(resp.status_code, 403)

    def test_logged_out_user_redirected_to_login(self):
        resp = self.app.get("/book", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    # ---- NFR-02: no double booking ----
    def test_booking_an_already_booked_slot_is_rejected(self):
        self.login("patient1", "patient123")
        conn = db.get_db()
        slot = conn.execute("SELECT id FROM slots WHERE status = 'booked' LIMIT 1").fetchone()
        conn.close()
        before = db.get_db().execute(
            "SELECT COUNT(*) FROM appointments WHERE slot_id = ?", (slot["id"],)
        ).fetchone()[0]

        self.app.post(f"/book/{slot['id']}", follow_redirects=True)

        after = db.get_db().execute(
            "SELECT COUNT(*) FROM appointments WHERE slot_id = ?", (slot["id"],)
        ).fetchone()[0]
        self.assertEqual(before, after, "booking a slot that was already booked must not create an appointment")

    def test_booking_an_open_slot_succeeds(self):
        self.login("patient1", "patient123")
        conn = db.get_db()
        slot = conn.execute("SELECT id FROM slots WHERE status = 'open' LIMIT 1").fetchone()
        conn.close()

        self.app.post(f"/book/{slot['id']}", follow_redirects=True)

        row = db.get_db().execute("SELECT status FROM slots WHERE id = ?", (slot["id"],)).fetchone()
        self.assertEqual(row["status"], "booked")

    # ---- FR-05: server-side allergy check ----
    def test_conflicting_prescription_is_blocked_and_not_saved(self):
        self.login("doctor1", "doctor123")
        conn = db.get_db()
        wilson = conn.execute("SELECT id FROM patients WHERE name = 'J. Wilson'").fetchone()
        before = conn.execute(
            "SELECT COUNT(*) FROM prescriptions WHERE patient_id = ?", (wilson["id"],)
        ).fetchone()[0]
        conn.close()

        resp = self.app.post(
            f"/doctor/patient/{wilson['id']}/prescribe",
            data={"medication": "Penicillin V", "dosage": "500mg", "duration": "7 days"},
        )
        self.assertIn(b"Allergy conflict", resp.data)

        after = db.get_db().execute(
            "SELECT COUNT(*) FROM prescriptions WHERE patient_id = ?", (wilson["id"],)
        ).fetchone()[0]
        self.assertEqual(before, after, "a conflicting prescription must never be saved")

    def test_safe_prescription_is_saved(self):
        self.login("doctor1", "doctor123")
        conn = db.get_db()
        wilson = conn.execute("SELECT id FROM patients WHERE name = 'J. Wilson'").fetchone()
        conn.close()

        self.app.post(
            f"/doctor/patient/{wilson['id']}/prescribe",
            data={"medication": "Ibuprofen 200mg", "dosage": "1 tablet as needed", "duration": "5 days"},
            follow_redirects=True,
        )

        row = db.get_db().execute(
            "SELECT * FROM prescriptions WHERE patient_id = ? AND medication = 'Ibuprofen 200mg'",
            (wilson["id"],),
        ).fetchone()
        self.assertIsNotNone(row, "a non-conflicting prescription should be saved")


if __name__ == "__main__":
    unittest.main()
