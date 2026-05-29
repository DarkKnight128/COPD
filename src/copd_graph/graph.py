from langgraph.graph import END, START, StateGraph

from copd_graph.nodes.assessment_generator import assessment_generator
from copd_graph.nodes.data_quality_check import data_quality_check
from copd_graph.nodes.evidence_builder import evidence_builder
from copd_graph.nodes.load_patient_data import load_patient_data
from copd_graph.nodes.report_generator import report_generator
from copd_graph.nodes.safety_check import safety_check
from copd_graph.nodes.timeline_analyzer import timeline_analyzer
from copd_graph.state import COPDState


def build_graph():
    workflow = StateGraph(COPDState)

    workflow.add_node("load_patient_data", load_patient_data)
    workflow.add_node("data_quality_check", data_quality_check)
    workflow.add_node("timeline_analyzer", timeline_analyzer)
    workflow.add_node("assessment_generator", assessment_generator)
    workflow.add_node("evidence_builder", evidence_builder)
    workflow.add_node("safety_check", safety_check)
    workflow.add_node("report_generator", report_generator)

    workflow.add_edge(START, "load_patient_data")
    workflow.add_edge("load_patient_data", "data_quality_check")
    workflow.add_edge("data_quality_check", "timeline_analyzer")
    workflow.add_edge("timeline_analyzer", "assessment_generator")
    workflow.add_edge("assessment_generator", "evidence_builder")
    workflow.add_edge("evidence_builder", "safety_check")
    workflow.add_edge("safety_check", "report_generator")
    workflow.add_edge("report_generator", END)

    return workflow.compile()
