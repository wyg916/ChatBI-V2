# ChatBI Legacy RAG Adapter

Thin HTTP interoperability adapter for the owner-authorized Legacy RAG runtime. The default workspace-echo check is fail-closed. The HTTP adapter itself imports no legacy module; the isolated RAG service calls only the three checksum-locked selected-source index/rerank/security modules documented in `docs/runtime/V1_3_PHASE3_OWNER_AUTHORIZED_LEGACY_RAG_LOCK.md`.
