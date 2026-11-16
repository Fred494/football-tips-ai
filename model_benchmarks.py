"""Football features and chronological benchmark helpers."""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson, skellam
from sklearn.linear_model import PoissonRegressor


FORM_WINDOW = 10


def recent_strength(team, games, opponent_ratings, window=FORM_WINDOW):
    """Use the pre-match opponent Elo to reward points against stronger sides."""
    games = games[-window:]
    if not games:
        return 1.35, 0.
    opponents = np.asarray(opponent_ratings[-len(games):])
    points = []
    for match in games:
        home, away = match['score']
        scored, conceded = (home, away) if match['home'] == team else (away, home)
        points.append(3 if scored > conceded else int(scored == conceded))
    weights = np.clip(10 ** ((opponents - 1500.) / 800), .5, 2.)
    return float(np.dot(weights, points) / len(games)), float(opponents.mean() - 1500.)


class EloGoals:
    """Poisson goal rates from Elo, optionally corrected for 0–0, 1–0, 0–1, 1–1."""
    def __init__(self, correction=False, neutral_index=None):
        self.correction = correction
        self.neutral_index = neutral_index
        self.rho = 0.

    def inputs(self, x):
        arr = np.asarray(x)
        elo = arr[:, 0] / 400
        return elo[:, None] if self.neutral_index is None else np.column_stack(
            (elo, arr[:, self.neutral_index]))

    def fit(self, x, scores):
        inputs = self.inputs(x)
        scores = np.asarray(scores)
        self.models = [PoissonRegressor(alpha=.02).fit(inputs, scores[:, i]) for i in range(2)]
        if self.correction:
            h, a = self.rates(inputs)
            hs, aws = scores.T
            coefficient = np.select(
                [(hs == 0) & (aws == 0), (hs == 1) & (aws == 0),
                 (hs == 0) & (aws == 1), (hs == 1) & (aws == 1)],
                [-h * a, a, h, -1.])
            self.rho = minimize_scalar(
                lambda rho: -np.log1p(coefficient * rho).mean(),
                bounds=(-min(.25, .99 / max(h.max(), a.max())),
                        min(.25, .99 / (h * a).max())), method='bounded').x
        return self

    def rates(self, inputs):
        return [np.clip(model.predict(inputs), .05, 6.) for model in self.models]

    def predict_proba(self, x):
        h, a = self.rates(self.inputs(x))
        rho = np.clip(self.rho, -.99 / np.maximum(h, a), .99 / (h * a))
        # Low-score changes preserve total mass and shift equal mass from each win into draws.
        change = poisson.pmf(0, h) * poisson.pmf(0, a) * h * a * rho
        away = skellam.cdf(-1, h, a) + change
        home = skellam.sf(0, h, a) + change
        return np.column_stack((home, 1 - home - away, away))


def market_metrics(p, y):
    result = {}
    for market, column in [('1X', 2), ('X2', 0)]:
        score, hits = 1 - p[:, column], y != column
        bands = []
        for low, high in zip([0, .60, .70, .80, .85, .90, .95], [.60, .70, .80, .85, .90, .95, 1.01]):
            mask = (score >= low) & (score < high)
            if mask.any():
                bands.append(dict(lo=low, hi=min(high, 1), n=int(mask.sum()),
                                  expected=float(score[mask].mean()), observed=float(hits[mask].mean())))
        eligible = score >= .85
        error = (score - hits) ** 2
        chance = np.clip(np.where(hits, score, 1 - score), 1e-9, 1)
        result[market] = dict(brier=float(error.mean()), logLoss=float(-np.log(chance).mean()),
                              bands=bands, above=int(eligible.sum()),
                              hitAbove=float(hits[eligible].mean()) if eligible.any() else None)
    return result
