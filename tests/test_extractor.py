from __future__ import annotations

from pathlib import Path

from w2p.extractor import extract_topology
from w2p.models import VisualDiagram


def test_visual_diagram_extracts_deterministic_topology() -> None:
    diagram = VisualDiagram.model_validate_json(Path("examples/diagram.json").read_text())

    topology = extract_topology(diagram)

    assert [service.id for service in topology.services] == ["payments-api"]
    assert [datastore.id for datastore in topology.datastores] == ["payments-db"]
    assert [edge.id for edge in topology.edges] == ["https-authorization", "postgres"]
    assert topology.services[0].security.public is True

