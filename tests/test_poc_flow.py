import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from copd_graph.graph import build_graph  # noqa: E402
from copd_graph.poc_storage import (  # noqa: E402
    build_patient_state_data,
    connect,
    import_workbook,
    list_patients,
)
from copd_graph.xlsx_importer import WorkbookData  # noqa: E402


TEST_DB_PATH = PROJECT_ROOT / "data" / "test_poc_flow.sqlite"


def demo_workbook():
    return WorkbookData(
        sheets={
            "Patients": [
                {
                    "patient_id": "TEST-001",
                    "age": 68,
                    "sex": "男",
                    "smoking_pack_years": 40,
                    "comorbidity": "高血压;糖尿病",
                    "CAT_score": 24,
                    "mMRC_score": 3,
                    "FEV1_L": 1.05,
                    "FVC_L": 2.3,
                    "FEV1_FVC": 0.46,
                    "FeNO_ppb": 38,
                    "eosinophil_109L": 0.36,
                    "CRP_mgL": 28.5,
                    "pathogen_result": "流感嗜血杆菌",
                    "current_medication": "LAMA/LABA",
                    "ct_feature_emphysema_pct": 30,
                    "ct_feature_airway_wall_thickening": "明显",
                    "ct_report_summary": "双肺透亮度增高，肺气肿改变；气道壁增厚。",
                    "exacerbation_count_1y": 2,
                    "readmission_90d": "是",
                    "survival_status": "存活",
                    "last_followup_date": "2026-05-20",
                }
            ],
            "Visits": [
                {
                    "event_id": "EV-001",
                    "patient_id": "TEST-001",
                    "event_date": "2026-01-10",
                    "event_type": "急性加重",
                    "event_detail": "咳嗽咳痰加重，门诊处理",
                    "severity": "门诊级",
                },
                {
                    "event_id": "EV-002",
                    "patient_id": "TEST-001",
                    "event_date": "2026-04-10",
                    "event_type": "急性加重住院",
                    "event_detail": "呼吸困难加重，住院治疗",
                    "severity": "住院级",
                },
            ],
            "Labs": [
                {
                    "lab_id": "LAB-001",
                    "patient_id": "TEST-001",
                    "sample_date": "2026-05-18",
                    "WBC_109L": 11.2,
                    "neutrophil_pct": 78.5,
                    "CRP_mgL": 28.5,
                    "PCT_ngmL": 0.18,
                    "FeNO_ppb": 38,
                    "pathogen_result": "肺炎链球菌",
                }
            ],
            "ModelOutputs": [
                {
                    "assessment_id": "MOCK-001",
                    "patient_id": "TEST-001",
                    "assessment_date": "2026-05-29",
                    "exacerbation_risk_level": "高",
                    "long_term_risk_level": "中",
                    "phenotype_label": "频繁加重表型",
                    "model_version": "mock-v0.1",
                }
            ],
        }
    )


class PocFlowTest(unittest.TestCase):
    def setUp(self):
        with connect(TEST_DB_PATH) as connection:
            import_workbook(connection, demo_workbook())

    def test_storage_imports_and_graph_generates_report(self):
        with connect(TEST_DB_PATH) as connection:
            patients = list_patients(connection, "TEST-001")
            self.assertEqual(len(patients), 1)
            self.assertEqual(patients[0]["risk_level"], "高")

            patient_data = build_patient_state_data(connection, "TEST-001")
            result = build_graph().invoke({"raw_patient_data": patient_data})

        self.assertTrue(result["data_quality"]["can_evaluate"])
        self.assertIn("频繁急性加重表型", result["phenotype"]["phenotype_tags"])
        self.assertTrue(result["safety_check_result"]["passed"])
        self.assertIn("report_draft", result)
        self.assertIn("source_dates", result["key_evidence"][0])
        self.assertIn("source_fields", result["key_evidence"][0])
        self.assertNotIn("建议使用", result["report_draft"])
        self.assertNotIn("治疗方案", result["report_draft"])

    def test_web_api_and_pages_are_available(self):
        from copd_graph import web_app

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)

        import_page = client.get("/import")
        self.assertEqual(import_page.status_code, 200)
        self.assertNotIn("默认样例文件", import_page.text)
        self.assertIn("type=\"file\"", import_page.text)

        self.assertEqual(client.get("/patients").status_code, 200)
        self.assertEqual(client.get("/patients/TEST-001").status_code, 200)
        self.assertEqual(client.get("/patients/TEST-001/timeline").status_code, 200)

        response = client.post("/api/patients/TEST-001/assessment")
        self.assertEqual(response.status_code, 200)
        assessment_id = response.json()["assessment_id"]

        self.assertEqual(client.get(f"/api/assessments/{assessment_id}").status_code, 200)
        report_response = client.post(f"/api/assessments/{assessment_id}/report")
        self.assertEqual(report_response.status_code, 200)
        self.assertIn("辅助评估报告草稿", report_response.json()["report_draft"])

    def test_api_imports_new_template_xlsx_upload(self):
        from copd_graph import web_app

        sample_path = PROJECT_ROOT / "data" / "copd_patient_import_sample_40.xlsx"
        self.assertTrue(sample_path.exists())

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        with sample_path.open("rb") as file:
            response = client.post(
                "/api/import/patients",
                files={
                    "file": (
                        "copd_patient_import_sample_40.xlsx",
                        file,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["patients"], 40)
        self.assertGreater(response.json()["counts"]["visits"], 0)
        self.assertEqual(response.json()["source"], "copd_patient_import_sample_40.xlsx")
        patient_response = client.get("/api/patients?q=COPD-S001")
        self.assertEqual(patient_response.status_code, 200)
        self.assertEqual(patient_response.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
