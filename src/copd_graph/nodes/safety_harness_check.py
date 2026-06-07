from copd_graph.nodes.safety_check import FORBIDDEN_TERMS
from copd_graph.state import COPDState


def safety_harness_check(state: COPDState) -> COPDState:
    structured_text = "\n".join(
        [
            state.get("patient_current_summary", ""),
            str(state.get("phenotype", {})),
            str(state.get("risk_assessment", {})),
            str(state.get("model_call_results", {})),
        ]
    )
    matched_terms = [term for term in FORBIDDEN_TERMS if term in structured_text]
    return {
        "safety_harness_result": {
            "passed": not matched_terms,
            "matched_terms": matched_terms,
            "notes": "检查结构化评估结果是否出现具体治疗方案、替代医生诊断或越界表达。",
        }
    }
