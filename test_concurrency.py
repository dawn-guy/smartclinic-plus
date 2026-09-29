"""
Proves NFR-02 (no double-booking) for real: fires two concurrent HTTP
requests at the SAME slot and shows that exactly one succeeds.

Run this while app.py is running (python3 app.py in another terminal),
after the database has been freshly seeded (delete smartclinic.db and
restart app.py to reseed).

    python3 test_concurrency.py
"""
import threading
import http.client
import http.cookies
import urllib.parse

HOST = "127.0.0.1"
PORT = 5000


def login(username, password):
    conn = http.client.HTTPConnection(HOST, PORT)
    body = urllib.parse.urlencode({"username": username, "password": password})
    conn.request("POST", "/login", body=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    resp.read()
    raw_cookie = resp.getheader("Set-Cookie")
    conn.close()
    cookie = http.cookies.SimpleCookie()
    cookie.load(raw_cookie)
    return "; ".join(f"{k}={v.value}" for k, v in cookie.items())


def book(slot_id, cookie, results, key):
    conn = http.client.HTTPConnection(HOST, PORT)
    conn.request("POST", f"/book/{slot_id}", headers={"Cookie": cookie, "Content-Length": "0"})
    resp = conn.getresponse()
    body = resp.read().decode(errors="ignore")
    conn.close()
    # Follow the redirect to read the flashed result
    conn2 = http.client.HTTPConnection(HOST, PORT)
    conn2.request("GET", "/book", headers={"Cookie": cookie})
    resp2 = conn2.getresponse()
    body2 = resp2.read().decode(errors="ignore")
    conn2.close()
    results[key] = "just taken" in body2 or "was just taken" in body2


if __name__ == "__main__":
    # Two separate patient sessions racing for the same open slot (id 3 == 09:40, per seed data)
    slot_id = 3
    cookie_a = login("patient1", "patient123")
    cookie_b = login("patient1", "patient123")  # same account, two sessions — good enough to prove the row lock

    results = {}
    t1 = threading.Thread(target=book, args=(slot_id, cookie_a, results, "a"))
    t2 = threading.Thread(target=book, args=(slot_id, cookie_b, results, "b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Verify final DB state directly
    from db import get_db

    conn = get_db()
    slot = conn.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)).fetchone()
    appt_count = conn.execute("SELECT COUNT(*) FROM appointments WHERE slot_id = ?", (slot_id,)).fetchone()[0]
    conn.close()

    print(f"Slot {slot_id} final status: {slot['status']}")
    print(f"Appointments created for this slot: {appt_count} (must be exactly 1, not 2)")
    assert appt_count == 1, "NFR-02 VIOLATED — the slot was double-booked!"
    print("PASS — the transaction lock prevented the double booking.")
