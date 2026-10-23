"""Compose 的資料初始化與 API 入口；不管理主機程序或模型生命週期。"""

import argparse
import os
from pathlib import Path
import subprocess

from psycopg.conninfo import make_conninfo

from .local_app import run_local_app
from .semantic_service import _origin, SERVICE_URL_ENV
from .storage.migrations import run_migrations


def initialize_data(root: Path, uid: int, gid: int, *, backend_uid: int | None = None) -> None:
    if backend_uid is None:
        backend_uid = uid
    if uid <= 0 or gid <= 0 or backend_uid <= 0 or root.is_symlink():
        raise ValueError("CONTAINER_DATA_INVALID")
    root_created = not root.exists()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # 資料管理者仍使用原身分；重跑 init 不更動既有資料根目錄權限。
    if root_created:
        root.chmod(0o700)
        os.chown(root, uid, gid)
    for relative, owner, group in (
        ("artifacts", backend_uid, gid), ("postgres", 999, 999),
    ):
        path = root / relative
        if path.is_symlink():
            raise ValueError("CONTAINER_DATA_INVALID")
        created = not path.exists()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        # 僅 artifact 根交給後端；既有子樹須由部署程序明確遷移。
        # PostgreSQL 只在首次建立時設 owner，不能重設既有資料權限。
        if relative == "artifacts" or created:
            path.chmod(0o700)
            os.chown(path, owner, group)


def configure_database(environment) -> None:
    password = environment["POSTGRES_PASSWORD"]
    if not password:
        raise ValueError("CONTAINER_DATABASE_INVALID")
    os.environ["STUDYDY_DATABASE_DSN"] = make_conninfo(
        host="postgres", port="5432", dbname=environment["POSTGRES_DB"],
        user=environment["POSTGRES_USER"], password=password, connect_timeout="5",
    )


def check_sandbox() -> None:
    result = subprocess.run(
        ["bwrap", "--unshare-all", "--ro-bind", "/", "/", "/usr/bin/true"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=5, check=False,
    )
    if result.returncode:
        raise RuntimeError("CONTAINER_SANDBOX_UNAVAILABLE")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "migrate", "serve"))
    command = parser.parse_args().command
    try:
        if command == "init":
            initialize_data(
                Path("/data"),
                int(os.environ["STUDYDY_UID"]),
                int(os.environ["STUDYDY_GID"]),
                backend_uid=int(os.environ["STUDYDY_BACKEND_UID"]),
            )
            return
        if command == "serve":
            _origin(os.environ[SERVICE_URL_ENV])
            check_sandbox()
        configure_database(os.environ)
        # 啟動時核對已套用的 checksum，再以交易執行待套用的 migration。
        run_migrations()
        if command == "migrate":
            return
        run_local_app(host="0.0.0.0", port=8001)
    except Exception:
        # 不把含密碼的 conninfo、模型位址或 SQL 例外輸出至容器 log。
        print("CONTAINER_OPERATION_FAILED: check configuration, database and sandbox", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
