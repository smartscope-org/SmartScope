"""Consensus of re-registration pairs after a grid reload.

Medium mag cross-correlation peaks are weak on many grids: correct matches can score below the
per-image thresholds (peak/margin) while wrong ones score as high. What separates them is
geometry: correct pairs all follow one rigid stage transform (translation + small rotation),
wrong ones land at random. Each candidate is an (old, new) stage position pair; a hypothesis is
built from one candidate (translation) or two candidates on different squares (rotation +
translation), and the hypothesis that the most squares agree with, within ``tol_um``, wins.
"""
from itertools import combinations
from typing import List, Optional

import numpy as np


def fit_rigid(old: np.ndarray, new: np.ndarray, rotation: bool = True) -> np.ndarray:
    """Least-squares rigid transform (2x3) mapping old -> new. Translation only if rotation is
    False or there is a single point."""
    old = np.asarray(old, dtype=float).reshape(-1, 2)
    new = np.asarray(new, dtype=float).reshape(-1, 2)
    co, cn = old.mean(axis=0), new.mean(axis=0)
    R = np.eye(2)
    if rotation and len(old) >= 2:
        H = (old - co).T @ (new - cn)
        U, _, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:  # no reflection
            Vt[-1] *= -1
            R = Vt.T @ U.T
    t = cn - R @ co
    return np.hstack([R, t[:, None]])


def apply(T: np.ndarray, pts) -> np.ndarray:
    pts = np.asarray(pts, dtype=float)
    return pts @ T[:, :2].T + T[:, 2]


def rotation_deg(T: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(T[1, 0], T[0, 0])))


def spread_um(points) -> float:
    """Largest distance between two of the points."""
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(p) < 2:
        return 0.0
    return float(max(np.linalg.norm(a - b) for a, b in combinations(p, 2)))


def find_consensus(candidates: List[dict], tol_um: float = 1.25, min_rotation_baseline_um: float = 200.0,
                   max_rotation_deg: float = 3.0) -> Optional[dict]:
    """Best transform supported by the candidates.

    candidates: dicts with 'square' (id), 'old' and 'new' (stage xy, um), optional 'strong'.
    Rotation is only fitted when the supporting squares span ``min_rotation_baseline_um``; closer
    pairs leave it dominated by measurement noise.

    Returns None if there are no candidates, else a dict with 'T' (2x3), 'inliers' (indices),
    'squares' (distinct inlier squares), 'spread_um', 'rotation_deg', 'rms_um'.
    """
    if not candidates:
        return None
    old = np.array([c['old'] for c in candidates], dtype=float)
    new = np.array([c['new'] for c in candidates], dtype=float)
    sq = [c['square'] for c in candidates]
    strong = np.array([bool(c.get('strong')) for c in candidates])

    hypotheses = [fit_rigid(old[i], new[i], rotation=False) for i in range(len(candidates))]
    for i, j in combinations(range(len(candidates)), 2):
        if sq[i] != sq[j] and np.linalg.norm(old[i] - old[j]) >= min_rotation_baseline_um:
            T = fit_rigid(old[[i, j]], new[[i, j]], rotation=True)
            if abs(rotation_deg(T)) <= max_rotation_deg:
                hypotheses.append(T)

    def evaluate(T):
        err = np.linalg.norm(apply(T, old) - new, axis=1)
        inl = np.flatnonzero(err <= tol_um)
        # Score: distinct squares agreeing, then strong matches among them, then tighter fit
        squares = {sq[k] for k in inl}
        return (len(squares), int(strong[inl].sum()), -float(err[inl].mean()) if len(inl) else 0.0), inl

    def select(hyps):
        best_score, best_inl = None, None
        for T in hyps:
            score, inl = evaluate(T)
            if best_score is None or score > best_score:
                best_score, best_inl = score, inl
        return best_score, best_inl

    best_score, best_inl = select(hypotheses)
    if best_score[0] < 3:
        # Rotation + translation from 2 points fits any 2 squares exactly: 2 squares "agreeing" that
        # way proves nothing. Below 3 squares only translation agreement counts.
        best_score, best_inl = select(hypotheses[:len(candidates)])

    def n_squares(idx):
        return len({sq[k] for k in idx})

    # Refit on the inliers, iterate once more in case the refit picks up / drops candidates
    for _ in range(2):
        rot = spread_um(old[best_inl]) >= min_rotation_baseline_um and n_squares(best_inl) >= 3
        T = fit_rigid(old[best_inl], new[best_inl], rotation=rot)
        if abs(rotation_deg(T)) > max_rotation_deg:
            T = fit_rigid(old[best_inl], new[best_inl], rotation=False)
        score, inl = evaluate(T)
        if len(inl) == 0:
            break
        best_inl = inl
    err = np.linalg.norm(apply(T, old[best_inl]) - new[best_inl], axis=1)
    squares = sorted({sq[k] for k in best_inl}, key=str)
    return {
        'T': T,
        'inliers': [int(k) for k in best_inl],
        'squares': squares,
        'spread_um': spread_um(old[best_inl]),
        'rotation_deg': rotation_deg(T),
        'rms_um': float(np.sqrt(np.mean(err ** 2))) if len(err) else 0.0,
    }


class ConsensusPlanner:
    """Decides which square to image next, where (prediction), and when to stop.

    squares_xy: {square id: pre-reload stage xy}. Order of work:
      1. No prediction yet: squares closest to the stage origin first.
      2. Then outward: the unvisited square closest to the agreeing squares while at least
         ``min_step_um`` away, so the baseline grows by steps small enough (``max_step_um``
         guides it) for the prediction error from an unknown small rotation to stay within the
         search window. With ``retry_unpredicted``, squares imaged while there was no prediction
         are retried once.
    Done when ``n_squares`` distinct squares agree and they span ``min_spread_um``.
    """

    def __init__(self, squares_xy: dict, n_squares: int = 3, tol_um: float = 1.25,
                 min_step_um: float = 150.0, min_rotation_baseline_um: float = 200.0,
                 min_spread_um: float = 150.0, max_rotation_deg: float = 3.0,
                 retry_unpredicted: bool = False):
        self.squares_xy = {k: np.asarray(v, dtype=float) for k, v in squares_xy.items()}
        self.n_squares = n_squares
        self.tol_um = tol_um
        self.min_step_um = min_step_um
        self.min_rotation_baseline_um = min_rotation_baseline_um
        self.min_spread_um = min_spread_um
        self.max_rotation_deg = max_rotation_deg
        # Retry squares imaged before there was a prediction once one exists. Off by default: on the
        # BD2_4 reloads the retried square failed again and only cost time.
        self.retry_unpredicted = retry_unpredicted
        self.candidates: List[dict] = []
        self.visited: List = []
        self.retry: List = []
        self._unpredicted: List = []
        self._consensus = None

    def add(self, square, candidates: List[dict], predicted: bool):
        self.visited.append(square)
        self.candidates.extend(candidates)
        self._consensus = find_consensus(self.candidates, self.tol_um, self.min_rotation_baseline_um,
                                         self.max_rotation_deg)
        if not predicted:
            self._unpredicted.append(square)
        P = self.prediction()
        if not self.retry_unpredicted:
            self._unpredicted = []
        if self._unpredicted and P is not None:
            # A prediction is now available: retry, once, the squares imaged without one that have
            # no candidate agreeing with it
            def agrees(s):
                return any(np.linalg.norm(apply(P, c['old']) - c['new']) <= self.tol_um
                           for c in self.candidates if c['square'] == s)
            self.retry.extend(s for s in self._unpredicted if not agrees(s))
            self._unpredicted = []

    def consensus(self) -> Optional[dict]:
        return self._consensus

    def agreeing_squares(self) -> list:
        c = self._consensus
        return list(c['squares']) if c is not None and len(c['squares']) >= 2 else []

    def prediction(self) -> Optional[np.ndarray]:
        """2x3 old -> new transform to acquire at, or None. From the consensus once 2 squares agree,
        else from strong (above threshold) matches."""
        if self.agreeing_squares():
            return self._consensus['T']
        strong = [c for c in self.candidates if c.get('strong')]
        if strong:
            return fit_rigid([c['old'] for c in strong], [c['new'] for c in strong], rotation=False)
        return None

    def done(self) -> bool:
        c = self._consensus
        return c is not None and len(c['squares']) >= self.n_squares and c['spread_um'] >= self.min_spread_um

    def result_pairs(self):
        """(old, new) positions of the agreeing candidates, or of the strong ones if not done."""
        if self.done():
            sel = [self.candidates[k] for k in self._consensus['inliers']]
        else:
            sel = [c for c in self.candidates if c.get('strong')]
        return [c['old'] for c in sel], [c['new'] for c in sel]

    def next_square(self):
        if self.retry:
            return self.retry.pop(0)
        unvisited = [s for s in self.squares_xy if s not in self.visited]
        if not unvisited:
            return None
        if self.prediction() is None:
            return min(unvisited, key=lambda s: np.linalg.norm(self.squares_xy[s]))
        ref = self.agreeing_squares() or list({c['square'] for c in self.candidates if c.get('strong')})
        ref_xy = [self.squares_xy[s] for s in ref if s in self.squares_xy]
        d = {s: min(np.linalg.norm(self.squares_xy[s] - p) for p in ref_xy) for s in unvisited}
        far_enough = [s for s in unvisited if d[s] >= self.min_step_um]
        if far_enough:
            return min(far_enough, key=lambda s: d[s])
        return max(unvisited, key=lambda s: d[s])
