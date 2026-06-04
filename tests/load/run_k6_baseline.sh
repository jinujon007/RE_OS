#!/bin/bash
# Run k6 baseline test
k6 run tests/load/k6_dashboard.js --out json=results.json
echo "Results saved to results.json"
