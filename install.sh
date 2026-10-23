#!/usr/bin/env bash
# install.sh — SpiderDeck bootstrap
# Run this FIRST, before spiderdeck.py. Safe to re-run any time;
# it only installs what's missing and retries failures on its own.
#
# Usage:
#   bash install.sh

set -uo pipefail  # (no -e: we handle failures ourselves so one bad
                   #  package doesn't kill the whole script)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
REQS="requirements.txt"
MIN_PY_MINOR=11
RETRIES=3
TIMEOUT=180

ok()   { echo "  ✅ $1"; }
warn() { echo "  ⚠️  $1"; }
err()  { echo "  ❌ $1"; }

echo "SpiderDeck bootstrap"
echo "===================="
echo

# --- 1. Check Python version -------------------------------------------
echo "[1/5] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found. Install it from https://www.python.org/downloads/ or 'brew install python' then re-run this script."
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt "$MIN_PY_MINOR" ]; }; then
    err "Python $PY_VER found, but SpiderDeck needs 3.$MIN_PY_MINOR or newer."
    echo "    Install a newer version: brew install python@3.13"
    exit 1
fi
ok "Python $PY_VER"
echo

# --- 2. Create venv if missing -------------------------------------------
echo "[2/5] Checking virtual environment..."
if [ -d "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ]; then
    ok "Virtual environment already exists at $VENV_DIR"
else
    echo "    Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    if [ -x "$VENV_DIR/bin/python" ]; then
        ok "Created virtual environment"
    else
        err "Failed to create virtual environment"
        exit 1
    fi
fi
echo

PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"

# --- 3. Upgrade pip itself -----------------------------------------------
echo "[3/5] Upgrading pip..."
"$PY" -m pip install --upgrade pip --timeout "$TIMEOUT" --quiet
ok "pip is up to date"
echo

# --- 4. Install each dependency one-by-one, with retries -----------------
echo "[4/5] Installing dependencies (one at a time, with retries)..."
FAILED=()

while IFS= read -r line || [ -n "$line" ]; do
    # skip blank lines and comments
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    pkg="$line"

    attempt=1
    installed=false
    while [ "$attempt" -le "$RETRIES" ]; do
        echo "    Installing $pkg (attempt $attempt/$RETRIES)..."
        if "$PIP" install "$pkg" --timeout "$TIMEOUT" --quiet; then
            installed=true
            break
        fi
        attempt=$((attempt + 1))
        sleep 2
    done

    if [ "$installed" = true ]; then
        ok "$pkg"
    else
        err "$pkg failed after $RETRIES attempts"
        FAILED+=("$pkg")
    fi
done < "$REQS"
echo

# --- 5. Verify everything actually imports --------------------------------
echo "[5/5] Verifying installed packages import correctly..."
"$PY" "$SCRIPT_DIR/verify.py"
VERIFY_STATUS=$?
echo

# --- Summary ---------------------------------------------------------------
echo "===================="
if [ ${#FAILED[@]} -eq 0 ] && [ "$VERIFY_STATUS" -eq 0 ]; then
    echo "✅ All dependencies installed and verified."
    echo
    echo "Next steps:"
    echo "  source $VENV_DIR/bin/activate"
    echo "  python spiderdeck.py"
else
    echo "⚠️  Some packages had trouble:"
    for p in "${FAILED[@]}"; do
        echo "    - $p"
    done
    echo
    echo "This is almost always a flaky connection, not a real problem."
    echo "Just re-run this script — it skips packages that already installed:"
    echo "  bash install.sh"
fi

# Optional: Playwright browsers
echo
read -p "Also install Playwright browsers (Chromium, Firefox)? [y/N]: " ans
if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
    "$PY" -m playwright install chromium firefox
fi
