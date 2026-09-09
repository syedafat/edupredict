import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.exceptions import NotFittedError


class AnomalyDetector:
    def __init__(self, contamination=0.05):
        self.model = IsolationForest(contamination=contamination, random_state=42)
        self._fitted = False

    def fit_predict(self, data):
        """Fit the model and return predictions (-1 for anomaly, 1 for normal)."""
        data = np.asarray(data, dtype=float)
        if data.ndim != 2 or len(data) < 2:
            raise ValueError('Anomaly training requires at least two rows of numeric data.')
        predictions = self.model.fit_predict(data)
        self._fitted = True
        return predictions

    def train(self, data):
        predictions = self.fit_predict(data)
        return {
            'samples': len(predictions),
            'anomalies': int(np.sum(predictions == -1)),
        }

    def predict_single(self, features):
        """
        Return True if the given feature vector is an anomaly.
        Raises RuntimeError if the model has not been fitted yet.
        """
        if not self._fitted:
            raise RuntimeError(
                "AnomalyDetector has not been fitted. "
                "Call fit_predict() with training data before calling predict_single()."
            )
        try:
            values = np.asarray(features, dtype=float)
            if values.ndim != 1 or values.size == 0:
                raise ValueError('features must be a non-empty list of numbers.')
            res = self.model.predict(values.reshape(1, -1))
            return res[0] == -1
        except NotFittedError:
            raise RuntimeError(
                "AnomalyDetector sklearn model is not fitted. "
                "This should not happen if fit_predict() was called successfully."
            )
