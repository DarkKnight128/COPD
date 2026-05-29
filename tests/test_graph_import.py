import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_graph_imports_and_builds():
    from copd_graph.graph import build_graph
    from copd_graph.state import COPDState

    graph = build_graph()

    assert graph is not None
    assert COPDState is not None
