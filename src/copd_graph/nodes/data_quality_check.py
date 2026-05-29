from copd_graph.state import COPDState


REQUIRED_FIELDS = [
    "patient",
    "timeline_events",
    "clinical_tests",
    "ct_records",
    "pathogen_tests",
]


def data_quality_check(state: COPDState) -> COPDState:
    patient_data = state.get("patient_data", {})
    missing_fields = [field for field in REQUIRED_FIELDS if not patient_data.get(field)]

    return {
        "data_quality": {
            "can_evaluate": not missing_fields,
            "missing_fields": missing_fields,
            "warnings": ["mNGS仅作为感染相关线索，需结合临床综合判断"],
        }
    }
