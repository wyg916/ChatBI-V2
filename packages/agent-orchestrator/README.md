# ChatBI Bounded Orchestrator

The local implementation is a finite, deterministic state machine. It has no model-controlled loop and can call only tools present in the request allowlist. The legacy HTTP adapter is present for compatibility reporting but refuses remote execution because the frozen endpoint cannot accept ChatBI V2 tool callbacks.
