from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


from app.sandbox import (
    DockerSandboxExecutor,
    DockerWorkerSpec,
    PythonCodeGuard,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxResult,
    SandboxStatus,
)
from app.sandbox.controller_client import PROTOCOL_VERSION
from app.sandbox.controller_server import (
    ControllerRequestError,
    JobRegistry,
    _validate_job_payload,
)


def test_guard_accepts_bounded_dataframe_analysis():
    report = PythonCodeGuard().validate(
        "import pandas as pd\nresult = pd.DataFrame(datasets['rows']).sum().to_dict()",
        {"rows": [{"amount": 3}, {"amount": 4}]},
    )
    assert report.imports == ("pandas",)
    assert report.ast_nodes > 0
    assert len(report.code_sha256) == 64


@pytest.mark.parametrize(
    "module",
    ["os", "subprocess", "socket", "ctypes", "pathlib", "urllib", "requests"],
)
def test_guard_denies_dangerous_imports(module):
    with pytest.raises(SandboxPolicyViolation) as caught:
        PythonCodeGuard().validate(f"import {module}\nresult = 1", {})
    assert caught.value.code == "SANDBOX_IMPORT_DENIED"


@pytest.mark.parametrize(
    "code",
    [
        "result = open('/etc/passwd').read()",
        "result = eval('1+1')",
        "result = __import__('os')",
        "result = pd.read_sql('select 1', object())",
        "result = pd.read_csv('https://example.invalid/a.csv')",
        "from pandas import read_csv as f\nresult = f('https://example.invalid/a.csv')",
        "result = datasets.__class__",
    ],
)
def test_guard_denies_dangerous_apis(code):
    with pytest.raises(SandboxPolicyViolation):
        PythonCodeGuard().validate(code, {})


@pytest.mark.parametrize(
    "datasets",
    [
        {"api_key": "plain"},
        {"nested": {"database_url": "plain"}},
        {"value": "postgresql://user:password@host/db"},
        {"value": "Bearer abcdefghijklmnopqrstuvwxyz"},
        {"value": "sk_abcdefghijklmnopqrstuvwxyz123456"},
    ],
)
def test_guard_denies_secret_shaped_datasets(datasets):
    with pytest.raises(SandboxPolicyViolation) as caught:
        PythonCodeGuard().validate("result = 1", datasets)
    assert caught.value.code == "SANDBOX_SECRET_INPUT"


def test_guard_enforces_code_dataset_and_ast_limits():
    tiny = SandboxLimits(max_code_bytes=8, max_dataset_bytes=8, max_ast_nodes=5)
    guard = PythonCodeGuard(tiny)
    with pytest.raises(SandboxPolicyViolation):
        guard.validate("result = 123456", {})
    with pytest.raises(SandboxPolicyViolation):
        guard.validate("x=1", {"rows": [1, 2, 3]})
    with pytest.raises(SandboxPolicyViolation):
        guard.validate("x=1\ny=2", {})


@pytest.mark.parametrize("value", [object(), float("nan"), float("inf")])
def test_guard_rejects_non_json_or_non_finite_dataset_values(value):
    with pytest.raises(SandboxPolicyViolation) as caught:
        PythonCodeGuard().validate("result = 1", {"value": value})
    assert caught.value.code == "SANDBOX_DATASET_TYPE"


def test_worker_spec_has_no_network_mount_secret_or_privilege_and_has_limits():
    limits = SandboxLimits()
    kwargs = DockerWorkerSpec().create_kwargs(
        job_id="safejob", limits=limits, command=["tail", "-f", "/dev/null"]
    )
    DockerWorkerSpec.assert_hardened(kwargs)
    assert kwargs["use_config_proxy"] is False
    assert kwargs["network_disabled"] is True
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["user"] == "65532:65532"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["pids_limit"] == limits.pids_limit
    assert kwargs["mem_limit"] == kwargs["memswap_limit"] == limits.memory_bytes
    assert kwargs["nano_cpus"] == limits.nano_cpus
    assert set(kwargs["tmpfs"]) == {"/tmp", "/workspace"}
    assert not ({"mounts", "volumes", "ports", "devices", "privileged"} & kwargs.keys())
    assert not any(
        token in key.upper()
        for key in kwargs["environment"]
        for token in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE", "CHATBI")
    )


def test_worker_spec_assertion_fails_for_network_or_mount_regression():
    limits = SandboxLimits()
    spec = DockerWorkerSpec()
    kwargs = spec.create_kwargs(job_id="bad", limits=limits, command=["true"])
    kwargs["network_disabled"] = False
    with pytest.raises(ValueError):
        spec.assert_hardened(kwargs)
    kwargs = spec.create_kwargs(job_id="bad2", limits=limits, command=["true"])
    kwargs["mounts"] = ["host:/workspace"]
    with pytest.raises(ValueError):
        spec.assert_hardened(kwargs)


class FakeContainer:
    def __init__(self, response: bytes, *, remove_fails: bool = False, block: bool = False):
        self.id = "container-123"
        self.response = response
        self.remove_fails = remove_fails
        self.block = block
        self.killed = threading.Event()
        self.removed = False
        self.started = False
        self.exec_environment = None

    def start(self):
        self.started = True

    def exec_run(self, command, demux=False, environment=None):
        self.exec_environment = environment
        if self.block:
            self.killed.wait(2)
        return SimpleNamespace(exit_code=0, output=self.response)

    def kill(self):
        self.killed.set()

    def remove(self, force=False):
        if self.remove_fails:
            raise RuntimeError("remove failed")
        self.removed = True
        self.killed.set()


class FakeContainers:
    def __init__(self, container):
        self.container = container
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self.container

    def get(self, container_id):
        if self.container.removed:
            raise NotFound(container_id)
        return self.container


class NotFound(Exception):
    status_code = 404


class FakeClient:
    def __init__(self, container, *, ping_fails=False):
        self.containers = FakeContainers(container)
        self.ping_fails = ping_fails

    def ping(self):
        if self.ping_fails:
            raise RuntimeError("daemon unavailable")
        return True


def success_payload(output=7):
    return json.dumps(
        {
            "status": "SUCCEEDED",
            "output": output,
            "stdout": "ok",
            "stderr": "",
            "artifacts": [],
        }
    ).encode()


def controller_result_payload(status="SUCCEEDED", **overrides):
    payload = {
        "status": status,
        "output": 7,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "artifacts": [],
        "error_code": None,
        "duration_ms": 5,
        "container_id": "container-remote",
        "container_destroyed": True,
        "runtime_verified": status == "SUCCEEDED",
        "trace_stages": ["python.execute.completed", "python.container.destroyed"],
        "security": {
            "network_disabled": True,
            "host_mounts": 0,
            "secrets_injected": 0,
        },
    }
    payload.update(overrides)
    return payload


def test_controller_client_sends_only_fixed_protocol_and_decodes_verified_result():
    calls = []
    job_id = "a" * 32

    def transport(method, path, payload, timeout):
        calls.append((method, path, payload, timeout))
        if method == "POST":
            return {
                "protocol_version": PROTOCOL_VERSION,
                "job_id": job_id,
                "state": "RUNNING",
            }
        return {
            "protocol_version": PROTOCOL_VERSION,
            "job_id": job_id,
            "state": "COMPLETED",
            "result": controller_result_payload(),
        }

    result = DockerSandboxExecutor(
        controller_url="http://localhost:18765",
        controller_transport=transport,
        client_factory=lambda: pytest.fail("Backend must not open Docker"),
    ).execute("result = sum(datasets['values'])", {"values": [3, 4]})

    assert result.status is SandboxStatus.SUCCEEDED
    assert result.runtime_verified and result.container_destroyed
    assert result.security["controller_protocol"] == PROTOCOL_VERSION
    submitted = calls[0][2]
    assert set(submitted) == {"protocol_version", "code", "datasets", "timeout_ms"}
    assert not ({"image", "command", "environment", "mounts", "network"} & submitted.keys())


def test_controller_unavailable_fails_closed_without_local_docker_fallback():
    def unavailable(method, path, payload, timeout):
        raise OSError("controller unavailable")

    result = DockerSandboxExecutor(
        controller_url="http://localhost:18765",
        controller_transport=unavailable,
        client_factory=lambda: pytest.fail("local Docker fallback is forbidden"),
    ).execute("result = 1", {})
    assert result.status is SandboxStatus.UNAVAILABLE
    assert result.error_code == "SANDBOX_CONTROLLER_UNAVAILABLE"
    assert not result.runtime_verified


def test_controller_url_is_fixed_allowlist_and_invalid_url_fails_closed():
    result = DockerSandboxExecutor(
        controller_url="https://attacker.invalid/controller",
        client_factory=lambda: pytest.fail("local Docker fallback is forbidden"),
    ).execute("result = 1", {})
    assert result.status is SandboxStatus.UNAVAILABLE
    assert result.error_code == "SANDBOX_CONTROLLER_URL_DENIED"


def test_controller_cancel_protocol_waits_for_destroyed_result():
    calls = []
    cancellation = threading.Event()
    job_id = "b" * 32

    def transport(method, path, payload, timeout):
        calls.append(method)
        if method == "POST":
            cancellation.set()
            return {
                "protocol_version": PROTOCOL_VERSION,
                "job_id": job_id,
                "state": "RUNNING",
            }
        if method == "DELETE":
            return {
                "protocol_version": PROTOCOL_VERSION,
                "job_id": job_id,
                "state": "RUNNING",
            }
        return {
            "protocol_version": PROTOCOL_VERSION,
            "job_id": job_id,
            "state": "COMPLETED",
            "result": controller_result_payload(
                "CANCELLED",
                output=None,
                error_code="SANDBOX_CANCELLED",
                runtime_verified=False,
            ),
        }

    result = DockerSandboxExecutor(
        controller_url="http://localhost:18765",
        controller_transport=transport,
    ).execute("result = 1", {}, cancellation_event=cancellation)
    assert result.status is SandboxStatus.CANCELLED
    assert result.container_destroyed
    assert "DELETE" in calls


@pytest.mark.parametrize("field", ["image", "command", "mounts", "environment"])
def test_controller_request_schema_rejects_worker_spec_overrides(field):
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "code": "result = 1",
        "datasets": {},
        "timeout_ms": 1000,
        field: "attacker-controlled",
    }
    with pytest.raises(ControllerRequestError) as caught:
        _validate_job_payload(payload)
    assert caught.value.error_code == "SANDBOX_REQUEST_FIELDS_DENIED"


def test_job_registry_propagates_cancel_to_executor_and_returns_destroy_proof():
    started = threading.Event()

    class ControlledExecutor:
        def execute(self, code, datasets, *, cancellation_event=None, **kwargs):
            started.set()
            assert cancellation_event.wait(1)
            return SandboxResult(
                status=SandboxStatus.CANCELLED,
                error_code="SANDBOX_CANCELLED",
                container_id="controlled-worker",
                container_destroyed=True,
                trace_stages=("python.cancelled", "python.container.destroyed"),
            )

    registry = JobRegistry(executor_factory=lambda limits: ControlledExecutor())
    job_id = registry.submit(
        {
            "protocol_version": PROTOCOL_VERSION,
            "code": "while True:\n    pass",
            "datasets": {},
            "timeout_ms": 1000,
        }
    )
    assert started.wait(1)
    assert registry.snapshot()["running_jobs"] == 1
    registry.cancel(job_id)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = registry.get(job_id)
        if response["state"] == "COMPLETED":
            break
        time.sleep(0.01)
    assert response["result"]["status"] == SandboxStatus.CANCELLED
    assert response["result"]["container_destroyed"] is True
    assert registry.snapshot() == {
        "registered_jobs": 1,
        "running_jobs": 0,
        "completed_jobs": 1,
    }
    registry.shutdown()


def test_compose_backend_has_no_docker_socket_and_controller_is_private_fixed_boundary():
    import yaml

    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    backend = services["backend"]
    controller = services["sandbox-controller"]
    proxy = services["sandbox-docker-proxy"]
    backend_mounts = json.dumps(backend.get("volumes") or [])
    assert "docker.sock" not in backend_mounts
    assert backend["environment"]["CHATBI_SANDBOX_CONTROLLER_URL"] == (
        "http://sandbox-controller:8765"
    )
    assert backend["depends_on"]["sandbox-controller"]["condition"] == "service_healthy"
    assert controller["image"] == DockerWorkerSpec().image
    assert "volumes" not in controller
    assert "ports" not in controller
    assert controller["user"] == "65532:65532"
    assert controller["environment"] == {
        "DOCKER_HOST": "tcp://sandbox-docker-proxy:2375"
    }
    assert controller["networks"] == ["sandbox-control", "sandbox-docker-control"]
    assert controller["depends_on"]["sandbox-docker-proxy"]["condition"] == "service_healthy"
    assert compose["networks"]["sandbox-control"]["internal"] is True
    assert compose["networks"]["sandbox-docker-control"]["internal"] is True
    assert controller["read_only"] is True
    assert controller["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in controller["security_opt"]
    assert "ports" not in proxy
    assert proxy["networks"] == ["sandbox-docker-control"]
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in proxy["security_opt"]
    assert proxy["volumes"] == [
        {
            "type": "bind",
            "source": "${CHATBI_DOCKER_SOCKET_PATH:-/var/run/docker.sock}",
            "target": "/var/run/docker.sock",
            "read_only": True,
        }
    ]
    socket_services = [
        name
        for name, service in services.items()
        if "docker.sock" in json.dumps(service.get("volumes") or [])
    ]
    assert socket_services == ["sandbox-docker-proxy"]


def test_missing_docker_fails_closed_as_unavailable():
    container = FakeContainer(success_payload())
    result = DockerSandboxExecutor(
        client_factory=lambda: FakeClient(container, ping_fails=True)
    ).execute("result = 1", {})
    assert result.status is SandboxStatus.UNAVAILABLE
    assert result.error_code == "SANDBOX_DOCKER_UNAVAILABLE"
    assert not result.runtime_verified
    assert not result.container_destroyed


def test_fake_runtime_success_proves_spec_and_synchronous_destroy_contract():
    container = FakeContainer(success_payload({"sum": 7}))
    client = FakeClient(container)
    result = DockerSandboxExecutor(client_factory=lambda: client).execute(
        "result = sum(datasets['values'])", {"values": [3, 4]}
    )
    assert result.status is SandboxStatus.SUCCEEDED
    assert result.output == {"sum": 7}
    assert result.runtime_verified
    assert result.container_destroyed
    assert container.removed
    assert container.exec_environment
    assert container.exec_environment[0].startswith("SANDBOX_REQUEST_B64=")
    assert "result = sum" not in container.exec_environment[0]
    DockerWorkerSpec.assert_hardened(client.containers.create_kwargs)
    assert result.trace_stages[-1] == "python.container.destroyed"


def test_timeout_kills_and_synchronously_destroys_container():
    container = FakeContainer(success_payload(), block=True)
    client = FakeClient(container)
    executor = DockerSandboxExecutor(
        limits=SandboxLimits(timeout_seconds=0.02),
        client_factory=lambda: client,
        poll_interval=0.005,
    )
    result = executor.execute("result = 1", {})
    assert result.status is SandboxStatus.TIMEOUT
    assert result.error_code == "SANDBOX_TIMEOUT"
    assert container.killed.is_set()
    assert container.removed
    assert result.container_destroyed
    assert not result.runtime_verified


def test_pre_cancelled_execution_never_creates_container():
    cancellation = threading.Event()
    cancellation.set()
    result = DockerSandboxExecutor(
        client_factory=lambda: pytest.fail("Docker client must not be created")
    ).execute("result = 1", {}, cancellation_event=cancellation)
    assert result.status is SandboxStatus.CANCELLED
    assert result.error_code == "SANDBOX_CANCELLED"


def test_live_cancellation_kills_and_destroys_container():
    cancellation = threading.Event()
    container = FakeContainer(success_payload(), block=True)
    client = FakeClient(container)
    timer = threading.Timer(0.02, cancellation.set)
    timer.start()
    try:
        result = DockerSandboxExecutor(
            client_factory=lambda: client, poll_interval=0.005
        ).execute("result = 1", {}, cancellation_event=cancellation)
    finally:
        timer.cancel()
    assert result.status is SandboxStatus.CANCELLED
    assert container.killed.is_set()
    assert container.removed
    assert result.container_destroyed


def test_destroy_failure_overrides_success_and_is_never_reported_verified():
    container = FakeContainer(success_payload(), remove_fails=True)
    result = DockerSandboxExecutor(
        client_factory=lambda: FakeClient(container)
    ).execute("result = 1", {})
    assert result.status is SandboxStatus.FAILED
    assert result.error_code == "SANDBOX_DESTROY_FAILED"
    assert not result.container_destroyed
    assert not result.runtime_verified


def test_output_limit_is_enforced_before_decoding():
    limits = SandboxLimits(max_output_bytes=32)
    container = FakeContainer(b"x" * 33)
    result = DockerSandboxExecutor(
        limits=limits, client_factory=lambda: FakeClient(container)
    ).execute("result = 1", {})
    assert result.status is SandboxStatus.FAILED
    assert result.error_code == "SANDBOX_OUTPUT_LIMIT"
    assert container.removed


def test_worker_report_exposes_output_truncation_flags():
    payload = json.dumps(
        {
            "status": "SUCCEEDED",
            "output": 1,
            "stdout": "bounded",
            "stderr": "",
            "stdout_truncated": True,
            "stderr_truncated": False,
            "artifacts": [],
        }
    ).encode()
    result = DockerSandboxExecutor(
        client_factory=lambda: FakeClient(FakeContainer(payload))
    ).execute("result = 1", {})
    assert result.status is SandboxStatus.SUCCEEDED
    assert result.stdout_truncated
    assert not result.stderr_truncated


@pytest.mark.skipif(
    os.getenv("CHATBI_TEST_REAL_DOCKER") != "1",
    reason="set CHATBI_TEST_REAL_DOCKER=1 after building chatbi-sandbox-runtime:phase3",
)
def test_real_docker_worker_or_fail_not_fake_pass():
    result = DockerSandboxExecutor().execute(
        "result = sum(datasets['values'])", {"values": [2, 5]}
    )
    assert result.status is SandboxStatus.SUCCEEDED, result
    assert result.output == 7
    assert result.runtime_verified
    assert result.container_destroyed


@pytest.mark.skipif(
    os.getenv("CHATBI_TEST_REAL_DOCKER") != "1",
    reason="set CHATBI_TEST_REAL_DOCKER=1 after building chatbi-sandbox-runtime:phase3",
)
def test_real_docker_attacks_limits_engine_spec_and_destroy_proof():
    import docker

    real_client = docker.from_env()
    engine_specs = []

    class RecordingContainers:
        def create(self, **kwargs):
            container = real_client.containers.create(**kwargs)
            container.reload()
            engine_specs.append(container.attrs)
            return container

        def get(self, container_id):
            return real_client.containers.get(container_id)

    recording_client = SimpleNamespace(
        ping=real_client.ping,
        containers=RecordingContainers(),
    )
    executor = DockerSandboxExecutor(client_factory=lambda: recording_client)

    network_attack = executor.execute("import socket\nresult = socket.socket()", {})
    file_attack = executor.execute("result = open('/etc/passwd').read()", {})
    artifact_attack = executor.execute(
        "result = save_artifact('oversized.bin', b'x' * 65537)", {}
    )
    output_attack = executor.execute("print('x' * 400000)\nresult = 1", {})
    timeout_attack = DockerSandboxExecutor(
        limits=SandboxLimits(timeout_seconds=0.05),
        client_factory=lambda: recording_client,
        poll_interval=0.005,
    ).execute("while True:\n    pass", {})

    assert network_attack.status is SandboxStatus.REFUSED
    assert network_attack.error_code == "SANDBOX_IMPORT_DENIED"
    assert file_attack.status is SandboxStatus.REFUSED
    assert file_attack.error_code == "SANDBOX_API_DENIED"
    assert artifact_attack.status is SandboxStatus.FAILED
    assert artifact_attack.error_code == "SANDBOX_CODE_FAILED"
    assert artifact_attack.container_destroyed
    assert output_attack.status is SandboxStatus.SUCCEEDED
    assert output_attack.stdout_truncated
    assert len(output_attack.stdout.encode()) <= executor.limits.max_output_bytes // 2
    assert output_attack.container_destroyed
    assert timeout_attack.status is SandboxStatus.TIMEOUT
    assert timeout_attack.container_destroyed
    assert not timeout_attack.runtime_verified

    assert len(engine_specs) == 3
    for attrs in engine_specs:
        config = attrs["Config"]
        host = attrs["HostConfig"]
        assert config["NetworkDisabled"] is True
        assert host["NetworkMode"] == "none"
        assert config["User"] == "65532:65532"
        inherited_public_names = {"GPG_KEY"}
        assert not any(
            token in name.upper() and name not in inherited_public_names
            for item in config["Env"]
            for name in [item.split("=", 1)[0]]
            for token in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE", "CHATBI")
        )
        assert host["ReadonlyRootfs"] is True
        assert not host.get("Binds")
        assert host["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert host["PidsLimit"] == executor.limits.pids_limit
        assert host["Memory"] == executor.limits.memory_bytes
        assert host["MemorySwap"] == executor.limits.memory_bytes
        assert host["NanoCpus"] == executor.limits.nano_cpus
        assert set(host["Tmpfs"]) == {"/tmp", "/workspace"}

    assert not real_client.containers.list(
        all=True, filters={"label": "com.chatbi.sandbox=true"}
    )


@pytest.mark.skipif(
    os.getenv("CHATBI_TEST_REAL_SANDBOX_CONTROLLER") != "1",
    reason="set CHATBI_TEST_REAL_SANDBOX_CONTROLLER=1 and controller URL",
)
def test_real_sandbox_controller_protocol_success_cancel_and_destroy():
    url = os.environ["CHATBI_TEST_SANDBOX_CONTROLLER_URL"]
    executor = DockerSandboxExecutor(controller_url=url)
    success = executor.execute("result = sum(datasets['values'])", {"values": [4, 5]})
    assert success.status is SandboxStatus.SUCCEEDED
    assert success.output == 9
    assert success.runtime_verified and success.container_destroyed
    assert success.security["controller_protocol"] == PROTOCOL_VERSION

    cancellation = threading.Event()
    timer = threading.Timer(0.05, cancellation.set)
    timer.start()
    try:
        cancelled = executor.execute(
            "while True:\n    pass", {}, cancellation_event=cancellation
        )
    finally:
        timer.cancel()
    assert cancelled.status is SandboxStatus.CANCELLED
    assert cancelled.container_destroyed
    assert not cancelled.runtime_verified
