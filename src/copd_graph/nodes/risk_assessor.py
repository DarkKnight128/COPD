from typing import Any, Dict

from copd_graph.nodes.assessment_rules import risk_by_rules
from copd_graph.qwen_client import qwen_metadata
from copd_graph.state import COPDState


ALLOWED_RISK_LEVELS = {"低", "中", "高"}


def risk_assessor(state: COPDState) -> COPDState:
    patient_data = state.get("patient_data", {})
    fallback = risk_by_rules(patient_data)
    cached_output = state.get("qwen_assessment_output", {})
    source_log = state.get("model_call_results", {}).get("current_status_summarizer", {})

    if source_log.get("status") == "success" and cached_output.get("risk_assessment"):
        output = cached_output.get("risk_assessment", {})
        model_result = _reused_model_result(source_log)
    else:
        output = {}
        model_result = _fallback_model_result(source_log, state.get("assessment_mode"))

    risk_assessment = {
        "acute_exacerbation_risk": _risk_or_fallback(
            output.get("acute_exacerbation_risk"), fallback["acute_exacerbation_risk"]
        ),
        "readmission_risk": _risk_or_fallback(
            output.get("readmission_risk"), fallback["readmission_risk"]
        ),
        "mortality_risk": _risk_or_fallback(
            output.get("mortality_risk"), fallback["mortality_risk"]
        ),
        "basis": output.get("basis") or fallback["basis"],
        "explanation_factors": _list_or_empty(output.get("explanation_factors")),
    }
    return {
        "risk_assessment": risk_assessment,
        "treatment_response_observations": [
            "当前阶段仅整理既往治疗和随访线索，不生成具体治疗方案。"
        ],
        "model_call_results": {
            **state.get("model_call_results", {}),
            "risk_assessor": {
                **model_result,
                "output": risk_assessment,
            },
        },
    }


def _reused_model_result(source_log: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "reused",
        "failure_reason": "已复用 current_status_summarizer 的 Qwen 结构化输出，未重复调用 API。",
        "provider": source_log.get("provider", ""),
        "model_name": source_log.get("model_name", ""),
        "model_version": source_log.get("model_version", ""),
        "enabled": source_log.get("enabled", True),
        "output": {},
    }


def _fallback_model_result(source_log: Dict[str, Any], assessment_mode: str | None) -> Dict[str, Any]:
    metadata = qwen_metadata()
    if assessment_mode == "local_rules":
        status = "local_rules"
        reason = "本次选择本地规则评估，未调用通义千问 API。"
    else:
        status = source_log.get("status", "fallback")
        reason = source_log.get("failure_reason") or "前序 Qwen 调用未成功，使用规则占位评估。"
    return {
        "status": status,
        "failure_reason": reason,
        "output": {},
        **metadata,
    }


def _risk_or_fallback(value: Any, fallback: str) -> str:
    return value if value in ALLOWED_RISK_LEVELS else fallback


def _list_or_empty(value: Any) -> list[str]:
    return value if isinstance(value, list) else []
