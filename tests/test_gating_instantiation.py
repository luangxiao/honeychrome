"""Phase 3 (C3.1): resolve a gating template into a per-sample GatingStrategy."""
import numpy as np
from flowkit import GatingStrategy, gates, Dimension

from honeychrome.controller_components.gating_instantiation import (
    instantiate_template_for_sample,
    sample_context_from_events,
)
from honeychrome.controller_components.gating_templates import SampleContext, dynamic_key


def _time_gate_strategy(lo=0.0, hi=1.0):
    """A GatingStrategy with a single 1D range gate on Time (placeholder range)."""
    gs = GatingStrategy()
    dim = Dimension("Time", range_min=lo, range_max=hi)
    gs.add_gate(gates.RectangleGate("TimeGate", dimensions=[dim]), gate_path=("root",))
    return gs


def _time_dim(strategy):
    return strategy.get_gate("TimeGate").dimensions[0]


def test_absolute_only_returns_unchanged_geometry():
    # C3.1: with no dynamic specs, geometry is identical to today's.
    gs = _time_gate_strategy(0.0, 1.0)
    out = instantiate_template_for_sample(gs, {}, SampleContext())
    dim = _time_dim(out)
    assert dim.min == 0.0 and dim.max == 1.0


def test_dynamic_time_resolved_from_sample_range():
    gs = _time_gate_strategy(0.0, 1.0)
    dynamic = {
        dynamic_key("TimeGate", "Time"): {"kind": "time", "params": {"min_frac": 0.1, "max_frac": 0.9}},
    }
    ctx = SampleContext(channel_ranges={"Time": (0.0, 1000.0)})
    out = instantiate_template_for_sample(gs, dynamic, ctx)
    dim = _time_dim(out)
    assert dim.min == 100.0 and dim.max == 900.0


def test_two_samples_resolve_differently():
    gs = _time_gate_strategy(0.0, 1.0)
    dynamic = {
        dynamic_key("TimeGate", "Time"): {"kind": "time", "params": {"min_frac": 0.0, "max_frac": 1.0}},
    }
    a = instantiate_template_for_sample(gs, dynamic, SampleContext(channel_ranges={"Time": (0.0, 500.0)}))
    b = instantiate_template_for_sample(gs, dynamic, SampleContext(channel_ranges={"Time": (100.0, 2100.0)}))
    assert (_time_dim(a).min, _time_dim(a).max) == (0.0, 500.0)
    assert (_time_dim(b).min, _time_dim(b).max) == (100.0, 2100.0)


def test_input_strategy_not_mutated():
    gs = _time_gate_strategy(0.0, 1.0)
    dynamic = {
        dynamic_key("TimeGate", "Time"): {"kind": "time", "params": {"min_frac": 0.0, "max_frac": 1.0}},
    }
    instantiate_template_for_sample(gs, dynamic, SampleContext(channel_ranges={"Time": (5.0, 15.0)}))
    # the original template strategy keeps its placeholder geometry
    assert (_time_dim(gs).min, _time_dim(gs).max) == (0.0, 1.0)


def test_sample_context_from_events():
    events = np.array([[0.0, 10.0], [5.0, 20.0], [2.0, 30.0]])
    pnn = ["Time", "FSC-A"]
    ctx = sample_context_from_events(events, pnn)
    assert ctx.channel_ranges["Time"] == (0.0, 5.0)
    assert ctx.channel_ranges["FSC-A"] == (10.0, 30.0)


def test_context_feeds_instantiation_end_to_end():
    # a sample's own Time range drives the resolved gate bounds.
    events = np.array([[100.0], [600.0], [1100.0]])  # Time column, range 100..1100
    ctx = sample_context_from_events(events, ["Time"])
    gs = _time_gate_strategy(0.0, 1.0)
    dynamic = {dynamic_key("TimeGate", "Time"): {"kind": "time", "params": {"min_frac": 0.0, "max_frac": 1.0}}}
    out = instantiate_template_for_sample(gs, dynamic, ctx)
    assert (_time_dim(out).min, _time_dim(out).max) == (100.0, 1100.0)
