import json
import sys
from pathlib import Path
from pprint import pprint


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from copd_graph.graph import build_graph  # noqa: E402


def main():
    sample_path = PROJECT_ROOT / "data" / "sample_patient.json"
    with sample_path.open("r", encoding="utf-8") as file:
        patient_data = json.load(file)

    initial_state = {"raw_patient_data": patient_data}
    graph = build_graph()
    result = graph.invoke(initial_state)

    fields = [
        "data_quality",
        "patient_timeline_summary",
        "patient_current_summary",
        "phenotype",
        "risk_assessment",
        "key_evidence",
        "safety_check_result",
        "report_draft",
    ]
    for field in fields:
        print(f"\n===== {field} =====")
        pprint(result.get(field), sort_dicts=False)


if __name__ == "__main__":
    main()
