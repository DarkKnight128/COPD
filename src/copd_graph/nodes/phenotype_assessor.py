from typing import Any, Dict

from copd_graph.nodes.assessment_rules import phenotype_by_rules
from copd_graph.qwen_client import qwen_metadata
from copd_graph.state import COPDState


def phenotype_assessor(state: COPDState) -> COPDState:
    patient_data = state.get("patient_data", {})
    fallback = phenotype_by_rules(patient_data)
    cached_output = state.get("qwen_assessment_output", {})
    source_log = state.get("model_call_results", {}).get("current_status_summarizer", {})

    if source_log.get("status") == "success" and cached_output.get("phenotype"):
        output = cached_output.get("phenotype", {})
        model_result = _reused_model_result(source_log)
    else:
        output = {}
        model_result = _fallback_model_result(source_log, state.get("assessment_mode"))

    phenotype = {
        "main_phenotype": output.get("main_phenotype") or fallback["main_phenotype"],
        "phenotype_tags": _list_or_fallback(
            output.get("phenotype_tags"), fallback["phenotype_tags"]
        ),
        "basis": output.get("basis") or fallback["basis"],
    }
    return {
        "phenotype": phenotype,
        "model_call_results": {
            **state.get("model_call_results", {}),
            "phenotype_assessor": {
                **model_result,
                "output": phenotype,
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


def _list_or_fallback(value: Any, fallback: list[str]) -> list[str]:
    return value if isinstance(value, list) and value else fallback
