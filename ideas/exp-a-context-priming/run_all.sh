#!/bin/bash
# Runs every design at REPS runs per cell (default 20, as reported). Resumable: finished
# runs are skipped, so deleting a suspect result file and re-running redoes just that run.
# exp-b needs all 4 cores -- run nothing else meanwhile.
cd "$(dirname "$0")"
REPS=${REPS:-20}
python3 run_exp.py exp-a     --reps $REPS --slots 1,2,3
python3 run_exp.py exp-a-web --reps $REPS --slots 1,2,3
python3 run_exp.py exp-a-mix --reps $REPS --slots 1,2,3
python3 run_exp.py exp-b     --reps $REPS
python3 run_exp.py exp-a-fps2 --reps $REPS --slots 1,2,3
