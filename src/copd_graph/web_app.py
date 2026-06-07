from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from copd_graph.graph import build_graph
from copd_graph.poc_storage import (
    DEFAULT_DB_PATH,
    ImportValidationError,
    build_patient_state_data,
    connect,
    delete_patients,
    get_assessment,
    get_assessment_model_logs,
    get_assessment_node_logs,
    get_import_batch,
    get_latest_assessment,
    get_patient_bundle,
    import_workbook,
    init_database,
    list_import_batches,
    list_patients,
    save_assessment,
)
from copd_graph.time_utils import LOCAL_TIMEZONE
from copd_graph.xlsx_importer import parse_xlsx_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    with connect(DEFAULT_DB_PATH) as connection:
        init_database(connection)
    yield


app = FastAPI(title="COPD POC Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def format_local_time(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def format_node_logs(node_logs: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    formatted = []
    for log in node_logs:
        item = dict(log)
        item["started_at_display"] = format_local_time(item.get("started_at"))
        item["ended_at_display"] = format_local_time(item.get("ended_at"))
        formatted.append(item)
    return formatted


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/patients", status_code=303)


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        batches = list_import_batches(connection)
    return templates.TemplateResponse(request, "import.html", {"batches": batches})


@app.post("/import-upload")
async def import_upload(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")
    content = await file.read()
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            result = import_workbook(connection, parse_xlsx_bytes(content), file.filename)
        except ImportValidationError as error:
            result = error.result
    return templates.TemplateResponse(request, "import_result.html", {"result": result})


@app.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        batches = list_import_batches(connection)
    return templates.TemplateResponse(request, "imports.html", {"batches": batches})


@app.get("/imports/{batch_id}", response_class=HTMLResponse)
def import_detail_page(request: Request, batch_id: int) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        batch = get_import_batch(connection, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return templates.TemplateResponse(request, "import_detail.html", {"batch": batch})


@app.get("/patients", response_class=HTMLResponse)
def patients_page(
    request: Request,
    q: str = "",
    risk: str = "",
    assessment_status: str = "",
    followup_status: str = "",
    import_batch_id: str = "",
) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        patients = list_patients(
            connection,
            q,
            risk=risk,
            assessment_status=assessment_status,
            followup_status=followup_status,
            import_batch_id=import_batch_id,
        )
        batches = list_import_batches(connection)
    return templates.TemplateResponse(
        request,
        "patients.html",
        {
            "patients": patients,
            "q": q,
            "risk": risk,
            "assessment_status": assessment_status,
            "followup_status": followup_status,
            "import_batch_id": import_batch_id,
            "batches": batches,
        },
    )


@app.post("/patients/delete")
def delete_patients_page(patient_ids: list[str] = Form(default=[])) -> RedirectResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        delete_patients(connection, patient_ids)
    return RedirectResponse(url="/patients", status_code=303)


@app.post("/patients/{patient_id}/delete")
def delete_patient_page(patient_id: str) -> RedirectResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        delete_patients(connection, [patient_id])
    return RedirectResponse(url="/patients", status_code=303)


@app.get("/patients/{patient_id}", response_class=HTMLResponse)
def patient_detail_page(request: Request, patient_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return templates.TemplateResponse(request, "patient_detail.html", bundle)


@app.get("/patients/{patient_id}/timeline", response_class=HTMLResponse)
def timeline_page(request: Request, patient_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    events = build_timeline_events(bundle)
    return templates.TemplateResponse(
        request,
        "timeline.html",
        {
            "patient": bundle["patient"],
            "events": events,
        },
    )


@app.post("/patients/{patient_id}/assessment")
def run_assessment_page(
    patient_id: str,
    assessment_mode: str = Form(default="api"),
) -> RedirectResponse:
    assessment = run_patient_assessment(patient_id, assessment_mode=assessment_mode)
    return RedirectResponse(url=f"/assessments/{assessment['assessment_id']}", status_code=303)


@app.get("/patients/{patient_id}/assessment", response_class=HTMLResponse)
def patient_assessment_page(request: Request, patient_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
        assessment = get_latest_assessment(connection, patient_id)
        model_logs = (
            get_assessment_model_logs(connection, assessment["assessment_id"])
            if assessment
            else []
        )
        node_logs = (
            get_assessment_node_logs(connection, assessment["assessment_id"])
            if assessment
            else []
        )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return templates.TemplateResponse(
        request,
        "assessment.html",
        {
            "patient": bundle["patient"],
            "assessment": assessment,
            "model_logs": model_logs,
            "node_logs": format_node_logs(node_logs),
        },
    )


@app.get("/assessments/{assessment_id}", response_class=HTMLResponse)
def assessment_page(request: Request, assessment_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        model_logs = get_assessment_model_logs(connection, assessment_id)
        node_logs = get_assessment_node_logs(connection, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return templates.TemplateResponse(
        request,
        "assessment.html",
        {
            "patient": {"patient_id": assessment["patient_id"]},
            "assessment": assessment,
            "model_logs": model_logs,
            "node_logs": format_node_logs(node_logs),
        },
    )


@app.get("/assessments/{assessment_id}/report", response_class=HTMLResponse)
def report_page(request: Request, assessment_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "assessment": assessment,
            "report": assessment.get("report_draft", ""),
        },
    )


@app.post("/api/import/patients")
async def api_import_patients(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")
    workbook = parse_xlsx_bytes(await file.read())
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            return import_workbook(connection, workbook, file.filename)
        except ImportValidationError as error:
            raise HTTPException(status_code=400, detail=error.result) from error


@app.get("/api/imports")
def api_imports() -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        batches = list_import_batches(connection)
    return {"imports": batches, "count": len(batches)}


@app.get("/api/imports/{batch_id}")
def api_import(batch_id: int) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        batch = get_import_batch(connection, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return batch


@app.get("/api/patients")
def api_patients(
    q: str = "",
    risk: str = "",
    assessment_status: str = "",
    followup_status: str = "",
    import_batch_id: str = "",
) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        patients = list_patients(
            connection,
            q,
            risk=risk,
            assessment_status=assessment_status,
            followup_status=followup_status,
            import_batch_id=import_batch_id,
        )
    return {"patients": patients, "count": len(patients)}


@app.post("/api/patients/delete")
async def api_delete_patients(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    patient_ids = payload.get("patient_ids", [])
    if not isinstance(patient_ids, list):
        raise HTTPException(status_code=400, detail="patient_ids must be a list")
    with connect(DEFAULT_DB_PATH) as connection:
        counts = delete_patients(connection, patient_ids)
    return {"deleted": counts}


@app.delete("/api/patients/{patient_id}")
def api_delete_patient(patient_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        counts = delete_patients(connection, [patient_id])
    return {"deleted": counts}


@app.get("/api/patients/{patient_id}")
def api_patient(patient_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return bundle


@app.get("/api/patients/{patient_id}/timeline")
def api_timeline(patient_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"patient_id": patient_id, "events": build_timeline_events(bundle)}


@app.post("/api/patients/{patient_id}/assessment")
def api_run_assessment(patient_id: str, assessment_mode: str = "api") -> Dict[str, Any]:
    return run_patient_assessment(patient_id, assessment_mode=assessment_mode)


@app.get("/api/assessments/{assessment_id}")
def api_assessment(assessment_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        model_logs = get_assessment_model_logs(connection, assessment_id)
        node_logs = get_assessment_node_logs(connection, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    assessment["model_logs"] = model_logs
    assessment["node_logs"] = format_node_logs(node_logs)
    return assessment


@app.post("/api/assessments/{assessment_id}/report")
def api_report(assessment_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {
        "assessment_id": assessment_id,
        "patient_id": assessment["patient_id"],
        "report_draft": assessment.get("report_draft", ""),
    }


def run_patient_assessment(patient_id: str, assessment_mode: str = "api") -> Dict[str, Any]:
    mode = assessment_mode if assessment_mode in {"api", "local_rules"} else "api"
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            patient_data = build_patient_state_data(connection, patient_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        graph = build_graph()
        result = graph.invoke({"raw_patient_data": patient_data, "assessment_mode": mode})
        return save_assessment(connection, patient_id, result)


def build_timeline_events(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = []
    for visit in bundle["visits"]:
        events.append(
            {
                "date": visit.get("event_date", ""),
                "type": visit.get("event_type", "病程事件"),
                "title": visit.get("event_type", "病程事件"),
                "detail": visit.get("event_detail", ""),
                "severity": visit.get("severity", ""),
            }
        )
    for lab in bundle["labs"]:
        events.append(
            {
                "date": lab.get("sample_date", ""),
                "type": "检验",
                "title": "实验室检验",
                "detail": f"WBC {lab.get('WBC_109L', '未知')}，CRP {lab.get('CRP_mgL', '未知')}，病原学：{lab.get('pathogen_result', '未记录')}",
                "severity": "",
            }
        )
    events.sort(key=lambda item: str(item.get("date", "")))
    return events
