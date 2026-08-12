#!/usr/bin/env python3
"""Trusted Mac runner for the monthly Beauty Weekly publication."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import previous_month_str  # noqa: E402
from build.generate_monthly import codex_logged_in  # noqa: E402

STATE_DIR = ROOT / ".beauty-weekly-state"
LOCK_PATH = STATE_DIR / "monthly-runner.lock"
PUBLISHED = ("index.html", "fragrance.html", ".deploy-manifest-hash", "deploy-manifest.json")
CANONICAL = ("report.json", "sources.json", "scoring.json", "manifest.json")
STRIP_ENV = (
    "CODEX_HOME",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN",
)


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name in STRIP_ENV:
        env.pop(name, None)
    if extra:
        env.update(extra)
    return env


def valid_month(value: str) -> str:
    if len(value) != 7 or value[4] != "-" or not value[:4].isdigit() or not value[5:].isdigit():
        raise ValueError(f"invalid month: {value!r}; expected YYYY-MM")
    if not 1 <= int(value[5:]) <= 12:
        raise ValueError(f"invalid month: {value!r}; expected YYYY-MM")
    return value


def run(
    cmd: list[str], month: str, *, check: bool = True, transport: str | None = None
) -> subprocess.CompletedProcess[str]:
    logging.info("RUN %s", " ".join(cmd))
    extra = {"BEAUTY_MONTHLY_MONTH": month}
    if transport:
        extra["BEAUTY_MONTHLY_TRANSPORT"] = transport
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=clean_env(extra),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        logging.info("%s", proc.stdout[-12000:])
    if check and proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def snapshot(month: str) -> Path:
    backup = Path(tempfile.mkdtemp(prefix="beauty-weekly-backup-"))
    month_dir = ROOT / "data" / "months" / month
    if month_dir.exists():
        shutil.copytree(month_dir, backup / "month")
    for name in PUBLISHED:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, backup / name)
    return backup


def restore(month: str, backup: Path) -> None:
    month_dir = ROOT / "data" / "months" / month
    if month_dir.exists():
        shutil.rmtree(month_dir)
    if (backup / "month").exists():
        shutil.copytree(backup / "month", month_dir)
    for name in PUBLISHED:
        dst, src = ROOT / name, backup / name
        if src.exists():
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()


def write_deploy_manifest(month: str) -> None:
    artifacts = {}
    for name in ("index.html", "fragrance.html"):
        path = ROOT / name
        artifacts[name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
    (ROOT / "deploy-manifest.json").write_text(
        json.dumps({"month": month, "artifacts": artifacts}, indent=2) + "\n",
        encoding="utf-8",
    )


def publish(month: str) -> None:
    paths = [*PUBLISHED, f"data/months/{month}/"]
    run(["git", "add", "--", *paths], month)
    if run(["git", "diff", "--staged", "--quiet"], month, check=False).returncode == 0:
        logging.info("No changes to publish")
        return
    run(
        [
            "git",
            "-c",
            "user.name=beauty-weekly-local[bot]",
            "-c",
            "user.email=beauty-weekly-local[bot]@users.noreply.github.com",
            "commit",
            "-m",
            f"Monthly auto-update: {month}",
        ],
        month,
    )
    run(["git", "fetch", "origin", "main"], month)
    if run(["git", "rebase", "origin/main"], month, check=False).returncode:
        run(["git", "rebase", "--abort"], month, check=False)
        raise RuntimeError("rebase conflict; push cancelled")
    run(["git", "push", "origin", "HEAD:main"], month)


def execute(month: str, *, no_commit: bool, force_collect: bool, skip_collect: bool) -> None:
    if not codex_logged_in():
        raise RuntimeError("default ~/.codex is not logged in; run `env -u CODEX_HOME codex login`")
    month_dir = ROOT / "data" / "months" / month
    raw = month_dir / "raw_collected.json"
    if skip_collect:
        if not raw.exists():
            raise RuntimeError(f"--skip-collect but {raw} does not exist")
        logging.info("--skip-collect: reusing existing raw data")
    elif force_collect or not raw.exists():
        run([sys.executable, "build/collect.py"], month)
    else:
        logging.info("Reusing existing raw data (use --force-collect to re-fetch)")
    run(
        [sys.executable, "build/generate_monthly.py"],
        month,
        check=True,
        transport="codex",
    )
    for name in CANONICAL:
        if not (month_dir / name).exists():
            raise RuntimeError(f"missing canonical output: {month_dir / name}")
    run(["bash", "build/monthly_update.sh"], month)
    write_deploy_manifest(month)
    if not no_commit:
        publish(month)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="YYYY-MM; defaults to previous month")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--force-collect", action="store_true")
    parser.add_argument("--skip-collect", action="store_true")
    args = parser.parse_args()
    month = valid_month(args.month or previous_month_str())
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.error("another monthly run is active")
            return 2
        backup = snapshot(month)
        try:
            execute(
                month,
                no_commit=args.no_commit,
                force_collect=args.force_collect,
                skip_collect=args.skip_collect,
            )
        except Exception:
            logging.exception("monthly run failed; restoring published state")
            restore(month, backup)
            return 1
        finally:
            shutil.rmtree(backup, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
