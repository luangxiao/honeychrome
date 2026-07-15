"""Phase-1 checkpoints for per-sample gating (see docs/per_sample_gating_design.md)."""
import pytest

from honeychrome.controller_components.gating_templates import (
    DimensionSpec,
    SampleContext,
    resolve_spec,
    register_dynamic_resolver,
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
