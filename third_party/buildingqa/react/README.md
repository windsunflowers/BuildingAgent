# Pinned BuildingQA ReAct baseline

Unmodified reference sources from [INFERLab/BuildingQA](https://github.com/INFERLab/BuildingQA/tree/b792a627419dfb679ad1f26e4d3dc325a758e95b).
File origins and SHA256 values are in `source_manifest.json`. The notebook is
reference data and is never executed. No SDK, key, remote endpoint or dependency
setup from the reference module is imported.

`react_reference.py` loads only the four reviewed prompt/message expressions
from the hash-checked source. `react_baseline.py` adapts its local writer/critic
loop to the configured shared API and isolated local query runner. Both roles
use the selected model, temperature 0 and JSON object responses, with no output
token limit added. The demo explicitly configures 3 rounds; the class default
is 5. Failures keep the last generated query exactly as in the reference.

The local reference reports row counts (not result previews) to the critic and
does not repair prefixes. Its ASK formatter failure is preserved. The adapter
retains the application's loaded graph/ontology merge, query deadlines, SDK
timeout, cancellation and shared official scorer; these are recorded as
engineering adaptations, not claimed to be the original GraphDB environment.
