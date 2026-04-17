"""
One-off: set Firestore users/{uid} so role is "admin".
Uses the same serviceAccountKey.json as the Flask app.

Usage:
  python tools/promote_admin.py D4uLnIyhWwS10AHRM3LIllqy9cS2
  python tools/promote_admin.py --uid D4uLnIyhWwS10AHRM3LIllqy9cS2 --email admin@admin.com --name "Admin"
"""

import argparse
import os
import sys

# Run from backend/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote a Firebase Auth user to admin in Firestore.")
    parser.add_argument("uid", nargs="?", default="", help="Firebase Auth UID")
    parser.add_argument("--uid", dest="uid_flag", default="", help="Firebase Auth UID (alternative)")
    parser.add_argument("--email", default="", help="Email to store on user doc (default: from Auth)")
    parser.add_argument("--name", default="Admin", help="Display name on user doc")
    args = parser.parse_args()
    uid = args.uid or args.uid_flag
    if not uid:
        print("Error: pass UID as first argument or --uid", file=sys.stderr)
        sys.exit(1)

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.path.join(base, "serviceAccountKey.json")
    if not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    email = args.email.strip()
    try:
        user_record = firebase_auth.get_user(uid)
        if not email:
            email = user_record.email or ""
    except Exception as exc:
        print(f"Warning: could not fetch Auth user: {exc}", file=sys.stderr)
        if not email:
            print("Error: provide --email if Auth lookup fails", file=sys.stderr)
            sys.exit(1)

    ref = db.collection("users").document(uid)
    snap = ref.get()
    existing = snap.to_dict() if snap.exists else {}
    payload = {
        "name": args.name.strip() or existing.get("name") or "Admin",
        "email": email or existing.get("email") or "",
        "role": "admin",
    }
    if not existing.get("created_at"):
        try:
            from google.cloud.firestore import SERVER_TIMESTAMP

            payload["created_at"] = SERVER_TIMESTAMP
        except Exception:
            from datetime import datetime

            payload["created_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    ref.set(payload, merge=True)
    print(f"OK: users/{uid} updated with role=admin")
    print(f"    email={payload['email']} name={payload['name']}")


if __name__ == "__main__":
    main()
