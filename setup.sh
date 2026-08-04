#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
git submodule update --init --recursive

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

for requirements in \
    engines/hook-engine/requirements.txt \
    engines/review-engine/requirements.txt
do
    if [ -f "$requirements" ]; then
        .venv/bin/python -m pip install -r "$requirements"
    fi
done

echo "Setup complete."
