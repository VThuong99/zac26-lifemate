#!/usr/bin/env python3
"""Run the explicitly selected archived tests that need no private workspace.

Each group gets its own interpreter because historical modules modify sys.path.
The rest of the archive requires absent SDKs, reference data or host receipts;
see docs/EVALUATION.md. No archive source or test is rewritten.
"""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    ("archive/host_validation/tests", [
        "test_validation.ComparisonTests",
        "test_image_identity.ImageIdentityTests",
    ]),
    ("archive/private_test/lifemate-private-rc2-host-20261120", [
        "test_workflow.HostSafety",
        "test_output_directory.OutputDirectory",
        "test_continuation.RecoverySafety",
    ]),
    ("archive/private_test/lifemate-private-rc2-investigation-20261120", [
        "test_inspect_failure.PrefixAssessment",
    ]),
    ("archive/rc2/overlay/tests", [
        "test_transport.TransportTest.test_private_split_discovery_and_ambiguous_mount",
        "test_transport.TransportTest.test_reference_fields_and_duplicate_ids_rejected",
        "test_transport.TransportTest.test_partial_failure_never_becomes_submission",
        "test_transport.TransportTest.test_offline_socket_guard",
    ]),
]


def main():
    failed = False
    for directory, names in GROUPS:
        print(f"Archived CPU group: {directory}", flush=True)
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", "-v", *names], cwd=ROOT / directory)
        failed = failed or result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
