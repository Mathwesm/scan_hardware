"""Run repeatable end-to-end OCR checks against a local photo manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi.testclient import TestClient
from loguru import logger
from pydantic import BaseModel, Field

from scan_hardware.api import create_app
from scan_hardware.models.item import ScanResponse


class PhotoCase(BaseModel):
    """Expected outcome for one licensed local hardware photograph."""

    name: str = Field(min_length=1)
    image: Path
    category: Literal["cpu", "gpu", "motherboard"]
    expected_status: Literal["matched", "suggestions", "not_found"]
    expected_item_id: str | None = None
    source_url: str | None = None
    license: str | None = None


class PhotoManifest(BaseModel):
    """Validated collection of local photo cases."""

    cases: list[PhotoCase] = Field(min_length=1)


class CaseResult(BaseModel):
    """Observed HTTP result and whether it met the expected outcome."""

    name: str
    category: str
    status: str
    expected_status: str
    top_item_id: str | None
    expected_item_id: str | None
    source_url: str | None
    license: str | None
    image_sha256: str
    elapsed_seconds: float
    passed: bool


def evaluate_case(
    case: PhotoCase, result: ScanResponse, elapsed_seconds: float, image_sha256: str
) -> CaseResult:
    """Judge status and top candidate without treating a suggestion as exact.

    Args:
        case: Expected result for the photo.
        result: Validated scanner response.
        elapsed_seconds: Complete HTTP scan duration.
        image_sha256: Digest of the original image bytes.

    Returns:
        Comparison with a Boolean pass decision.
    """
    top_id = result.matches[0].id if result.matches else None
    passed = result.status == case.expected_status and (
        case.expected_item_id is None or top_id == case.expected_item_id
    )
    return CaseResult(
        name=case.name,
        category=case.category,
        status=result.status,
        expected_status=case.expected_status,
        top_item_id=top_id,
        expected_item_id=case.expected_item_id,
        source_url=case.source_url,
        license=case.license,
        image_sha256=image_sha256,
        elapsed_seconds=round(elapsed_seconds, 3),
        passed=passed,
    )


def run_manifest(manifest_path: Path, output_root: Path) -> Path:
    """Scan each local image and save an immutable validation report.

    Args:
        manifest_path: UTF-8 JSON manifest with paths relative to its directory.
        output_root: Root directory for versioned validation reports.

    Returns:
        Path of the saved report.

    Raises:
        RuntimeError: Any expected behavior differs from the observed behavior.
    """
    manifest = PhotoManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    client = TestClient(create_app())
    results: list[CaseResult] = []
    for case in manifest.cases:
        image_path = manifest_path.parent / case.image
        content = image_path.read_bytes()
        started = time.perf_counter()
        response = client.post(
            "/scan", files={"image": (image_path.name, content, "application/octet-stream")}
        )
        elapsed = time.perf_counter() - started
        response.raise_for_status()
        result = ScanResponse.model_validate(response.json())
        case_result = evaluate_case(case, result, elapsed, hashlib.sha256(content).hexdigest())
        results.append(case_result)
        logger.info(
            "Photo validation name={} status={} top_id={} passed={} seconds={}",
            case.name,
            result.status,
            case_result.top_item_id,
            case_result.passed,
            case_result.elapsed_seconds,
        )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = output_root / run_id / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=False)
    report_path.write_text(
        json.dumps(
            {
                "total": len(results),
                "passed": sum(case.passed for case in results),
                "cases": [case.model_dump(mode="json") for case in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if not all(case.passed for case in results):
        raise RuntimeError(f"Photo validation failed; see {report_path}")
    return report_path


@logger.catch(reraise=True)
def main() -> None:
    """Run a photo manifest from the command line."""
    parser = argparse.ArgumentParser(description="Validate real photos through the scanner API")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/validation"))
    args = parser.parse_args()
    logger.info("Photo validation report path={}", run_manifest(args.manifest, args.output_root))


if __name__ == "__main__":
    main()
