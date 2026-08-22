# ChatBI V1.3.0 Phase 5 Release Candidate Notes

This is a Phase 5 release-hardening candidate, not a formal V1.3.0 release.

The candidate adds no planned product capability. It hardens the Sandbox Docker control boundary with a private, stateful, exact-allowlist proxy; pins GitHub Actions to immutable Node 24 revisions; isolates Starlette's `httpx2` compatibility bridge while retaining application `httpx`; applies an audited `aiohttp` compatibility override to the frozen DB-GPT AWEL boundary; and adds Phase 5 contract, migration, security, dependency, SBOM and regression automation.

Release Evidence is intentionally fail-closed. A manifest check is labelled as contract evidence, direct database load is not reported as Backend API correctness, and an injected expected envelope is not reported as a live fault result. Final performance, cost, security, browser, cold-start and remote CI claims are populated only from same-SHA executions.

There is no `main` merge, V1.3.0 tag, formal GitHub Release or Phase 6 work in this candidate.
