"""Phase-1 checkpoints for per-sample gating (see docs/per_sample_gating_design.md)."""
import pytest

from honeychrome.controller_components.gating_templates import (
    DimensionSpec,
    SampleContext,
    resolve_spec,
    register_dynamic_resolver,
    GatingTemplate,
    build_default_template,
    migrate_cytometry_templates,
    template_for_sample,
    dynamic_key,
    DEFAULT_TEMPLATE_NAME,
)


def ctx(**ranges):
    return SampleContext(channel_ranges=dict(ranges))


def test_absolute_passthrough():
    # C1.5: absolute specs are returned unchanged.
    spec = DimensionSpec(channel="CD4", mode="absolute", min=0.3, max=0.7)
    assert resolve_spec(spec, ctx(CD4=(0.0, 1.0))) == (0.3, 0.7)


def test_time_dynamic_resolves_from_sample_range():
    # C1.2: built-in time resolver maps fractions -> absolute using the sample range.
    spec = DimensionSpec(
        channel="Time", mode="dynamic", kind="time",
        params={"min_frac": 0.05, "max_frac": 0.95},
    )
    assert resolve_spec(spec, ctx(Time=(0.0, 1000.0))) == (50.0, 950.0)


def test_time_dynamic_differs_between_samples():
    # C1.4: same spec resolves differently for two sample contexts.
    spec = DimensionSpec(
        channel="Time", mode="dynamic", kind="time",
        params={"min_frac": 0.0, "max_frac": 1.0},
    )
    a = resolve_spec(spec, ctx(Time=(0.0, 500.0)))
    b = resolve_spec(spec, ctx(Time=(100.0, 2100.0)))
    assert a == (0.0, 500.0)
    assert b == (100.0, 2100.0)
    assert a != b


def test_register_new_dynamic_kind():
    # C1.3: a new dynamic kind works without touching core code.
    def full_range_resolver(params, context, channel):
        return context.channel_ranges[channel]

    register_dynamic_resolver("full_range", full_range_resolver)
    spec = DimensionSpec(channel="SSC-A", mode="dynamic", kind="full_range", params={})
    assert resolve_spec(spec, ctx(**{"SSC-A": (10.0, 90.0)})) == (10.0, 90.0)


def test_unknown_kind_raises():
    spec = DimensionSpec(channel="X", mode="dynamic", kind="does_not_exist", params={})
    with pytest.raises(KeyError):
        resolve_spec(spec, ctx(X=(0.0, 1.0)))


# --- Phase 2: template model + migration ------------------------------------

def test_template_dict_roundtrip():
    # C2.1: GatingTemplate serialises and restores, including dynamic dims.
    tmpl = GatingTemplate(
        name="panelA",
        raw_gml="<raw/>",
        unmixed_gml="<unmixed/>",
        dynamic_dimensions={
            "raw": {dynamic_key("TimeGate", "Time"): {"kind": "time", "params": {"min_frac": 0.0, "max_frac": 1.0}}},
            "unmixed": {},
        },
    )
    restored = GatingTemplate.from_dict("panelA", tmpl.to_dict())
    assert restored == tmpl


def test_migrate_legacy_cytometry_creates_default_template():
    # C2.2: an old .kit (no gating_templates) yields a single 'default' template
    # built from the legacy raw_gating / gating GML.
    legacy = {"raw_gating": "<raw-gml/>", "gating": "<unmixed-gml/>"}
    templates = migrate_cytometry_templates(legacy)
    assert set(templates) == {DEFAULT_TEMPLATE_NAME}
    default = templates[DEFAULT_TEMPLATE_NAME]
    assert default["raw_gml"] == "<raw-gml/>"
    assert default["unmixed_gml"] == "<unmixed-gml/>"


def test_migrate_preserves_existing_templates():
    existing = {"gating_templates": {"panelA": {"raw_gml": "<x/>"}}}
    assert migrate_cytometry_templates(existing) == existing["gating_templates"]


def test_build_default_template_handles_missing_gml():
    tmpl = build_default_template(None, None)
    assert tmpl.name == DEFAULT_TEMPLATE_NAME
    assert tmpl.raw_gml == "" and tmpl.unmixed_gml == ""


def test_template_for_sample_defaults_and_assignment():
    # C2.3: assignment is read, missing assignment falls back to 'default'.
    samples = {"sample_template_assignments": {"Raw/Tube_003.fcs": "panelA"}}
    assert template_for_sample("Raw/Tube_003.fcs", samples) == "panelA"
    assert template_for_sample("Raw/Tube_002.fcs", samples) == DEFAULT_TEMPLATE_NAME
    assert template_for_sample("anything", {}) == DEFAULT_TEMPLATE_NAME
