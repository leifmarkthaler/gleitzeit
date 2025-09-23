#!/bin/bash
cd "/Users/leifmarkthaler/github/gleitzeit 0.0.7"
export PYTHONPATH="/Users/leifmarkthaler/github/gleitzeit 0.0.7/src:$PYTHONPATH"
python -m gleitzeit.orchestrator.component_orchestrator gleitzeit.yaml