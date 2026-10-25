"""核對後端映像的執行 UID 有 passwd 身分，HOME 落在 /tmp tmpfs。

競賽版沒有 OCR／torch；這是預防 getpass、~ 在無 passwd 項目時失敗。以正式 backend
相同的 UID、唯讀 rootfs 與 /tmp tmpfs，清空環境執行；不 build／pull、不掛載產品資料。
"""

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
print("PASS", entry.pw_name, os.getuid())
"""
result = subprocess.run(
    [
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
        "--user", f"{uid}:1000",
        "--entrypoint", "env", image,
        "-i", "/app/backend/.venv/bin/python", "-I", "-c", probe,
    ],
    capture_output=True,
    text=True,
)
print(result.stdout.strip() or result.stderr.strip()[-2000:])
raise SystemExit(result.returncode)
