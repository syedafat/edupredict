"""
ml/performance_model.py
=======================
Academic Performance Prediction Model for EduPredict.

Predicts expected final grade score (0–100% scale) based on canonical
educational indicators (attendance, continuous assessment, LMS activity, GPA, etc.).
"""
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.dummy import DummyRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


class PerformanceModel:
    def __init__(self, n_estimators=100, random_state=42):
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model = RandomForestRegressor(n_estimators=self.n_estimators, random_state=self.random_state)

    def train(self, X, y):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
            raise ValueError('X must be a non-empty 2D matrix and y must have the same number of rows.')

        # Baseline dummy model for honest benchmark comparison
        dummy = DummyRegressor(strategy="mean")
        dummy.fit(X, y)
        dummy_preds = dummy.predict(X)
        baseline_mae = float(mean_absolute_error(y, dummy_preds))
        baseline_rmse = float(np.sqrt(mean_squared_error(y, dummy_preds)))

        if len(X) < 5:
            self.model.fit(X, y)
            preds = self.model.predict(X)
            mae = float(mean_absolute_error(y, preds))
            rmse = float(np.sqrt(mean_squared_error(y, preds)))
            r2 = float(r2_score(y, preds)) if len(X) > 1 else 1.0
            return {
                'mae': mae,
                'rmse': rmse,
                'r2': r2,
                'baseline_mae': baseline_mae,
                'baseline_rmse': baseline_rmse,
                'samples': len(X),
            }

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=self.random_state
        )
        self.model.fit(X_train, y_train)
        predictions = self.model.predict(X_test)
        mae = float(mean_absolute_error(y_test, predictions))
        rmse = float(np.sqrt(mean_squared_error(y_test, predictions)))
        r2 = float(r2_score(y_test, predictions)) if len(np.unique(y_test)) > 1 else 0.0

        return {
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'baseline_mae': baseline_mae,
            'baseline_rmse': baseline_rmse,
            'samples': len(X),
        }

    def predict(self, features):
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise ValueError('features must be a non-empty list of numbers.')
        pred = float(self.model.predict(values.reshape(1, -1))[0])
        # Return score in original 0–100% grade units
        return float(np.clip(pred, 0.0, 100.0))