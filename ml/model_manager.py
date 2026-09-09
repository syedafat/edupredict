import os
import logging
import hashlib
import joblib
from flask import current_app

from ml.performance_model import PerformanceModel
from ml.dropout_model import DropoutModel
from ml.anomaly_detection import AnomalyDetector
from ml.demand_model import DemandModel
from ml.trend_model import TrendModel

logger = logging.getLogger(__name__)

# Canonical set of supported model types — must match VALID_MODEL_TYPES in ml_routes.py
SUPPORTED_MODEL_TYPES = {'performance', 'dropout', 'anomaly', 'demand', 'trend'}


def _model_folder() -> str:
    """Return the model storage directory from app config, falling back to a local default."""
    try:
        folder = current_app.config.get('MODEL_FOLDER')
    except RuntimeError:
        # No app context (e.g., during testing)
        folder = None
    if not folder:
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models')
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    return folder


def _model_path(model_type: str) -> str:
    """Return the absolute path for a given model type's persisted file."""
    if model_type not in SUPPORTED_MODEL_TYPES:
        raise ValueError(f"Unknown model type: '{model_type}'. Supported: {sorted(SUPPORTED_MODEL_TYPES)}")
    # Filename derived from validated model_type only — no user input reaches the filename
    return os.path.join(_model_folder(), f"{model_type}.joblib")


def artifact_hash(model_type: str) -> str | None:
    """Return the SHA-256 of the active artifact, or None when absent."""
    try:
        path = _model_path(model_type)
    except ValueError:
        return None
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ModelManager:

    @staticmethod
    def artifact_hash(model_type: str):
        return artifact_hash(model_type)

    @staticmethod
    def artifact_matches(model_type: str, metadata: dict) -> bool:
        expected = metadata.get("artifact_hash")
        return bool(expected and expected == artifact_hash(model_type))

    @staticmethod
    def get_model(model_type: str):
        """Return a new (unfitted) model instance for the given type."""
        if model_type == 'performance':
            return PerformanceModel()
        elif model_type == 'dropout':
            return DropoutModel()
        elif model_type == 'anomaly':
            return AnomalyDetector()
        elif model_type == 'demand':
            return DemandModel()
        elif model_type == 'trend':
            return TrendModel()
        else:
            raise ValueError(f"Unknown model type: '{model_type}'. Supported: {sorted(SUPPORTED_MODEL_TYPES)}")

    @staticmethod
    def model_exists(model_type: str) -> bool:
        """Return True if a persisted model file exists for the given type."""
        try:
            path = _model_path(model_type)
            return os.path.isfile(path)
        except ValueError:
            return False

    @staticmethod
    def save_model(model_type: str, model_object) -> bool:
        """
        Persist a trained model to disk using joblib.
        Returns True on success, False on failure.
        model_object is the fitted model instance (PerformanceModel, DropoutModel, etc.)
        """
        try:
            path = _model_path(model_type)
            joblib.dump(model_object, path)
            logger.info("Model '%s' saved to '%s'.", model_type, path)
            return True
        except ValueError as exc:
            logger.error("Cannot save model: %s", exc)
            return False
        except Exception as exc:
            logger.error("Failed to save model '%s': %s", model_type, exc)
            return False

    @staticmethod
    def load_model(model_type: str):
        """
        Load and return a persisted model from disk.
        Returns None if the file does not exist or cannot be loaded.
        Logs a clear error rather than raising.
        """
        try:
            path = _model_path(model_type)
        except ValueError as exc:
            logger.error("Cannot load model: %s", exc)
            return None

        if not os.path.isfile(path):
            logger.warning("Model file not found for type '%s' at '%s'.", model_type, path)
            return None

        try:
            model = joblib.load(path)
            logger.info("Model '%s' loaded from '%s'.", model_type, path)
            return model
        except Exception as exc:
            logger.error(
                "Failed to load model '%s' from '%s'. "
                "File may be corrupt or incompatible: %s",
                model_type, path, exc
            )
            return None
