"""A .kit saved on another operating system keeps its per-sample settings.

Sample keys are experiment-relative paths: 'Raw/sub/A.fcs' on macOS and Linux,
'Raw\\sub\\A.fcs' on Windows. A .kit stores them with '/' and they are read
back with this system's separator, so tags, AF assignments and custom gates
saved on one system still match the samples found on another.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import af_synthetic as syn  # noqa: E402

from honeychrome.experiment_model import ExperimentModel  # noqa: E402

FOREIGN_SEP = '/' if os.sep == '\\' else '\\'
SAMPLES = ('Raw/sub/A.fcs', 'Raw/sub/B.fcs', 'Raw/C.fcs')


def native(key):
    return str(Path(key))


def foreign(key):
    return key.replace('/', FOREIGN_SEP)


@pytest.fixture
def kit_from_other_system(tmp_path):
    """A .kit whose sample-path fields use the other system's separator."""
    kit = tmp_path / 'exp.kit'
    model = ExperimentModel()
    model.create(kit)
    for n, key in enumerate(SAMPLES):
        syn.write_raw_fcs(tmp_path / 'exp' / key, syn.raw_events(50, seed=n))

    data = json.loads(kit.read_text(encoding='utf-8'))
    a, b, c = (foreign(k) for k in SAMPLES)
    data['samples'].update({
        'all_samples': {a: 'A', b: 'B', c: 'C'},
        'all_sample_nevents': {a: 50, b: 50, c: 50},
        'unstained_samples': [a],
        'bead_samples': [b],
        'bead_checked_samples': [a, b, c],
        'sample_af_profiles': {c: ['AF one']},
        'bead_scatter_scores': {a: 0.1},
        'bead_scatter_centres': {b: [1.0, 2.0]},
    })
    data['cytometry']['raw_custom_sample_gates'] = {a: {'Cells': '<gml/>'}}
    data['cytometry']['unmixed_custom_sample_gates'] = {c: {'Cells': '<gml/>'}}
    data['process']['af_profiles'] = {'AF one': {'spectra': [[1.0]], 'source_fcs': a, 'channel_names': ['D1-A']}}
    data['process']['noise_model'] = {'unstained': a}
    data['process']['spectral_corrections'] = {
        'base_fingerprint': 'x',
        'groups': {'g': {'samples': [b, c], 'unstained': a, 'events': {b: 10, c: 20}}},
    }
    kit.write_text(json.dumps(data), encoding='utf-8')
    return kit


def _load(kit):
    model = ExperimentModel()
    model.load(kit)
    model.scan_sample_tree(sample_name_source_instance='filename')
    return model


def test_tags_and_assignments_survive_opening_on_another_system(kit_from_other_system):
    model = _load(kit_from_other_system)
    a, b, c = (native(k) for k in SAMPLES)
    s, cy, p = model.samples, model.cytometry, model.process

    assert set(s['all_samples']) == {a, b, c}
    assert s['unstained_samples'] == [a]
    assert b in s['bead_samples']
    assert set(s['bead_checked_samples']) >= {a, b, c}
    assert s['sample_af_profiles'] == {c: ['AF one']}
    assert list(s['bead_scatter_scores']) == [a] and list(s['bead_scatter_centres']) == [b]
    assert list(cy['raw_custom_sample_gates']) == [a]
    assert list(cy['unmixed_custom_sample_gates']) == [c]
    assert p['af_profiles']['AF one']['source_fcs'] == a
    assert p['noise_model']['unstained'] == a
    group = p['spectral_corrections']['groups']['g']
    assert group['samples'] == [b, c] and group['unstained'] == a and set(group['events']) == {b, c}


def test_saved_kit_stores_sample_paths_with_forward_slashes(kit_from_other_system):
    model = _load(kit_from_other_system)
    model.save()

    saved = json.loads(Path(kit_from_other_system).read_text(encoding='utf-8'))
    a, b, c = SAMPLES
    assert set(saved['samples']['all_samples']) == {a, b, c}
    assert saved['samples']['unstained_samples'] == [a]
    assert saved['samples']['sample_af_profiles'] == {c: ['AF one']}
    assert list(saved['cytometry']['raw_custom_sample_gates']) == [a]
    assert saved['process']['af_profiles']['AF one']['source_fcs'] == a
    assert saved['process']['spectral_corrections']['groups']['g']['samples'] == [b, c]


def test_saving_does_not_change_the_open_experiment(kit_from_other_system):
    model = _load(kit_from_other_system)
    before = json.dumps([model.samples, model.cytometry, model.process], sort_keys=True)
    model.save()
    assert json.dumps([model.samples, model.cytometry, model.process], sort_keys=True) == before
    assert native(SAMPLES[0]) in model.samples['all_samples']
