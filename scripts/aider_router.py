"""
RE_OS — Aider Key Router
Tests Gemini keys 1-4 in order, picks first with available quota, launches Aider.
Falls back to Groq Scout if all Gemini keys exhausted.

Usage:
  python scripts/aider_router.py                   # auto-picks model
  python scripts/aider_router.py --model gemini/gemini-2.5-flash
  .\\scripts\\aider.ps1                              # PowerShell shortcut
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".env"
TEST_MODEL = "gemini-2.5-flash"
AIDER_GEMINI_MODEL = "gemini/gemini-2.5-flash"


def parse_env(path: Path) -> dict:
    """Parse .env file — no external dependencies needed."""
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def test_gemini_key(key: str) -> bool:
    """
    Pings Gemini with a 1-token request.
    Returns True  → key has available quota.
    Returns False → 429 quota exceeded OR invalid key.
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{TEST_MODEL}:generateContent?key={key}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": "1"}]}]}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=12):
            return True
    except urllib.error.HTTPError as e:
        # 429 = quota exhausted, 400/403 = bad key — both mean "don't use this"
        return False
    except Exception:
        return False


def collect_gemini_keys(env: dict) -> list:
    """Returns [(slot_name, key_value), ...] for all non-empty GEMINI_API_KEY_1..4."""
    pairs = []
    for i in range(1, 5):
        key = env.get(f"GEMINI_API_KEY_{i}", "").strip()
        if key:
            pairs.append((f"GEMINI_API_KEY_{i}", key))
    return pairs


def main():
    if not ENV_FILE.exists():
        print(f"[router] ERROR: .env not found at {ENV_FILE}")
        sys.exit(1)

    env = parse_env(ENV_FILE)
    gemini_keys = collect_gemini_keys(env)
    groq_key = env.get("GROQ_API_KEY", "").strip()
    groq_model = env.get(
        "GROQ_CEO_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
    ).strip()

    if not gemini_keys:
        print("[router] No GEMINI_API_KEY_1..4 found in .env — add keys first.")
    else:
        print(f"\n[Aider Router] Testing {len(gemini_keys)} Gemini key(s)...")

    working_gemini_key = None
    for name, key in gemini_keys:
        preview = f"{key[:8]}...{key[-4:]}"
        sys.stdout.write(f"  {name} ({preview}): ")
        sys.stdout.flush()
        if test_gemini_key(key):
            print("available ✓")
            working_gemini_key = key
            break
        else:
            print("quota exhausted ✗")

    runtime_env = os.environ.copy()
    extra_args = sys.argv[1:]  # pass any extra args straight to aider

    if working_gemini_key:
        runtime_env["GEMINI_API_KEY"] = working_gemini_key
        model_flag = [] if extra_args else ["--model", AIDER_GEMINI_MODEL]
        print("[Aider Router] Launching → Gemini 2.5 Flash\n")
        subprocess.run(["aider"] + model_flag + extra_args, env=runtime_env)

    elif groq_key:
        runtime_env["GROQ_API_KEY"] = groq_key
        model_flag = [] if extra_args else ["--model", f"groq/{groq_model}"]
        print("[Aider Router] All Gemini keys exhausted → Groq Scout fallback\n")
        subprocess.run(["aider"] + model_flag + extra_args, env=runtime_env)

    else:
        print("[Aider Router] No working keys found.")
        print("  → Add more Gemini keys to GEMINI_API_KEY_2/3/4 in .env")
        print("  → Or add a GROQ_API_KEY for fallback")
        sys.exit(1)


if __name__ == "__main__":
    main()
