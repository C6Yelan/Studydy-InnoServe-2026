"""核對後端映像的執行帳號與可寫暫存目錄。"""

import os
import subprocess
import sys

image = sys.argv[1] if len(sys.argv) > 1 else "studydy-competition-backend:latest"
uid = os.environ.get("STUDYDY_BACKEND_UID", "20002")
probe = """
import getpass, os, pwd
entry = pwd.getpwuid(os.getuid())
assert entry.pw_dir == "/tmp", entry.pw_dir
assert os.path.expanduser("~") == "/tmp"
getpass.getuser()
import matplotlib
assert matplotlib.get_configdir().startswith("/tmp/"), matplotlib.get_configdir()
print("PASS", entry.pw_name, os.getuid())
"""
result = subprocess.run(
    [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
        "--user", f"{uid}:1000",
        "--entrypoint", "env", image,
        "-i", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "HF_HOME=/tmp/huggingface",
        "/app/backend/.venv/bin/python", "-I", "-c", probe,
    ],
    capture_output=True,
    text=True,
)
print(result.stdout.strip() or result.stderr.strip()[-2000:])
raise SystemExit(result.returncode)
