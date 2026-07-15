"""Per-sample gating — dynamic dimension specs and resolvers (foundation).

See ``docs/per_sample_gating_design.md``. A gate dimension is either:

* ``absolute`` — fixed display-coordinate ``(min, max)`` (today's behaviour), or
* ``dynamic`` — resolved *per sample* by a resolver registered under a ``kind``
  (e.g. ``"time"``), so the same template adapts to each sample.

This module is intentionally free of Qt and flowkit so it can be unit-tested in
isolation and reused from any process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class SampleContext:
    """Per-sample information a dynamic resolver may need.

    ``channel_ranges`` maps a channel name to its ``(min, max)`` in the same
    coordinate space as gate dimensions. Resolvers read only what they need, so
    new dynamic kinds can be added without changing this structure.
    """

    channel_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class DimensionSpec:
    """A single gate dimension.

    ``mode == 'absolute'``: use ``(min, max)`` directly (display coordinates).
    ``mode == 'dynamic'`` : resolve ``(min, max)`` per sample via the resolver
    registered for ``kind``.
    """

    channel: str
    mode: str = "absolute"  # 'absolute' | 'dynamic'
    min: float | None = None
    max: float | None = None
    kind: str | None = None  # used when dynamic, e.g. 'time'
    params: dict = field(default_factory=dict)

    def is_dynamic(self) -> bool:
        return self.mode == "dynamic"


# --- Resolver registry -------------------------------------------------------

Resolver = Callable[[dict, SampleContext, str], tuple[float, float]]
_RESOLVERS: dict[str, Resolver] = {}


def register_dynamic_resolver(kind: str, resolver: Resolver) -> None:
    """Register a resolver for a dynamic-dimension ``kind`` (extensibility hook)."""
    _RESOLVERS[kind] = resolver


def get_dynamic_resolver(kind: str) -> Resolver:
    try:
        return _RESOLVERS[kind]
    except KeyError as exc:
        raise KeyError(
            f"No dynamic gate resolver registered for kind {kind!r}. "
            f"Registered kinds: {sorted(_RESOLVERS)}"
        ) from exc


def resolve_spec(spec: DimensionSpec, context: SampleContext) -> tuple[float, float]:
    """Resolve a dimension spec to an absolute ``(min, max)`` for one sample."""
    if not spec.is_dynamic():
        return (spec.min, spec.max)
    resolver = get_dynamic_resolver(spec.kind)
    return resolver(spec.params, context, spec.channel)


# --- Built-in resolvers ------------------------------------------------------

def _time_resolver(params: dict, context: SampleContext, channel: str) -> tuple[float, float]:
    """Resolve a Time gate expressed as fractions of the sample's own range.

    ``params``: ``{'min_frac': 0.0..1.0, 'max_frac': 0.0..1.0}``. Each sample's
    own ``(min, max)`` for ``channel`` is used, so every sample gets its own
    absolute Time window — replacing the current global-max + clamp workaround.
    """
    lo, hi = context.channel_ranges[channel]
    span = hi - lo
    min_frac = params.get("min_frac", 0.0)
    max_frac = params.get("max_frac", 1.0)
    return (lo + min_frac * span, lo + max_frac * span)


register_dynamic_resolver("time", _time_resolver)


# --- Template model + persistence (Phase 2) ---------------------------------

DEFAULT_TEMPLATE_NAME = "default"


def dynamic_key(gate_id: str, channel: str) -> str:
    """Stable key for a dynamic dimension within a template/mode."""
    return f"{gate_id}|{channel}"


@dataclass
class GatingTemplate:
    """A named gating template.

    The base hierarchy is stored as GatingML (``raw_gml`` / ``unmixed_gml``);
    ``dynamic_dimensions`` holds the specs GatingML cannot express, keyed by
    mode then ``dynamic_key(gate_id, channel)``.
    """

    name: str
    raw_gml: str = ""
    unmixed_gml: str = ""
    dynamic_dimensions: dict = field(default_factory=lambda: {"raw": {}, "unmixed": {}})

    def to_dict(self) -> dict:
        return {
            "raw_gml": self.raw_gml,
            "unmixed_gml": self.unmixed_gml,
            "dynamic_dimensions": self.dynamic_dimensions,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "GatingTemplate":
        dyn = data.get("dynamic_dimensions") or {}
        dyn.setdefault("raw", {})
        dyn.setdefault("unmixed", {})
        return cls(
            name=name,
            raw_gml=data.get("raw_gml", ""),
            unmixed_gml=data.get("unmixed_gml", ""),
            dynamic_dimensions=dyn,
        )


def build_default_template(raw_gml: str, unmixed_gml: str) -> GatingTemplate:
    """Synthesize the ``default`` template from legacy experiment gating.

    All dimensions stay absolute, so gating output is identical to today.
    """
    return GatingTemplate(
        name=DEFAULT_TEMPLATE_NAME,
        raw_gml=raw_gml or "",
        unmixed_gml=unmixed_gml or "",
    )


def migrate_cytometry_templates(cytometry: dict) -> dict:
    """Return the ``gating_templates`` dict for an experiment's cytometry.

    Old ``.kit`` files (no ``gating_templates``) get a single ``default``
    template synthesized from the legacy ``raw_gating`` / ``gating`` GML.
    Non-destructive: existing templates are returned unchanged and legacy
    fields are left in place.
    """
    templates = cytometry.get("gating_templates")
    if templates:
        return templates
    default = build_default_template(
        cytometry.get("raw_gating", ""),
        cytometry.get("gating", ""),
    )
    return {default.name: default.to_dict()}


def template_for_sample(sample_path: str, samples: dict) -> str:
    """Template id assigned to a sample, defaulting to ``default``."""
    assignments = samples.get("sample_template_assignments", {})
    return assignments.get(sample_path, DEFAULT_TEMPLATE_NAME)
