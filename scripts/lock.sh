#!/bin/sh
# Generate requirements.txt from pyproject.toml using pip-compile.
set -eu
pip-compile pyproject.toml -o requirements.txt
