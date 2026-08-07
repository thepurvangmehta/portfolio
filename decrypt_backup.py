#!/usr/bin/env python3
"""Recover a gated case study's content/<slug>.json from its encrypted
backup (content/.backups/<slug>.json.enc, committed to the repo) using the
same gate password used to unlock the live site.

Usage:
    python3 decrypt_backup.py healthcare
    python3 decrypt_backup.py communication-saas

Writes content/<slug>.json.recovered so it never silently overwrites a file
that already exists -- rename it yourself once you've checked it.
"""
import sys, os, json, base64, hashlib, getpass, pathlib

ROOT = pathlib.Path(__file__).parent

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    slug = sys.argv[1]
    src = ROOT / "content" / ".backups" / f"{slug}.json.enc"
    if not src.exists():
        print(f"No backup found at {src}")
        sys.exit(1)
    blob = json.loads(src.read_text(encoding="utf-8"))
    password = os.environ.get("CS_GATE_PW") or getpass.getpass("Gate password: ")

    from Crypto.Cipher import AES
    salt = base64.b64decode(blob["salt"])
    iv = base64.b64decode(blob["iv"])
    raw = base64.b64decode(blob["data"])
    ct, tag = raw[:-16], raw[-16:]
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, blob["iters"], dklen=32)
    try:
        plaintext = AES.new(key, AES.MODE_GCM, nonce=iv).decrypt_and_verify(ct, tag)
    except ValueError:
        print("Wrong password (decryption failed).")
        sys.exit(1)

    data = json.loads(plaintext)
    out = ROOT / "content" / f"{slug}.json.recovered"
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recovered -> {out}")
    print(f"Review it, then rename to content/{slug}.json to use it.")

if __name__ == "__main__":
    main()
