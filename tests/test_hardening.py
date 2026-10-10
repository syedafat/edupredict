import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

from services.audit_service import AuditService
from services.hadoop_service import HadoopService, _allowed_namenode


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

    def test_hdfs_rejects_credentials_and_unallowlisted_hosts_in_urls(self):
        app = Flask(__name__)
        app.config["HADOOP_ALLOWED_HOSTS"] = {"namenode", "datanode"}
        with app.app_context():
            self.assertTrue(_allowed_namenode("https://namenode:9871"))
            self.assertFalse(_allowed_namenode("http://user:secret@namenode"))
            self.assertFalse(_allowed_namenode("http://namenode/?token=secret"))
            self.assertFalse(_allowed_namenode("http://169.254.169.254/latest/meta-data"))

    def test_hdfs_upload_only_follows_allowlisted_datanode_redirect(self):
        app = Flask(__name__)
        app.config.update(
            HADOOP_ENABLED=True,
            HADOOP_NAMENODE_URL="http://namenode",
            HADOOP_ALLOWED_HOSTS={"namenode", "datanode"},
        )
        settings = Mock()
        settings.find_one.return_value = {}
        fake_db = Mock(settings=settings)
        mkdir = Mock(ok=True, status_code=200)
        redirect = Mock(ok=True, status_code=307, headers={"Location": "http://169.254.169.254/latest/meta-data"})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            path.write_text("student_id,score\nS-1,80\n", encoding="utf-8")
            with app.app_context(), patch("services.hadoop_service.mongo") as mongo, patch(
                "services.hadoop_service.requests.put", side_effect=[mkdir, redirect]
            ) as put:
                mongo.db = fake_db
                result = HadoopService.upload_to_hdfs(str(path), "academic/2026/09")

        self.assertFalse(result)
        self.assertEqual(put.call_count, 2)
        self.assertFalse(put.call_args.kwargs.get("allow_redirects", False))

    def test_hdfs_upload_succeeds_through_allowlisted_datanode(self):
        app = Flask(__name__)
        app.config.update(
            HADOOP_ENABLED=True,
            HADOOP_NAMENODE_URL="http://namenode",
            HADOOP_ALLOWED_HOSTS={"namenode", "datanode"},
        )
        settings = Mock()
        settings.find_one.return_value = {}
        fake_db = Mock(settings=settings)
        mkdir = Mock(ok=True, status_code=200)
        redirect = Mock(
            ok=True,
            status_code=307,
            headers={"Location": "http://datanode:9864/webhdfs/v1/edupredict/academic/dataset.csv?op=CREATE"},
        )
        upload = Mock(ok=True, status_code=201)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            path.write_text("student_id,score\nS-1,80\n", encoding="utf-8")
            with app.app_context(), patch("services.hadoop_service.mongo") as mongo, patch(
                "services.hadoop_service.requests.put", side_effect=[mkdir, redirect, upload]
            ) as put:
                mongo.db = fake_db
                result = HadoopService.upload_to_hdfs(str(path), "academic/2026/09")

        self.assertTrue(result)
        self.assertEqual(put.call_count, 3)
        self.assertEqual(put.call_args.args[0], "http://datanode:9864/webhdfs/v1/edupredict/academic/dataset.csv?op=CREATE")
        self.assertFalse(put.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
