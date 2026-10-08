"""Explicit original-file managed fixtures shared by engine acceptance tests."""

from copy import deepcopy
from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from test_plot_ir import managed_example


def request_for_source(directory: Path, name="A"):
    template, binding, _ = managed_example()
    template, binding = deepcopy(template), deepcopy(binding)
    other = "B" if name == "A" else "A"
    template["series_slots"] = ["slot:" + name]
    template["presentation"]["objects"].pop("slot:" + other)
    template["presentation"]["layout"]["series_styles"].pop("slot:" + other)
    binding["slots"] = {"slot:" + name: binding["slots"]["slot:" + name]}
    binding["data_sources"] = [item for item in binding["data_sources"] if item["source_id"] == name]
    binding["transforms"] = [item for item in binding["transforms"] if item["id"] == "normalize-" + name]
    source = directory / (name + ".csv")
    source.write_text("Time,Signal\ns,V\n0,2\n1,4\n2,8\n")
    binding["data_sources"][0].update(path=str(source), sha256=file_sha256(source))
    return {"idempotency_key": "create-" + name, "template_definition": template, "data_binding": binding,
            "rule_id": "uvvis_spectrum", "theme": {"kind": "sciplot_theme", "schema_version": 1,
                "theme_id": "paper", "rules": []}}


def patch(description, key, prop, value, target, *, scientific=False):
    return {"plot_id": description["plot_id"], "base_revision": description["revision"],
            "idempotency_key": key, "intent_class": "scientific" if scientific else "presentation",
            "changes": [{"op": "set", "target": [target], "property": prop, "value": value}]}
