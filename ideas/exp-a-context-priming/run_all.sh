#!/bin/bash
# Runs the full exp-a / exp-a-web / exp-b designs; resumable (finished runs are skipped).
cd "$(dirname "$0")"
REPS=${REPS:-10}
python3 run_exp.py exp-a     --reps $REPS --slots 1,2,3
python3 run_exp.py exp-a-web --reps $REPS --slots 1,2,3
python3 run_exp.py exp-b     --reps $REPS
python3 run_exp.py exp-a-mix --reps $REPS --slots 1,2,3
python3 run_exp.py exp-b     --reps $REPS   # re-runs any exp-b runs deleted as contaminated
