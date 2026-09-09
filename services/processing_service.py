import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from flask import current_app


class ProcessingService:
    """Shared batch and streaming data processing primitives.

    Processing is deliberately format-aware and bounded by the upload limit.
    MongoDB stores metadata and summaries; the original file remains available
    for reproducibility while cleaned output is written to uploads/processed.
    """

    @staticmethod
    def load_dataframe(file_path):
        extension = os.path.splitext(file_path)[1].lower()
        if extension == ".csv":
            return pd.read_csv(file_path)
        if extension in {".xls", ".xlsx"}:
            return pd.read_excel(file_path)
        if extension == ".json":
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                payload = payload.get("records", payload.get("data", [payload]))
            return pd.json_normalize(payload)
        if extension == ".txt":
            return pd.read_csv(file_path, sep=None, engine="python")
        raise ValueError("Unsupported file format. Use CSV, JSON, XLSX, XLS or delimited TXT.")

    @staticmethod
    def clean_dataframe(df):
        if df is None or df.empty:
            raise ValueError("The dataset contains no records.")
        cleaned = df.copy()
        cleaned.columns = [
            str(column).strip().lower().replace(" ", "_").replace("-", "_")
            for column in cleaned.columns
        ]
        cleaned = cleaned.dropna(axis=1, how="all").drop_duplicates()
        for column in cleaned.columns:
            if pd.api.types.is_numeric_dtype(cleaned[column]):
                cleaned[column] = cleaned[column].fillna(cleaned[column].median())
            else:
                mode = cleaned[column].dropna().mode()
                cleaned[column] = cleaned[column].fillna(mode.iloc[0] if not mode.empty else "unknown")
        return cleaned

    @staticmethod
    def summarize(df):
        numeric = df.select_dtypes(include=[np.number])
        correlations = []
        if numeric.shape[1] >= 2:
            matrix = numeric.corr(numeric_only=True).replace({np.nan: None})
            for left in matrix.columns:
                for right in matrix.columns:
                    if left < right and matrix.loc[left, right] is not None:
                        correlations.append({
                            "left": left,
                            "right": right,
                            "coefficient": round(float(matrix.loc[left, right]), 4),
                        })
        return {
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "column_names": list(df.columns),
            "missing_values_before_cleaning": int(df.isna().sum().sum()),
            "numeric_columns": list(numeric.columns),
            "correlations": sorted(correlations, key=lambda item: abs(item["coefficient"]), reverse=True)[:20],
        }

    @staticmethod
    def quality_report(df):
        """Return transparent quality counts for normalized educational data."""
        checked = df.copy()
        checked.columns = [
            str(column).strip().lower().replace(" ", "_").replace("-", "_")
            for column in checked.columns
        ]
        invalid_rows = set()
        warnings = []
        required = {"student_id", "course_id"}
        missing_columns = sorted(required - set(checked.columns))
        if missing_columns:
            warnings.append(f"Missing relationship columns: {', '.join(missing_columns)}")
        for column in required.intersection(checked.columns):
            invalid_rows.update(checked.index[checked[column].isna() | (checked[column].astype(str).str.strip() == "")])
        for column in ("attendance_rate", "attendance_percentage", "attendance"):
            if column in checked.columns:
                values = pd.to_numeric(checked[column], errors="coerce")
                invalid_rows.update(checked.index[(values < 0) | (values > 100)])
                warnings.append(f"Validated {column} range 0-100")
                break
        for column in ("score", "marks", "mark"):
            if column in checked.columns:
                values = pd.to_numeric(checked[column], errors="coerce")
                invalid_rows.update(checked.index[(values < 0) | (values > 100)])
                warnings.append(f"Validated {column} range 0-100")
                break
        if "gpa" in checked.columns:
            values = pd.to_numeric(checked["gpa"], errors="coerce")
            invalid_rows.update(checked.index[(values < 0) | (values > 4)])
            warnings.append("Validated gpa range 0-4")
        input_records = int(len(checked))
        duplicate_count = int(checked.duplicated().sum())
        missing_values = int(checked.isna().sum().sum())
        invalid_count = len(invalid_rows)
        quality_score = round(max(0, (input_records - invalid_count) / input_records * 100), 2) if input_records else 0
        return {
            "records_input": input_records,
            "records_valid": input_records - invalid_count,
            "records_invalid": invalid_count,
            "duplicates_removed": duplicate_count,
            "missing_values_handled": missing_values,
            "warnings": warnings,
            "data_quality_score": quality_score,
            "quality_status": "INVALID" if invalid_count else "WARNING" if warnings or missing_values or duplicate_count else "VALID",
        }

    @staticmethod
    def process_dataset(file_path):
        try:
            raw = ProcessingService.load_dataframe(file_path)
            summary = ProcessingService.summarize(raw)
            quality = ProcessingService.quality_report(raw)
            df = ProcessingService.clean_dataframe(raw)
            processed_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "processed")
            os.makedirs(processed_folder, exist_ok=True)
            extension = os.path.splitext(file_path)[1].lower()
            output_path = os.path.join(processed_folder, "processed_" + os.path.basename(file_path))
            if extension in {".csv", ".txt"}:
                df.to_csv(output_path, index=False)
            elif extension == ".json":
                df.to_json(output_path, orient="records", date_format="iso")
            else:
                df.to_excel(output_path, index=False)
            summary.update({
                "clean_rows": int(len(df)),
                "processed_path": output_path,
                "processed_at": datetime.now(timezone.utc),
                "processing_mode": "LOCAL_PANDAS_FALLBACK",
                **quality,
            })
            return {"success": True, **summary}
        except Exception as exc:
            current_app.logger.exception("Dataset processing failed for %s", file_path)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def process_stream_event(event):
        """Validate one real-time event and return a normalized record.

        Kafka/Spark deployments can call this same function from a consumer.
        The app's local fallback persists the normalized event in MongoDB.
        """
        if not isinstance(event, dict) or not event:
            raise ValueError("Stream event must be a non-empty JSON object.")
        event_type = str(event.get("event_type", "generic")).strip()[:80]
        student_id = str(event.get("student_id", "")).strip()[:120]
        if not student_id:
            raise ValueError("Stream event requires student_id.")
        return {
            **event,
            "event_type": event_type,
            "student_id": student_id,
            "received_at": datetime.now(timezone.utc),
            "processed": True,
        }

    @staticmethod
    def records_for_storage(processed_path, dataset_type, dataset_id):
        from models import mongo
        df = ProcessingService.load_dataframe(processed_path)
        records = []
        now = datetime.now(timezone.utc)
        for row in df.head(100000).to_dict(orient="records"):
            normalized = {}
            for key, value in row.items():
                if isinstance(value, (np.integer, np.floating)):
                    value = value.item()
                if isinstance(value, pd.Timestamp):
                    value = value.to_pydatetime()
                if pd.isna(value) if not isinstance(value, (dict, list)) else False:
                    value = None
                normalized[str(key)] = value
            if dataset_type == "attendance" and "present" in normalized:
                normalized["present"] = str(normalized["present"]).strip().lower() in {"1", "true", "yes", "present"}
            normalized.update({"dataset_id": str(dataset_id), "ingested_at": now})
            records.append(normalized)
        collection_name = {
            "academic": "academic_records",
            "attendance": "attendance",
            "lms": "lms_records",
            "demographics": "demographics",
            "general": "educational_records",
        }[dataset_type]
        if records:
            mongo.db[collection_name].insert_many(records, ordered=False)
        return {"collection": collection_name, "records": len(records)}