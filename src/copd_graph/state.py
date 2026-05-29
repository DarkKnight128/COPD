from typing import Any, Dict, List, TypedDict


class COPDState(TypedDict, total=False):
    raw_patient_data: Dict[str, Any]
    patient_data: Dict[str, Any]

    data_quality: Dict[str, Any]

    patient_timeline_summary: str
    patient_current_summary: str

    phenotype: Dict[str, Any]
    risk_assessment: Dict[str, Any]

    key_evidence: List[Dict[str, str]]
    treatment_response_observations: List[str]

    safety_check_result: Dict[str, Any]

    report_draft: str
    errors: List[str]
