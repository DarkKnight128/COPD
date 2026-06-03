from copd_graph.state import COPDState


def _latest_clinical_test(patient_data):
    tests = patient_data.get("clinical_tests", [])
    if not tests:
        return {}
    return sorted(tests, key=lambda item: item.get("date", ""))[-1]


def _has_emphysema(patient_data):
    for record in patient_data.get("ct_records", []):
        ct_report = record.get("ct_report", "")
        ct_feature = record.get("ct_feature", {})
        if "肺气肿" in ct_report or ct_feature.get("emphysema_level"):
            return True
    return False


def _has_infection_signal(patient_data, latest_test):
    has_mngs = any(test.get("mNGS_result") for test in patient_data.get("pathogen_tests", []))
    crp = latest_test.get("CRP", 0) or 0
    wbc = latest_test.get("WBC", 0) or 0
    return has_mngs and (crp > 10 or wbc > 10)


def assessment_generator(state: COPDState) -> COPDState:
    patient_data = state.get("patient_data", {})
    timeline_events = patient_data.get("timeline_events", [])
    latest_test = _latest_clinical_test(patient_data)

    exacerbation_count = sum(
        1 for event in timeline_events if "急性加重" in event.get("event_type", "")
    )
    readmission_90d = patient_data.get("follow_up", {}).get("readmission_within_90_days", False)

    phenotype_tags = []
    main_phenotype = "非频繁急性加重表型"
    if exacerbation_count >= 2:
        main_phenotype = "频繁急性加重表型"
        phenotype_tags.append(main_phenotype)

    cat = latest_test.get("CAT", 0) or 0
    mmrc = latest_test.get("mMRC", 0) or 0
    if cat >= 20 or mmrc >= 2:
        phenotype_tags.append("症状负担较重表型")
    if _has_emphysema(patient_data):
        phenotype_tags.append("肺气肿相关表型")
    if _has_infection_signal(patient_data, latest_test):
        phenotype_tags.append("感染相关表型")

    phenotype_tags = list(dict.fromkeys(phenotype_tags))
    if not phenotype_tags:
        phenotype_tags.append(main_phenotype)

    fev1_percent = latest_test.get("FEV1_percent_predicted")
    if fev1_percent in ("", None, "未知"):
        lung_function_text = f"FEV1为{latest_test.get('FEV1', '未知')}L"
    else:
        lung_function_text = f"FEV1占预计值{fev1_percent}%"

    current_summary = (
        f"最近一次评估CAT为{cat}，mMRC为{mmrc}，"
        f"{lung_function_text}，"
        f"近阶段记录到{exacerbation_count}次急性加重相关事件。"
    )

    return {
        "patient_current_summary": current_summary,
        "phenotype": {
            "main_phenotype": main_phenotype,
            "phenotype_tags": phenotype_tags,
            "basis": "基于急性加重记录、症状评分、CT描述和感染相关线索的规则占位评估。",
        },
        "risk_assessment": {
            "acute_exacerbation_risk": "高" if exacerbation_count >= 2 else "中",
            "readmission_risk": "高" if readmission_90d else "中",
            "mortality_risk": "中",
        },
        "treatment_response_observations": [
            "当前阶段仅整理既往治疗和随访线索，不生成具体治疗方案。"
        ],
    }
