#!/usr/bin/env bash

dir=$(dirname "$0")
cd "$dir/.."

if [ $# -eq 0 ]; then
  uv run python -m pytest -v -p no:faulthandler tests
else
  uv run python -m pytest -v -p no:faulthandler "$@"
fi
