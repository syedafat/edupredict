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

    def predict_trend(self, features):
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise ValueError("features must be a non-empty list of numbers.")
        return float(self.model.predict(values.reshape(1, -1))[0])