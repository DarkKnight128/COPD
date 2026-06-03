from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from copd_graph.graph import build_graph
from copd_graph.poc_storage import (
    DEFAULT_DB_PATH,
    build_patient_state_data,
    connect,
    get_assessment,
    get_latest_assessment,
    get_patient_bundle,
    import_workbook,
    init_database,
    list_patients,
    save_assessment,
)
from copd_graph.xlsx_importer import parse_xlsx, parse_xlsx_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"
DEFAULT_SAMPLE_XLSX = Path.home() / "Desktop" / "plan" / "copd_mock_data_v1(1).xlsx"

@asynccontextmanager
async def lifespan(_: FastAPI):
    with connect(DEFAULT_DB_PATH) as connection:
        init_database(connection)
    yield


app = FastAPI(title="COPD POC Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/patients", status_code=303)


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "default_sample_path": str(DEFAULT_SAMPLE_XLSX),
            "default_sample_exists": DEFAULT_SAMPLE_XLSX.exists(),
        },
    )


@app.post("/import-demo")
async def import_demo() -> RedirectResponse:
    if not DEFAULT_SAMPLE_XLSX.exists():
        raise HTTPException(status_code=404, detail=f"Sample Excel not found: {DEFAULT_SAMPLE_XLSX}")
    with connect(DEFAULT_DB_PATH) as connection:
        import_workbook(connection, parse_xlsx(DEFAULT_SAMPLE_XLSX))
    return RedirectResponse(url="/patients", status_code=303)


@app.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request, q: str = "") -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        patients = list_patients(connection, q)
    return templates.TemplateResponse(request, "patients.html", {"patients": patients, "q": q})


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
def run_assessment_page(patient_id: str) -> RedirectResponse:
    assessment = run_patient_assessment(patient_id)
    return RedirectResponse(url=f"/assessments/{assessment['assessment_id']}", status_code=303)


@app.get("/patients/{patient_id}/assessment", response_class=HTMLResponse)
def patient_assessment_page(request: Request, patient_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
        assessment = get_latest_assessment(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return templates.TemplateResponse(
        request,
        "assessment.html",
        {
            "patient": bundle["patient"],
            "assessment": assessment,
        },
    )


@app.get("/assessments/{assessment_id}", response_class=HTMLResponse)
def assessment_page(request: Request, assessment_id: str) -> HTMLResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return templates.TemplateResponse(
        request,
        "assessment.html",
        {
            "patient": {"patient_id": assessment["patient_id"]},
            "assessment": assessment,
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
async def api_import_patients(
    request: Request,
    source_path: str | None = Query(default=None, description="Optional local xlsx path"),
) -> Dict[str, Any]:
    body = await request.body()
    if body:
        workbook = parse_xlsx_bytes(body)
        source = "request body"
    else:
        path = Path(source_path) if source_path else DEFAULT_SAMPLE_XLSX
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Excel file not found: {path}")
        workbook = parse_xlsx(path)
        source = str(path)

    with connect(DEFAULT_DB_PATH) as connection:
        counts = import_workbook(connection, workbook)
    return {"source": source, "counts": counts}


@app.get("/api/patients")
def api_patients(q: str = "") -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        patients = list_patients(connection, q)
    return {"patients": patients, "count": len(patients)}


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
def api_run_assessment(patient_id: str) -> Dict[str, Any]:
    return run_patient_assessment(patient_id)


@app.get("/api/assessments/{assessment_id}")
def api_assessment(assessment_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
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


def run_patient_assessment(patient_id: str) -> Dict[str, Any]:
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            patient_data = build_patient_state_data(connection, patient_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        graph = build_graph()
        result = graph.invoke({"raw_patient_data": patient_data})
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
