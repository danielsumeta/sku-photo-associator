#!/bin/bash
set -e
mkdir -p /logs/verifier

# Use preinstalled uvx if available, otherwise fall back to pip.
# No apt-get or curl at grading time — all deps are pip-installable.
if command -v uvx >/dev/null 2>&1; then
  uvx \
    --with pytest==8.4.1 \
    --with pytest-json-ctrf==0.3.5 \
    --with Pillow==10.4.0 \
    pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA 2>&1 | tee /tmp/pytest.log
else
  pip install -q Pillow==10.4.0 pytest==8.4.1 pytest-json-ctrf==0.3.5 2>&1 | tail -5
  python -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA 2>&1 | tee /tmp/pytest.log
fi

RET=${PIPESTATUS[0]}
if [ $RET -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
exit $RET
