"""Rehearse README quickstart from a tracked Git revision in an empty, pip-free venv."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def rehearse(revision, output, interpreter=sys.executable):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "rev-parse", revision], cwd=root, text=True).strip()
    checks = {}
    started = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="settlementlab-first-run-") as temporary:
        directory = Path(temporary)
        checkout = directory / "checkout"
        checkout.mkdir()
        archive = directory / "source.tar"
        subprocess.run(["git", "archive", "--output", str(archive), commit], cwd=root, check=True)
        subprocess.run(["tar", "-xf", str(archive), "-C", str(checkout)], check=True)
        python = directory / "venv" / "bin" / "python"
        subprocess.run(
            [interpreter, "-m", "venv", "--without-pip", str(python.parents[1])], check=True
        )
        env = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(key, None)
        env["PYTHONNOUSERSITE"] = "1"
        isolation = subprocess.check_output(
            [
                str(python),
                "-c",
                "import importlib.util,json; print(json.dumps({n:importlib.util.find_spec(n) is None for n in ['pip','settlementlab','playwright']}))",
            ],
            cwd=directory,
            env=env,
            text=True,
        )
        runtime = json.loads(
            subprocess.check_output(
                [
                    str(python),
                    "-c",
                    "import platform,sqlite3,json; print(json.dumps(dict(python=platform.python_version(),sqlite=sqlite3.sqlite_version)))",
                ],
                cwd=directory,
                env=env,
                text=True,
            )
        )
        checks["empty_environment"] = json.loads(isolation)
        assert all(checks["empty_environment"].values())
        result = subprocess.run(
            [
                str(python),
                "scripts/incident_quickstart.py",
                "--no-serve",
                "--output",
                "artifacts/first-run",
            ],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        (output / "quickstart.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads((checkout / "artifacts/first-run/results.json").read_text())
        (output / "incident-results.json").write_text(json.dumps(report, indent=2) + "\n")
        assert report["status"] == "passed"
        assert report["worker_checkpoint_exit"] == 73
        assert (
            report["export_verification"]["verification_level"] == "INTEGRITY_AND_SCOPED_ECONOMICS"
        )
        checks["quickstart_exit_code"] = result.returncode
        checks["incident_status"] = report["status"]
        checks["injected_worker_exit"] = report["worker_checkpoint_exit"]
        checks["evidence_created"] = all(
            (checkout / "artifacts/first-run" / name).is_file()
            for name in ["investigate.zip", "resolved.zip", "results.json"]
        )
        assert checks["evidence_created"]
        # Do not disturb any service already listening on the documented quickstart port.
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8086)) == 0:
                raise RuntimeError("Port 8086 is occupied; stop your own demo or retry later")
        with (output / "server.log").open("w") as log:
            process = subprocess.Popen(
                [str(python), "scripts/incident_quickstart.py", "--output", "artifacts/served-run"],
                cwd=checkout,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Quickstart server exited; see server.log")
                    try:
                        with urllib.request.urlopen(
                            "http://127.0.0.1:8086/investigation", timeout=1
                        ) as response:
                            body = response.read().decode()
                            checks["investigation_http_status"] = response.status
                            assert "From accepted terms to accounting result" in body
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Quickstart server did not become ready")
                with urllib.request.urlopen(
                    "http://127.0.0.1:8086/api/health", timeout=2
                ) as response:
                    checks["health_http_status"] = response.status
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        checks["server_stopped"] = process.poll() is not None
    report = dict(
        status="passed",
        source_commit=commit,
        runtime=runtime,
        started_at=started,
        scope="Automated fresh-user rehearsal of tracked source, not independent human review; pip-free venv; no model or API key",
        checks=checks,
        files={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.iterdir()
            if p.is_file()
        },
    )
    (output / "rehearsal.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument(
        "--python", default=sys.executable, help="Interpreter used to create the empty venv"
    )
    parser.add_argument("--output", default="artifacts/fresh-checkout")
    args = parser.parse_args()
    rehearse(args.revision, args.output, args.python)


if __name__ == "__main__":
    main()
