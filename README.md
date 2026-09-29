# SmartClinic+

![CI](https://github.com/dawn-guy/smartclinic-plus/actions/workflows/ci.yml/badge.svg)

SENG205 Software Engineering — Assessment 3, Group 5, Kent Institute Australia.

A small, genuinely working slice of SmartClinic+, built with **Flask + SQLite** (no
external services, no hosting cost — consistent with the $0 project budget). Data is
actually written to and read from a real database on the server, and the rules that
matter for the assessment are enforced there, not just in the UI.

## What's real here

| Requirement | How it's actually implemented |
|---|---|
| **NFR-01** — role-based access | Login checks a hashed password against the `users` table; your role is read from the database and stored server-side in the session — the browser never decides which dashboard you get. |
| **NFR-02** — no double-booking | Booking a slot runs inside a SQLite transaction that takes a write lock (`BEGIN IMMEDIATE`) *before* checking the slot's status. Two simultaneous booking requests for the same slot are serialised by the database itself — the second always loses. Proven in `test_concurrency.py` and `test_app.py`, not just claimed. |
| **FR-05** — allergy check on e-prescriptions | The medication name is checked against the patient's `allergies` column in the database, on the server, before anything is saved. A blocked prescription is never written to the `prescriptions` table. |
| **FR-09** — operational dashboard | The manager's numbers (slots booked/open, prescriptions on file, doctor utilisation) come from real SQL `COUNT()` queries over the same tables the booking and prescription flows write to — not hardcoded numbers. |

Everything else (staff tasks, notes, prescription history) reads and writes to the
same SQLite database, so actions in one role are visible from another — book a slot
as the patient, then check the doctor's dashboard and the manager's numbers update.

## Running it

Requires Python 3.9+ (no other software, no Docker, no account signups).

```bash
git clone https://github.com/dawn-guy/smartclinic-plus
cd smartclinic-plus
pip install -r requirements.txt      # just Flask
python3 app.py
```

Then open **http://127.0.0.1:5000** in a browser. The database file
(`smartclinic.db`, gitignored) is created and seeded automatically on first run —
delete it and restart `app.py` to reset everything back to the starting demo data.

### Demo accounts

| Username | Password | Role |
|---|---|---|
| `patient1` | `patient123` | Patient (Riya Sharma) |
| `doctor1` | `doctor123` | Doctor (Dr. Amelia Chen) |
| `manager1` | `manager123` | Clinic Manager |
| `staff1` | `staff123` | Nurse / Staff |

## Suggested walkthrough for a live demo

1. **Log in as `patient1`** → Book Appointment → book an open slot → note the flash
   message says it's now locked in the database.
2. **Log in as `doctor1`** (in a new private/incognito window, so both sessions are
   live at once) → Dashboard → you'll see the booking that was just made → click the
   patient's name → open their record.
3. From the patient record, click **New Prescription** → type `Penicillin` (J. Wilson's
   recorded allergy) → the server rejects it with a red warning, and it was never
   saved. Then try a real medication (e.g. `Metformin 500mg`) → it saves and appears
   in the prescription history immediately.
4. **Log in as `manager1`** → Operational Dashboard → point out the booked/open counts
   match what was just done in steps 1–3, computed live by a SQL query.
5. **Log in as `staff1`** → Staff Tasks → the prescription from step 3 already appears
   here, generated automatically from the same table.

## Testing

```bash
python3 -m unittest test_app.py -v   # 7 tests: RBAC, booking, allergy check
python3 test_concurrency.py          # fires two real concurrent requests at one slot
```

Both run automatically on every push via GitHub Actions (see the badge above and the
[Actions tab](https://github.com/dawn-guy/smartclinic-plus/actions)).

`test_concurrency.py` needs `app.py` running in another terminal first. Expected
output:

```
Slot 3 final status: booked
Appointments created for this slot: 1 (must be exactly 1, not 2)
PASS — the transaction lock prevented the double booking.
```

The "PASS" line is a genuine assertion (`assert appt_count == 1`), not printed text.

## Why Flask + SQLite instead of Django + PostgreSQL (as in the report's architecture)

The report and architecture diagram describe Django on PostgreSQL as the target
production stack, and that's still the right answer there — this repo doesn't change
that. It exists to prove, with working and tested code, that the three riskiest
non-functional requirements (role gating, transaction-safe booking, and a hard
server-side validation rule) are implementable the way the design claims, not just
diagrammed. Flask + SQLite gets there with zero setup and zero cost; swapping to
Django + PostgreSQL for a real deployment would not change any of the logic above,
only the framework it's written in.

## Scope — what this repo does *not* cover

This is a small slice, not the full system: no real SMS/email sending, no full
patient self-registration, no password reset, and the other functional requirements
(queue status, notifications, staff task routing, etc.) are either static or backed
by simple read queries rather than full workflows. That's a deliberate scope decision
to keep this demo small, working and easy to explain — not a limitation to hide.

## Team

| Member | Role |
|---|---|
| Aayush | Team Leader |
| Prashant | Requirements Engineer |
| Aarambha | System Designer |
| Shakshyam | DevOps / PM Lead |
| Kripesh | QA / Planning Lead |
