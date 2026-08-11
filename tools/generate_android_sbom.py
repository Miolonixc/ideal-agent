#!/usr/bin/env python3
"""Generate a small CycloneDX SBOM from direct Android Gradle dependencies."""
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path


def components(gradle_text: str):
    result = []
    for notation in re.findall(r'(?:implementation|api)\("([^"]+)"\)', gradle_text):
        parts = notation.split(":")
        if len(parts) < 2:
            continue
        group, artifact = parts[:2]
        version = parts[2] if len(parts) > 2 else None
        component = {
            "type": "library",
            "group": group,
            "name": artifact,
            "purl": f"pkg:maven/{group.replace('.', '/')}/{artifact}" + (f"@{version}" if version else ""),
        }
        if version:
            component["version"] = version
        result.append(component)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gradle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    text = args.gradle.read_text(encoding="utf-8")
    app_id = re.search(r'applicationId\s*=\s*"([^"]+)"', text).group(1)
    version = re.search(r'versionName\s*=\s*"([^"]+)"', text).group(1)
    app = {"type": "application", "name": app_id, "version": version,
           "purl": f"pkg:generic/{app_id}@{version}"}
    bom = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, app_id + '@' + version)}",
        "metadata": {"component": app, "properties": [
            {"name": "ideal-agent:sbom-scope", "value": "declared Android Gradle dependencies"},
        ]},
        "components": components(text),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
