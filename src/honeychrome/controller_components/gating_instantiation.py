"""Resolve a gating template into a concrete per-sample GatingStrategy.

This is the flowkit-touching companion to ``gating_templates`` (which stays
framework-free). ``instantiate_template_for_sample`` takes a base
``GatingStrategy`` (the template's absolute skeleton) plus the template's dynamic
dimension specs, and returns a copy in which every dynamic dimension has been
resolved to absolute values for one sample. For templates with no dynamic
dimensions it returns the strategy unchanged (identical to today's behaviour).
"""
from copy import deepcopy

import numpy as np

from honeychrome.controller_components.gating_templates import (
    DimensionSpec,
    SampleContext,
    resolve_spec,
)


def sample_context_from_events(event_data, pnn, channels=None):
    """Build a ``SampleContext`` (per-channel ``(min, max)``) from a sample.

    ``event_data`` is an ``(n_events, n_channels)`` array; ``pnn`` the channel
    order. Dynamic resolvers (e.g. Time) read these ranges to adapt a template
    to the sample. Channels with no events are skipped.
    """
    wanted = channels if channels is not None else pnn
    ranges = {}
    for channel in wanted:
        if channel in pnn:
            column = event_data[:, pnn.index(channel)]
            if column.size:
                ranges[channel] = (float(np.min(column)), float(np.max(column)))
    return SampleContext(channel_ranges=ranges)


def instantiate_template_for_sample(base_strategy, dynamic_specs, sample_context):
    """Return a ``GatingStrategy`` with dynamic dimensions resolved for a sample.

    Parameters
    ----------
    base_strategy : flowkit.GatingStrategy
        The template's absolute skeleton (e.g. from ``from_gml``).
    dynamic_specs : dict
        ``{ dynamic_key(gate_id, channel): {"kind": str, "params": dict} }``.
    sample_context : SampleContext
        Per-sample data used by resolvers (e.g. channel ranges).
    """
    if not dynamic_specs:
        return base_strategy

    resolved = deepcopy(base_strategy)
    for key, spec_dict in dynamic_specs.items():
        gate_id, channel = key.split("|", 1)
        spec = DimensionSpec(
            channel=channel,
            mode="dynamic",
            kind=spec_dict["kind"],
            params=spec_dict.get("params", {}),
        )
        lo, hi = resolve_spec(spec, sample_context)

        gate = resolved.get_gate(gate_id)
        dimension_ids = list(gate.get_dimension_ids())
        if channel in dimension_ids:
            dim = gate.dimensions[dimension_ids.index(channel)]
            dim.min = lo
            dim.max = hi
    return resolved
