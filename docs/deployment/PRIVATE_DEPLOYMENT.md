# Private Deployment

Positioning: documented from the containerized architecture, not production certified.

## Supported topology

One Windows or Linux server provides:

- Docker Engine/Desktop and Compose;
- Git;
- the ChatBI Backend, governed RAG Runtime, Frontend, and restricted Sandbox services;
- network access to a PostgreSQL metadata database;
- network access from Backend to enterprise read-only business datasources.

PostgreSQL may be installed on the same host or managed separately. ChatBI Compose does not create a database container or database volume.

## Windows server

Follow [Quick Start](QUICK_START.md). Use an explicit secure environment file, a unique Compose project name, fixed ports, and a project-owned storage/backup directory. Configure firewall ingress only for the Frontend or an approved reverse proxy. Backend and RAG ports should remain internal when an external reverse proxy is used.

## Linux server

Linux deployment is documented but unverified in this one-day Windows timebox.

1. Install Docker Engine, Compose plugin, Git, and PowerShell 7 (`pwsh`) if using repository scripts.
2. Clone the repository and place the environment file outside the checkout.
3. Set `CHATBI_DOCKER_SOCKET_PATH=/var/run/docker.sock`.
4. Run the same scripts with `pwsh -File`, for example:

```bash
pwsh -File ./scripts/doctor.ps1 -EnvFile /etc/chatbi/runtime.env
pwsh -File ./scripts/bootstrap.ps1 -EnvFile /etc/chatbi/runtime.env
pwsh -File ./scripts/start.ps1 -EnvFile /etc/chatbi/runtime.env -SkipBuild
```

5. Put TLS and authentication-aware routing in an approved reverse proxy.
6. Restrict the environment file, storage root, and backup root to the deployment operator.

Do not claim Linux PASS until the exact host, Docker version, filesystem permissions, network policy, and lifecycle commands have been exercised.

## Enterprise database and datasource boundary

The metadata role requires DDL/DML only inside the ChatBI-owned metadata database/schema. Business datasource roles require `CONNECT`, schema `USAGE`, and `SELECT` only. They must not own schemas or have DDL/DML privileges.

## Not included

Kubernetes, Helm, Terraform, enterprise SSO development, HA PostgreSQL, multi-node disaster recovery, production monitoring, key-rotation automation, OCI signing, SLA, and production certification are outside this guide.
