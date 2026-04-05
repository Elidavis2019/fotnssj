#!/usr/bin/env bash
PORTS=(5000 5001 5002 5003)
NAMES=(student viewer teacher admin)
all_ok=true
for i in "${!PORTS[@]}"; do
    if curl -sf "http://localhost:${PORTS[$i]}/health" > /dev/null 2>&1; then
        echo "OK ${NAMES[$i]} (${PORTS[$i]})"
    else
        echo "FAIL ${NAMES[$i]} (${PORTS[$i]})"
        all_ok=false
    fi
done
$all_ok && exit 0 || exit 1