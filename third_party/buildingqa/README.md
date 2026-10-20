# BuildingQA reference metrics

`metrics.py` is an unmodified copy of the official BuildingQA implementation:

- Repository: https://github.com/INFERLab/BuildingQA
- Commit: `b792a627419dfb679ad1f26e4d3dc325a758e95b`
- Source: https://github.com/INFERLab/BuildingQA/blob/b792a627419dfb679ad1f26e4d3dc325a758e95b/metrics.py

The adapter in `evaluation_metrics.py` converts local rows to SPARQL JSON bindings.
The reference preserves duplicates, uses one global column mapping, and computes
Exact Match F1 with fixed column positions, allowing partial credit. Binary
execution accuracy is reported separately. Do not edit the reference to improve
benchmark scores.
