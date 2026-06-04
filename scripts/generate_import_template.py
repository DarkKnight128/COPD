from __future__ import annotations

import html
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "copd_patient_import_template.xlsx"

Field = Tuple[str, str, str, str, str, str]


SHEETS: Dict[str, List[Field]] = {
    "patients": [
        ("patient_id", "患者ID", "string", "是", "P0001", "系统内唯一患者编号"),
        ("patient_name", "姓名/脱敏编号", "string", "否", "患者001", "可使用脱敏编号"),
        ("gender", "性别", "string", "是", "男", "男/女"),
        ("birth_date", "出生日期", "date", "否", "1958-05-12", "用于计算年龄"),
        ("age", "年龄", "int", "是", "66", "可由出生日期计算"),
        ("height_cm", "身高", "float", "否", "170", "单位cm"),
        ("weight_kg", "体重", "float", "否", "65", "单位kg"),
        ("bmi", "BMI", "float", "否", "22.5", "可自动计算"),
        ("phone", "联系方式", "string", "否", "脱敏", "POC阶段可不填"),
        ("created_date", "建档日期", "date", "是", "2026-01-10", "患者首次进入系统时间"),
    ],
    "smoking_history": [
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("smoking_status", "是否吸烟", "string", "是", "既往吸烟", "从不/既往/当前"),
        ("cigarettes_per_day", "每日支数", "int", "否", "20", "当前或既往吸烟量"),
        ("smoking_years", "吸烟年限", "int", "否", "30", "吸烟持续年数"),
        ("pack_years", "包年", "float", "否", "30", "可由每日支数和年限计算"),
        ("quit_smoking", "是否戒烟", "string", "否", "是", "是/否"),
        ("quit_years", "戒烟年限", "int", "否", "5", "已戒烟年数"),
    ],
    "comorbidities": [
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("copd_diagnosis_date", "慢阻肺确诊时间", "date", "否", "2020-06-01", "首次确诊时间"),
        ("gold_grade", "GOLD分级", "string", "否", "GOLD 3", "根据肺功能或医生标注"),
        ("hypertension", "高血压", "boolean", "否", "是", "共病"),
        ("diabetes", "糖尿病", "boolean", "否", "否", "共病"),
        ("coronary_disease", "冠心病", "boolean", "否", "是", "共病"),
        ("bronchiectasis", "支气管扩张", "boolean", "否", "否", "共病"),
        ("asthma", "哮喘", "boolean", "否", "否", "共病"),
        ("other_comorbidities", "其他共病", "text", "否", "骨质疏松", "自由文本"),
    ],
    "symptom_scores": [
        ("symptom_id", "记录ID", "string", "是", "S0001", "症状记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("assessment_date", "评估日期", "date", "是", "2026-01-15", "评分日期"),
        ("cat_score", "CAT评分", "int", "否", "18", "COPD Assessment Test"),
        ("mmrc_score", "mMRC评分", "int", "否", "2", "呼吸困难评分"),
        ("cough", "咳嗽", "string", "否", "明显", "无/轻度/明显"),
        ("sputum", "咳痰", "string", "否", "有", "无/有"),
        ("dyspnea", "气促", "string", "否", "活动后气促", "症状描述"),
        ("other_symptoms", "其他症状", "text", "否", "夜间喘息", "自由文本"),
    ],
    "pulmonary_tests": [
        ("pulmonary_test_id", "检查ID", "string", "是", "PF0001", "肺功能检查编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("test_date", "检查日期", "date", "是", "2026-01-16", "肺功能检查日期"),
        ("fev1_l", "FEV1", "float", "否", "1.25", "单位L"),
        ("fvc_l", "FVC", "float", "否", "2.80", "单位L"),
        ("fev1_fvc_ratio", "FEV1/FVC", "float", "否", "0.45", "比值"),
        ("fev1_percent_predicted", "FEV1占预计值百分比", "float", "否", "42.0", "单位%"),
        ("fvc_percent_predicted", "FVC占预计值百分比", "float", "否", "68.0", "单位%"),
        ("feno", "FeNO", "float", "否", "35", "呼出气一氧化氮"),
        ("pulmonary_test_summary", "检查结论", "text", "否", "中重度阻塞性通气功能障碍", "报告结论"),
    ],
    "lab_results": [
        ("lab_id", "检验ID", "string", "是", "L0001", "检验记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("lab_date", "检验日期", "date", "是", "2026-01-16", "检验日期"),
        ("wbc", "白细胞计数", "float", "否", "8.2", "WBC"),
        ("neutrophil_percent", "中性粒细胞比例", "float", "否", "72.5", "单位%"),
        ("eosinophil_count", "嗜酸性粒细胞计数", "float", "否", "0.32", "炎症表型参考"),
        ("crp", "CRP", "float", "否", "12.5", "C反应蛋白"),
        ("pct", "PCT", "float", "否", "0.08", "降钙素原"),
        ("spo2", "血氧饱和度", "float", "否", "92", "单位%"),
        ("pao2", "PaO2", "float", "否", "68", "动脉氧分压"),
        ("paco2", "PaCO2", "float", "否", "48", "动脉二氧化碳分压"),
    ],
    "pathogen_results": [
        ("pathogen_id", "病原学记录ID", "string", "是", "M0001", "病原学记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("pathogen_test_date", "检测日期", "date", "是", "2026-01-17", "检测日期"),
        ("sample_type", "样本类型", "string", "否", "BALF", "肺泡灌洗液/痰液等"),
        ("test_method", "检测方法", "string", "否", "mNGS", "mNGS/培养/PCR"),
        ("detected_pathogens", "检出病原体", "text", "否", "铜绿假单胞菌", "多个可用分号分隔"),
        ("pathogen_abundance", "病原体丰度", "text", "否", "120 reads", "POC阶段可用文本"),
        ("clinical_relevance", "临床相关性", "string", "否", "待医生判断", "只作为感染线索"),
    ],
    "ct_features": [
        ("ct_id", "CT记录ID", "string", "是", "CT0001", "CT记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("ct_date", "检查日期", "date", "是", "2026-01-18", "CT检查日期"),
        ("ct_report_text", "CT报告文本", "text", "否", "双肺肺气肿表现", "结构化或半结构化文本"),
        ("emphysema_percent", "肺气肿比例", "float", "否", "18.5", "已提取影像特征"),
        ("airway_wall_thickness", "气道壁厚度", "float", "否", "1.8", "已提取影像特征"),
        ("lung_volume_index", "肺容积指标", "float", "否", "5.2", "已提取影像特征"),
        ("airway_wall_thickening", "气道壁增厚", "boolean", "否", "是", "来自CT报告"),
        ("bullae", "肺大疱", "boolean", "否", "否", "来自CT报告"),
        ("infection_signs", "感染表现", "boolean", "否", "是", "来自CT报告"),
        ("ct_summary", "CT结论", "text", "否", "慢阻肺影像学改变", "影像总结"),
    ],
    "medications": [
        ("medication_id", "用药ID", "string", "是", "MED0001", "用药记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("start_date", "开始日期", "date", "是", "2026-01-20", "用药开始时间"),
        ("end_date", "结束日期", "date", "否", "2026-02-20", "可为空"),
        ("medication_name", "药物名称", "string", "是", "噻托溴铵", "药物名称"),
        ("medication_type", "药物类别", "string", "否", "LAMA", "LAMA/LABA/ICS等"),
        ("dosage", "用法用量", "string", "否", "每日一次", "文本"),
        ("maintenance_treatment", "是否维持治疗", "boolean", "否", "是", "是/否"),
        ("medication_note", "用药备注", "text", "否", "规律使用", "备注"),
    ],
    "exacerbations": [
        ("exacerbation_id", "急性加重ID", "string", "是", "AE0001", "急性加重记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("exacerbation_date", "发生日期", "date", "是", "2026-02-05", "急性加重发生时间"),
        ("severity", "严重程度", "string", "否", "中度", "轻度/中度/重度"),
        ("hospitalization", "是否住院", "boolean", "否", "是", "是否因加重住院"),
        ("antibiotics_used", "是否使用抗生素", "boolean", "否", "是", "是/否"),
        ("steroid_used", "是否使用激素", "boolean", "否", "是", "是/否"),
        ("trigger_factor", "加重诱因", "text", "否", "感染可能", "可为空"),
        ("outcome", "处理结果", "text", "否", "好转出院", "简要结果"),
    ],
    "followups": [
        ("followup_id", "随访ID", "string", "是", "FU0001", "随访记录编号"),
        ("patient_id", "患者ID", "string", "是", "P0001", "关联患者"),
        ("followup_date", "随访日期", "date", "是", "2026-03-01", "随访时间"),
        ("symptom_change", "当前症状变化", "text", "否", "气促较前加重", "文本"),
        ("new_exacerbation", "是否再次急性加重", "boolean", "否", "否", "是/否"),
        ("rehospitalization", "是否再入院", "boolean", "否", "否", "是/否"),
        ("pulmonary_function_change", "肺功能变化", "text", "否", "FEV1下降", "文本"),
        ("survival_status", "生存状态", "string", "否", "存活", "存活/死亡/失访"),
        ("followup_note", "随访备注", "text", "否", "继续门诊随访", "备注"),
    ],
}


README_ROWS = [
    ["慢阻肺病智能诊疗决策支持系统数据导入模板"],
    ["用途", "用于 POC/MVP 阶段批量录入结构化患者数据。"],
    ["填写规则", "业务 Sheet 第一行必须保留英文系统字段名，不要修改表头。"],
    ["关联规则", "所有 Sheet 的 patient_id 必须能在 patients 表中找到。"],
    ["日期格式", "统一使用 YYYY-MM-DD。"],
    ["CT边界", "仅填写 CT 报告文本或已提取影像特征，不上传原始 CT/DICOM。"],
    ["病原学边界", "mNGS/病原学结果仅作为感染相关线索，不作为诊断结论。"],
    ["说明", "字段中文名、类型、必填、示例和说明见 field_dictionary。"],
]


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    worksheets = {"README": README_ROWS, "field_dictionary": field_dictionary_rows()}
    for sheet_name, fields in SHEETS.items():
        worksheets[sheet_name] = [[field[0] for field in fields]]
    write_xlsx(OUTPUT_PATH, worksheets)
    print(f"created {OUTPUT_PATH}")


def field_dictionary_rows() -> List[List[str]]:
    rows = [["sheet", "field_name", "中文名", "类型", "是否必填", "示例", "说明"]]
    for sheet_name, fields in SHEETS.items():
        for field in fields:
            rows.append([sheet_name, *field])
    return rows


def write_xlsx(path: Path, worksheets: Dict[str, List[List[str]]]) -> None:
    sheet_names = list(worksheets)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types(sheet_names))
        archive.writestr("_rels/.rels", package_rels())
        archive.writestr("xl/workbook.xml", workbook_xml(sheet_names))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels(sheet_names))
        archive.writestr("xl/styles.xml", styles_xml())
        for index, sheet_name in enumerate(sheet_names, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(worksheets[sheet_name]))


def content_types(sheet_names: Iterable[str]) -> str:
    sheet_overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index, _ in enumerate(sheet_names, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {sheet_overrides}
</Types>"""


def package_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def workbook_xml(sheet_names: List[str]) -> str:
    sheets = "\n".join(
        f'<sheet name="{escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, sheet_name in enumerate(sheet_names, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    {sheets}
  </sheets>
</workbook>"""


def workbook_rels(sheet_names: List[str]) -> str:
    sheet_rels = "\n".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index, _ in enumerate(sheet_names, start=1)
    )
    style_id = len(sheet_names) + 1
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {sheet_rels}
  <Relationship Id="rId{style_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Microsoft YaHei"/></font>
    <font><b/><sz val="11"/><name val="Microsoft YaHei"/></font>
  </fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def worksheet_xml(rows: List[List[str]]) -> str:
    row_xml = "\n".join(
        f'<row r="{row_index}">'
        + "".join(
            cell_xml(row_index, column_index, value, style=1 if row_index == 1 else 0)
            for column_index, value in enumerate(row, start=1)
        )
        + "</row>"
        for row_index, row in enumerate(rows, start=1)
    )
    max_col = max((len(row) for row in rows), default=1)
    columns = "\n".join(
        f'<col min="{index}" max="{index}" width="{column_width(index, max_col)}" customWidth="1"/>'
        for index in range(1, max_col + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <cols>{columns}</cols>
  <sheetData>{row_xml}</sheetData>
</worksheet>"""


def cell_xml(row: int, column: int, value: str, style: int = 0) -> str:
    cell_ref = f"{column_name(column)}{row}"
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{cell_ref}" t="inlineStr"{style_attr}><is><t>{escape(str(value))}</t></is></c>'


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def column_width(index: int, max_col: int) -> int:
    if max_col <= 3:
        return 24
    if index == 1:
        return 22
    if index in {2, 3, 4, 5}:
        return 18
    return 28


def escape(value: str) -> str:
    return html.escape(value, quote=True)


if __name__ == "__main__":
    main()
