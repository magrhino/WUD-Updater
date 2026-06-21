#!/bin/sh
# Generate requirements.txt from pyproject.toml using pip-compile.
set -eu
pip-compile --strip-extras --generate-hashes pyproject.toml -o requirements.txt
