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
    ImportValidationError,
    build_patient_state_data,
    connect,
    delete_patients,
    get_import_batch,
    get_latest_assessment,
    import_workbook,
    list_import_batches,
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


def login(client: TestClient, username: str = "doctor", password: str = "doctor123"):
    return client.post(
        "/login",
        data={"username": username, "password": password, "next": "/patients"},
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
        self.assertIn("current_status_summarizer", result["model_call_results"])
        self.assertEqual(
            result["model_call_results"]["current_status_summarizer"]["status"],
            "disabled",
        )
        self.assertIn("risk_assessor", result["model_call_results"])
        self.assertIn("node_run_logs", result)
        self.assertIn("频繁急性加重表型", result["phenotype"]["phenotype_tags"])
        self.assertTrue(result["safety_check_result"]["passed"])
        self.assertIn("report_draft", result)
        self.assertIn("source_dates", result["key_evidence"][0])
        self.assertIn("source_fields", result["key_evidence"][0])
        self.assertNotIn("建议使用", result["report_draft"])
        self.assertNotIn("治疗方案", result["report_draft"])

    def test_storage_deletes_patient_and_related_records(self):
        with connect(TEST_DB_PATH) as connection:
            patients = list_patients(connection, "TEST-001")
            self.assertEqual(len(patients), 1)
            result = build_graph().invoke(
                {"raw_patient_data": build_patient_state_data(connection, "TEST-001")}
            )
            from copd_graph.poc_storage import save_assessment

            save_assessment(connection, "TEST-001", result)
            self.assertIsNotNone(get_latest_assessment(connection, "TEST-001"))

            counts = delete_patients(connection, ["TEST-001"])

            self.assertEqual(counts["patients"], 1)
            self.assertGreaterEqual(counts["visits"], 2)
            self.assertGreaterEqual(counts["labs"], 1)
            self.assertGreaterEqual(counts["assessments"], 1)
            self.assertEqual(list_patients(connection, "TEST-001"), [])
            self.assertIsNone(get_latest_assessment(connection, "TEST-001"))

    def test_web_api_and_pages_are_available(self):
        from copd_graph import web_app

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        self.assertEqual(client.get("/patients", follow_redirects=False).status_code, 303)
        login(client, "admin", "admin123")

        import_page = client.get("/import")
        self.assertEqual(import_page.status_code, 200)
        self.assertNotIn("默认样例文件", import_page.text)
        self.assertIn("type=\"file\"", import_page.text)

        self.assertEqual(client.get("/patients").status_code, 200)
        self.assertIn("no-store", client.get("/patients").headers.get("Cache-Control", ""))
        self.assertEqual(client.get("/patients/TEST-001").status_code, 200)
        self.assertEqual(client.get("/patients/TEST-001/timeline").status_code, 200)

        response = client.post("/api/patients/TEST-001/assessment")
        self.assertEqual(response.status_code, 200)
        assessment_id = response.json()["assessment_id"]

        self.assertEqual(client.get(f"/api/assessments/{assessment_id}").status_code, 200)
        assessment_payload = client.get(f"/api/assessments/{assessment_id}").json()
        self.assertGreaterEqual(len(assessment_payload["model_logs"]), 3)
        self.assertGreaterEqual(len(assessment_payload["node_logs"]), 7)
        self.assertIn("started_at_display", assessment_payload["node_logs"][0])
        self.assertNotIn("DASHSCOPE_API_KEY", str(assessment_payload))
        report_response = client.post(f"/api/assessments/{assessment_id}/report")
        self.assertEqual(report_response.status_code, 200)
        self.assertIn("辅助评估报告草稿", report_response.json()["report_draft"])

        detail_page = client.get("/patients/TEST-001")
        self.assertEqual(detail_page.status_code, 200)
        self.assertIn("查看报告", detail_page.text)
        self.assertIn("查看报告", detail_page.text)
        self.assertIn("最近评估与报告摘要", detail_page.text)
        self.assertIn("报告摘要", detail_page.text)
        self.assertIn("生成智能评估", detail_page.text)
        self.assertIn("临床流程进度", detail_page.text)
        self.assertIn(f'href="/assessments/{assessment_id}"', detail_page.text)

        list_page = client.get("/patients")
        self.assertEqual(list_page.status_code, 200)
        self.assertIn("任务筛选", list_page.text)
        self.assertIn("下一步", list_page.text)
        self.assertIn(f"/assessments/{assessment_id}/report", list_page.text)

        doctor_client = TestClient(web_app.app)
        login(doctor_client)
        doctor_detail = doctor_client.get("/patients/TEST-001")
        self.assertEqual(doctor_detail.status_code, 200)
        self.assertIn("进入复核", doctor_detail.text)
        self.assertIn(f'href="/assessments/{assessment_id}/review"', doctor_detail.text)
        assessment_page = doctor_client.get(f"/assessments/{assessment_id}")
        self.assertEqual(assessment_page.status_code, 200)
        self.assertIn("重新生成评估", assessment_page.text)
        self.assertIn(">重新生成智能评估<", assessment_page.text)
        self.assertIn(">规则评估测试<", assessment_page.text)
        self.assertIn("智能评估生成中...", assessment_page.text)
        self.assertIn("button-loading", assessment_page.text)
        self.assertIn(f'href="/reports/', assessment_page.text)
        doctor_list = doctor_client.get("/patients")
        self.assertEqual(doctor_list.status_code, 200)
        self.assertIn("进入复核", doctor_list.text)

        dashboard_page = doctor_client.get("/dashboard")
        self.assertEqual(dashboard_page.status_code, 200)
        self.assertIn("医生工作台", dashboard_page.text)
        self.assertIn("今日优先处理", dashboard_page.text)

    def test_local_rule_assessment_mode_skips_qwen_api(self):
        from copd_graph import web_app

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        login(client)

        response = client.post("/api/patients/TEST-001/assessment?assessment_mode=local_rules")
        self.assertEqual(response.status_code, 200)
        assessment_id = response.json()["assessment_id"]

        assessment_payload = client.get(f"/api/assessments/{assessment_id}").json()
        statuses = {log["status"] for log in assessment_payload["model_logs"]}
        self.assertEqual(statuses, {"local_rules"})
        self.assertEqual(assessment_payload["assessment_mode"], "local_rules")
        self.assertNotIn("DASHSCOPE_API_KEY", str(assessment_payload))

    def test_web_delete_single_and_bulk_patients(self):
        from copd_graph import web_app

        sample_path = PROJECT_ROOT / "data" / "copd_patient_import_sample_100.xlsx"
        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        login(client, "admin", "admin123")
        with sample_path.open("rb") as file:
            client.post(
                "/api/import/patients",
                files={
                    "file": (
                        "copd_patient_import_sample_100.xlsx",
                        file,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        single = client.delete("/api/patients/COPD-S001")
        self.assertEqual(single.status_code, 200)
        self.assertEqual(client.get("/api/patients?q=COPD-S001").json()["count"], 0)

        bulk = client.post(
            "/api/patients/delete",
            json={"patient_ids": ["COPD-S002", "COPD-S003"]},
        )
        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(client.get("/api/patients?q=COPD-S002").json()["count"], 0)
        self.assertEqual(client.get("/api/patients?q=COPD-S003").json()["count"], 0)

    def test_clinical_review_report_version_and_export_flow(self):
        from copd_graph import web_app

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        login(client)

        response = client.post("/api/patients/TEST-001/assessment?assessment_mode=local_rules")
        self.assertEqual(response.status_code, 200)
        assessment_id = response.json()["assessment_id"]

        assessment_payload = client.get(f"/api/assessments/{assessment_id}").json()
        report = assessment_payload["report"]
        report_id = report["report_id"]
        self.assertEqual(report["review_status"], "待复核")
        self.assertEqual(report["report_status"], "草稿")
        self.assertEqual(report["current_version"], 1)

        blocked_confirm = client.post(
            f"/api/reports/{report_id}/confirm",
            json={"reviewer_name": "测试医生", "review_comment": "尚未复核 AI 评估。"},
        )
        self.assertEqual(blocked_confirm.status_code, 400)
        self.assertIn("需先完成 AI 评估复核", blocked_confirm.text)

        edit_response = client.post(
            f"/reports/{report_id}/edit",
            data={
                "content": "编辑后的慢阻肺智能辅助评估报告。\n本报告不替代医生临床判断。",
                "edited_by": "测试医生",
                "change_summary": "补充复核后的报告正文",
            },
        )
        self.assertEqual(edit_response.status_code, 200)
        edited = client.get(f"/api/reports/{report_id}").json()
        self.assertEqual(edited["current_version"], 2)
        self.assertEqual(edited["report_status"], "待确认")
        self.assertEqual(edited["review_status"], "待复核")
        self.assertEqual(len(edited["versions"]), 2)

        review_page = client.get(f"/assessments/{assessment_id}/review")
        self.assertEqual(review_page.status_code, 200)
        self.assertIn("AI 评估复核", review_page.text)
        self.assertIn("复核 AI 智能评估结果是否可信", review_page.text)

        approve_review = client.post(
            f"/assessments/{assessment_id}/review",
            data={
                "action": "confirm",
                "reviewer_name": "测试医生",
                "review_comment": "AI 评估结果、证据和安全边界可接受。",
            },
        )
        self.assertEqual(approve_review.status_code, 200)
        approved = client.get(f"/api/reports/{report_id}").json()
        self.assertEqual(approved["review_status"], "评估已通过")
        self.assertEqual(approved["report_status"], "待确认")

        confirm_response = client.post(
            f"/api/reports/{report_id}/confirm",
            json={"reviewer_name": "测试医生", "review_comment": "确认可作为辅助评估报告。"},
        )
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.json()["report_status"], "已确认")
        self.assertEqual(confirm_response.json()["review_status"], "评估已通过")

        locked_page = client.get(f"/reports/{report_id}/edit")
        self.assertEqual(locked_page.status_code, 200)
        self.assertIn("报告正文已锁定", locked_page.text)
        self.assertIn("修改报告", locked_page.text)

        blocked_edit = client.post(
            f"/reports/{report_id}/edit",
            data={
                "content": "未点击修改按钮的编辑不应保存。",
                "edited_by": "测试医生",
                "change_summary": "绕过锁定",
            },
        )
        self.assertEqual(blocked_edit.status_code, 400)

        unlocked_page = client.get(f"/reports/{report_id}/edit?edit=1")
        self.assertEqual(unlocked_page.status_code, 200)
        self.assertIn("你正在修改已确认报告", unlocked_page.text)
        self.assertIn("require-review-comment", unlocked_page.text)
        self.assertIn("disabled>确认并锁定报告", unlocked_page.text)
        self.assertIn("disabled formaction", unlocked_page.text)

        confirmed_edit = client.post(
            f"/reports/{report_id}/edit",
            data={
                "content": "修改已确认报告后生成的新版本。",
                "edited_by": "测试医生",
                "change_summary": "确认后再次修改",
                "allow_confirmed_edit": "1",
            },
        )
        self.assertEqual(confirmed_edit.status_code, 200)
        edited_after_confirm = client.get(f"/api/reports/{report_id}").json()
        self.assertEqual(edited_after_confirm["current_version"], 3)
        self.assertEqual(edited_after_confirm["report_status"], "待确认")
        self.assertEqual(edited_after_confirm["review_status"], "评估已通过")

        empty_reject_page = client.post(
            f"/reports/{report_id}/reject",
            data={"reviewer_name": "测试医生", "review_comment": ""},
        )
        self.assertEqual(empty_reject_page.status_code, 400)
        self.assertIn("驳回报告必须填写原因", empty_reject_page.text)
        self.assertIn("报告确认", empty_reject_page.text)
        self.assertNotIn('{"detail"', empty_reject_page.text)

        empty_reject = client.post(
            f"/api/reports/{report_id}/reject",
            json={"reviewer_name": "测试医生", "review_comment": ""},
        )
        self.assertEqual(empty_reject.status_code, 400)

        reject_response = client.post(
            f"/api/reports/{report_id}/reject",
            json={"reviewer_name": "测试医生", "review_comment": "需要补充关键证据说明。"},
        )
        self.assertEqual(reject_response.status_code, 200)
        self.assertEqual(reject_response.json()["report_status"], "已驳回")
        self.assertEqual(reject_response.json()["review_status"], "评估已通过")
        self.assertGreaterEqual(len(reject_response.json()["review_logs"]), 4)

        export_page = client.get(f"/reports/{report_id}/export")
        self.assertEqual(export_page.status_code, 200)
        self.assertIn("慢阻肺智能辅助评估报告", export_page.text)
        self.assertIn("AI 评估复核与报告确认", export_page.text)
        self.assertIn("版本追溯", export_page.text)

    def test_api_imports_new_template_xlsx_upload(self):
        from copd_graph import web_app

        sample_path = PROJECT_ROOT / "data" / "copd_patient_import_sample_100.xlsx"
        self.assertTrue(sample_path.exists())

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        login(client, "admin", "admin123")
        with sample_path.open("rb") as file:
            response = client.post(
                "/api/import/patients",
                files={
                    "file": (
                        "copd_patient_import_sample_100.xlsx",
                        file,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["patients"], 100)
        self.assertGreater(response.json()["counts"]["visits"], 0)
        self.assertEqual(response.json()["source"], "copd_patient_import_sample_100.xlsx")
        patient_response = client.get("/api/patients?q=COPD-S001")
        self.assertEqual(patient_response.status_code, 200)
        self.assertEqual(patient_response.json()["count"], 1)

    def test_qwen_config_does_not_expose_secrets(self):
        env_example = PROJECT_ROOT / ".env.example"
        gitignore = PROJECT_ROOT / ".gitignore"
        self.assertTrue(env_example.exists())
        env_text = env_example.read_text(encoding="utf-8")
        self.assertIn("DASHSCOPE_API_KEY=", env_text)
        self.assertIn("QWEN_ENABLE=false", env_text)
        self.assertNotIn("sk-", env_text)
        self.assertIn(".env", gitignore.read_text(encoding="utf-8"))

    def test_web_time_filter_displays_beijing_time(self):
        from copd_graph.web_app import format_local_time

        self.assertEqual(
            format_local_time("2026-06-06T19:02:39.807"),
            "2026-06-07 03:02:39",
        )
        self.assertEqual(
            format_local_time("2026-06-07T03:02:39.807+08:00"),
            "2026-06-07 03:02:39",
        )

    def test_import_logs_and_patient_filters(self):
        from copd_graph import web_app

        sample_path = PROJECT_ROOT / "data" / "copd_patient_import_sample_100.xlsx"
        web_app.DEFAULT_DB_PATH = TEST_DB_PATH
        client = TestClient(web_app.app)
        login(client, "admin", "admin123")
        with sample_path.open("rb") as file:
            response = client.post(
                "/api/import/patients",
                files={
                    "file": (
                        "copd_patient_import_sample_100.xlsx",
                        file,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        self.assertEqual(response.status_code, 200)
        batch_id = response.json()["batch_id"]
        self.assertEqual(client.get("/api/imports").status_code, 200)
        batch_response = client.get(f"/api/imports/{batch_id}")
        self.assertEqual(batch_response.status_code, 200)
        self.assertEqual(batch_response.json()["counts"]["patients"], 100)

        filtered = client.get(f"/api/patients?followup_status=已随访&import_batch_id={batch_id}")
        self.assertEqual(filtered.status_code, 200)
        self.assertGreater(filtered.json()["count"], 0)
        self.assertEqual(client.get("/imports").status_code, 200)
        self.assertEqual(client.get(f"/imports/{batch_id}").status_code, 200)

    def test_role_permissions_and_audit_logs(self):
        from copd_graph import web_app

        web_app.DEFAULT_DB_PATH = TEST_DB_PATH

        anonymous = TestClient(web_app.app)
        self.assertEqual(anonymous.get("/api/patients").status_code, 401)

        doctor_login = TestClient(web_app.app)
        login_response = doctor_login.post(
            "/login",
            data={"username": "doctor", "password": "doctor123", "next": "/patients"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 303)
        self.assertEqual(login_response.headers["location"], "/dashboard")

        researcher = TestClient(web_app.app)
        login(researcher, "researcher", "researcher123")
        self.assertEqual(researcher.get("/api/patients").status_code, 200)
        self.assertEqual(researcher.get("/dashboard", follow_redirects=False).status_code, 303)
        self.assertEqual(
            researcher.post("/api/patients/TEST-001/assessment").status_code,
            403,
        )
        self.assertEqual(researcher.get("/import").status_code, 403)

        admin = TestClient(web_app.app)
        login(admin, "admin", "admin123")
        self.assertEqual(admin.get("/admin/users").status_code, 200)
        config_page = admin.get("/admin/config")
        self.assertEqual(config_page.status_code, 200)
        self.assertIn("DASHSCOPE_API_KEY", config_page.text)
        self.assertNotIn("sk-", config_page.text)
        audit_response = admin.get("/api/audit-logs")
        self.assertEqual(audit_response.status_code, 200)
        self.assertGreaterEqual(audit_response.json()["count"], 1)
        self.assertNotIn("DASHSCOPE_API_KEY", str(audit_response.json()))

    def test_template_import_validation_reports_errors(self):
        workbook = WorkbookData(
            sheets={
                "patients": [
                    {
                        "patient_id": "",
                        "gender": "男",
                        "age": 66,
                        "created_date": "2026-01-01",
                    },
                    {
                        "patient_id": "BAD-001",
                        "gender": "男",
                        "age": 140,
                        "created_date": "2026/01/02",
                    },
                    {
                        "patient_id": "BAD-001",
                        "gender": "男",
                        "age": 66,
                        "created_date": "2026-01-03",
                    },
                ],
                "symptom_scores": [
                    {
                        "symptom_id": "S-BAD",
                        "patient_id": "UNKNOWN",
                        "assessment_date": "2026-01-02",
                        "cat_score": 99,
                    }
                ],
            }
        )

        with connect(TEST_DB_PATH) as connection:
            with self.assertRaises(ImportValidationError) as context:
                import_workbook(connection, workbook, "bad.xlsx")
            result = context.exception.result
            batch = get_import_batch(connection, result["batch_id"])
            batches = list_import_batches(connection)

        messages = " ".join(issue["message"] for issue in result["errors"])
        self.assertIn("patient_id 为必填字段", messages)
        self.assertIn("同一次导入内患者ID重复", messages)
        self.assertIn("日期格式应为 YYYY-MM-DD", messages)
        self.assertIn("数值超出合理范围", messages)
        self.assertIn("不存在于 patients sheet", messages)
        self.assertEqual(batch["status"], "failed")
        self.assertTrue(any(item["batch_id"] == result["batch_id"] for item in batches))


if __name__ == "__main__":
    unittest.main()
