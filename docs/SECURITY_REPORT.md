# ChatBI V2 V1.1.0 security report

## Verdict and evidence rule

The pre-freeze active attack suite passes 110/110 cases. The release verdict is not taken from this tracked report: after the candidate SHA is committed and pushed, the same runner must create `artifacts/v2_1/final/<SHA>/security.json`; that raw artifact and `FINAL_EVIDENCE_MANIFEST.json` are authoritative. A failed or different-SHA rerun blocks release.

## Active attack results

| Surface | Cases | Result | Required invariant |
| --- | ---: | --- | --- |
| SQL Guard and API execution | 56 | 56/56 blocked | block rate 1.0; business DB writes 0 |
| Authentication and RBAC | 13 | 13/13 | unauthorized success 0 |
| Attachment boundary | 12 | 12/12 | malicious attachment execution 0 |
| Governed RAG | 8 | 8/8 | unauthorized/cross-scenario recall 0; injection evidence used 0; citation accuracy 1.0 |
| Bounded Agent | 13 | 13/13 | direct DB, Guard/Oracle bypass, unknown tool, infinite loop and cross-Workspace leak 0 |
| Fixed file interpreter | 8 | 8/8 | sandbox escape and host/database/provider credential access 0; unrestricted network 0 |
| **Total** | **110** | **110/110** | **PASS before SHA freeze** |

The SQL corpus actively covers SELECT/multi-statement bypass, DDL/DML, write CTE, COPY/CALL, EXPLAIN ANALYZE mutation, comments/encoding, dangerous functions and system catalogs. Both direct SQLGlot Guard and authenticated PostgreSQL/MySQL Data Workspace routes are exercised. The fact table remained at 10,000,000 rows and its security-probe signature remained `953c8f96061b87ab1e8f452d4109ee18c7f1bc35116ccb3deceab4967ff4ef05` before and after the attack run; observed business-database write count was 0.

Authentication probes cover anonymous, expired, forged and revoked sessions, cross-user/cross-Workspace resource guessing, role escalation and logout revocation. RAG probes insert temporary malicious and unauthorized documents and then remove them; a malicious document passes only when that exact document/version/chunk is absent from returned evidence, while unrelated authorized evidence is allowed. Citation IDs are verified against stored document/version/chunk relationships.

Agent probes invoke the real fixed ToolExecutor. A supplied `DROP TABLE` argument is ignored rather than executed: the data tool regenerates SQL from the natural-language request, then requires SQL Guard and Result Oracle PASS. The tool catalogue remains six entries, role-to-tool permissions are fixed, no connector/file/network tool exists, and step/tool/replan/depth/timeout bounds are actively challenged. File probes use the real non-executable interpreter policy and test traversal, host mount, secrets, credentials, network, resource exhaustion and oversized output.

## Supply chain

- Repository secret scan: PASS, 0 hits in the governed scan.
- CycloneDX 1.6 and SPDX 2.3 SBOMs are generated from the installed Backend container plus the complete frontend lockfile; 319 dependency components are represented and unknown/NOASSERTION dependency licenses are 0.
- Exact upstream repositories and commits are frozen in `docs/UPSTREAM_LOCK.json`; license interpretation and excluded paths are recorded in `docs/OPEN_SOURCE_LICENSE_AUDIT.md` and notices in `THIRD_PARTY_NOTICES.md`.
- Full-lock `npm audit --json` and `pip-audit -r backend/requirements.txt` are mandatory same-SHA commands. Their machine-readable outputs must report 0 known vulnerabilities in the final evidence root; command absence, non-zero exit or a finding blocks the manifest.

## Corrected pre-freeze findings

An earlier 110-case run reported 108/110. Investigation found two evidence-runner defects rather than accepted attacks: the malicious-document assertion rejected safe authorized documents that shared the benign word “revenue”, and Agent setup selected an arbitrary leftover published test model. The runner now checks the exact malicious document/version/chunk identity and selects the named V2.1 10M release datasource/model deterministically. The corrected active rerun is 110/110; the earlier failure remains retained in ignored raw evidence and is not represented as a pass.

The first Python dependency audit also correctly blocked the candidate: it found 86 advisories across seven pinned packages. The security refresh pins FastAPI 0.140.8, Starlette 1.3.1, cryptography 50.0.0, pytest 9.1.1, python-multipart 0.0.32, PyArrow 25.0.0, pypdf 6.15.0 and Pillow 12.3.0. An intermediate audit reduced the result to three advisories in two packages; the final pre-freeze `pip-audit` reports no known vulnerabilities. These version changes remain subject to the full Backend, attachment/PDF/image, product, E2E and same-SHA release gates; audit success alone is not a compatibility PASS.

## Residual controls

The Backend still depends on deployment TLS/reverse-proxy policy and locally protected `.env` permissions. Complete enterprise OIDC/Vault and a general-purpose code sandbox are deliberately outside V1.1.0; no generated Python is executed, so the release does not claim those P2 capabilities. Any future executable plugin/file path requires a new threat model and cannot reuse this PASS.
