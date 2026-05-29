from copd_graph.state import COPDState


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
        }
    )

    clinical_tests = sorted(patient_data.get("clinical_tests", []), key=lambda item: item.get("date", ""))
    if clinical_tests:
        latest = clinical_tests[-1]
        evidence.append(
            {
                "evidence": (
                    f"{latest.get('date', '日期不详')} CAT {latest.get('CAT', '未知')}，"
                    f"mMRC {latest.get('mMRC', '未知')}，"
                    f"FEV1占预计值{latest.get('FEV1_percent_predicted', '未知')}%。"
                ),
                "source": "clinical_tests",
            }
        )

    for record in patient_data.get("ct_records", []):
        evidence.append(
            {
                "evidence": record.get("ct_report", "CT记录未提供报告文本。"),
                "source": "ct_records",
            }
        )

    for test in patient_data.get("pathogen_tests", []):
        pathogens = [item.get("pathogen", "未知病原体") for item in test.get("mNGS_result", [])]
        if pathogens:
            evidence.append(
                {
                    "evidence": f"{test.get('date', '日期不详')} {test.get('method', '检测')}提示：{', '.join(pathogens)}。",
                    "source": "pathogen_tests",
                }
            )

    if patient_data.get("follow_up", {}).get("readmission_within_90_days"):
        evidence.append(
            {
                "evidence": "随访信息记录90天内再住院。",
                "source": "follow_up",
            }
        )

    return {"key_evidence": evidence}
