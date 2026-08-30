from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def proxy():
    return _load("phase5_docker_proxy", ROOT / "sandbox_runtime" / "docker_control_proxy.py")


@pytest.fixture(scope="module")
def gate():
    return _load(
        "phase5_security_supply_gate",
        ROOT / "backend" / "scripts" / "run_v13_phase5_security_supply_gate.py",
    )


@pytest.fixture(scope="module")
def sbom():
    return _load("phase5_sbom", ROOT / "scripts" / "phase5-generate-sbom.py")


def _request(proxy, method: str, target: str, body=None):
    encoded = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
    return proxy.DockerRequest(method, target, {"content-length": str(len(encoded))}, encoded)


def _safe_worker(proxy, job_id: str = "a" * 32):
    return {
        "Image": proxy.WORKER_IMAGE,
        "Cmd": proxy.WORKER_COMMAND,
        "User": proxy.WORKER_USER,
        "Tty": False,
        "OpenStdin": False,
        "StdinOnce": False,
        "AttachStdin": False,
        "AttachStdout": False,
        "AttachStderr": False,
        "WorkingDir": "/workspace",
        "NetworkDisabled": True,
        "Env": [
            "LANG=C.UTF-8",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONHASHSEED=0",
            "PYTHONUNBUFFERED=1",
        ],
        "Labels": {
            "com.chatbi.sandbox": "true",
            "com.chatbi.sandbox.job_id": job_id,
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 32,
            "Memory": 536870912,
            "MemorySwap": 536870912,
            "NanoCpus": 500000000,
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=8m,mode=1777",
                "/workspace": "rw,noexec,nosuid,nodev,size=16m,mode=700,uid=65532,gid=65532",
            },
        },
    }


def test_docker_proxy_allows_only_fixed_hardened_worker(proxy):
    job_id = "a" * 32
    policy = proxy.DockerControlPolicy()
    request = _request(
        proxy,
        "POST",
        f"/v1.47/containers/create?name=chatbi_sandbox_{job_id}",
        _safe_worker(proxy, job_id),
    )
    assert policy.authorize(request) == "container-create"

    for key, value in (("Image", "attacker:latest"), ("User", "0:0"), ("Cmd", ["sh"])):
        body = json.loads(json.dumps(_safe_worker(proxy, job_id)))
        body[key] = value
        with pytest.raises(proxy.PolicyDenied):
            policy.authorize(
                _request(
                    proxy,
                    "POST",
                    f"/v1.47/containers/create?name=chatbi_sandbox_{job_id}",
                    body,
                )
            )


def test_real_docker_sdk_serialized_create_shape_matches_exact_proxy_policy(proxy):
    import docker
    from docker.models.containers import _create_container_args

    from app.sandbox import DockerWorkerSpec, SandboxLimits

    job_id = "f" * 32
    kwargs = DockerWorkerSpec().create_kwargs(
        job_id=job_id,
        limits=SandboxLimits(),
        command=proxy.WORKER_COMMAND,
    )
    kwargs["version"] = "1.47"
    create_args = _create_container_args(kwargs)
    api = docker.APIClient(base_url="http://127.0.0.1:1", version="1.47")
    api.create_container_from_config = lambda config, name, platform: {
        "config": dict(config),
        "name": name,
    }
    serialized = api.create_container(**create_args)
    assert serialized["name"] == f"chatbi_sandbox_{job_id}"
    wire_config = {
        key: value for key, value in serialized["config"].items() if value is not None
    }
    assert proxy.DockerControlPolicy().authorize(
        _request(
            proxy,
            "POST",
            f"/v1.47/containers/create?name={serialized['name']}",
            wire_config,
        )
    ) == "container-create"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("Privileged", True),
        ("NetworkMode", "host"),
        ("Binds", ["/:/host"]),
        ("CapAdd", ["SYS_ADMIN"]),
        ("PortBindings", {"22/tcp": [{"HostPort": "22"}]}),
        ("Devices", [{"PathOnHost": "/dev/kvm"}]),
        ("PidMode", "host"),
        ("IpcMode", "host"),
        ("UTSMode", "host"),
        ("UsernsMode", "host"),
        ("SecurityOpt", ["no-new-privileges:true", "seccomp=unconfined"]),
        ("PidsLimit", 33),
        ("Memory", 536870913),
        ("NanoCpus", 1000000001),
    ],
)
def test_docker_proxy_denies_control_escape(proxy, key, value):
    job_id = "b" * 32
    body = _safe_worker(proxy, job_id)
    body["HostConfig"][key] = value
    with pytest.raises(proxy.PolicyDenied):
        proxy.DockerControlPolicy().authorize(
            _request(
                proxy,
                "POST",
                f"/v1.47/containers/create?name=chatbi_sandbox_{job_id}",
                body,
            )
        )


def test_docker_proxy_denies_entrypoint_unknown_field_and_oversized_tmpfs(proxy):
    job_id = "9" * 32
    for mutate in (
        lambda body: body.update({"Entrypoint": ["sh"]}),
        lambda body: body.update({"Unexpected": True}),
        lambda body: body["HostConfig"]["Tmpfs"].update(
            {"/workspace": "rw,noexec,nosuid,nodev,size=17m,mode=700"}
        ),
    ):
        body = _safe_worker(proxy, job_id)
        mutate(body)
        with pytest.raises(proxy.PolicyDenied):
            proxy.DockerControlPolicy().authorize(
                _request(
                    proxy,
                    "POST",
                    f"/v1.47/containers/create?name=chatbi_sandbox_{job_id}",
                    body,
                )
            )


@pytest.mark.parametrize(
    "options",
    [
        "rw,noexec,exec,nosuid,suid,nodev,dev,size=8m,size=1g,mode=1777",
        "rw,rw,noexec,nosuid,nodev,size=8m,mode=1777",
        "rw,noexec,nosuid,nodev,size=8m,size=8m,mode=1777",
        "rw,noexec,nosuid,nodev,shared,size=8m,mode=1777",
        "rw,noexec,nosuid,nodev,size=8m,mode=0777",
    ],
)
def test_docker_proxy_denies_tmpfs_conflicts_duplicates_and_unknowns(proxy, options):
    job_id = "8" * 32
    body = _safe_worker(proxy, job_id)
    body["HostConfig"]["Tmpfs"]["/tmp"] = options
    with pytest.raises(proxy.PolicyDenied):
        proxy.DockerControlPolicy().authorize(
            _request(
                proxy,
                "POST",
                f"/v1.47/containers/create?name=chatbi_sandbox_{job_id}",
                body,
            )
        )


def test_docker_proxy_denies_unknown_create_query_field(proxy):
    job_id = "7" * 32
    with pytest.raises(proxy.PolicyDenied):
        proxy.DockerControlPolicy().authorize(
            _request(
                proxy,
                "POST",
                f"/v1.47/containers/create?name=chatbi_sandbox_{job_id}&platform=linux%2Famd64",
                _safe_worker(proxy, job_id),
            )
        )


def test_docker_proxy_registers_only_its_container_and_exec_ids(proxy):
    policy = proxy.DockerControlPolicy()
    container_id = "c" * 64
    create_response = (
        b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(json.dumps({'Id': container_id}))}\r\n\r\n".encode()
        + json.dumps({"Id": container_id}).encode()
    )
    policy.observe_response("container-create", create_response)
    assert policy.authorize(_request(proxy, "POST", f"/v1.47/containers/{container_id}/start")) == "container-start"
    with pytest.raises(proxy.PolicyDenied):
        policy.authorize(_request(proxy, "POST", f"/v1.47/containers/{'d' * 64}/start"))

    exec_id = "e" * 64
    exec_response = (
        b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(json.dumps({'Id': exec_id}))}\r\n\r\n".encode()
        + json.dumps({"Id": exec_id}).encode()
    )
    policy.observe_response("exec-create", exec_response)
    assert policy.authorize(
        _request(proxy, "POST", f"/v1.47/exec/{exec_id}/start", {"Detach": False, "Tty": False})
    ) == "exec-start"


def test_docker_proxy_denies_generic_api_and_unfiltered_discovery(proxy):
    policy = proxy.DockerControlPolicy()
    with pytest.raises(proxy.PolicyDenied):
        policy.authorize(_request(proxy, "GET", "/v1.47/secrets"))
    with pytest.raises(proxy.PolicyDenied):
        policy.authorize(_request(proxy, "GET", "/v1.47/containers/json?all=1"))
    filters = json.dumps({"label": ["com.chatbi.sandbox=true"]})
    assert policy.authorize(
        _request(
            proxy,
            "GET",
            f"/v1.47/containers/json?limit=-1&all=1&size=0&trunc_cmd=0&filters={filters}",
        )
    ) == "container-list"


def test_compose_exposes_socket_only_to_private_restricted_proxy(gate):
    result = gate._compose_security()
    assert result["failures"] == []
    assert result["socket_exposed_services"] == ["sandbox-docker-proxy"]
    assert result["controller_non_root"] is True
    assert result["proxy_private"] is True
    assert result["docker_control_escape"] == 0


def test_all_requested_attack_surfaces_fail_closed(gate):
    result = gate.attack_matrix()
    assert result["surface_count"] == 11
    assert result["attack_case_count"] >= 30
    assert result["escape_count"] == 0
    assert result["all_passed"] is True
    assert set(result["surfaces"]) == {
        "sql",
        "rag",
        "image",
        "file",
        "agent",
        "share",
        "artifact",
        "env",
        "filesystem",
        "network",
        "docker",
    }


def test_supply_integrity_secret_actions_notices_and_deprecations(gate):
    policy = json.loads(gate.POLICY_PATH.read_text(encoding="utf-8"))
    secret = gate.secret_scan()
    dependencies = gate.dependency_integrity(policy)
    actions = gate.action_integrity(policy)
    notices = gate.notice_and_license_integrity(policy)
    deprecations = gate.deprecation_integrity()
    assert secret["secret_hit_count"] == 0, secret["hits"]
    assert secret["git_history_complete"] is True
    assert dependencies["failures"] == []
    assert dependencies["direct_sqlbot_calls"] == 0
    assert dependencies["pip_check_returncode"] == 0
    assert dependencies["release_wheel_pins"] == ["wheel==0.46.2"]
    assert dependencies["selected_dbgpt_aiohttp_requirements"] == ["aiohttp==3.14.3"]
    assert actions["failures"] == []
    assert actions["node20_action_uses"] == 0
    assert notices["failures"] == []
    assert notices["sqlbot_runtime_calls"] == 0
    assert deprecations["failures"] == []
    assert deprecations["starlette_httpx2_bridge"] == "PINNED"


def test_release_runtime_has_one_authoritative_patched_wheel_pin():
    hardening = (ROOT / "backend" / "requirements-runtime-hardening.txt").read_text(encoding="utf-8")
    entries = [
        line.strip() for line in hardening.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert [entry for entry in entries if entry.lower().startswith("wheel==")] == ["wheel==0.46.2"]
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir --upgrade -r requirements-runtime-hardening.txt" in dockerfile
    for workflow_name in ("v13-phase5-release-hardening.yml", "v21-eval-golden-feedback.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "pip install --upgrade -r backend/requirements-runtime-hardening.txt" in workflow


def test_secret_fixture_exception_is_credential_scoped_and_cannot_hide_real_secret(gate):
    pattern = re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mariadb)://[^\s:@/]+:[^\s@/]+@",
        re.I,
    )
    assert gate._credential_matches_are_placeholders(
        "postgresql://user:password@example.invalid/db", pattern
    )
    assert gate._credential_matches_are_placeholders(
        "postgresql://user:${CHATBI_PASSWORD}@localhost/db", pattern
    )
    unsafe = "postgresql://" + "admin:" + "real-secret@" + "db.internal/prod"
    assert not gate._credential_matches_are_placeholders(
        "example fixture " + unsafe, pattern
    )


def test_deterministic_sbom_and_license_gate(sbom, gate, tmp_path):
    inventory = [
        {"name": "FastAPI", "version": "0.140.8", "license": "MIT", "classifiers": []},
        {"name": "httpx2", "version": "2.12.0", "license": "BSD-3-Clause", "classifiers": []},
    ]
    policy = json.loads(sbom.POLICY_PATH.read_text(encoding="utf-8"))
    generated_at = sbom._timestamp(policy["source_date_epoch"])
    first = sbom.build_documents(
        inventory,
        ROOT / "frontend" / "package-lock.json",
        generated_at=generated_at,
        policy=policy,
    )
    second = sbom.build_documents(
        inventory,
        ROOT / "frontend" / "package-lock.json",
        generated_at=generated_at,
        policy=policy,
    )
    assert first[:2] == second[:2]
    cyclonedx_path = tmp_path / "chatbi.cdx.json"
    spdx_path = tmp_path / "chatbi.spdx.json"
    receipt_path = tmp_path / "sbom-receipt.json"
    cyclonedx_path.write_bytes(first[0])
    spdx_path.write_bytes(first[1])
    receipt = {
        **first[2],
        "deterministic": True,
        "cyclonedx_sha256": gate._file_sha256(cyclonedx_path),
        "spdx_sha256": gate._file_sha256(spdx_path),
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    check = gate.sbom_integrity(
        cyclonedx_path,
        spdx_path,
        receipt_path,
        audit_inventory_sha256=first[2]["backend_inventory_sha256"],
    )
    assert check["failures"] == []
    assert check["component_count"] > 100
    cyclonedx = json.loads(first[0])
    assert cyclonedx["metadata"]["component"]["version"] == "1.4.0"
    assert first[2]["unknown_or_denied_license_count"] == 0


def test_release_license_aliases_and_policy_cover_real_venv_metadata(sbom):
    legacy = sbom._legacy_module()
    expected = {
        "Apache 2": "Apache-2.0",
        "Apache 2.0": "Apache-2.0",
        "PSF": "PSF-2.0",
        "PSFL": "PSF-2.0",
        "LGPL": "LGPL-2.1-or-later",
        "3-Clause BSD License": "BSD-3-Clause",
        "BSD 3-Clause": "BSD-3-Clause",
        "BSD-3-Clause, Apache-2.0, dependency licenses": (
            "BSD-3-Clause AND Apache-2.0"
        ),
    }
    for raw, normalized in expected.items():
        assert legacy._normalise_license(raw, [], "pypdfium2") == normalized

    assert legacy._normalise_license(
        "",
        ["GNU Lesser General Public License v2 or later (LGPLv2+)"],
        "example",
    ) == "LGPL-2.1-or-later"
    assert legacy._normalise_license(
        "",
        ["Python Software Foundation License"],
        "example",
    ) == "PSF-2.0"

    policy = json.loads(sbom.POLICY_PATH.read_text(encoding="utf-8"))
    assert "Apache-2.0" in policy["allowed_license_ids"]
    assert "PSF-2.0" in policy["allowed_license_ids"]
    assert "LGPL-2.1-or-later" in policy["allowed_license_ids"]
    assert sbom._license_allowed("BSD-3-Clause AND Apache-2.0", policy)


def test_sbom_fails_closed_on_unknown_or_denied_license(sbom):
    policy = json.loads(sbom.POLICY_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="unknown or denied licenses"):
        sbom.build_documents(
            [{"name": "bad", "version": "1.0", "license": "GPL-3.0-only", "classifiers": []}],
            ROOT / "frontend" / "package-lock.json",
            generated_at=sbom._timestamp(policy["source_date_epoch"]),
            policy=policy,
        )


def test_sbom_container_inventory_name_is_strict(sbom):
    with pytest.raises(ValueError, match="container name"):
        sbom._load_inventory(None, None, "../../docker.sock")


def test_external_vulnerability_audit_json_is_never_trusted(gate, tmp_path):
    pip_path = tmp_path / "pip.json"
    npm_path = tmp_path / "npm.json"
    pip_path.write_text(json.dumps({"dependencies": [{"name": "safe", "vulns": []}]}), encoding="utf-8")
    npm_path.write_text(json.dumps({"metadata": {"vulnerabilities": {"total": 0}}}), encoding="utf-8")
    result = gate.external_audits(pip_path, npm_path)
    assert result["evidence_trust"] == "EXTERNAL_UNTRUSTED"
    assert result["failures"] == [
        "caller-supplied vulnerability audit JSON is EXTERNAL_UNTRUSTED"
    ]
    npm_path.write_text(json.dumps({"metadata": {"vulnerabilities": {"total": 1}}}), encoding="utf-8")
    assert gate.external_audits(pip_path, npm_path)["failures"]


def test_gate_generated_audits_bind_commands_tools_inventory_and_locks(
    gate, tmp_path, monkeypatch
):
    inventory = [
        {"name": "alpha", "version": "1.0", "license": "MIT", "classifiers": []},
        {"name": "beta", "version": "2.0", "license": "BSD", "classifiers": []},
    ]
    monkeypatch.setattr(gate, "_current_distribution_inventory", lambda: inventory)
    audit_prefix = tmp_path / "isolated-audit-venv"
    audit_python = audit_prefix / "bin" / "python"
    audit_python.parent.mkdir(parents=True)
    audit_python.write_text("isolated", encoding="utf-8")
    (audit_prefix / "pyvenv.cfg").write_text("home = isolated", encoding="utf-8")
    monkeypatch.setenv("CHATBI_PHASE5_AUDIT_PYTHON", str(audit_python))

    def fake_recorded(command, *, stdout_path=None, expose_stdout=False):
        if "pip_audit" in command and "--output" in command:
            output = Path(command[command.index("--output") + 1])
            output.write_text(
                json.dumps({"dependencies": [{"name": "alpha", "vulns": []}]}),
                encoding="utf-8",
            )
        elif "audit" in command:
            assert stdout_path is not None
            stdout_path.write_text(
                json.dumps({"metadata": {"vulnerabilities": {"total": 0}}}),
                encoding="utf-8",
            )
        record = {
            "command": command,
            "returncode": 0,
            "started_at": "2026-08-22T00:00:00Z",
            "completed_at": "2026-08-22T00:00:01Z",
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "stderr_sha256": "0" * 64,
        }
        if expose_stdout:
            record["stdout"] = "11.0.0"
        return record

    monkeypatch.setattr(gate, "_recorded_command", fake_recorded)
    result = gate.generated_audits(tmp_path)
    assert result["failures"] == []
    assert result["evidence_trust"] == "GENERATED_IN_GATE_PROCESS"
    assert result["python_distribution_count"] == 2
    assert result["pip_vulnerabilities"] == 0
    assert result["npm_vulnerabilities"] == 0
    receipt = json.loads((tmp_path / "audit-receipt.json").read_text(encoding="utf-8"))
    assert receipt["commands"]["pip"]["command"][1:3] == ["-m", "pip_audit"]
    assert "--path" in receipt["commands"]["pip"]["command"]
    assert Path(receipt["isolated_audit_python"]) == audit_python.absolute()
    assert Path(receipt["isolated_audit_prefix"]) == audit_prefix.absolute()
    assert Path(receipt["isolated_audit_prefix"]) != Path(sys.prefix).absolute()
    assert receipt["commands"]["npm"]["command"][-4:] == [
        "audit",
        "--prefix",
        "frontend",
        "--json",
    ]
    assert receipt["python_inventory_sha256"] == gate._inventory_sha256(inventory)
    assert set(receipt["input_hashes"]) == {
        "backend/requirements.txt",
        "backend/requirements-phase3-upstream.txt",
        "backend/requirements-runtime-hardening.txt",
        "sandbox_runtime/requirements.txt",
        "frontend/package-lock.json",
    }
