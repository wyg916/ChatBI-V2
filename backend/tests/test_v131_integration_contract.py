import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_env_example_is_unique_complete_and_secret_free():
    lines = _read(".env.example").splitlines()
    keys = [line.split("=", 1)[0] for line in lines if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line)]

    assert len(keys) == 100
    assert len(keys) == len(set(keys))
    assert {
        "CHATBI_GIT_SHA",
        "CHATBI_RELEASE_VERSION",
        "CHATBI_FRONTEND_BUILD",
        "CHATBI_BACKEND_IMAGE",
        "CHATBI_FRONTEND_IMAGE",
        "CHATBI_SANDBOX_IMAGE",
    }.issubset(keys)
    assert {key for key in keys if re.match(r"^CHATBI_(MIMO|DEEPSEEK|KIMI)_API_KEY$", key)} == {
        "CHATBI_MIMO_API_KEY",
        "CHATBI_DEEPSEEK_API_KEY",
        "CHATBI_KIMI_API_KEY",
    }
    assert not any(re.search(r"sk-[A-Za-z0-9]{12,}", line) for line in lines)


def test_one_compose_has_mode_identity_and_no_database_server():
    compose = _read("docker-compose.yml")
    services_block = compose.split("services:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    services = set(re.findall(r"^  ([a-z][a-z0-9-]+):\s*$", services_block, re.MULTILINE))

    assert services == {
        "backend",
        "sandbox-controller",
        "sandbox-docker-proxy",
        "rag-runtime",
        "frontend",
        "maintenance",
    }
    assert "\nvolumes:\n" not in compose
    assert "CHATBI_ENVIRONMENT: development" not in compose
    assert "CHATBI_ENVIRONMENT: ${CHATBI_ENVIRONMENT:-local}" in compose
    assert "CHATBI_GIT_SHA: ${CHATBI_GIT_SHA:-UNAVAILABLE}" in compose
    assert "CHATBI_RELEASE_VERSION: ${CHATBI_RELEASE_VERSION:-v1.3.1}" in compose
    assert "CHATBI_FRONTEND_IMAGE" in compose
    assert compose.count("CHATBI_SANDBOX_WORKER_IMAGE: ${CHATBI_SANDBOX_IMAGE") == 2


def test_showcase_and_deployment_precedence_are_project_scoped():
    showcase = _read("scripts/showcase.ps1")
    deployment = _read("scripts/deployment/ChatBI.Deployment.ps1")
    stop = _read("scripts/stop.ps1")

    assert "$env:COMPOSE_PROJECT_NAME = $showcaseProjectName" in showcase
    assert "$env:CHATBI_ENVIRONMENT = 'development'" in showcase
    assert "$env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'" in showcase
    assert "$env:CHATBI_MODEL_PROVIDER = 'deterministic'" in showcase
    assert "IsNullOrWhiteSpace($env:CHATBI_BACKEND_IMAGE)" in showcase
    assert "IsNullOrWhiteSpace($env:CHATBI_FRONTEND_IMAGE)" in showcase
    assert "IsNullOrWhiteSpace($env:CHATBI_SANDBOX_IMAGE)" in showcase
    assert "& docker compose" not in showcase
    assert showcase.count("-EnvFile $resolvedEnv") >= 5
    assert "if ([string]::IsNullOrWhiteSpace($explicitProcessValue))" in deployment
    assert "Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName" in stop


def test_candidate_migration_and_backup_contracts_are_version_aware():
    cold_start = _read("scripts/test-release-cold-start.ps1")
    rollback = _read("scripts/test-v13-phase5-rollback-dry-run.ps1")
    backup = _read("scripts/backup.ps1")
    restore = _read("scripts/restore.ps1")

    assert "ExpectedMigrationHead = '20260828_0013'" in cold_start
    assert "CandidateMigrationHead = '20260828_0013'" in rollback
    assert "RollbackMigrationHead = '20260822_0012'" in rollback
    assert "alembic downgrade $RollbackMigrationHead" in rollback
    assert "chatbi-enterprise-backup-v2" in backup
    assert "metadata_sha256" in backup
    assert "20260828_0013" in restore
    assert "RESTORED_METADATA=SETTINGS_PROVIDER_INVITATION_RBAC_WORKSPACE_PERSISTENCE_PASS" in restore


def test_architecture_decision_ids_and_references_are_unambiguous():
    decisions = _read("docs/DECISIONS.md")
    ids = re.findall(r"^## ADR-(\d+)\b", decisions, re.MULTILINE)
    assert len(ids) == len(set(ids))

    known = set(ids)
    references: set[str] = set()
    for path in (ROOT / "docs").rglob("*.md"):
        if path.name == "DECISIONS.md":
            continue
        references.update(re.findall(r"\bADR-(\d+)\b", path.read_text(encoding="utf-8")))
    assert references - known == set()
