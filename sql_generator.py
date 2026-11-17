from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable


DEFAULT_DICTIONARY = Path(__file__).with_name("DICTIONNAIRE.csv")
ALT_DICTIONARY = Path(__file__).with_name("DICTIONAAIRE.csv")
FALLBACK_DICTIONARY = Path(__file__).with_name("ACC.csv")


def canonicalize(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]+", "", str(value).upper())


def application_canonical_key(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    cleaned = re.sub(r"^(T24MD\.|T24MD)", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.split("#", 1)[0].split("@", 1)[0]
    cleaned = cleaned.replace("-", "_")
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.upper()


def normalize_alias(value: str) -> str:
    raw = str(value or "FIELD").strip()
    raw = re.sub(r"^@+", "", raw)
    raw = raw.replace("-", "_").replace("/", "_").replace(".", "_")
    raw = raw.replace(" ", "_")
    raw = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        raw = "FIELD"
    if raw[0].isdigit():
        raw = f"F{raw}"
    return raw.upper()


def parse_dictionary(csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            if raw is None:
                continue
            cleaned = {key.strip(): (value.strip() if isinstance(value, str) else value) for key, value in raw.items() if key is not None}
            if not cleaned.get("APPLICATION"):
                continue
            rows.append(cleaned)
    return rows


def infer_application_name(application_name: str | None, table_name: str | None) -> str:
    candidates: list[str] = []
    for candidate in (application_name, table_name):
        if not candidate or not candidate.strip():
            continue
        value = candidate.strip()
        value = re.sub(r"^(T24MD\.)", "", value, flags=re.IGNORECASE)
        value = value.split("#", 1)[0]
        value = value.split("@", 1)[0]
        value = value.strip()
        if value:
            candidates.append(value)
    if candidates:
        return candidates[0]
    raise ValueError("You must provide an application name or a table name.")


def find_matching_rows(rows: Iterable[dict], application_name: str | None, table_name: str | None) -> list[dict]:
    target = infer_application_name(application_name, table_name)
    target_key = application_canonical_key(target)

    matches: list[dict] = []
    for row in rows:
        app = (row.get("APPLICATION") or "").strip()
        app_key = application_canonical_key(app)
        if app_key == target_key:
            matches.append(row)

    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for row in matches:
        key = ((row.get("ORDRE_CHAMPS") or "").strip(), (row.get("CHAMP") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def lr_multi_index(row: dict) -> str | None:
    regle = (row.get("REGLE") or "").strip()
    type_input = (row.get("TYPE_INPUT") or "").strip()
    for value in (regle, type_input):
        if not value:
            continue
        match = re.search(r"\d+", value)
        if match:
            return match.group(0)
    return None


def derive_xml_order(row: dict) -> str:
    ordre = (row.get("ORDRE_CHAMPS") or "").strip()
    if ordre and ordre.isdigit():
        return ordre
    if is_lr_multi_field(row):
        idx = lr_multi_index(row)
        if idx:
            return idx
    return ""


def is_lr_multi_field(row: dict) -> bool:
    if (row.get("CHAMP_MUTIPLE") or "").strip().upper() != "M":
        return False

    regle = (row.get("REGLE") or "").strip().upper()
    type_input = (row.get("TYPE_INPUT") or "").strip().upper()
    if "LR" in regle or "LR" in type_input:
        return True
    return False


def is_simple_xml_field(row: dict) -> bool:
    champ = (row.get("CHAMP") or "").strip()
    if not champ:
        return False

    lowered = champ.upper()
    if any(token in lowered for token in ["SUBR(", "LOWER(", "IF ", "CASE ", "CONDITION.GROUP", "@ID", ">", "[", "]"]):
        return False

    if derive_xml_order(row):
        return True

    return False


def sort_field_rows(rows: Iterable[dict]) -> list[dict]:
    def key(row: dict) -> tuple[int, int]:
        order = derive_xml_order(row)
        if order.isdigit():
            return (0, int(order))
        return (1, 999999)

    return sorted((row for row in rows if is_simple_xml_field(row)), key=key)


def field_expression(alias: str, ordre: str, is_multi: bool = False, multi_index: str | int | None = None) -> str:
    if is_multi:
        if multi_index is None:
            multi_index = 1
        return f"EXTRACTVALUE({alias}.XMLRECORD, 'row/c{ordre}[@m={multi_index}]')"
    return f"EXTRACTVALUE({alias}.XMLRECORD, 'row/c{ordre}[1]')"


def build_select_query(
    application_name: str | None = None,
    application: str | None = None,
    table_name: str | None = None,
    alias: str = "T",
    dictionary_path: str | Path | None = None,
    field_name: str | None = None,
    fields: list[str] | None = None,
) -> str:
    if application_name is None:
        application_name = application
    if table_name is None:
        raise ValueError("A table name is required.")
    if application_name is None:
        raise ValueError("An application name is required.")

    path = Path(dictionary_path) if dictionary_path else DEFAULT_DICTIONARY
    if not path.exists():
        path = ALT_DICTIONARY
    if not path.exists():
        path = FALLBACK_DICTIONARY
    if not path.exists():
        raise FileNotFoundError("Dictionary file not found. Expected DICTIONNAIRE.csv, DICTIONAAIRE.csv, or ACC.csv in the same folder.")

    rows = parse_dictionary(path)
    matches = find_matching_rows(rows, application_name, table_name)

    selected_fields = fields or []
    if field_name is not None:
        selected_fields.append(field_name)
    if selected_fields:
        normalized = {normalize_alias(f).lower() for f in selected_fields if f}
        matches = [
            row for row in matches
            if normalize_alias((row.get("CHAMP") or "")).lower() in normalized
            or (row.get("CHAMP") or "").strip().lower() in {f.lower() for f in selected_fields if f}
        ]

    if not matches:
        raise ValueError(
            f"No dictionary fields were found for '{application_name or table_name}'. "
            "Check the application name, table name, or field filter."
        )

    ordered_rows = sort_field_rows(matches)
    select_lines: list[str] = [f"SELECT"]
    select_lines.append(f"    {alias}.RECID AS RECID,")

    for row in ordered_rows:
        ordre = derive_xml_order(row)
        champ = (row.get("CHAMP") or "").strip()
        if not ordre or not champ:
            continue
        if not is_simple_xml_field(row):
            continue
        if champ in {"@ID", "ID"}:
            continue

        if champ.lower().startswith("@id"):
            continue
        if champ.lower().startswith("local.ref"):
            continue
        if champ.lower().startswith("reserved."):
            continue
        if champ.lower().startswith("override"):
            continue
        if champ.lower().startswith("record.status"):
            continue
        if champ.lower().startswith("curr.no"):
            continue
        if champ.lower().startswith("inputter"):
            continue
        if champ.lower().startswith("date.time"):
            continue
        if champ.lower().startswith("authoriser"):
            continue
        if champ.lower().startswith("co.code"):
            continue
        if champ.lower().startswith("dept.code"):
            continue
        if champ.lower().startswith("auditor.code"):
            continue
        if champ.lower().startswith("audit.date.time"):
            continue

        is_multi = is_lr_multi_field(row)
        multi_idx = None
        if is_multi:
            multi_idx = lr_multi_index(row)

        alias_name = normalize_alias(champ)
        select_lines.append(f"    {field_expression(alias, ordre, is_multi=is_multi, multi_index=multi_idx)} AS {alias_name},")

    if select_lines[-1].endswith(","):
        select_lines[-1] = select_lines[-1][:-1]

    select_lines.append(f"FROM")
    select_lines.append(f"    {table_name} {alias}")

    return "\n".join(select_lines) + ";"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a T24 XML extraction query from a dictionary CSV.")
    parser.add_argument("application_name", nargs="?", help="Application name such as ACCOUNT or FUNDS.TRANSFER")
    parser.add_argument("table_name", help="Full table name such as T24MD.ACCOUNT#HIS@AMLCRT")
    parser.add_argument("--alias", default="T", help="Table alias to use in the SQL query")
    parser.add_argument("--dictionary", default=str(DEFAULT_DICTIONARY), help="Path to the dictionary CSV file")
    parser.add_argument("--application", dest="application", help="Alternate name for the application, accepted for compatibility")
    parser.add_argument("--field", dest="field_name", help="Only keep this field from the dictionary, e.g. CUSTOMER")
    args = parser.parse_args()

    query = build_select_query(
        application_name=args.application_name,
        application=args.application,
        table_name=args.table_name,
        alias=args.alias,
        dictionary_path=args.dictionary,
        field_name=args.field_name,
    )
    print(query)


if __name__ == "__main__":
    main()
