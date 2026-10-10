import os
import re
from urllib.parse import quote, urljoin, urlparse

import requests
from flask import current_app
from models import mongo


def _allowed_namenode(url, allow_query=False):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        allowed = {str(value).lower() for value in current_app.config.get('HADOOP_ALLOWED_HOSTS', set())}
        return (
            parsed.scheme in {'http', 'https'}
            and bool(host)
            and host in allowed
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and (allow_query or not parsed.query)
        )
    except (TypeError, ValueError):
        return False


class HadoopService:
    @staticmethod
    def upload_to_hdfs(local_path, hdfs_destination):
        if not current_app.config.get("HADOOP_ENABLED", False):
            current_app.logger.info("HDFS upload skipped because HADOOP_ENABLED is false.")
            return False
        platform = mongo.db.settings.find_one({"_id": "platform"}) or {}
        namenode_url = platform.get("namenode_url") or current_app.config.get("HADOOP_NAMENODE_URL", "http://localhost:50070")
        namenode_url = namenode_url.rstrip("/")
        if not _allowed_namenode(namenode_url):
            current_app.logger.error("WebHDFS NameNode URL is invalid or its host is not allowlisted.")
            return False
        destination = str(hdfs_destination or "").strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*", destination):
            current_app.logger.error("Invalid HDFS destination: %r", hdfs_destination)
            return False
        file_name = os.path.basename(local_path)
        directory = f"/edupredict/{destination}"
        try:
            mkdir_response = requests.put(f"{namenode_url}/webhdfs/v1{directory}?op=MKDIRS", timeout=15)
            if not mkdir_response.ok:
                current_app.logger.error("WebHDFS directory creation failed with HTTP %s.", mkdir_response.status_code)
                return False
            url = (
                f"{namenode_url}/webhdfs/v1{directory}/{quote(file_name, safe='')}"
                "?op=CREATE&overwrite=true"
            )
            create_response = requests.put(url, allow_redirects=False, timeout=15)
            if create_response.status_code not in {307, 308}:
                current_app.logger.error("WebHDFS CREATE did not return a DataNode redirect.")
                return False
            location = create_response.headers.get("Location")
            if not location:
                current_app.logger.error("WebHDFS CREATE redirect did not include a destination.")
                return False
            data_node_url = urljoin(url, location or "")
            if not _allowed_namenode(data_node_url, allow_query=True):
                current_app.logger.error("WebHDFS returned a DataNode outside the configured host allowlist.")
                return False
            if urlparse(namenode_url).scheme == "https" and urlparse(data_node_url).scheme != "https":
                current_app.logger.error("WebHDFS DataNode redirect attempted to downgrade TLS.")
                return False
            with open(local_path, "rb") as handle:
                response = requests.put(data_node_url, data=handle, allow_redirects=False, timeout=30)
            if not response.ok:
                current_app.logger.error("WebHDFS upload failed with HTTP %s.", response.status_code)
            return response.status_code in {200, 201}
        except requests.exceptions.Timeout:
            current_app.logger.error("WebHDFS upload timed out for %s.", file_name)
        except requests.exceptions.ConnectionError:
            current_app.logger.error("WebHDFS is unreachable.")
        except Exception:
            current_app.logger.error("Unexpected WebHDFS upload error.")
        return False

    @staticmethod
    def status():
        if not current_app.config.get("HADOOP_ENABLED", False):
            return {"enabled": False, "reachable": False, "message": "HDFS disabled; local storage fallback is active."}
        platform = mongo.db.settings.find_one({"_id": "platform"}) or {}
        namenode_url = (platform.get("namenode_url") or current_app.config.get("HADOOP_NAMENODE_URL", "")).rstrip("/")
        if not _allowed_namenode(namenode_url):
            return {"enabled": True, "reachable": False, "message": "WebHDFS NameNode host is not allowlisted."}
        try:
            response = requests.get(f"{namenode_url}/webhdfs/v1/?op=GETFILESTATUS", timeout=5)
            return {
                "enabled": True,
                "reachable": response.ok,
                "message": "WebHDFS reachable." if response.ok else f"WebHDFS returned HTTP {response.status_code}.",
            }
        except requests.RequestException:
            current_app.logger.warning("WebHDFS status check failed.")
            return {"enabled": True, "reachable": False, "message": "WebHDFS is unavailable."}
