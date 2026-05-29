from copd_graph.state import COPDState


def report_generator(state: COPDState) -> COPDState:
    evidence_lines = [
        f"- {item.get('evidence', '')}（来源：{item.get('source', '')}）"
        for item in state.get("key_evidence", [])
    ]
    phenotype = state.get("phenotype", {})
    risks = state.get("risk_assessment", {})

    report = "\n".join(
        [
            "# 慢阻肺智能辅助评估报告草稿",
            "",
            "## 病程摘要",
            state.get("patient_timeline_summary", "暂无病程摘要。"),
            "",
            "## 当前状态",
            state.get("patient_current_summary", "暂无当前状态摘要。"),
            "",
            "## 表型提示",
            f"主要表型：{phenotype.get('main_phenotype', '未知')}",
            f"相关标签：{', '.join(phenotype.get('phenotype_tags', []))}",
            f"依据说明：{phenotype.get('basis', '')}",
            "",
            "## 风险评估",
            f"急性加重风险：{risks.get('acute_exacerbation_risk', '未知')}",
            f"再住院风险：{risks.get('readmission_risk', '未知')}",
            f"死亡风险：{risks.get('mortality_risk', '未知')}",
            "",
            "## 关键证据",
            "\n".join(evidence_lines) if evidence_lines else "暂无关键证据。",
            "",
            "## 辅助评估免责声明",
            "本报告为规则占位生成的辅助评估草稿，仅用于研发和流程验证；不能替代医生临床判断，"
            "不得作为独立诊疗依据。当前阶段不输出具体治疗方案。",
        ]
    )
    return {"report_draft": report}
