"""Pretrained linear quality probes on SimSiam hole embeddings, recalibrated per grid.

A probe is a logistic regression (StandardScaler + LogisticRegression) trained offline
on a curated grid.

Export a probe trained by nav_dqn/build_probe_table.py:

    python -m Smartscope.core.quality_probe probe_model.joblib config/smartscope/navigation_probes/ns39_3.json --name NS39_3
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class LinearProbe:
    name: str
    coef: np.ndarray
    intercept: float
    meta: Dict = field(default_factory=dict)

    @property
    def emb_dim(self) -> int:
        return len(self.coef)

    def logit(self, embeddings: np.ndarray) -> np.ndarray:
        return embeddings @ self.coef + self.intercept

    @classmethod
    def from_json(cls, file: Path) -> 'LinearProbe':
        data = json.loads(Path(file).read_text())
        return cls(name=data['name'], coef=np.asarray(data['coef'], dtype=float),
                   intercept=float(data['intercept']), meta=data.get('meta', {}))

    def to_json(self, file: Path):
        Path(file).write_text(json.dumps(dict(name=self.name, coef=self.coef.tolist(),
                                              intercept=self.intercept, meta=self.meta)))


@lru_cache(maxsize=None)
def load_probes(directories: Tuple[Path, ...]) -> List[LinearProbe]:
    """Load every probe JSON found in the directories. A file in an earlier directory
    overrides a file with the same name in a later one (custom config before default)."""
    files = {}
    for directory in reversed(directories):
        if directory.is_dir():
            files.update({f.name: f for f in sorted(directory.glob('*.json'))})
    probes = []
    for file in files.values():
        try:
            probes.append(LinearProbe.from_json(file))
        except Exception:
            logger.exception(f'Failed to load quality probe {file}, skipping.')
    return probes


@dataclass
class Calibration:
    probes: List[LinearProbe]
    slopes: np.ndarray
    intercept: float
    n_good: int = 0
    n_bad: int = 0

    @property
    def is_calibrated(self) -> bool:
        return self.n_good > 0 and self.n_bad > 0

    def probe_logits(self, embeddings: np.ndarray) -> np.ndarray:
        return np.column_stack([probe.logit(embeddings) for probe in self.probes])

    def predict(self, embeddings: np.ndarray) -> np.ndarray:
        """P(good) for each row of embeddings."""
        return _sigmoid(self.probe_logits(embeddings) @ self.slopes + self.intercept)

    def __str__(self):
        terms = ' + '.join(f'{a:.3g}*{p.name}' for a, p in zip(self.slopes, self.probes))
        source = f'{self.n_good} good / {self.n_bad} bad labels' if self.is_calibrated else 'uncalibrated prior'
        return f'logit P = {terms} + {self.intercept:.3g} ({source})'


def fit_calibration(logits: np.ndarray, labels: np.ndarray, prior: np.ndarray,
                    l2: float = 1.0, n_iter: int = 50) -> Tuple[np.ndarray, float]:
    """Penalised logistic regression of labels on probe logits, by Newton's method.
    The slopes are shrunk towards ``prior``; the intercept is (almost) free."""
    X = np.column_stack([logits, np.ones(len(logits))])
    target = np.append(prior, 0.0)
    penalty = np.append(np.full(len(prior), l2), 1e-6)
    theta = target.copy()
    for _ in range(n_iter):
        p = _sigmoid(X @ theta)
        grad = X.T @ (p - labels) + penalty * (theta - target)
        hessian = (X * (p * (1 - p))[:, None]).T @ X + np.diag(penalty)
        step = np.linalg.solve(hessian, grad)
        theta -= step
        if np.abs(step).max() < 1e-8:
            break
    return theta[:-1], float(theta[-1])


def calibrate(probes: Sequence[LinearProbe], embeddings: np.ndarray, labels: np.ndarray,
              min_per_class: int = 2, l2: float = 1.0) -> Optional[Calibration]:
    """Recalibrate the probes on a grid's labelled holes (labels: 1 good, 0 bad).

    Falls back to the prior (mean of the probe logits) until there are at least
    ``min_per_class`` good and bad labels. Returns None when every fitted slope is
    non-positive, i.e. the probes rank this grid's holes the wrong way round.
    """
    probes = list(probes)
    prior = np.full(len(probes), 1.0 / len(probes))
    labels = np.asarray(labels, dtype=float)
    n_good, n_bad = int(labels.sum()), int(len(labels) - labels.sum())
    if n_good < min_per_class or n_bad < min_per_class:
        return Calibration(probes, prior, 0.0)
    calibration = Calibration(probes, prior, 0.0, n_good=n_good, n_bad=n_bad)
    calibration.slopes, calibration.intercept = fit_calibration(
        calibration.probe_logits(embeddings), labels, prior, l2=l2)
    if np.all(calibration.slopes <= 0):
        logger.warning(f'Quality probes anti-correlate with this grid\'s labels: {calibration}')
        return None
    return calibration


def export_sklearn_probe(joblib_file: Path, out_file: Path, name: str) -> LinearProbe:
    """Fold a saved StandardScaler + LogisticRegression pipeline into a LinearProbe JSON."""
    import joblib
    saved = joblib.load(joblib_file)
    scaler, regression = saved['model'][0], saved['model'][-1]
    coef = regression.coef_.ravel() / scaler.scale_
    intercept = float(regression.intercept_[0] - scaler.mean_ @ coef)
    meta = {key: value for key, value in saved.items() if key != 'model'}
    meta['n_features'] = len(meta.pop('feature_cols', coef))
    probe = LinearProbe(name=name, coef=coef, intercept=intercept, meta=meta)
    probe.to_json(out_file)
    return probe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export a probe_model.joblib to a navigation probe JSON.')
    parser.add_argument('joblib_file', type=Path)
    parser.add_argument('out_file', type=Path)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    probe = export_sklearn_probe(args.joblib_file, args.out_file, args.name)
    print(f'Wrote {args.out_file}: {probe.name}, {probe.emb_dim} dims, meta {probe.meta}')
