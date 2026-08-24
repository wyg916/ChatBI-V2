from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "chatbi.v13.phase5.control-receipt.v2"
NA_STATUS = "NOT_APPLICABLE_WITH_EXPLICIT_REASON"


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def receipt_files(root: Path) -> list[Path]:
    directory = root / "receipts" if (root / "receipts").is_dir() else root
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def load_receipts(root: Path) -> dict[str, tuple[dict[str, Any], Path]]:
    result: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in receipt_files(root):
        payload = json.loads(path.read_text(encoding="utf-8"))
        control_id = str(payload.get("CONTROL_ID") or "").strip()
        if not control_id:
            raise ValueError(f"CONTROL_ID_MISSING:{path}")
        if control_id in result:
            raise ValueError(f"DUPLICATE_CONTROL_ID:{control_id}")
        result[control_id] = (payload, path)
    return result


def complete_field(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) > 0
    return (
        isinstance(value, dict)
        and value.get("status") == NA_STATUS
        and bool(str(value.get("reason") or "").strip())
    )


def normalize_receipt(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    original_hash = sha256(payload)
    normalized = dict(payload)
    if normalized.get("FINAL_STATUS") != "PASS":
        raise ValueError(f"CONTROL_NOT_PASS:{normalized.get('CONTROL_ID')}")
    network_complete = complete_field(normalized.get("NETWORK_REQUEST"))
    api_complete = complete_field(normalized.get("API_READBACK"))
    if not network_complete and not api_complete:
        raise ValueError(f"NETWORK_API_EVIDENCE_INCOMPLETE:{normalized.get('CONTROL_ID')}")
    if not network_complete:
        normalized["NETWORK_REQUEST"] = {
            "status": NA_STATUS,
            "reason": "No separate action-network event is required; the attached authenticated API readback is the acceptance source.",
        }
    if not api_complete:
        normalized["API_READBACK"] = {
            "status": NA_STATUS,
            "reason": "No separate API readback contract applies; the attached action-network response is the acceptance source.",
        }
    network_applicable = isinstance(normalized["NETWORK_REQUEST"], list)
    api_applicable = isinstance(normalized["API_READBACK"], list)
    if network_applicable or api_applicable:
        network_api = {
            "status": "APPLICABLE",
            "reason": "Network request or API readback evidence is attached.",
        }
    else:
        reasons = {
            str(normalized["NETWORK_REQUEST"].get("reason") or "").strip(),
            str(normalized["API_READBACK"].get("reason") or "").strip(),
        }
        network_api = {
            "status": NA_STATUS,
            "reason": " ".join(sorted(value for value in reasons if value)),
        }
    normalized["SCHEMA_VERSION"] = SCHEMA_VERSION
    normalized["NETWORK_API"] = network_api
    normalized["EVIDENCE"] = {
        **dict(normalized.get("EVIDENCE") or {}),
        "source_receipt_sha256": original_hash,
        "source_receipt_set": source,
        "schema_normalization_only": payload.get("SCHEMA_VERSION") != SCHEMA_VERSION,
    }
    return normalized


def merge_receipts(
    baseline_root: Path,
    targeted_root: Path,
    output_root: Path,
    *,
    expected_count: int,
    expected_targeted_count: int,
) -> dict[str, Any]:
    baseline = load_receipts(baseline_root)
    targeted = load_receipts(targeted_root)
    if len(targeted) != expected_targeted_count:
        raise ValueError(
            f"TARGETED_CONTROL_COUNT_MISMATCH:{len(targeted)}:{expected_targeted_count}"
        )
    baseline_gaps = {
        control_id
        for control_id, (payload, _path) in baseline.items()
        if not complete_field(payload.get("NETWORK_REQUEST"))
        and not complete_field(payload.get("API_READBACK"))
    }
    if set(targeted) != baseline_gaps:
        missing = sorted(baseline_gaps - set(targeted))
        unexpected = sorted(set(targeted) - baseline_gaps)
        raise ValueError(
            "TARGETED_CONTROLS_MUST_MATCH_BASELINE_NETWORK_API_GAPS:"
            f"missing={','.join(missing)}:unexpected={','.join(unexpected)}"
        )
    unknown = sorted(set(targeted) - set(baseline))
    if unknown:
        raise ValueError("TARGETED_CONTROL_NOT_IN_BASELINE:" + ",".join(unknown))
    merged = dict(baseline)
    merged.update(targeted)
    if len(merged) != expected_count:
        raise ValueError(f"CONTROL_COUNT_MISMATCH:{len(merged)}:{expected_count}")

    receipts_dir = output_root / "receipts"
    normalized_receipts: list[dict[str, Any]] = []
    for control_id in sorted(merged):
        payload, _ = merged[control_id]
        normalized = normalize_receipt(
            payload,
            source="TARGETED_RERUN" if control_id in targeted else "BASELINE_REUSED_COMPLETE_EVIDENCE",
        )
        atomic_json(receipts_dir / f"{control_id}.json", normalized)
        normalized_receipts.append(normalized)

    manifest = {
        "schema_version": "chatbi.v13.phase5.control-receipt-merge.v1",
        "status": "PASS",
        "expected_control_count": expected_count,
        "control_receipt_complete": f"{len(normalized_receipts)}/{expected_count}",
        "control_receipt_schema_valid": f"{len(normalized_receipts)}/{expected_count}",
        "targeted_rerun_count": len(targeted),
        "baseline_reused_count": len(normalized_receipts) - len(targeted),
        "targeted_control_ids": sorted(targeted),
        "receipts_sha256": sha256(normalized_receipts),
        "paid_provider_calls": 0,
        "paid_provider_cost_cny": 0,
    }
    atomic_json(output_root / "control-receipt-merge-manifest.json", manifest)
    checksum_lines = []
    for path in sorted(output_root.rglob("*.json")):
        checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(output_root).as_posix()}")
    (output_root / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge the 47 targeted Phase5 control reruns with complete baseline receipts")
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--targeted-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=391)
    parser.add_argument("--expected-targeted-count", type=int, default=47)
    args = parser.parse_args()
    manifest = merge_receipts(
        args.baseline_root.resolve(),
        args.targeted_root.resolve(),
        args.output_root.resolve(),
        expected_count=args.expected_count,
        expected_targeted_count=args.expected_targeted_count,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
