# ChatBI sandbox controller

The Backend, controller and disposable compute Worker never receive
`/var/run/docker.sock`. In Docker Compose the Backend sends a fixed version-1
job protocol over the private `sandbox-control` network. The non-root
controller reaches a separate, unexposed Docker control proxy over the private
`sandbox-docker-control` network. Only that proxy mounts the configured Docker
endpoint read-only; for rootless Docker set `CHATBI_DOCKER_SOCKET_PATH` to the
rootless daemon socket before starting Compose.

The proxy validates both Docker API paths and request bodies. It accepts only
the fixed worker image, command, uid/gid, secret-free environment,
no-network/read-only/cap-drop/no-new-privileges configuration, bounded tmpfs
and resource limits. Container and exec identifiers must have been registered
by the proxy. Arbitrary images, commands, mounts, ports, devices, host
namespaces, privileged mode and unrelated Docker objects are denied.

The controller creates `chatbi-sandbox-runtime:phase3` workers through
`DockerWorkerSpec`. Workers run as uid/gid 65532 with network disabled, no host
mounts or secrets, read-only rootfs, bounded tmpfs, all capabilities dropped,
no-new-privileges and CPU/RAM/PID limits. Completion, timeout and DELETE cancel
all pass through the executor's synchronous `finally` removal check.

The controller removes only containers carrying `com.chatbi.sandbox=true` at
startup. If Docker, the restricted proxy, the fixed worker image, cancellation
cleanup or the private protocol is unavailable, execution fails closed; it
never falls back to local execution in the Backend.

Validation commands:

```text
docker compose config --no-interpolate
docker build -f sandbox_runtime/Dockerfile -t chatbi-sandbox-runtime:phase3 .
pytest backend/tests/test_v13_phase3_python_sandbox.py backend/tests/test_v13_phase5_security_supply.py
```
