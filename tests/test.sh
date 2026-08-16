#!/bin/bash

# Install deps needed by verifier helpers (PIL for synthetic images)
pip install -q Pillow>=10 2>&1 | tail -3

apt-get update
apt-get install -y curl 2>&1 | tail -3

curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh 2>&1 | tail -3

source $HOME/.local/bin/env

# Ensure sku-photo is discoverable: if solution was installed, its bin is on PATH
# Tests resolve bin via _sku_photo_bin() with fallbacks to python -m
mkdir -p /logs/verifier

uvx \
  --with pytest==8.4.1 \
  --with pytest-json-ctrf==0.3.5 \
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA 2>&1 | tee /tmp/pytest.log

RET=${PIPESTATUS[0]}
if [ $RET -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
exit $RET
