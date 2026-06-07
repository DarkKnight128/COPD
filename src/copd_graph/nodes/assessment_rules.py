from __future__ import annotations

from typing import Any, Dict, List


def latest_clinical_test(patient_data: Dict[str, Any]) -> Dict[str, Any]:
    tests = patient_data.get("clinical_tests", [])
    if not tests:
        return {}
    return sorted(tests, key=lambda item: item.get("date", ""))[-1]


def exacerbation_count(patient_data: Dict[str, Any]) -> int:
    explicit_count = patient_data.get("follow_up", {}).get("exacerbation_count_1y")
    if isinstance(explicit_count, (int, float)):
        return int(explicit_count)
    return sum(
        1
        for event in patient_data.get("timeline_events", [])
        if "急性加重" in str(event.get("event_type", ""))
    )


def has_emphysema(patient_data: Dict[str, Any]) -> bool:
    for record in patient_data.get("ct_records", []):
        ct_report = str(record.get("ct_report", ""))
        ct_feature = record.get("ct_feature", {}) or {}
        if (
            "肺气肿" in ct_report
            or ct_feature.get("emphysema_level")
            or ct_feature.get("emphysema_percent")
        ):
            return True
    return False


def has_infection_signal(patient_data: Dict[str, Any], latest_test: Dict[str, Any]) -> bool:
    has_pathogen = any(test.get("mNGS_result") for test in patient_data.get("pathogen_tests", []))
    crp = _number(latest_test.get("CRP"))
    wbc = _number(latest_test.get("WBC"))
    return has_pathogen and (crp > 10 or wbc > 10)


def current_summary_by_rules(patient_data: Dict[str, Any]) -> str:
    latest_test = latest_clinical_test(patient_data)
    count = exacerbation_count(patient_data)
    cat = latest_test.get("CAT", "未知")
    mmrc = latest_test.get("mMRC", "未知")
    fev1 = latest_test.get("FEV1", "未知")
    fev1_percent = latest_test.get("FEV1_percent_predicted")
    if fev1_percent in ("", None, "未知"):
        lung_function_text = f"FEV1 为 {fev1}L"
    else:
        lung_function_text = f"FEV1 占预计值 {fev1_percent}%"
    return (
        f"最近一次评估 CAT 为 {cat}，mMRC 为 {mmrc}，{lung_function_text}，"
        f"近阶段记录到 {count} 次急性加重相关事件。"
    )


def phenotype_by_rules(patient_data: Dict[str, Any]) -> Dict[str, Any]:
    latest_test = latest_clinical_test(patient_data)
    count = exacerbation_count(patient_data)
    phenotype_tags: List[str] = []
    main_phenotype = "非频繁急性加重表型"
    if count >= 2:
        main_phenotype = "频繁急性加重表型"
        phenotype_tags.append(main_phenotype)

    cat = _number(latest_test.get("CAT"))
    mmrc = _number(latest_test.get("mMRC"))
    if cat >= 20 or mmrc >= 2:
        phenotype_tags.append("症状负担较重表型")
    if has_emphysema(patient_data):
        phenotype_tags.append("肺气肿相关表型")
    if has_infection_signal(patient_data, latest_test):
        phenotype_tags.append("感染相关表型")

    phenotype_tags = list(dict.fromkeys(phenotype_tags))
    if not phenotype_tags:
        phenotype_tags.append(main_phenotype)
    return {
        "main_phenotype": main_phenotype,
        "phenotype_tags": phenotype_tags,
        "basis": "基于急性加重记录、症状评分、CT 描述和感染相关线索的规则占位评估。",
    }


def risk_by_rules(patient_data: Dict[str, Any]) -> Dict[str, Any]:
    count = exacerbation_count(patient_data)
    readmission_90d = patient_data.get("follow_up", {}).get("readmission_within_90_days", False)
    return {
        "acute_exacerbation_risk": "高" if count >= 2 else "中",
        "readmission_risk": "高" if readmission_90d else "中",
        "mortality_risk": "中",
        "basis": "基于急性加重次数、90 天再住院记录和当前 POC 规则生成。",
    }


def qwen_payload(patient_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "patient": patient_data.get("patient", {}),
        "timeline_events": patient_data.get("timeline_events", [])[-20:],
        "clinical_tests": patient_data.get("clinical_tests", [])[-5:],
        "ct_records": patient_data.get("ct_records", [])[-5:],
        "pathogen_tests": patient_data.get("pathogen_tests", [])[-5:],
        "follow_up": patient_data.get("follow_up", {}),
        "mock_model_output": patient_data.get("mock_model_output"),
    }


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
