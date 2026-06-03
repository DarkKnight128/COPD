from copd_graph.state import COPDState


def _dates_for(records):
    dates = []
    for record in records:
        date = record.get("date") or record.get("event_date")
        if date:
            dates.append(str(date))
    return sorted(dict.fromkeys(dates))


def evidence_builder(state: COPDState) -> COPDState:
    patient_data = state.get("patient_data", {})
    evidence = []

    timeline_events = patient_data.get("timeline_events", [])
    exacerbation_count = sum(
        1 for event in timeline_events if "急性加重" in event.get("event_type", "")
    )
    evidence.append(
        {
            "evidence": f"病程记录中包含{exacerbation_count}次急性加重相关事件。",
            "source": "timeline_events",
            "source_dates": _dates_for(timeline_events),
            "source_fields": ["event_type", "severity"],
        }
    )

    clinical_tests = sorted(patient_data.get("clinical_tests", []), key=lambda item: item.get("date", ""))
    if clinical_tests:
        latest = clinical_tests[-1]
        fev1_percent = latest.get("FEV1_percent_predicted")
        if fev1_percent in ("", None, "未知"):
            lung_function_text = f"FEV1 {latest.get('FEV1', '未知')}L"
            source_fields = ["CAT", "mMRC", "FEV1"]
        else:
            lung_function_text = f"FEV1占预计值{fev1_percent}%"
            source_fields = ["CAT", "mMRC", "FEV1_percent_predicted"]
        evidence.append(
            {
                "evidence": (
                    f"{latest.get('date', '日期不详')} CAT {latest.get('CAT', '未知')}，"
                    f"mMRC {latest.get('mMRC', '未知')}，"
                    f"{lung_function_text}。"
                ),
                "source": "clinical_tests",
                "source_dates": [latest.get("date", "日期不详")],
                "source_fields": source_fields,
            }
        )

    for record in patient_data.get("ct_records", []):
        evidence.append(
            {
                "evidence": record.get("ct_report", "CT记录未提供报告文本。"),
                "source": "ct_records",
                "source_dates": [record.get("date", "日期不详")],
                "source_fields": ["ct_report", "ct_feature"],
            }
        )

    for test in patient_data.get("pathogen_tests", []):
        pathogens = [item.get("pathogen", "未知病原体") for item in test.get("mNGS_result", [])]
        if pathogens:
            evidence.append(
                {
                    "evidence": f"{test.get('date', '日期不详')} {test.get('method', '检测')}提示：{', '.join(pathogens)}。",
                    "source": "pathogen_tests",
                    "source_dates": [test.get("date", "日期不详")],
                    "source_fields": ["method", "sample_type", "mNGS_result"],
                }
            )

    if patient_data.get("follow_up", {}).get("readmission_within_90_days"):
        evidence.append(
            {
                "evidence": "随访信息记录90天内再住院。",
                "source": "follow_up",
                "source_dates": [patient_data.get("follow_up", {}).get("last_followup_date", "日期不详")],
                "source_fields": ["readmission_within_90_days", "survival_status"],
            }
        )

    return {"key_evidence": evidence}
