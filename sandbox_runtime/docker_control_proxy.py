from __future__ import annotations

import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit


MAX_HEADER_BYTES = 32 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
WORKER_IMAGE = os.environ.get("CHATBI_SANDBOX_WORKER_IMAGE", "chatbi-sandbox-runtime:phase3")
WORKER_USER = "65532:65532"
WORKER_COMMAND = ["tail", "-f", "/dev/null"]
EXEC_COMMAND = ["python", "/opt/chatbi/sandbox_runner.py"]
CONTAINER_NAME = re.compile(r"^chatbi_sandbox_([0-9a-f]{32})$")
CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")
EXEC_ID = re.compile(r"^[0-9a-f]{12,64}$")
API_PREFIX = re.compile(r"^/v[0-9]+(?:\.[0-9]+)?(?=/)")
SECRET_ENV = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|DATABASE|CHATBI)", re.I)
REQUEST_ENV = re.compile(r"^SANDBOX_REQUEST_B64=([A-Za-z0-9+/=]{1,2097152})$")
CREATE_KEYS = {
    "User", "Tty", "OpenStdin", "StdinOnce", "AttachStdin", "AttachStdout",
    "AttachStderr", "Env", "Cmd", "Image", "NetworkDisabled", "WorkingDir",
    "HostConfig", "Labels",
}
HOST_CONFIG_KEYS = {
    "Memory", "MemorySwap", "ReadonlyRootfs", "NetworkMode", "CapDrop",
    "SecurityOpt", "Tmpfs", "PidsLimit", "NanoCpus",
}
EXEC_CREATE_KEYS = {
    "Container", "User", "Privileged", "Tty", "AttachStdin", "AttachStdout",
    "AttachStderr", "Cmd", "Env",
}
MAX_PIDS = 32
MAX_MEMORY = 512 * 1024 * 1024
MAX_NANO_CPUS = 1_000_000_000
MAX_TMPFS_BYTES = {"/tmp": 8 * 1024 * 1024, "/workspace": 16 * 1024 * 1024}


class PolicyDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerRequest:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes

    @property
    def path(self) -> str:
        return API_PREFIX.sub("", urlsplit(self.target).path)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.target).query, keep_blank_values=True)

    def json_body(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PolicyDenied("invalid JSON request") from exc
        if not isinstance(payload, dict):
            raise PolicyDenied("Docker request body must be an object")
        return payload


class DockerControlPolicy:
    """Stateful least-privilege policy for the Sandbox controller's Docker calls."""

    def __init__(self) -> None:
        self._containers: set[str] = set()
        self._execs: set[str] = set()
        self._lock = threading.Lock()

    def authorize(self, request: DockerRequest) -> str:
        method = request.method
        path = request.path
        if method == "GET" and path in {"/_ping", "/version"}:
            return "metadata"
        if method == "GET" and path.startswith("/images/") and path.endswith("/json"):
            image = unquote(path[len("/images/") : -len("/json")]).strip("/")
            if image != WORKER_IMAGE:
                raise PolicyDenied("image is not allowlisted")
            return "image-inspect"
        if method == "GET" and path == "/containers/json":
            self._validate_orphan_list(request)
            return "container-list"
        if method == "POST" and path == "/containers/create":
            self._validate_create(request)
            return "container-create"

        container_match = re.fullmatch(
            r"/containers/([0-9a-f]{12,64})(?:/(start|kill|exec|json))?", path
        )
        if container_match:
            container_id, operation = container_match.groups()
            self._require_container(container_id)
            if method == "POST" and operation == "start" and not request.body:
                return "container-start"
            if method == "POST" and operation == "kill":
                if set(request.query) - {"signal"}:
                    raise PolicyDenied("kill query is not allowlisted")
                signal = request.query.get("signal", ["SIGKILL"])
                if signal not in (["SIGKILL"], ["KILL"]):
                    raise PolicyDenied("kill signal is not allowlisted")
                return "container-kill"
            if method == "POST" and operation == "exec":
                self._validate_exec_create(request, container_id)
                return "exec-create"
            if method == "GET" and operation in {None, "json"}:
                return "container-inspect"

        delete_match = re.fullmatch(r"/containers/([0-9a-f]{12,64})", path)
        if method == "DELETE" and delete_match:
            self._require_container(delete_match.group(1))
            allowed = {"force", "v", "link"}
            if set(request.query) - allowed:
                raise PolicyDenied("delete query is not allowlisted")
            if request.query.get("force") not in (["1"], ["true"], ["True"]):
                raise PolicyDenied("synchronous force removal is required")
            for key in ("v", "link"):
                if request.query.get(key, ["0"]) not in (["0"], ["false"], ["False"]):
                    raise PolicyDenied("volume/link removal options are denied")
            return "container-delete"

        exec_match = re.fullmatch(r"/exec/([0-9a-f]{12,64})/(start|json)", path)
        if exec_match:
            exec_id, operation = exec_match.groups()
            self._require_exec(exec_id)
            if method == "POST" and operation == "start":
                body = request.json_body()
                if body != {"Detach": False, "Tty": False}:
                    raise PolicyDenied("exec start options are not allowlisted")
                return "exec-start"
            if method == "GET" and operation == "json":
                return "exec-inspect"

        raise PolicyDenied("Docker API operation is not allowlisted")

    def observe_response(self, operation: str, response: bytes) -> None:
        status, body = _response_status_and_body(response)
        if status >= 400:
            return
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, ValueError):
            return
        if operation == "container-create" and isinstance(payload, dict):
            container_id = str(payload.get("Id") or "")
            if CONTAINER_ID.fullmatch(container_id):
                with self._lock:
                    self._containers.add(container_id)
        elif operation == "container-list" and isinstance(payload, list):
            discovered = {
                str(item.get("Id"))
                for item in payload
                if isinstance(item, dict)
                and item.get("Labels", {}).get("com.chatbi.sandbox") == "true"
                and CONTAINER_ID.fullmatch(str(item.get("Id") or ""))
            }
            with self._lock:
                self._containers.update(discovered)
        elif operation == "exec-create" and isinstance(payload, dict):
            exec_id = str(payload.get("Id") or "")
            if EXEC_ID.fullmatch(exec_id):
                with self._lock:
                    self._execs.add(exec_id)

    def _validate_orphan_list(self, request: DockerRequest) -> None:
        if set(request.query) - {"all", "filters", "limit", "size", "trunc_cmd"}:
            raise PolicyDenied("container list query is not allowlisted")
        if request.query.get("all") not in (["1"], ["true"], ["True"]):
            raise PolicyDenied("only all-container orphan cleanup is allowed")
        if request.query.get("limit", ["-1"]) != ["-1"]:
            raise PolicyDenied("container list limit is not allowlisted")
        if request.query.get("size", ["0"]) not in (["0"], ["false"], ["False"]):
            raise PolicyDenied("container list size expansion is denied")
        if request.query.get("trunc_cmd", ["0"]) not in (["0"], ["false"], ["False"]):
            raise PolicyDenied("container list command expansion is denied")
        raw_filters = request.query.get("filters")
        if not raw_filters or len(raw_filters) != 1:
            raise PolicyDenied("sandbox label filter is required")
        try:
            filters = json.loads(raw_filters[0])
        except ValueError as exc:
            raise PolicyDenied("invalid container label filter") from exc
        labels = filters.get("label") if isinstance(filters, dict) else None
        if labels not in (["com.chatbi.sandbox=true"], {"com.chatbi.sandbox=true": True}):
            raise PolicyDenied("container list must be restricted to sandbox labels")

    def _validate_create(self, request: DockerRequest) -> None:
        if set(request.query) != {"name"}:
            raise PolicyDenied("worker create query fields differ from the exact allowlist")
        query_name = request.query.get("name", [""])
        if len(query_name) != 1:
            raise PolicyDenied("worker name is required")
        name_match = CONTAINER_NAME.fullmatch(query_name[0])
        if not name_match:
            raise PolicyDenied("worker name is not allowlisted")
        body = request.json_body()
        if set(body) != CREATE_KEYS:
            missing = sorted(CREATE_KEYS - set(body))
            unknown = sorted(set(body) - CREATE_KEYS)
            raise PolicyDenied(
                f"worker create fields differ from the exact allowlist; "
                f"missing={missing!r}; unknown={unknown!r}"
            )
        labels = body.get("Labels") or {}
        if labels != {
            "com.chatbi.sandbox": "true",
            "com.chatbi.sandbox.job_id": name_match.group(1),
        }:
            raise PolicyDenied("worker labels are not allowlisted")
        expected = {
            "Image": WORKER_IMAGE,
            "Cmd": WORKER_COMMAND,
            "User": WORKER_USER,
            "WorkingDir": "/workspace",
        }
        if any(body.get(key) != value for key, value in expected.items()):
            raise PolicyDenied("worker identity or command is not allowlisted")
        exact_defaults = {
            "Tty": False,
            "OpenStdin": False,
            "StdinOnce": False,
            "AttachStdin": False,
            "AttachStdout": False,
            "AttachStderr": False,
            "NetworkDisabled": True,
        }
        if any(body.get(key) != value for key, value in exact_defaults.items()):
            raise PolicyDenied("worker top-level defaults differ from the exact policy")
        env = body.get("Env") or []
        if not isinstance(env, list) or any(
            not isinstance(item, str)
            or "=" not in item
            or SECRET_ENV.search(item.split("=", 1)[0])
            for item in env
        ):
            raise PolicyDenied("worker environment is not allowlisted")
        allowed_env = {
            "LANG=C.UTF-8",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONHASHSEED=0",
            "PYTHONUNBUFFERED=1",
        }
        if set(env) != allowed_env:
            raise PolicyDenied("worker environment differs from the fixed policy")
        host = body.get("HostConfig")
        if not isinstance(host, dict):
            raise PolicyDenied("worker HostConfig is required")
        if set(host) != HOST_CONFIG_KEYS:
            missing = sorted(HOST_CONFIG_KEYS - set(host))
            unknown = sorted(set(host) - HOST_CONFIG_KEYS)
            raise PolicyDenied(
                f"worker HostConfig fields differ from the exact allowlist; "
                f"missing={missing!r}; unknown={unknown!r}"
            )
        if host.get("NetworkMode") != "none" or host.get("ReadonlyRootfs") is not True:
            raise PolicyDenied("worker network/root filesystem is not isolated")
        if host.get("CapDrop") != ["ALL"]:
            raise PolicyDenied("worker capabilities are not fully dropped")
        if host.get("SecurityOpt") != ["no-new-privileges:true"]:
            raise PolicyDenied("worker no-new-privileges is required")
        ceilings = {"PidsLimit": MAX_PIDS, "Memory": MAX_MEMORY, "NanoCpus": MAX_NANO_CPUS}
        for key, ceiling in ceilings.items():
            value = host.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= ceiling:
                raise PolicyDenied("worker resource limit is missing or exceeds the ceiling")
        if isinstance(host.get("MemorySwap"), bool) or not isinstance(host.get("MemorySwap"), int):
            raise PolicyDenied("worker swap limit is invalid")
        if host["Memory"] != host["MemorySwap"]:
            raise PolicyDenied("worker swap must not exceed memory")
        tmpfs = host.get("Tmpfs") or {}
        if set(tmpfs) != {"/tmp", "/workspace"}:
            raise PolicyDenied("worker tmpfs policy is not bounded")
        for path, options in tmpfs.items():
            _validate_tmpfs_options(path, options)

    def _validate_exec_create(self, request: DockerRequest, container_id: str) -> None:
        body = request.json_body()
        if set(body) != EXEC_CREATE_KEYS:
            raise PolicyDenied("exec fields differ from the exact allowlist")
        if str(body.get("Container") or "") != container_id:
            raise PolicyDenied("exec container identity does not match the path")
        if body.get("Cmd") != EXEC_COMMAND:
            raise PolicyDenied("exec command is not allowlisted")
        env = body.get("Env") or []
        if not isinstance(env, list) or len(env) != 1 or not REQUEST_ENV.fullmatch(str(env[0])):
            raise PolicyDenied("exec environment is not the bounded request payload")
        if body.get("User") not in ("", WORKER_USER):
            raise PolicyDenied("exec user is not allowlisted")
        if body.get("Privileged") is not False or body.get("Tty") is not False:
            raise PolicyDenied("privileged or TTY exec is forbidden")
        if body.get("AttachStdin") is not False or body.get("AttachStdout") is not True or body.get("AttachStderr") is not True:
            raise PolicyDenied("bounded output attachment is required")

    def _require_container(self, container_id: str) -> None:
        with self._lock:
            allowed = any(item.startswith(container_id) or container_id.startswith(item) for item in self._containers)
        if not allowed:
            raise PolicyDenied("container is not registered to this proxy")

    def _require_exec(self, exec_id: str) -> None:
        with self._lock:
            allowed = any(item.startswith(exec_id) or exec_id.startswith(item) for item in self._execs)
        if not allowed:
            raise PolicyDenied("exec is not registered to this proxy")


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            request, raw = _read_request(self.request)
            operation = self.server.policy.authorize(request)  # type: ignore[attr-defined]
            if operation == "exec-start":
                transferred = _stream_exec_start(raw, self.request)
                print(
                    json.dumps(
                        {"event": "docker_control", "operation": operation, "status": 101, "bytes": transferred},
                        separators=(",", ":"),
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                return
            response = _forward_to_docker(raw)
            self.server.policy.observe_response(operation, response)  # type: ignore[attr-defined]
            status, _ = _response_status_and_body(response)
            print(
                json.dumps(
                    {"event": "docker_control", "operation": operation, "status": status, "bytes": len(response)},
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
            self.request.sendall(response)
        except PolicyDenied as exc:
            print(
                json.dumps(
                    {"event": "docker_control_denied", "detail": str(exc)},
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
            self.request.sendall(_error_response(HTTPStatus.FORBIDDEN, "DOCKER_CONTROL_DENIED", str(exc)))
        except (OSError, ValueError) as exc:
            self.request.sendall(_error_response(HTTPStatus.BAD_GATEWAY, "DOCKER_CONTROL_UNAVAILABLE", type(exc).__name__))


class ThreadingDockerProxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], policy: DockerControlPolicy | None = None) -> None:
        self.policy = policy or DockerControlPolicy()
        super().__init__(address, _ProxyHandler)


def _read_request(client: socket.socket) -> tuple[DockerRequest, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = client.recv(8192)
        if not chunk:
            raise ValueError("incomplete HTTP request")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ValueError("HTTP header limit exceeded")
    header_end = data.index(b"\r\n\r\n") + 4
    header = bytes(data[:header_end])
    lines = header[:-4].split(b"\r\n")
    try:
        method, target, version = lines[0].decode("ascii").split(" ", 2)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid HTTP request line") from exc
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ValueError("unsupported HTTP version")
    headers: dict[str, str] = {}
    rewritten = [lines[0]]
    for line in lines[1:]:
        try:
            name, value = line.decode("latin-1").split(":", 1)
        except ValueError as exc:
            raise ValueError("invalid HTTP header") from exc
        lowered = name.strip().lower()
        if lowered in headers:
            raise ValueError("duplicate HTTP header")
        headers[lowered] = value.strip()
        if lowered not in {"connection", "proxy-connection"}:
            rewritten.append(line)
    if headers.get("transfer-encoding"):
        raise ValueError("chunked Docker control requests are denied")
    try:
        content_length = int(headers.get("content-length", "0"))
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if content_length < 0 or header_end + content_length > MAX_REQUEST_BYTES:
        raise ValueError("Docker control request limit exceeded")
    while len(data) < header_end + content_length:
        chunk = client.recv(min(8192, header_end + content_length - len(data)))
        if not chunk:
            raise ValueError("incomplete HTTP request body")
        data.extend(chunk)
    body = bytes(data[header_end : header_end + content_length])
    is_exec_start = bool(re.fullmatch(r"/v[0-9]+(?:\.[0-9]+)?/exec/[0-9a-f]{12,64}/start", urlsplit(target).path))
    if is_exec_start:
        if headers.get("upgrade", "").lower() != "tcp":
            raise ValueError("exec start requires the Docker TCP upgrade")
        rewritten.append(b"Connection: Upgrade")
    else:
        rewritten.append(b"Connection: close")
    rewritten.extend([b"", b""])
    raw = b"\r\n".join(rewritten) + body
    return DockerRequest(method.upper(), target, headers, body), raw


def _tmpfs_size(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([kmgt]?)b?", value, flags=re.I)
    if not match:
        raise PolicyDenied("worker tmpfs size value is invalid")
    multiplier = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    return int(match.group(1)) * multiplier[match.group(2).lower()]


def _validate_tmpfs_options(path: str, raw_options: Any) -> None:
    if not isinstance(raw_options, str) or raw_options != raw_options.lower():
        raise PolicyDenied(f"worker tmpfs options are not canonical for {path}")
    tokens = raw_options.split(",")
    if not tokens or any(not token for token in tokens):
        raise PolicyDenied(f"worker tmpfs options are invalid for {path}")
    parsed: dict[str, str | None] = {}
    for token in tokens:
        if "=" in token:
            if token.count("=") != 1:
                raise PolicyDenied(f"worker tmpfs assignment is invalid for {path}")
            key, value = token.split("=", 1)
            if not key or not value:
                raise PolicyDenied(f"worker tmpfs assignment is invalid for {path}")
        else:
            key, value = token, None
        if key in parsed:
            raise PolicyDenied(f"worker tmpfs option is duplicated for {path}")
        parsed[key] = value

    expected_keys = {"rw", "noexec", "nosuid", "nodev", "size", "mode"}
    if path == "/workspace":
        expected_keys.update({"uid", "gid"})
    if set(parsed) != expected_keys:
        raise PolicyDenied(f"worker tmpfs fields differ from the exact policy for {path}")
    for flag in ("rw", "noexec", "nosuid", "nodev"):
        if parsed[flag] is not None:
            raise PolicyDenied(f"worker tmpfs flag value is invalid for {path}")
    expected_values = (
        {"mode": "1777"}
        if path == "/tmp"
        else {"mode": "700", "uid": "65532", "gid": "65532"}
    )
    if any(parsed.get(key) != value for key, value in expected_values.items()):
        raise PolicyDenied(f"worker tmpfs identity/mode differs from the exact policy for {path}")
    size = _tmpfs_size(str(parsed["size"]))
    if size <= 0 or size > MAX_TMPFS_BYTES[path]:
        raise PolicyDenied(f"worker tmpfs exceeds the size ceiling for {path}")
    if path == "/tmp" and size != MAX_TMPFS_BYTES[path]:
        raise PolicyDenied("worker /tmp size differs from the exact policy")


def _forward_to_docker(raw_request: bytes) -> bytes:
    socket_path = os.getenv("CHATBI_DOCKER_SOCKET_PATH", "/var/run/docker.sock")
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    upstream.settimeout(30.0)
    try:
        upstream.connect(socket_path)
        upstream.sendall(raw_request)
        response = bytearray()
        while True:
            chunk = upstream.recv(64 * 1024)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > MAX_RESPONSE_BYTES:
                raise ValueError("Docker control response limit exceeded")
        if not response.startswith(b"HTTP/"):
            raise ValueError("invalid Docker response")
        return bytes(response)
    finally:
        upstream.close()


def _stream_exec_start(raw_request: bytes, client: socket.socket) -> int:
    """Relay a Docker hijack without buffering its payload behind the 101 header."""
    socket_path = os.getenv("CHATBI_DOCKER_SOCKET_PATH", "/var/run/docker.sock")
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    upstream.settimeout(30.0)
    transferred = 0
    try:
        upstream.connect(socket_path)
        upstream.sendall(raw_request)
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            chunk = upstream.recv(1)
            if not chunk:
                raise ValueError("incomplete Docker exec upgrade response")
            header.extend(chunk)
            if len(header) > MAX_HEADER_BYTES:
                raise ValueError("Docker exec upgrade header limit exceeded")
        status, _ = _response_status_and_body(bytes(header))
        if status != HTTPStatus.SWITCHING_PROTOCOLS:
            raise ValueError("Docker exec did not switch protocols")
        try:
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        client.sendall(header)
        transferred = len(header)
        # docker-py takes ownership of the raw TCP stream only after parsing
        # the 101 response.  Keep the first multiplexed frame out of its HTTP
        # reader buffer so no worker output is lost during that hand-off.
        time.sleep(0.01)
        while True:
            chunk = upstream.recv(64 * 1024)
            if not chunk:
                break
            transferred += len(chunk)
            if transferred > MAX_RESPONSE_BYTES:
                raise ValueError("Docker exec response limit exceeded")
            client.sendall(chunk)
        return transferred
    finally:
        upstream.close()


def _response_status_and_body(response: bytes) -> tuple[int, bytes]:
    try:
        header, body = response.split(b"\r\n\r\n", 1)
        status = int(header.split(b"\r\n", 1)[0].split()[1])
    except (ValueError, IndexError) as exc:
        raise ValueError("invalid Docker response") from exc
    if b"transfer-encoding: chunked" in header.lower():
        body = _decode_chunked(body)
    return status, body


def _decode_chunked(body: bytes) -> bytes:
    decoded = bytearray()
    offset = 0
    while True:
        line_end = body.find(b"\r\n", offset)
        if line_end < 0:
            raise ValueError("invalid chunked Docker response")
        size_text = body[offset:line_end].split(b";", 1)[0]
        size = int(size_text, 16)
        offset = line_end + 2
        if size == 0:
            return bytes(decoded)
        decoded.extend(body[offset : offset + size])
        offset += size + 2


def _error_response(status: HTTPStatus, code: str, detail: str) -> bytes:
    payload = json.dumps(
        {"message": detail, "error_code": code, "detail": detail},
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        f"HTTP/1.1 {status.value} {status.phrase}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n\r\n"
    ).encode("ascii") + payload


def main() -> None:
    host = os.getenv("CHATBI_DOCKER_PROXY_HOST", "0.0.0.0")
    port = int(os.getenv("CHATBI_DOCKER_PROXY_PORT", "2375"))
    with ThreadingDockerProxy((host, port)) as server:
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
