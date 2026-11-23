"""Satu direktori immutable per invocation dan manifest untuk reproduksi."""
import contextlib
import hashlib
import importlib.metadata
import json
import logging
import math
import os
import platform
import shlex
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path


def write_json(path, value):
    def finite(v):
        if isinstance(v, dict):
            return {k: finite(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [finite(x) for x in v]
        return None if isinstance(v, float) and not math.isfinite(v) else v
    Path(path).write_text(json.dumps(finite(value), indent=2, ensure_ascii=False,
                                    allow_nan=False, default=str) + "\n", encoding="utf-8")


def fingerprint(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def command_text(argv, windows=None):
    """Reproducible display command for PowerShell or POSIX shell."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        # PowerShell literal strings double embedded single quotes. Always use &
        # so executable paths containing spaces work, including venv python.exe.
        return "& " + " ".join("'" + str(v).replace("'", "''") + "'" for v in argv)
    return shlex.join(map(str, argv))


class Run:
    def __init__(self, root, command, args):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = Path(root).resolve() / f"{stamp}_{command}_{uuid.uuid4().hex[:6]}"
        self.path.mkdir(parents=True)
        self.manifest = {"status": "running", "started_utc": stamp,
                         "command": command, "argv": sys.argv,
                         "cwd": str(Path.cwd()), "arguments": args,
                         "python": sys.version, "platform": platform.platform(),
                         "inputs": [], "versions": {}}
        for name in ("numpy", "scipy", "pandas", "matplotlib"):
            with contextlib.suppress(importlib.metadata.PackageNotFoundError):
                self.manifest["versions"][name] = importlib.metadata.version(name)
        self.start = time.monotonic()
        self.log = logging.getLogger(str(self.path))
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        handler = logging.FileHandler(self.path / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.log.addHandler(handler)
        (self.path / "command.txt").write_text(command_text([sys.executable, *sys.argv]) + "\n", encoding="utf-8")
        write_json(self.path / "command_argv.json", [sys.executable, *sys.argv])
        # Store the implementation used, including config/help invocations.
        base = Path(__file__).resolve().parent
        self.manifest["source"] = [fingerprint(p) for p in sorted(base.glob("*.py"))]
        self.manifest["source"].append(fingerprint(base.parent / "case_b.py"))
        snapshot = self.path / "source" / "caseb"
        snapshot.mkdir(parents=True)
        for source in base.glob("*.py"):
            shutil.copy2(source, snapshot/source.name)
        shutil.copy2(base.parent/"case_b.py", snapshot.parent/"case_b.py")
        shutil.copytree(base.parent/"config", snapshot.parent/"config")
        shutil.copytree(base.parent/"tests", snapshot.parent/"tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(base.parent/"requirements.txt", snapshot.parent/"requirements.txt")
        for name in ("setup_windows.ps1", "README.md", "WINDOWS.md", "PANDUAN_IMPLEMENTASI.md"):
            if (base.parent/name).exists():
                shutil.copy2(base.parent/name, snapshot.parent/name)
        write_json(self.path / "manifest.json", self.manifest)
        print(f"OUTPUT: {self.path}", flush=True)

    def input(self, path):
        self.manifest["inputs"].append(fingerprint(path))

    def finish(self, status, error=None):
        self.manifest.update(status=status, elapsed_s=round(time.monotonic() - self.start, 3),
                             finished_utc=datetime.now(timezone.utc).isoformat())
        if error:
            self.manifest["error"] = error
        if not (self.path / "README.md").exists():
            artifacts = [str(p.relative_to(self.path)) for p in sorted(self.path.rglob("*"))
                         if p.is_file() and "source" not in p.relative_to(self.path).parts]
            synthetic = (self.path/"SYNTHETIC.json").exists()
            (self.path / "README.md").write_text(
                f"# Run {self.manifest['command']}\n\nStatus: **{status}**.\n\n"
                + ("**DATA SINTETIS — bukan hasil pengukuran manusia.**\n\n" if synthetic else "") +
                "Perintah: `command.txt`. Parameter, input SHA256, versi, dan artefak: "
                "`manifest.json`. Log: `run.log`. Snapshot kode: `source/`.\n\n" +
                "## Artefak\n\n" + "\n".join(f"- [{p}]({p})" for p in artifacts) + "\n" +
                (f"\nError: {self.manifest.get('error', error)}\n" if self.manifest.get("error", error) else ""),
                encoding="utf-8")
        self.manifest["artifacts"] = [str(p.relative_to(self.path))
                                      for p in sorted(self.path.rglob("*")) if p.is_file()]
        write_json(self.path / "manifest.json", self.manifest)
        self.log.info("Finished: %s", status)
        for h in self.log.handlers[:]:
            h.close()
            self.log.removeHandler(h)

    def failure(self):
        detail = traceback.format_exc()
        self.log.error(detail)
        (self.path / "error.txt").write_text(detail, encoding="utf-8")
