"""
scripts/verify_admin_login.py
=============================
End-to-end verification of Admin Login through Flask test client and MongoDB.
"""
import sys
import re
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app

def verify_login_flow(email=None, password=None):
    email = (email or os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = password or os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        print("[FAIL] ADMIN_EMAIL and ADMIN_PASSWORD must be provided through the environment.")
        return False
    app = create_app()
    client = app.test_client()

    print("[*] Initiating configured admin login flow.")

    # 1. GET /auth/login
    res_get = client.get("/auth/login")
    if res_get.status_code != 200:
        print(f"[FAIL] GET /auth/login returned {res_get.status_code}")
        return False

    # Extract CSRF token from rendered HTML
    html = res_get.data.decode("utf-8")
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        print("[FAIL] CSRF token could not be extracted from login page HTML")
        return False
    csrf_token = match.group(1)
    print(f"[+] Extracted CSRF token successfully")

    from extensions import limiter
    limiter.reset()

    # 2. POST /auth/login
    res_post = client.post(
        "/auth/login",
        data={
            "email": email,
            "password": password,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    print(f"[*] POST /auth/login response status: {res_post.status_code}")
    print(f"[*] Redirect URL: {res_post.headers.get('Location')}")

    if res_post.status_code != 302:
        print(f"[FAIL] Expected 302 redirect, got {res_post.status_code}")
        # Look for flash messages in rendered HTML
        for msg in re.findall(r'role="status"[^>]*>([^<]+)</div>', res_post.data.decode('utf-8')):
            print(f"[FLASH MESSAGE]: {msg.strip()}")
        return False

    location = res_post.headers.get("Location")
    if "/admin" not in location:
        print(f"[FAIL] Expected redirect to /admin, got {location}")
        return False

    # 3. Request Admin Dashboard
    res_dash = client.get(location)
    print(f"[*] GET {location} response status: {res_dash.status_code}")

    if res_dash.status_code == 200 and b"Admin Dashboard" in res_dash.data:
        print(f"[SUCCESS] Admin authenticated and dashboard rendered successfully!")
        return True
    else:
        print(f"[FAIL] Dashboard did not render as expected.")
        return False

if __name__ == "__main__":
    if verify_login_flow():
        print("\n[CHECK PASSED] Configured admin login verified.\n")
    else:
        print("\n[CHECK FAILED]\n")
