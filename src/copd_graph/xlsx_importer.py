from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List
from xml.etree import ElementTree as ET


NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


@dataclass(frozen=True)
class WorkbookData:
    sheets: Dict[str, List[Dict[str, Any]]]


def parse_xlsx(path: str | Path) -> WorkbookData:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: _normalize_workbook_target(rel.attrib["Target"])
            for rel in rels.findall(f"{NS_PKG_REL}Relationship")
        }

        parsed_sheets: Dict[str, List[Dict[str, Any]]] = {}
        sheets_node = workbook.find(f"{NS_MAIN}sheets")
        if sheets_node is None:
            return WorkbookData(sheets={})

        for sheet in sheets_node.findall(f"{NS_MAIN}sheet"):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib[f"{NS_REL}id"]
            rows = _read_sheet_rows(archive, rel_targets[rel_id], shared_strings)
            parsed_sheets[name] = _rows_to_dicts(rows)

    return WorkbookData(sheets=parsed_sheets)


def parse_xlsx_bytes(content: bytes) -> WorkbookData:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(content)) as archive:
        shared_strings = _read_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: _normalize_workbook_target(rel.attrib["Target"])
            for rel in rels.findall(f"{NS_PKG_REL}Relationship")
        }

        parsed_sheets: Dict[str, List[Dict[str, Any]]] = {}
        sheets_node = workbook.find(f"{NS_MAIN}sheets")
        if sheets_node is None:
            return WorkbookData(sheets={})

        for sheet in sheets_node.findall(f"{NS_MAIN}sheet"):
            name = sheet.attrib["name"]
            rel_id = sheet.attrib[f"{NS_REL}id"]
            rows = _read_sheet_rows(archive, rel_targets[rel_id], shared_strings)
            parsed_sheets[name] = _rows_to_dicts(rows)

    return WorkbookData(sheets=parsed_sheets)


def _normalize_workbook_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def _read_shared_strings(archive: zipfile.ZipFile) -> List[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(raw)
    values = []
    for item in root.findall(f"{NS_MAIN}si"):
        values.append("".join(text.text or "" for text in item.iter(f"{NS_MAIN}t")))
    return values


def _read_sheet_rows(
    archive: zipfile.ZipFile, sheet_path: str, shared_strings: List[str]
) -> List[List[Any]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: List[List[Any]] = []
    for row in root.findall(f".//{NS_MAIN}row"):
        values: List[Any] = []
        for cell in row.findall(f"{NS_MAIN}c"):
            column_index = _column_index(cell.attrib.get("r", "A1"))
            while len(values) < column_index:
                values.append("")
            values.append(_cell_value(cell, shared_strings))
        rows.append(values)
    return rows


def _cell_value(cell: ET.Element, shared_strings: List[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return _coerce_number("".join(text.text or "" for text in cell.iter(f"{NS_MAIN}t")))

    value_node = cell.find(f"{NS_MAIN}v")
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text
    if cell_type == "s":
        return shared_strings[int(raw_value)]
    if cell_type == "b":
        return raw_value == "1"
    return _coerce_number(raw_value)


def _coerce_number(value: str) -> Any:
    if not re.fullmatch(r"-?\d+(\.\d+)?", value):
        return value
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    index = 0
    for char in letters.group(0):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def _rows_to_dicts(rows: Iterable[List[Any]]) -> List[Dict[str, Any]]:
    rows = list(rows)
    if not rows:
        return []
    headers = [str(header).strip() for header in rows[0]]
    items: List[Dict[str, Any]] = []
    for row in rows[1:]:
        item = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            value = row[index] if index < len(row) else ""
            item[header] = value
        if any(value not in ("", None) for value in item.values()):
            items.append(item)
    return items
