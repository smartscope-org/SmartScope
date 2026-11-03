import numpy as np

from ..quality_probe import LinearProbe, load_probes, calibrate


def make_probe(name, coef, intercept=0.0):
    return LinearProbe(name=name, coef=np.asarray(coef, dtype=float), intercept=intercept)


def test_probe_json_roundtrip(tmp_path):
    probe = make_probe('a', [0.5, -1.0, 2.0], intercept=0.25)
    probe.to_json(tmp_path / 'a.json')
    loaded = LinearProbe.from_json(tmp_path / 'a.json')
    X = np.random.default_rng(0).normal(size=(5, 3))
    np.testing.assert_allclose(loaded.logit(X), probe.logit(X))


def test_load_probes_custom_overrides_default(tmp_path):
    custom, default = tmp_path / 'custom', tmp_path / 'default'
    custom.mkdir(), default.mkdir()
    make_probe('default_a', [1.0]).to_json(default / 'a.json')
    make_probe('default_b', [1.0]).to_json(default / 'b.json')
    make_probe('custom_a', [1.0]).to_json(custom / 'a.json')
    names = sorted(p.name for p in load_probes((custom, default)))
    assert names == ['custom_a', 'default_b']


def test_calibrate_uses_prior_without_both_classes():
    probes = [make_probe('a', [1.0, 0.0]), make_probe('b', [0.0, 1.0])]
    X = np.random.default_rng(0).normal(size=(10, 2))
    calibration = calibrate(probes, X, np.ones(10))
    assert not calibration.is_calibrated
    np.testing.assert_allclose(calibration.slopes, [0.5, 0.5])
    np.testing.assert_allclose(calibration.predict(X), 1 / (1 + np.exp(-X.mean(axis=1))))


def test_calibrate_weights_the_informative_probe():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 2))
    y = (X[:, 1] + 0.3 * rng.normal(size=200) > 0.5).astype(int)
    probes = [make_probe('noise', [1.0, 0.0]), make_probe('signal', [0.0, 1.0])]
    calibration = calibrate(probes, X, y)
    assert calibration.is_calibrated
    assert calibration.slopes[1] > 1.0 > abs(calibration.slopes[0])
    assert calibration.intercept < 0


def test_calibrate_rejects_anticorrelated_probe():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(100, 1))
    y = (X[:, 0] < 0).astype(int)
    assert calibrate([make_probe('backwards', [1.0])], X, y) is None
