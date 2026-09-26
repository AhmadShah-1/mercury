import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WEB_WORKERS", "2"))
threads = 2
timeout = 30
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = False
worker_tmp_dir = "/tmp"  # noqa: S108 - isolated container tmpfs
