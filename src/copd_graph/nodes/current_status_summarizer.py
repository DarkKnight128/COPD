from copd_graph.nodes.assessment_rules import current_summary_by_rules, qwen_payload
from copd_graph.qwen_client import call_qwen_structured
from copd_graph.state import COPDState


def current_status_summarizer(state: COPDState) -> COPDState:
    patient_data = state.get("patient_data", {})
    fallback = current_summary_by_rules(patient_data)
    model_result = call_qwen_structured(
        "generate_copd_structured_assessment",
        qwen_payload(patient_data),
        {
            "patient_current_summary": "一句中文摘要，说明 CAT/mMRC/肺功能/近期急性加重状态，不给治疗建议",
            "lung_function_estimation": "肺功能估算或现有肺功能摘要",
            "phenotype": {
                "main_phenotype": "主要表型",
                "phenotype_tags": ["表型标签"],
                "basis": "依据说明，只能基于结构化临床数据、CT 报告/特征和感染线索",
            },
            "risk_assessment": {
                "acute_exacerbation_risk": "低/中/高",
                "readmission_risk": "低/中/高",
                "mortality_risk": "低/中/高",
                "basis": "风险依据说明，不输出治疗方案",
                "explanation_factors": ["关键解释因素"],
            },
        },
        force_local_rules=state.get("assessment_mode") == "local_rules",
    )
    output = model_result.get("output", {})
    summary = output.get("patient_current_summary") or fallback
    lung_function_estimation = output.get("lung_function_estimation", "")
    return {
        "patient_current_summary": summary,
        "lung_function_estimation": lung_function_estimation,
        "qwen_assessment_output": output if model_result.get("status") == "success" else {},
        "model_call_results": {
            **state.get("model_call_results", {}),
            "current_status_summarizer": {
                **model_result,
                "output": {
                    "patient_current_summary": summary,
                    "lung_function_estimation": lung_function_estimation,
                    "explanation_factors": output.get("explanation_factors", []),
                },
            },
        },
    }
