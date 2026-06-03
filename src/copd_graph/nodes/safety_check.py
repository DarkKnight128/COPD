from copd_graph.state import COPDState


FORBIDDEN_TERMS = [
    "确诊",
    "诊断为",
    "建议使用",
    "建议增加",
    "增加ICS",
    "使用抗生素",
    "由某病原体引起",
    "替代医生诊断",
    "直接诊断",
    "最终诊断",
    "治疗方案",
    "推荐用药",
    "处方",
]


def safety_check(state: COPDState) -> COPDState:
    text_fields = [
        state.get("patient_timeline_summary", ""),
        state.get("patient_current_summary", ""),
        str(state.get("phenotype", {})),
        str(state.get("risk_assessment", {})),
        str(state.get("key_evidence", [])),
        state.get("report_draft", ""),
    ]
    combined_text = "\n".join(text_fields)
    matched_terms = [term for term in FORBIDDEN_TERMS if term in combined_text]

    return {
        "safety_check_result": {
            "passed": not matched_terms,
            "matched_terms": matched_terms,
            "notes": "当前阶段仅记录潜在越界内容，不自动重写。",
        }
    }
