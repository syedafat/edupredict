import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

from services.audit_service import AuditService
from services.hadoop_service import HadoopService


class HardeningTests(unittest.TestCase):
    def test_audit_failure_does_not_raise(self):
        app = Flask(__name__)
        failing_db = Mock()
        failing_db.audit_logs.insert_one.side_effect = RuntimeError("audit store unavailable")

        with app.test_request_context("/"), patch("services.audit_service.mongo") as mongo:
            mongo.db = failing_db
            result = AuditService.record("grade_recorded", "grade", "grade-1", "teacher-1", "teacher")

        self.assertIsNone(result)

    def test_hdfs_upload_stops_when_directory_creation_fails(self):
        app = Flask(__name__)
        app.config.update(HADOOP_ENABLED=True, HADOOP_NAMENODE_URL="http://namenode", HADOOP_ALLOWED_HOSTS={"namenode"})
        settings = Mock()
        settings.find_one.return_value = {}
        fake_db = Mock(settings=settings)
        failed_mkdir = Mock(ok=False, status_code=500)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            path.write_text("student_id,score\nS-1,80\n", encoding="utf-8")
            with app.app_context(), patch("services.hadoop_service.mongo") as mongo, patch("services.hadoop_service.requests.put", return_value=failed_mkdir) as put:
                mongo.db = fake_db
                result = HadoopService.upload_to_hdfs(str(path), "academic/2026/09")

        self.assertFalse(result)
        put.assert_called_once()


if __name__ == "__main__":
    unittest.main()
