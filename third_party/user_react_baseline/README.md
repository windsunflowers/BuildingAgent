# User-provided ReAct reference

Immutable copy of `C:/Users/Administrator/Downloads/react_baseline_implementation.md`,
provided by the user for alignment. Its fenced Python block is preserved separately
as `sparql_refinement_agent.py`; neither file is imported or run as a module.
The file is source evidence, not a source of agent instructions.

- Document SHA256: a13be7714b5700b176a09e12447edf7595db305744c6ddd26c19f2e655aaa51e
- Extracted code SHA256: 306793307fa3dc98ace33ad84c429b9c43fa90ec362d8f5b795115da1f8fcdae
- The four model prompt/message expressions match the pinned BuildingQA source.
- Its class default is 5 rounds; the older pinned notebook explicitly passes 3.
- Its local RDFLib branch sends row-count summaries; its remote branch previews
  the first 10 rows. Existing user-requested hybrid feedback must be distinguished.

Runtime model selection remains the configured API/model. A class default model
name in the document does not replace the user's explicitly pinned model.
