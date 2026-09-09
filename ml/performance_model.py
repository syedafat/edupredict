import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error

class PerformanceModel:
    def __init__(self):
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)

    def train(self, X, y):
        X = np.asarray(X)
        y = np.asarray(y)
        if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
            raise ValueError('X must be a non-empty 2D matrix and y must have the same number of rows.')
        if len(X) < 5:
            self.model.fit(X, y)
            return {'mse': None, 'samples': len(X)}
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        self.model.fit(X_train, y_train)
        predictions = self.model.predict(X_test)
        mse = mean_squared_error(y_test, predictions)
        return {'mse': float(mse), 'samples': len(X)}

    def predict(self, features):
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise ValueError('features must be a non-empty list of numbers.')
        return float(self.model.predict(values.reshape(1, -1))[0])