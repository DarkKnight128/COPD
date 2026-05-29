from copd_graph.state import COPDState


def timeline_analyzer(state: COPDState) -> COPDState:
    events = state.get("patient_data", {}).get("timeline_events", [])
    if not events:
        return {"patient_timeline_summary": "暂无可用病程事件。"}

    sorted_events = sorted(events, key=lambda item: item.get("date", ""))
    event_summaries = [
        f"{event.get('date', '日期不详')}发生{event.get('event_type', '事件')}："
        f"{event.get('event_detail', '详情不详')}（{event.get('severity', '严重程度不详')}）"
        for event in sorted_events
    ]
    return {"patient_timeline_summary": "；".join(event_summaries) + "。"}
