"""C2.4: per-sample gating fields wired into ExperimentModel, backward compatible.

These tests are hermetic (tmp_path only) and must pass both for freshly created
experiments and for legacy .kit files that predate per-sample gating.
"""
import json
from pathlib import Path

from honeychrome.experiment_model import ExperimentModel
from honeychrome.controller_components.gating_templates import DEFAULT_TEMPLATE_NAME


def test_create_adds_template_fields(tmp_path):
    e = ExperimentModel()
    e.create(tmp_path / "exp.kit")
    assert DEFAULT_TEMPLATE_NAME in e.cytometry["gating_templates"]
    assert "sample_template_assignments" in e.samples


def test_roundtrip_preserves_template_fields(tmp_path):
    e = ExperimentModel()
    e.create(tmp_path / "exp.kit")
    e.save()

    e2 = ExperimentModel()
    e2.load(tmp_path / "exp.kit")
    assert DEFAULT_TEMPLATE_NAME in e2.cytometry["gating_templates"]
    assert e2.samples["sample_template_assignments"] == {}


def test_load_legacy_kit_migrates(tmp_path):
    # Build a real experiment, then strip the new fields and re-save to simulate
    # an old .kit that predates per-sample gating.
    e = ExperimentModel()
    e.create(tmp_path / "exp.kit")
    e.cytometry.pop("gating_templates", None)
    e.samples.pop("sample_template_assignments", None)
    e.save()

    on_disk = json.loads(Path(e.experiment_path).read_text(encoding="utf-8"))
    assert "gating_templates" not in on_disk["cytometry"]  # genuinely legacy-shaped

    # Loading migrates it to a default template mirroring the legacy gating.
    e2 = ExperimentModel()
    e2.load(tmp_path / "exp.kit")
    templates = e2.cytometry["gating_templates"]
    assert DEFAULT_TEMPLATE_NAME in templates
    assert templates[DEFAULT_TEMPLATE_NAME]["raw_gml"] == e2.cytometry.get("raw_gating", "")
    assert e2.samples["sample_template_assignments"] == {}
