import os
import pandas as pd
from flask import current_app
from werkzeug.utils import secure_filename


class ReportService:
    @staticmethod
    def generate_institutional_report(data_dict, report_name='institutional_summary.csv'):
        try:
            df = pd.DataFrame(data_dict)
            reports_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'historical')
            os.makedirs(reports_folder, exist_ok=True)

            safe_name = secure_filename(report_name)
            if not safe_name:
                safe_name = 'report.csv'

            output_path = os.path.join(reports_folder, safe_name)

            # Verify the resolved path stays within the intended reports folder
            # (prevents any path traversal that survived secure_filename)
            reports_root = os.path.abspath(reports_folder)
            try:
                inside_reports_folder = os.path.commonpath(
                    [reports_root, os.path.abspath(output_path)]
                ) == reports_root
            except ValueError:
                inside_reports_folder = False
            if not inside_reports_folder:
                return {'success': False, 'error': 'Invalid report filename.'}

            df.to_csv(output_path, index=False)
            return {'success': True, 'path': output_path}
        except Exception as exc:
            current_app.logger.error("Institutional report generation failed (error type: %s).", type(exc).__name__)
            return {'success': False, 'error': 'The report could not be generated.'}
