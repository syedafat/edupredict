import numpy as np
from sklearn.linear_model import LinearRegression

class DemandModel:
    def __init__(self):
        self.model = LinearRegression()

    def train(self, X, y):
        X = np.asarray(X)
        y = np.asarray(y)
        if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
            raise ValueError('X must be a non-empty 2D matrix and y must have the same number of rows.')
        self.model.fit(X, y)
        return {'score': float(self.model.score(X, y)), 'samples': len(X)}

    def predict_demand(self, features):
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise ValueError('features must be a non-empty list of numbers.')
        return float(self.model.predict(values.reshape(1, -1))[0])