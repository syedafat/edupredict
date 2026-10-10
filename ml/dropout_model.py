"""
ml/dropout_model.py
===================
Academic Risk / Low Performance Proxy Classifier for EduPredict.

Scientific Note:
In the absence of longitudinal student withdrawal/dropout ground-truth labels,
this model classifies Academic Failure Risk (expected final grade < 50%).
It is explicitly labeled as a proxy and never claimed as direct dropout truth.
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score


class DropoutModel:
    def __init__(self, n_estimators=100, random_state=42):
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model = RandomForestClassifier(n_estimators=self.n_estimators, random_state=self.random_state)

    def train(self, X, y):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int)
        if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
            raise ValueError('X must be a non-empty 2D matrix and y must have the same number of rows.')
        if np.unique(y).size < 2:
            raise ValueError('Dropout training requires at least two target classes.')

        if len(X) < 5:
            self.model.fit(X, y)
            preds = self.model.predict(X)
            probs = self.model.predict_proba(X)[:, 1] if self.model.classes_.size > 1 else np.zeros(len(X))
            return {
                'accuracy': float(accuracy_score(y, preds)),
                'f1': float(f1_score(y, preds, zero_division=0)),
                'precision': float(precision_score(y, preds, zero_division=0)),
                'recall': float(recall_score(y, preds, zero_division=0)),
                'roc_auc': float(roc_auc_score(y, probs)) if np.unique(y).size > 1 else 0.5,
                'is_dropout_ground_truth': False,
                'proxy_type': 'academic_failure_risk',
                'samples': len(X),
            }

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=self.random_state, stratify=y
        )
        self.model.fit(X_train, y_train)
        predictions = self.model.predict(X_test)
        classes = list(self.model.classes_)
        positive_idx = classes.index(1) if 1 in classes else (classes.index('1') if '1' in classes else 0)
        probabilities = self.model.predict_proba(X_test)[:, positive_idx]

        accuracy = float(accuracy_score(y_test, predictions))
        f1 = float(f1_score(y_test, predictions, zero_division=0))
        precision = float(precision_score(y_test, predictions, zero_division=0))
        recall = float(recall_score(y_test, predictions, zero_division=0))
        try:
            roc_auc = float(roc_auc_score(y_test, probabilities))
        except Exception:
            roc_auc = 0.5

        return {
            'accuracy': accuracy,
            'f1': f1,
            'precision': precision,
            'recall': recall,
            'roc_auc': roc_auc,
            'is_dropout_ground_truth': False,
            'proxy_type': 'academic_failure_risk',
            'samples': len(X),
        }

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