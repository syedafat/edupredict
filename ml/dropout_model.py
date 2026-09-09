import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

class DropoutModel:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)

    def train(self, X, y):
        X = np.asarray(X)
        y = np.asarray(y)
        if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
            raise ValueError('X must be a non-empty 2D matrix and y must have the same number of rows.')
        if np.unique(y).size < 2:
            raise ValueError('Dropout training requires at least two target classes.')
        if len(X) < 5:
            self.model.fit(X, y)
            return {'accuracy': None, 'samples': len(X)}
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        self.model.fit(X_train, y_train)
        predictions = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, predictions)
        return {'accuracy': float(accuracy), 'samples': len(X)}

    def predict_risk(self, features):
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise ValueError('features must be a non-empty list of numbers.')
        probabilities = self.model.predict_proba(values.reshape(1, -1))[0]
        classes = list(self.model.classes_)
        if 1 in classes:
            return float(probabilities[classes.index(1)])
        if '1' in classes:
            return float(probabilities[classes.index('1')])
        return 0.0