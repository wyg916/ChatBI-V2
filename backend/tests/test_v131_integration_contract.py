import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_env_example_is_unique_complete_and_secret_free():
    lines = _read(".env.example").splitlines()
    keys = [line.split("=", 1)[0] for line in lines if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line)]

    assert len(keys) == 102
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
    assert compose.count("${CHATBI_BIND_HOST:-0.0.0.0}:") == 3


def test_showcase_and_deployment_precedence_are_project_scoped():
    showcase = _read("scripts/showcase.ps1")
    launcher = _read("一键启动-ChatBI-V2.cmd")
    deployment = _read("scripts/deployment/ChatBI.Deployment.ps1")
    runtime = showcase + deployment
    stop = _read("scripts/stop.ps1")

    assert "Set-ChatBIShowcaseProcessEnvironment" in showcase
    assert "$env:COMPOSE_PROJECT_NAME = 'chatbi-v2-showcase'" in deployment
    assert "$env:CHATBI_BIND_HOST = '127.0.0.1'" in deployment
    assert "$env:CHATBI_ENVIRONMENT = 'development'" in deployment
    assert "$env:CHATBI_SEED_DEMO_SEMANTIC_MODEL = 'true'" in deployment
    assert "[ValidateSet('Auto', 'Live', 'Deterministic')]" in showcase
    assert "$env:CHATBI_MODEL_PROVIDER = 'auto'" in runtime
    assert "$env:CHATBI_GENERAL_MODEL_PROVIDER = 'auto'" in runtime
    assert "$env:CHATBI_VISION_MODEL_PROVIDER = 'auto'" in runtime
    assert "$env:CHATBI_MODEL_BUDGET_MODE = 'quality'" in runtime
    assert "$env:CHATBI_MODEL_PROVIDER = 'deterministic'" in runtime
    assert "$env:CHATBI_TEST_COST_CONTROL = 'NO'" in runtime
    assert "$env:CHATBI_TEST_EXECUTION_LEVEL = 'FINAL'" in runtime
    assert "$env:CHATBI_TEST_EXECUTION_LEVEL = 'LEVEL0'" in runtime
    assert "$env:CHATBI_PAID_GATE_AUTHORIZED = 'YES'" in runtime
    assert "$env:CHATBI_LEVEL0_PAID_EXCEPTION = 'YES'" in runtime
    assert "$env:CHATBI_PROVIDER_USAGE_UNRESTRICTED = 'true'" in runtime
    assert all(name in runtime for name in (
        "CHATBI_MIMO_API_KEY", "CHATBI_DEEPSEEK_API_KEY", "CHATBI_KIMI_API_KEY",
    ))
    assert "ProviderRuntimeSetting" not in showcase
    assert "-Action Start -ProviderMode Auto" in launcher
    assert "IsNullOrWhiteSpace($env:CHATBI_BACKEND_IMAGE)" in showcase
    assert "IsNullOrWhiteSpace($env:CHATBI_FRONTEND_IMAGE)" in showcase
    assert "IsNullOrWhiteSpace($env:CHATBI_SANDBOX_IMAGE)" in showcase
    assert "& docker compose" not in showcase
    assert showcase.count("-EnvFile $resolvedEnv") >= 5
    assert "if ([string]::IsNullOrWhiteSpace($explicitProcessValue))" in deployment
    assert "Assert-ChatBIShowcaseDatabaseTarget -Configuration $showcaseConfiguration" in showcase
    assert "app.db.deployment_state spreadsheet-helpers" in showcase
    assert "org.opencontainers.image.revision" in showcase
    assert "-m app.db.deployment_state --help" in showcase
    assert "Get-ChatBIComposeArguments -EnvFile $resolvedEnv -ProjectName $configuration.ProjectName" in stop


def test_bootstrap_is_safe_for_the_windows_powershell_one_click_launcher():
    bootstrap = _read("scripts/bootstrap.ps1")

    assert "sh -c $bootstrapScript" not in bootstrap
    assert "backend python -c $databaseReadinessProbe" in bootstrap
    assert "backend alembic upgrade head" in bootstrap
    assert "backend alembic current" in bootstrap
    assert "'backend', 'python', '-m', 'app.db.deployment_bootstrap'" in bootstrap


def test_candidate_migration_and_backup_contracts_are_version_aware():
    cold_start = _read("scripts/test-release-cold-start.ps1")
    rollback = _read("scripts/test-v131-historical-rollback-dry-run.ps1")
    backup = _read("scripts/backup.ps1")
    restore = _read("scripts/restore.ps1")
    deployment = _read("scripts/deployment/ChatBI.Deployment.ps1")

    assert "ExpectedMigrationHead = '20260829_0014'" in cold_start
    assert "CandidateMigrationHead = '20260828_0013'" in rollback
    assert "RollbackMigrationHead = '20260822_0012'" in rollback
    assert "CandidateSha = '852d8aa35a6ec0a31bed34ba695ec6a17034b457'" in rollback
    assert "$certifiedCandidateSha = '852d8aa35a6ec0a31bed34ba695ec6a17034b457'" in rollback
    assert "use a separate current-version runner for migration 0014" in rollback
    assert "import psycopg; import pydantic; import pydantic_settings" in rollback
    assert "Pass -Python <path-to-backend-venv-python> explicitly" in rollback
    assert "Join-Path $projectRoot '.env'" in rollback
    assert "Join-Path $projectRoot 'backend\\.venv\\Scripts\\python.exe'" in rollback
    assert "Split-Path -Parent (Split-Path -Parent $projectRoot)" not in rollback
    assert "alembic downgrade $RollbackMigrationHead" in rollback
    assert not (ROOT / "scripts/test-v13-phase5-rollback-dry-run.ps1").exists()
    assert "chatbi-enterprise-backup-v3" in backup
    assert "chatbi-enterprise-backup-v2" not in backup
    assert "chatbi-enterprise-backup-v3" in restore
    assert "chatbi-enterprise-backup-v2" in restore
    assert "chatbi-v2-v1.3.1" in restore
    assert "metadata_sha256" in backup
    assert "20260829_0014" in restore
    assert "datasource_import" in backup
    assert "excel_datasource" in backup
    assert "datasource_import" in restore
    assert "excel_datasource" in restore
    assert "[string]$ProjectName" in backup
    assert "[string]$ProjectName" in restore
    assert "chatbi-v2-showcase" in backup
    assert "chatbi-v2-showcase" in restore
    assert "function Assert-ChatBINoCompetingMetadataWriteStack" in deployment
    assert "COMPETING_METADATA_WRITER=$candidate" in deployment
    assert "IsNullOrWhiteSpace([string]$_)" in deployment
    for script, operation in ((backup, "backup"), (restore, "restore")):
        assert "Assert-ChatBINoCompetingMetadataWriteStack" in script
        assert "@('chatbi-v2-showcase', 'chatbi-v2', $configuredProjectName)" in script
        assert f"-Operation {operation}" in script
    assert "IsNullOrWhiteSpace([string]$_)" in backup
    assert "storage_sha256" in backup
    assert "storage_sha256" in restore
    assert "Backup name already exists" in backup
    assert "$stagedDumpFile" in backup
    assert backup.index("Move-Item -LiteralPath $stagedManifestPath") > backup.index("Move-Item -LiteralPath $stagedDumpPath")
    assert "--file=/backups/$Name.dump" not in backup
    assert "Assert-ChatBISafeStorageTarget" in restore
    assert "restore-staging" in restore
    assert "--single-transaction" in restore
    assert restore.index("Move-Item -LiteralPath $storageRestoreStaging") < restore.index("pg_restore --clean")
    assert "$databaseRestoreCompleted" in restore
    assert "bootstrap.ps1" not in restore
    assert restore.index("alembic current") < restore.index("app.db.deployment_state snapshot")
    assert "--schema=$metadataSchema" in backup
    assert "RESTORED_METADATA=SETTINGS_PROVIDER_INVITATION_RBAC_WORKSPACE_PERSISTENCE_PASS" in restore


def test_current_product_release_identity_is_v131_and_v130_history_remains_immutable():
    backend_config = _read("backend/app/core/config.py")
    app_shell = _read("frontend/src/components/AppShell.tsx")
    showcase = _read("scripts/showcase.ps1")
    deployment = _read("scripts/deployment/ChatBI.Deployment.ps1")
    release_sbom = _read("scripts/release/generate_sbom.py")
    supply_policy = _read("supply-chain/v1.3-phase5-policy.json")
    readme = _read("README.md")

    assert 'app_version: str = "1.3.1"' in backend_config
    assert "v1.3.1 · 开源企业版" in app_shell
    assert "$env:CHATBI_RELEASE_VERSION = 'v1.3.1'" in showcase + deployment
    assert "v1.3.1-candidate" not in showcase
    assert 'PROJECT_VERSION = "1.3.1"' in release_sbom
    assert '"project_version": "1.3.1"' in supply_policy
    assert "release-v1.3.1" in readme
    assert "chatbi-v2-v1.3.1" in readme
    assert "chatbi-v2-v1.3.0" in readme
    assert "52db955fd67ebe592c289399a135528c13cb3e3d" in readme


def test_release_docs_separate_published_tag_from_unreleased_0014_successor():
    release_notes = _read("docs/releases/V1_3_1_RELEASE_NOTES.md")
    published, successor = release_notes.split("## Unreleased `0014` main successor", 1)
    rollback = _read("docs/releases/V1_3_1_ROLLBACK.md")
    backup_restore = _read("docs/deployment/BACKUP_RESTORE.md")

    assert "dddca12d3f4a337c51a12ce5cd9a880239b8429d" in published
    assert "20260828_0013" in published
    assert "20260829_0014" not in published
    assert "704 collected" in published
    assert "20260829_0014" in successor
    assert "704 collected" not in successor
    assert "must not be reused as evidence for later `main` changes" in published
    assert "test-v131-historical-rollback-dry-run.ps1" in rollback
    assert "must not be used for `0014`" in rollback
    assert "chatbi-enterprise-backup-v3" in backup_restore
    assert "chatbi-v2-v1.3.1" in backup_restore


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
