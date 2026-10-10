import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error


class TrendModel:
    def __init__(self):
        self.model = LinearRegression()

    def train(self, X, y):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if X.ndim != 2 or y.ndim != 1 or len(X) != len(y) or len(X) < 2:
            raise ValueError("Trend training requires a 2D feature matrix, matching target vector and at least two rows.")
        self.model.fit(X, y)
        predicted = self.model.predict(X)
        return {"mse": float(mean_squared_error(y, predicted)), "samples": len(X)}

    def _calculate_slope(self, values):
        series = np.asarray(values, dtype=float)
        if series.ndim != 1 or series.size < 2:
            raise ValueError("insufficient_temporal_data")
        x = np.arange(series.size, dtype=float)
        # Use a proper time-indexed linear fit to estimate the change in score over time.
        model = LinearRegression()
        model.fit(x.reshape(-1, 1), series)
        return float(model.coef_[0])

    def predict_trend(self, features):
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or values.size < 2:
            raise ValueError("insufficient_temporal_data")
        return self._calculate_slope(values)

    def evaluate_student_trajectory(self, values):
        series = np.asarray(values, dtype=float)
        if series.ndim != 1 or series.size < 2:
            raise ValueError("insufficient_temporal_data")
        slope = self._calculate_slope(series)
        return {
            "slope": slope,
            "trajectory": series.tolist(),
            "points_analyzed": int(series.size),
        }