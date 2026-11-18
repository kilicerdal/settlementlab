"""Bounded, declarative external scenario packs; never import user code."""

import json
import re
from pathlib import Path
from typing import Any, Optional, Union

IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field: " + key)
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value: " + value)


def validate_external(spec: Any, target: str, source: str) -> dict[str, Any]:
    if not isinstance(spec, dict) or set(spec) - {"id", "title", "target", "control", "steps"}:
        raise ValueError(source + ": unknown scenario fields")
    if not isinstance(spec.get("id"), str) or not IDENTIFIER.fullmatch(spec["id"]):
        raise ValueError(source + ": invalid scenario ID")
    if not isinstance(spec.get("title"), str) or not 1 <= len(spec["title"]) <= 200:
        raise ValueError(source + ": invalid scenario title")
    if spec.get("target", target) != target or target == "settlement":
        raise ValueError(source + ": external packs require a matching non-settlement target")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
        raise ValueError(source + ": requires 1–200 steps")
    aliases = {"run_id"}

    def validate_references(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                reference = value["$ref"]
                if not isinstance(reference, str) or reference.split(".")[0] not in aliases:
                    raise ValueError(source + ": unknown or forward response reference")
            else:
                for item in value.values():
                    validate_references(item)
        elif isinstance(value, list):
            for item in value:
                validate_references(item)
        elif isinstance(value, str):
            for reference in re.findall(r"\$\{([A-Za-z0-9_.]+)\}", value):
                if reference.split(".")[0] not in aliases:
                    raise ValueError(source + ": unknown or forward template reference")

    for step in steps:
        if not isinstance(step, dict) or set(step) - {
            "action",
            "method",
            "path",
            "data",
            "key",
            "status",
            "save",
            "assert",
            "control",
        }:
            raise ValueError(source + ": unknown HTTP step fields")
        if step.get("action") != "http" or step.get("method", "GET") not in ("GET", "POST"):
            raise ValueError(source + ": only declarative HTTP GET/POST steps are supported")
        path = step.get("path")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError(source + ": invalid relative request path")
        status = step.get("status", 200)
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError(source + ": invalid expected HTTP status")
        assertions = step.get("assert", {})
        if not isinstance(assertions, dict) or any(
            not isinstance(k, str) or not k for k in assertions
        ):
            raise ValueError(source + ": assertions must map paths to expected JSON values")
        if "save" in step and (
            not isinstance(step["save"], str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", step["save"])
            or step["save"] == "run_id"
        ):
            raise ValueError(source + ": invalid response alias")
        validate_references({k: v for k, v in step.items() if k not in ("save", "control")})
        if "save" in step:
            if step["save"] in aliases:
                raise ValueError(source + ": response alias is already defined")
            aliases.add(step["save"])
    for node in [spec, *steps]:
        if "control" in node and (
            not isinstance(node["control"], str) or not IDENTIFIER.fullmatch(node["control"])
        ):
            raise ValueError(source + ": invalid control identifier")
    return dict(spec, target=target, source=source)


def load_external(directory: Union[str, Path], target: str) -> list[dict[str, Any]]:
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Scenario directory must be a real directory")
    paths = sorted(root.glob("*.json"))
    if not 1 <= len(paths) <= 100:
        raise ValueError("External pack requires 1–100 JSON files")
    specs: list[dict[str, Any]] = []
    ids: set[str] = set()
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Scenario file must be a regular JSON file of at most 64 KiB")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("Scenario exceeds 64 KiB")
        spec = validate_external(
            json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant),
            target,
            path.name,
        )
        if spec["id"] in ids:
            raise ValueError("Duplicate scenario ID: " + spec["id"])
        ids.add(spec["id"])
        specs.append(spec)
    return specs


def validate_selection(directory: Optional[str], suite: str) -> None:
    if directory and suite not in ("all", "scenarios"):
        raise ValueError("--scenario-dir requires --suite scenarios or all")
