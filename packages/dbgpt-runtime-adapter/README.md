# ChatBI DB-GPT runtime adapter

This package is the only supported boundary between ChatBI and the pinned
DB-GPT AWEL selected source. It invokes `DAG`, `MapOperator`, and
`BaseOperator.call()` from the exact upstream revision while keeping model
credentials, database connections, connectors, SQL text, RAG state, auth, and
conversation state outside AWEL.

The dependency is intentionally lazy. Missing or provenance-mismatched DB-GPT
installs fail closed and never fall back to the project-authored orchestrator
while claiming an upstream call.
