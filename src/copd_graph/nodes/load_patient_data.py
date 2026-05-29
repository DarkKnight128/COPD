from copd_graph.state import COPDState


def load_patient_data(state: COPDState) -> COPDState:
    raw_patient_data = state.get("raw_patient_data", {})
    if not raw_patient_data:
        return {
            "patient_data": {},
            "errors": [*state.get("errors", []), "raw_patient_data is empty"],
        }
    return {"patient_data": raw_patient_data}
