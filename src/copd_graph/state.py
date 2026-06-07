from typing import Any, Dict, List, TypedDict


class COPDState(TypedDict, total=False):
    assessment_mode: str
    raw_patient_data: Dict[str, Any]
    patient_data: Dict[str, Any]

    data_quality: Dict[str, Any]

    patient_timeline_summary: str
    patient_current_summary: str
    lung_function_estimation: str

    phenotype: Dict[str, Any]
    risk_assessment: Dict[str, Any]
    qwen_assessment_output: Dict[str, Any]
    model_call_results: Dict[str, Any]
    model_metadata: Dict[str, Any]

    key_evidence: List[Dict[str, Any]]
    treatment_response_observations: List[str]

    safety_harness_result: Dict[str, Any]
    safety_check_result: Dict[str, Any]

    report_draft: str
    node_run_logs: List[Dict[str, Any]]
    errors: List[str]
