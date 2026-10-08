"""A pending managed transaction depends only on its own scientific/native closure."""

import json
from pathlib import Path
import re

import pytest

from managed_plot_helpers import patch, request_for_source
from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, read, transaction_path


@pytest.mark.comprehensive
@pytest.mark.parametrize("unrelated_change", ["native", "source", "source_refresh"])
def test_pending_a_review_survives_unrelated_b_changes(tmp_path, unrelated_change):
    request_a = request_for_source(tmp_path)
    request_b = request_for_source(tmp_path, "B")
    service = PlotService()
    try:
        a, b = service.create(request_a), service.create(request_b)
        assert a["ready_to_use"] and b["ready_to_use"], (a, b)
        a_root, b_root = Path(a["plot"]), Path(b["plot"])
        assert a_root.parent == b_root.parent and a_root != b_root
        a_before, b_before = load_head(a_root), load_head(b_root)
        a_source = Path(request_a["data_binding"]["data_sources"][0]["path"])
        a_source_sha = file_sha256(a_source)
        review = service.patch(a_root, patch(a, "pending-A-legend", "legend.position", [.6, .8], "legend:main"))
        assert review["status"] == "needs_review", review
        transaction = transaction_path(a_root, "pending-A-legend")
        pending_before = read(transaction)

        if unrelated_change == "native":
            changed_path = Path(b_before["binding"]["document"])
            changed, count = re.subn(r"Set\('markerSize', '[^']+'\)", "Set('markerSize', '19pt')", changed_path.read_text())
            assert count == 1
            changed_path.write_text(changed)
        else:
            changed_path = Path(request_b["data_binding"]["data_sources"][0]["path"])
            changed_path.write_text(changed_path.read_text().replace("2,8", "2,6"))
        b_stale = service.describe(b_root)
        assert b_stale["status"] == "stale" and str(changed_path) in b_stale["changed_inputs"]
        if unrelated_change == "native":
            assert b_stale["external_mutation"]["classification"] == "opaque_native_change"
        if unrelated_change == "source_refresh":
            refreshed = service.patch(b_root, patch(b, "refresh-B-while-A-pending", "source.sha256",
                file_sha256(changed_path), "source:B", scientific=True))
            assert refreshed["ready_to_use"] and refreshed["scientific_hash"] != b["scientific_hash"], refreshed
        assert load_head(a_root) == a_before and read(transaction) == pending_before
        assert service.describe(a_root)["changed_inputs"] == []
        b_at_acceptance = load_head(b_root)
        changed_sha = file_sha256(changed_path)

        accepted = service.decide(a_root, {**review["next_step"]["request"], "accept": True})
        assert accepted["ready_to_use"] and accepted["revision"] == a["revision"] + 1, accepted
        assert accepted["scientific_hash"] == a["scientific_hash"]
        assert accepted["presentation_hash"] != a["presentation_hash"]
        assert file_sha256(a_source) == a_source_sha
        assert load_head(b_root) == b_at_acceptance and file_sha256(changed_path) == changed_sha
        b_after = service.describe(b_root)
        if unrelated_change == "source_refresh":
            assert b_after["status"] == "current" and b_after["revision"] == b["revision"] + 1
            assert b_after["dependencies"]["invalidated"] == []
        else:
            assert b_after["status"] == "stale" and str(changed_path) in b_after["changed_inputs"]
            assert b_after["scientific_hash"] == b["scientific_hash"]
            assert load_head(b_root) == b_before
        assert service.describe(a_root)["dependencies"]["invalidated"] == []
        evidence = REPO_ROOT / ".tmp_verify/managed_architecture_20261008" / ("pending_dependency_" + unrelated_change + ".json")
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({"pending_a": review, "unrelated_b_stale": b_stale,
            "accepted_a": accepted, "unrelated_b_after": b_after,
            "a_scientific_hash_preserved": True, "b_unchanged_by_a_acceptance": True}, ensure_ascii=False, indent=2))
    finally:
        service.close()
