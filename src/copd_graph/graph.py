from langgraph.graph import END, START, StateGraph

from copd_graph.nodes.current_status_summarizer import current_status_summarizer
from copd_graph.nodes.data_quality_check import data_quality_check
from copd_graph.nodes.evidence_builder import evidence_builder
from copd_graph.nodes.load_patient_data import load_patient_data
from copd_graph.nodes.phenotype_assessor import phenotype_assessor
from copd_graph.nodes.report_generator import report_generator
from copd_graph.nodes.risk_assessor import risk_assessor
from copd_graph.nodes.safety_harness_check import safety_harness_check
from copd_graph.nodes.safety_check import safety_check
from copd_graph.nodes.timeline_analyzer import timeline_analyzer
from copd_graph.state import COPDState
from copd_graph.time_utils import local_isoformat


def _logged_node(name, node_fn):
    def wrapped(state: COPDState) -> COPDState:
        started_at = local_isoformat(timespec="milliseconds")
        try:
            result = node_fn(state)
            ended_at = local_isoformat(timespec="milliseconds")
            return {
                **result,
                "node_run_logs": [
                    *state.get("node_run_logs", []),
                    {
                        "node_name": name,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "status": "success",
                        "error_message": "",
                    },
                ],
            }
        except Exception as error:
            ended_at = local_isoformat(timespec="milliseconds")
            return {
                "node_run_logs": [
                    *state.get("node_run_logs", []),
                    {
                        "node_name": name,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "status": "failed",
                        "error_message": str(error),
                    },
                ],
                "errors": [*state.get("errors", []), f"{name}: {error}"],
            }

    return wrapped


def build_graph():
    workflow = StateGraph(COPDState)

    workflow.add_node("load_patient_data", _logged_node("load_patient_data", load_patient_data))
    workflow.add_node("data_quality_check", _logged_node("data_quality_check", data_quality_check))
    workflow.add_node("timeline_analyzer", _logged_node("timeline_analyzer", timeline_analyzer))
    workflow.add_node("current_status_summarizer", _logged_node("current_status_summarizer", current_status_summarizer))
    workflow.add_node("phenotype_assessor", _logged_node("phenotype_assessor", phenotype_assessor))
    workflow.add_node("risk_assessor", _logged_node("risk_assessor", risk_assessor))
    workflow.add_node("evidence_builder", _logged_node("evidence_builder", evidence_builder))
    workflow.add_node("safety_harness_check", _logged_node("safety_harness_check", safety_harness_check))
    workflow.add_node("safety_check", _logged_node("safety_check", safety_check))
    workflow.add_node("report_generator", _logged_node("report_generator", report_generator))

    workflow.add_edge(START, "load_patient_data")
    workflow.add_edge("load_patient_data", "data_quality_check")
    workflow.add_edge("data_quality_check", "timeline_analyzer")
    workflow.add_edge("timeline_analyzer", "current_status_summarizer")
    workflow.add_edge("current_status_summarizer", "phenotype_assessor")
    workflow.add_edge("phenotype_assessor", "risk_assessor")
    workflow.add_edge("risk_assessor", "evidence_builder")
    workflow.add_edge("evidence_builder", "safety_harness_check")
    workflow.add_edge("safety_harness_check", "safety_check")
    workflow.add_edge("safety_check", "report_generator")
    workflow.add_edge("report_generator", END)

    return workflow.compile()
