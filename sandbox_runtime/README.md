# ChatBI sandbox controller

The Backend never receives `/var/run/docker.sock`. In Docker Compose it sends a
fixed version-1 job protocol over the private `sandbox-control` network. Only
the controller mounts the Docker endpoint, and its request schema accepts only
`code`, JSON `datasets`, and a timeout up to 15 seconds. Image, command,
environment, mounts, network, user, capabilities and resource limits cannot be
overridden by callers.

The controller creates `chatbi-sandbox-runtime:phase3` workers through
`DockerWorkerSpec`. Workers run as uid/gid 65532 with network disabled, no host
mounts or secrets, read-only rootfs, bounded tmpfs, all capabilities dropped,
no-new-privileges and CPU/RAM/PID limits. Completion, timeout and DELETE cancel
all pass through the executor's synchronous `finally` removal check.

The controller removes only containers carrying `com.chatbi.sandbox=true` at
startup. If Docker, the fixed worker image, cancellation cleanup or the private
protocol is unavailable, execution fails closed; it never falls back to local
execution in the Backend.

Validation commands:

```text
docker compose config --no-interpolate
docker build -f sandbox_runtime/Dockerfile -t chatbi-sandbox-runtime:phase3 .
pytest backend/tests/test_v13_phase3_python_sandbox.py
```
