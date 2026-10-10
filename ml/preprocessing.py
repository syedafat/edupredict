"""
ml/preprocessing.py
===================
Canonical Preprocessing, Feature Pipeline & Target Scaling for EduPredict.

Enforces:
1. Canonical 9-feature schema matching AcademicDataService.
2. Complete isolation of feature transformation from target variables (zero leakage).
3. Preprocessing fitted strictly on training splits.
4. Accurate target inversion preserving domain scale (0–100% grades).
"""
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, LabelEncoder

# Canonical 9-feature schema matching AcademicDataService.FEATURE_ORDER
CANONICAL_FEATURE_NAMES = [
    "attendance_rate",
    "average_score",
    "lms_activity",
    "gpa",
    "assignments_assigned",
    "assignments_submitted",
    "assignment_completion_rate",
    "late_submissions",
    "average_submission_delay_days",
]

FEATURE_SCHEMA_VERSION = "academic-v2"


class FeaturePreprocessor:
    """
    Validates and transforms numeric feature matrices strictly according to
    the canonical schema.
    """

    def __init__(self, feature_names=None):
        self.feature_names = list(feature_names or CANONICAL_FEATURE_NAMES)
        self.expected_dim = len(self.feature_names)
        self.scaler = StandardScaler()
        self.medians = None
        self.is_fitted = False

    def fit(self, X):
        X_arr = np.asarray(X, dtype=float)
        if X_arr.ndim != 2:
            raise ValueError(f"Feature matrix must be 2D. Received shape: {X_arr.shape}")
        if X_arr.shape[1] != self.expected_dim:
            raise ValueError(
                f"Feature dimension mismatch: expected {self.expected_dim} features "
                f"({self.feature_names}), but received {X_arr.shape[1]} columns."
            )
        # Compute column medians for imputation
        self.medians = np.nanmedian(X_arr, axis=0)
        nan_mask = np.isnan(X_arr)
        if np.any(nan_mask):
            X_clean = np.where(nan_mask, self.medians, X_arr)
        else:
            X_clean = X_arr

        self.scaler.fit(X_clean)
        self.is_fitted = True
        return self

    def transform(self, X):
        if not self.is_fitted:
            raise RuntimeError("FeaturePreprocessor has not been fitted yet.")
        X_arr = np.asarray(X, dtype=float)
        single_sample = False
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(1, -1)
            single_sample = True

        if X_arr.shape[1] != self.expected_dim:
            raise ValueError(
                f"Feature dimension mismatch: expected {self.expected_dim} features, "
                f"but received {X_arr.shape[1]} columns."
            )

        nan_mask = np.isnan(X_arr)
        if np.any(nan_mask):
            X_clean = np.where(nan_mask, self.medians, X_arr)
        else:
            X_clean = X_arr

        scaled = self.scaler.transform(X_clean)
        return scaled[0] if single_sample else scaled

    def fit_transform(self, X):
        return self.fit(X).transform(X)


class TargetTransformer:
    """
    Transforms targets for modeling and inverts model predictions back to
    original domain units without arbitrary scaling factors.
    """

    def __init__(self, mode="identity", min_val=0.0, max_val=100.0):
        self.mode = mode  # "identity" or "minmax"
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.range = self.max_val - self.min_val
        if self.range <= 0:
            raise ValueError("max_val must be strictly greater than min_val.")
        self.is_fitted = False

    def fit(self, y):
        y_arr = np.asarray(y, dtype=float)
        if y_arr.size == 0:
            raise ValueError("Target vector y cannot be empty.")
        self.is_fitted = True
        return self

    def transform(self, y):
        y_arr = np.asarray(y, dtype=float)
        if self.mode == "minmax":
            return (y_arr - self.min_val) / self.range
        return y_arr

    def fit_transform(self, y):
        return self.fit(y).transform(y)

    def inverse_transform(self, y):
        y_arr = np.asarray(y, dtype=float)
        if self.mode == "minmax":
            return y_arr * self.range + self.min_val
        return y_arr


class DataPreprocessor:
    """Legacy dataset cleaning helper maintained for backward compatibility."""

    @staticmethod
    def clean_and_scale_data(df):
        df = df.copy()
        numeric_columns = df.select_dtypes(include='number').columns
        if len(numeric_columns):
            df[numeric_columns] = df[numeric_columns].fillna(
                df[numeric_columns].median()
            )
        categorical_columns = df.select_dtypes(include=['object', 'category']).columns
        if len(categorical_columns):
            df[categorical_columns] = df[categorical_columns].fillna('unknown')

        for col in categorical_columns:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))

        scaler = StandardScaler()
        numeric_cols = df.select_dtypes(include='number').columns
        if len(numeric_cols):
            df[numeric_cols] = scaler.fit_transform(df[numeric_cols])

        return df