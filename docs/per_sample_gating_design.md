# Per-Sample Gating — Technical Design

**Status:** Draft for review · **Feature branch:** `feature/per-sample-gating`

## 1. Background: how gating works today

Honeychrome currently applies **one gating hierarchy to every sample**.

| Concern | Where | Notes |
|---|---|---|
| In-memory gates | `controller.py` `self.raw_gating`, `self.unmixed_gating` | one `flowkit.GatingStrategy` each, shared by all samples |
| Gate geometry | `functions.py` `define_*_gate()` | `flowkit.Dimension` with **absolute** `range_min`/`range_max` in **display (transformed) coordinates** |
| Persistence | `experiment.cytometry['raw_gating']` / `['gating']` | GatingML strings via `to_gml()` / `from_gml()` ([gml_functions_mod_from_flowkit.py](../src/honeychrome/controller_components/gml_functions_mod_from_flowkit.py)) |
| Fast gating | `controller.py` `calculate_lookup_tables()` | for each gate, run flowkit **once** over a unit grid in transformed space → boolean **lookup table** per `gate_id`; stored in `raw_lookup_tables` / `unmixed_lookup_tables`, **shared across samples** |
| Apply gating | `functions.py` `apply_gates_in_place()` | bin each event with `np.searchsorted(transform.scale, x)`, index the lookup table, multiply by parent mask → `gate_membership = {gate_id: bool array}` |

**The Time problem (the existing per-sample pain):** the Time channel uses the *default* transform (`transform.py` `set_default()`, `xform=None`) whose range depends on each sample's acquisition duration. Today this is worked around by (a) inflating limits to the max across samples (`transform.py` L38 TODO) and (b) clamping out-of-range indices (`functions.py` `apply_gates_in_place` TODO). Both are explicitly marked *"until we implement custom sample gates for time"*.

FlowKit already supports per-sample gates via `add_gate(..., sample_id=...)` / `gate_sample(sample, sample_id=...)`; there are commented attempts in `scripts_and_development_sandboxes/workflow_test.py` and `#todo export/import all sample gates` in the GML helpers.

## 2. Goals & non-goals

**Goals**
- A gate hierarchy is a reusable **template**; a sample is **assigned** a template.
- Multiple samples share a template, but **dynamic dimensions** (initially Time) are **resolved per sample** at apply time — "one template, one resolved instance per sample".
- Editing a gate edits the **template** (decision confirmed with the team).
- The dynamic-dimension mechanism is **extensible** beyond Time (kind-based resolver registry).
- Backward compatible: existing `.kit` files keep working (single implicit template).

**Non-goals (this feature)**
- **No manual per-sample gate override.** A gate edit always edits the template; to gate a sample differently, **assign it a different template**. (Per-sample variation comes only from dynamic dimensions.) A future "detach this sample" override is explicitly deferred.
- Cross-template statistics reconciliation beyond shared gate names.
- Changing the GatingML standard; per-sample/dynamic data is stored **outside** GML.

## 3. Core model

```
GatingTemplate (a "class")
  ├─ base gating hierarchy  (absolute dims, current GatingStrategy / GML)
  └─ dynamic dimension specs: { (gate_id, channel): DimensionSpec(dynamic) }

Sample  ──assigned──►  template_id
   │
   └─ instantiate(template, sample_context) ──► resolved GatingStrategy  (+ per-sample lookup tables for dynamic gates)
```

- **DimensionSpec**: a gate dimension is either
  - `absolute`: fixed `(min, max)` in display coords (today's behaviour), or
  - `dynamic`: `kind` (e.g. `"time"`) + `params` (e.g. `{min_frac, max_frac}` or percentiles), resolved from the sample.
- **Resolver registry**: `kind -> resolver(params, sample_context) -> (min, max)`. New dynamic kinds register a resolver; no core changes needed. (Answers "there may be dynamic dimensions beyond Time".)
- **Instance**: a concrete `GatingStrategy` where dynamic dims are resolved to absolute values for that sample. Instances are **derived and cached**, never persisted.

## 4. Data model & storage (experiment model)

Additive fields in `experiment.cytometry` (default-safe for old files):

```jsonc
"cytometry": {
  "raw_gating":  "<GML>",           // unchanged: template base (absolute dims)
  "gating":      "<GML>",           // unchanged: unmixed template base
  "gating_templates": {             // NEW (optional). Absent => single implicit template = today's behaviour
    "default": {
      "raw_gml":     "<GML>",
      "unmixed_gml": "<GML>",
      "dynamic_dimensions": {       // only non-absolute dims live here
        "raw":     { "<gate_id>|<channel>": {"kind": "time", "params": {"min_frac": 0.0, "max_frac": 1.0}} },
        "unmixed": {}
      }
    }
  }
}
```

Sample → template assignment (additive in `experiment.samples`):
```jsonc
"samples": { "sample_template_assignments": { "<sample_path>": "default" } }  // default template when missing
```

## 5. Runtime pipeline changes

1. **Instantiation** (`gating_templates.py`, new): `instantiate_template_for_sample(template, mode, sample_context)` → `GatingStrategy` with dynamic dims resolved. Absolute-only templates return a value identical to today's `from_gml(...)`.
2. **Lookup tables**: split into
   - **static tables** — gates whose dims are all absolute: computed once per template, shared across its samples (today's cost).
   - **dynamic tables** — gates with ≥1 dynamic dim: computed per (sample, gate) on sample load.
   `apply_gates_in_place()` selects the dynamic table when present, else the static one. This removes the Time index-clamp hack.
3. **`load_sample()` / `initialise_ephemeral_data()`**: build the sample's resolved instance + dynamic lookup tables; keep static tables cached per template.
4. **Statistics**: samples on the same template remain directly comparable (identical gate ids); ties into the per-sample statistics/heatmap work already merged.

## 6. GUI / ease of use

- **Editing a gate edits the template** (confirmed). All samples on that template update. This keeps the common workflow unchanged and simple: users edit gates as they do now.
- **Template management panel** (in the gating hierarchy area): list templates, create/duplicate/rename/delete, and **assign the current sample (or a selection) to a template**. Default: every sample on `"default"`.
- **Dynamic-dimension editing:** for Time (and future kinds), the ROI edits the *relative spec* (e.g. drag Time gate = adjust `min_frac`/`max_frac`), shown with a distinct style/label ("auto-scaled per sample") so users understand it adapts.
- **Clarity aids:** header shows "Template: default"; a tooltip explains that edits affect all samples on the template; dynamic gates get a small "⟳ per-sample" badge.
- **Progressive disclosure:** if a user never touches templates, behaviour is identical to today (single default template) — zero added complexity for the basic case.

## 7. Serialization & compatibility

- `to_gml()` / `from_gml()` stay as-is for the **base** (absolute) hierarchy.
- Dynamic specs + assignments are stored in the additive JSON fields above (outside GML — intentionally, as GatingML can't express them).
- **Migration:** loading an old `.kit` (no `gating_templates`) synthesises a single `"default"` template from the existing `raw_gating`/`gating`, with all dims absolute → behaviour identical to today.

## 8. Phased plan & checkpoints

Each checkpoint is independently testable; ✅ = implemented on this branch so far.

**Phase 1 — Foundation (this commit)**
- [x] C1.1 `DimensionSpec` supports `absolute` and `dynamic(kind, params)`.
- [x] C1.2 Resolver registry; built-in `time` resolver maps relative fractions → absolute using a sample's Time range.
- [x] C1.3 Registering a **new** dynamic kind works without touching core (extensibility).
- [x] C1.4 Two different sample contexts resolve the same dynamic spec to different absolute values.
- [x] C1.5 Absolute specs pass through unchanged.
- [x] C1.6 Unit tests cover C1.1–C1.5 and pass; no existing tests break.

**Phase 2 — Template model + storage (no behaviour change)**
- [x] C2.1 `GatingTemplate` (base GML + dynamic specs) load/save round-trips. *(model + tests done)*
- [x] C2.2 Old `.kit` without templates migrates to a single `default` template. *(`migrate_cytometry_templates` + tests done)*
- [x] C2.3 Sample→template assignment read; missing assignment ⇒ `default`. *(`template_for_sample` + tests done)*
- [x] C2.4 Wire the above into `experiment_model` `create/load/save`; legacy `.kit` files migrate on load (verified against a real pre-feature `.kit`).

**Phase 3 — Runtime instantiation + per-sample lookup tables**
- [ ] C3.1 `instantiate_template_for_sample` returns a `GatingStrategy` equal to today's for absolute-only templates.
- [ ] C3.2 Dynamic (Time) gate produces a per-sample lookup table; `apply_gates_in_place` uses it.
- [ ] C3.3 Time index-clamp hack removed; membership correct across samples with different durations.
- [ ] C3.4 Static tables still shared/cached per template (no perf regression for absolute gates).

**Phase 4 — GUI**
- [ ] C4.1 Template panel: create/duplicate/rename/delete + assign current sample.
- [ ] C4.2 Editing a gate updates the template (all its samples).
- [ ] C4.3 Dynamic gates rendered with per-sample badge; editing adjusts the relative spec.
- [ ] C4.4 Basic case (never open template panel) behaves exactly like today.

**Phase 5 — Statistics/UX polish**
- [ ] C5.1 Statistics/heatmap respect per-sample resolved gates.
- [ ] C5.2 Warnings when comparing samples across templates with non-shared gates.

## 9. File-by-file change list

| File | Change | Phase |
|---|---|---|
| `controller_components/gating_templates.py` (new) | `DimensionSpec`, resolver registry, `resolve_spec`, `instantiate_template_for_sample` | 1,3 |
| `experiment_model.py` | additive `gating_templates`, `sample_template_assignments`; migration from legacy fields | 2 |
| `controller.py` | build/cache per-sample instances + dynamic lookup tables in `initialise_ephemeral_data`/`load_sample`; template-aware `calculate_lookup_tables` | 3 |
| `controller_components/functions.py` | `apply_gates_in_place` selects dynamic vs static table; drop Time clamp | 3 |
| `controller_components/transform.py` | remove Time limit-inflation hack once dynamic Time lands | 3 |
| `gml_functions_mod_from_flowkit.py` | keep base GML; no per-sample data in GML (documented) | 2 |
| `view_components/gating_hierarchy_widget.py` | template panel + assignment UI; per-sample badges | 4 |
| `view_components/regions_of_interest.py` | dynamic-dim ROI edits relative spec | 4 |
| `tests/test_gating_templates.py` (new) | Phase-1 checkpoints | 1 |

## 10. Decisions & remaining questions

- **Edit semantics — DECIDED**: a gate edit always edits the **template**; there is **no** "only this sample" option. Samples differ only by (a) being assigned a different template, or (b) dynamic dimensions. Manual per-sample override is out of scope.
- **Dynamic vocabulary**: start with `time`; keep the registry small and documented. Percentile vs fraction semantics to be decided per kind.
- **Lookup-table memory**: dynamic tables are per (sample, dynamic gate) — cache with sample eviction.
- **Cross-template comparison** in statistics needs guardrails (Phase 5).
