"""Portable, escaped incident export with content checksums and source provenance."""

import hashlib
import html
import io
import json
import platform
import subprocess
import zipfile
from pathlib import Path

from .. import __version__
from ..application.investigation import Investigation
from ..core.validation import DomainError


def provenance():
    root = Path(__file__).resolve().parents[3]
    # Installed wheels deliberately have no inferred unrelated working-directory commit.
    if not (root / "pyproject.toml").is_file() or not (root / "src/settlementlab").is_dir():
        return dict(version=__version__, source_commit=None, dirty=None, mode="installed-package")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
        )
        return dict(version=__version__, source_commit=commit, dirty=dirty, mode="source-checkout")
    except (OSError, subprocess.SubprocessError):
        return dict(version=__version__, source_commit=None, dirty=None, mode="unavailable")


def package(snapshot, source=None):
    report = json.dumps(snapshot, sort_keys=True, indent=2, ensure_ascii=True).encode()
    if len(report) > 16 * 1024 * 1024:
        raise DomainError("Incident export exceeds 16 MiB", 413)

    def esc(value):
        return html.escape(str(value), quote=True)

    rows = "".join(
        "<tr><td>"
        + esc(n["at"])
        + "</td><td>"
        + esc(n["kind"])
        + "</td><td>"
        + esc(n["title"])
        + "</td><td>"
        + esc(n["id"])
        + "</td></tr>"
        for n in snapshot["timeline"]
    )
    page = (
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab incident evidence</title><style>body{background:#0b1421;color:#dfebf4;font:15px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:0 24px}h1{color:#a3dfca}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #304050;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}.scroll{overflow:auto}a{color:#a3dfca}</style><h1>Incident investigation / """
        + esc(snapshot["trade"]["id"])
        + "</h1><p>"
        + esc(snapshot["scope"])
        + '</p><p>Read incident.json for complete snapshots, comparisons, correlations and journal lines. Checksums detect changed files; they do not authenticate their author.</p><div class="scroll"><table><tr><th>UTC time</th><th>Type</th><th>Event</th><th>Evidence ID</th></tr>'
        + rows
        + "</table></div><details><summary>Current financial result</summary><pre>"
        + esc(
            json.dumps(
                {
                    k: snapshot["trade"][k]
                    for k in (
                        "state",
                        "settled_quantity",
                        "reversed_quantity",
                        "net_settled_quantity",
                        "remaining_quantity",
                    )
                },
                indent=2,
            )
        )
        + "</pre></details></html>"
    ).encode()
    files = {"incident.json": report, "index.html": page}
    manifest = dict(
        format_version=1,
        source=source or provenance(),
        python=platform.python_version(),
        trade_id=snapshot["trade"]["id"],
        trade_version=snapshot["trade"]["version"],
        generated_at=snapshot["generated_at"],
        files={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        scope="Portable synthetic evidence, not a digital signature or independent review",
    )
    files["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


def export(service, trade_id):
    return package(Investigation(service).snapshot(trade_id))


def verify(path, expectations=None):
    from .bundle_audit import unique

    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != 3 or set(archive.namelist()) != {
            "incident.json",
            "index.html",
            "manifest.json",
        }:
            raise ValueError("Unexpected export members")
        if any(i.file_size > 32 * 1024 * 1024 for i in archive.infolist()):
            raise ValueError("Export member too large")
        manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=unique)
        if set(manifest["files"]) != {"incident.json", "index.html"}:
            raise ValueError("Incomplete checksum manifest")
        for name, digest in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Evidence checksum differs: " + name)
        data = json.loads(archive.read("incident.json"), object_pairs_hook=unique)
        if (
            manifest["trade_id"] != data["trade"]["id"]
            or manifest["trade_version"] != data["trade"]["version"]
        ):
            raise ValueError("Export identity mismatch")
        ids = {n["id"] for n in data["timeline"]}
        if len(ids) != len(data["timeline"]) or any(
            e["source"] not in ids or e["target"] not in ids for e in data["correlations"]
        ):
            raise ValueError("Broken investigation correlations")
        if expectations is not None:
            from .bundle_audit import audit, load_plan

            plan, digest = load_plan(expectations)
            try:
                economics = audit(data, plan)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("Invalid scoped economic evidence structure") from error
            return dict(
                status=economics["status"],
                integrity="passed",
                verification_level="INTEGRITY_AND_SCOPED_ECONOMICS",
                expectations_sha256=digest,
                economics=economics,
                trade_id=manifest["trade_id"],
                source=manifest["source"],
            )
        return dict(
            status="passed",
            verification_level="CONTENT_INTEGRITY_ONLY",
            economic_verification="NOT_RUN",
            files=len(manifest["files"]),
            trade_id=manifest["trade_id"],
            source=manifest["source"],
        )
