from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compiler import compile_topology
from .extractor import extract_topology
from .models import TopologySpec, VisualDiagram, topology_json_schema, visual_json_schema


def main() -> None:
    parser = argparse.ArgumentParser(prog="w2p", description="Whiteboard-to-Production compiler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="compile a topology JSON file")
    compile_parser.add_argument("topology", type=Path)
    compile_parser.add_argument("--out", type=Path, default=Path("generated"))

    extract_parser = subparsers.add_parser("extract", help="extract topology from normalized visual JSON")
    extract_parser.add_argument("diagram", type=Path)
    extract_parser.add_argument("--out", type=Path, required=True)

    schema_parser = subparsers.add_parser("schema", help="write a JSON schema")
    schema_parser.add_argument("--kind", choices=["topology", "visual"], default="topology")
    schema_parser.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()

    if args.command == "compile":
        _compile(args.topology, args.out)
    elif args.command == "extract":
        _extract(args.diagram, args.out)
    elif args.command == "schema":
        _schema(args.kind, args.out)


def _compile(topology_path: Path, out_dir: Path) -> None:
    topology = TopologySpec.model_validate_json(topology_path.read_text())
    response = compile_topology(topology)
    for generated in response.generated_files:
        destination = out_dir / generated.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(generated.content)

    manifest = {
        "status": response.status,
        "topology_hash": response.topology_hash,
        "policy_issues": [issue.model_dump(mode="json") for issue in response.policy_issues],
        "files": [generated.path for generated in response.generated_files],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


def _extract(diagram_path: Path, out_path: Path) -> None:
    diagram = VisualDiagram.model_validate_json(diagram_path.read_text())
    topology = extract_topology(diagram)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(topology.model_dump(mode="json", by_alias=True, exclude_none=True), indent=2, sort_keys=True)
        + "\n"
    )


def _schema(kind: str, out_path: Path) -> None:
    schema = topology_json_schema() if kind == "topology" else visual_json_schema()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

