"""Football features and chronological benchmark helpers."""
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import softmax
from scipy.stats import poisson, skellam
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import log_loss


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


class ProbabilityCalibration:
    """Preserve a single 1X2 distribution while calibrating the win/draw odds."""
    def __init__(self, method):
        self.method = method
        self.offsets = {}

    @staticmethod
    def logits(probabilities):
        return np.log(np.clip(probabilities, 1e-9, 1))

    def fit(self, probabilities, outcomes, competitions):
        logits = self.logits(probabilities)
        indicator = np.eye(3)[outcomes]

        def loss(params, base, observed, shrinkage):
            offsets = [params[1], 0., params[2]] if len(params) == 3 else 0.
            calibrated = softmax(base / params[0] + offsets, axis=1)
            cross_entropy = -np.sum(observed * np.log(np.clip(calibrated, 1e-9, 1)))
            return cross_entropy + shrinkage * np.sum(np.square(params[1:]))

        if self.method == 'temperature':
            self.temperature = minimize_scalar(
                lambda t: loss([t], logits, indicator, 0),
                bounds=(.4, 4), method='bounded').x
            self.bias = np.zeros(3)
            return self

        fit = minimize(loss, [1., 0., 0.], args=(logits, indicator, 16),
                       bounds=[(.4, 4), (-1., 1.), (-1., 1.)], method='L-BFGS-B')
        self.temperature = fit.x[0]
        self.bias = np.array([fit.x[1], 0., fit.x[2]])
        if self.method == 'competition':
            pooled = logits / self.temperature + self.bias
            for code in sorted(set(competitions)):
                mask = competitions == code
                if mask.sum() < 60:
                    continue
                fit = minimize(lambda delta: loss([1., *delta], pooled[mask], indicator[mask], 80),
                               [0., 0.], bounds=[(-.5, .5)] * 2, method='L-BFGS-B')
                self.offsets[code] = np.array([fit.x[0], 0., fit.x[1]])
        return self

    def predict(self, probabilities, competitions):
        logits = self.logits(probabilities) / self.temperature + self.bias
        for code, offsets in self.offsets.items():
            logits[competitions == code] += offsets
        return softmax(logits, axis=1)


class ModelBlend:
    def __init__(self, first, second):
        self.first, self.second = first, second

    def predict_proba(self, features):
        return (self.first.predict_proba(features) + self.second.predict_proba(features)) / 2


def select_forecast_model(fitted, p_features, labels, codes, dates, adjust=None):
    """Fit calibration on the earlier dates and choose on later validation dates."""
    if adjust is None:
        adjust = lambda probabilities, mask: probabilities
    unique_dates = sorted(set(dates))
    if len(unique_dates) < 2:
        raise ValueError('Calibration needs two distinct matchdays')
    cut = unique_dates[max(1, int(.6 * len(unique_dates)))]
    earlier = dates < cut
    later = ~earlier
    candidates = []
    base = {}
    for name, model in fitted:
        raw = model.predict_proba(p_features)
        for method in ('temperature', 'outcome bias', 'competition'):
            calibration = ProbabilityCalibration(method).fit(raw[earlier], labels[earlier], codes[earlier])
            forecast = adjust(calibration.predict(raw[later], codes[later]), later)
            metrics = measure_binary_markets(forecast, labels[later])
            validation_loss = log_loss(labels[later], forecast, labels=[0, 1, 2])
            candidates.append((validation_loss, metrics, name, model, method))
        all_matches = np.ones(len(labels), dtype=bool)
        logits = ProbabilityCalibration.logits(raw)
        def baseline_loss(temperature):
            forecast = adjust(softmax(logits / temperature, axis=1), all_matches)
            return log_loss(labels, forecast, labels=[0, 1, 2])
        fit = minimize_scalar(baseline_loss, bounds=(.4, 4), method='bounded')
        calibration = ProbabilityCalibration('temperature')
        calibration.temperature = fit.x
        calibration.bias = np.zeros(3)
        base[name] = (fit.fun, model, calibration)

    _, incumbent_name, incumbent_model, incumbent_calibration = min(
        (loss, name, model, calibration) for name, (loss, model, calibration) in base.items()
        if name != 'Logistic + Elo Poisson blend'
    )
    best = min(candidates, key=lambda c: (c[0], c[1]))
    best_model, best_method = best[3:]
    calibration = ProbabilityCalibration(best_method).fit(best_model.predict_proba(p_features), labels, codes)
    return best[2], best_model, calibration, (incumbent_name, incumbent_model, incumbent_calibration), base


def measure_binary_markets(probabilities, outcomes):
    predicted = 1 - probabilities[:, [2, 0]]
    actual = outcomes[:, None] != np.array([2, 0])
    return float(np.mean((predicted - actual) ** 2))
