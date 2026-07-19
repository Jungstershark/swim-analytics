import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.diff_sgaquatics_manifest import diff_manifests


def record(url, filename, category, sha):
    return {
        "url": url,
        "filename": filename,
        "category": category,
        "sha256": sha,
        "saved": f"by-sha/{sha}.pdf",
    }


def test_diff_manifests_detects_added_documents():
    old = {"files": [record("https://example.test/day1.pdf", "day1.pdf", "overall_results", "aaa")]}
    new = {"files": [
        record("https://example.test/day1.pdf", "day1.pdf", "overall_results", "aaa"),
        record("https://example.test/day2.pdf", "day2.pdf", "overall_results", "bbb"),
    ]}

    diff = diff_manifests(old, new)

    assert [item["filename"] for item in diff["added_documents"]] == ["day2.pdf"]
    assert diff["summary"]["added"] == 1
    assert diff["summary"]["changed_same_identity"] == 0


def test_diff_manifests_detects_same_filename_reused_with_new_hash():
    old = {"files": [record("https://example.test/results.pdf", "results.pdf", "overall_results", "oldhash")]}
    new = {"files": [record("https://example.test/results.pdf", "results.pdf", "overall_results", "newhash")]}

    diff = diff_manifests(old, new)

    assert diff["summary"]["added"] == 0
    assert diff["summary"]["changed_same_identity"] == 1
    changed = diff["changed_same_identity"][0]
    assert changed["filename"] == "results.pdf"
    assert changed["old_sha256"] == "oldhash"
    assert changed["new_sha256"] == "newhash"
    assert changed["category"] == "overall_results"
    assert changed["importable"] is True


def test_diff_manifests_detects_removed_documents():
    old = {"files": [record("https://example.test/day1.pdf", "day1.pdf", "overall_results", "aaa")]}
    new = {"files": []}

    diff = diff_manifests(old, new)

    assert [item["filename"] for item in diff["removed_documents"]] == ["day1.pdf"]
    assert diff["summary"]["removed"] == 1
