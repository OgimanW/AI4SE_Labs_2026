import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict, deque
from pathlib import Path
from statistics import fmean


TASK_DIR = Path(__file__).resolve().parent
DATA_DIR = TASK_DIR.parent / "Task_2" / "data"
LABELS_PATH = DATA_DIR / "restaurants_dataset.csv"
SCHEMA_PATH = DATA_DIR / "restaurants-schema.csv"
DATABASE_PATH = DATA_DIR / "restaurants-db.txt"
PREDICTION_FILES = {
    "CO-STAR": DATA_DIR / "OUTPUT" / "CO-STAR_restaurants_dataset_predictions.csv",
    "RTF": DATA_DIR / "OUTPUT" / "RTF_restaurants_dataset_predictions.csv",
    "RACE": DATA_DIR / "OUTPUT" / "RACE_restaurants_dataset_predictions.csv",
}
SUMMARY_PATH = TASK_DIR / "f1_results.csv"
DETAILS_PATH = TASK_DIR / "f1_per_question.csv"
REPORT_PATH = TASK_DIR / "REPORT.md"


def sqlite_type(schema_type):
    normalized_type = schema_type.strip().lower()
    if normalized_type.startswith("int"):
        return "INTEGER"
    if normalized_type.startswith(("decimal", "float")):
        return "REAL"
    return "TEXT"


def load_database():
    tables = {}
    with SCHEMA_PATH.open(encoding="utf-8-sig", newline="") as schema_file:
        for table, field, primary_key, _foreign_key, column_type in csv.reader(
            schema_file, skipinitialspace=True
        ):
            table = table.strip()
            if table == "-":
                continue
            tables.setdefault(table, []).append(
                (field.strip(), sqlite_type(column_type), primary_key.strip().lower() == "y")
            )

    connection = sqlite3.connect(":memory:")
    for table, columns in tables.items():
        definitions = []
        for field, column_type, primary_key in columns:
            definition = f'"{field}" {column_type}'
            if primary_key:
                definition += " PRIMARY KEY"
            definitions.append(definition)
        connection.execute(f'CREATE TABLE "{table}" ({", ".join(definitions)})')

    with DATABASE_PATH.open(encoding="utf-8") as database_file:
        for line_number, line in enumerate(database_file, start=1):
            match = re.fullmatch(r"([A-Z_]+)\((.*)\)", line.rstrip("\r\n"))
            if match is None:
                raise ValueError(f"Invalid database record on line {line_number}")

            table, values_text = match.groups()
            if table not in tables:
                raise ValueError(f"Unknown table {table!r} on line {line_number}")

            values = next(csv.reader([values_text], skipinitialspace=True))
            columns = tables[table]
            if len(values) != len(columns):
                raise ValueError(
                    f"Expected {len(columns)} values for {table} on line "
                    f"{line_number}, got {len(values)}"
                )

            converted_values = []
            for value, (_field, column_type, _primary_key) in zip(values, columns):
                if column_type == "INTEGER":
                    converted_values.append(int(value))
                elif column_type == "REAL":
                    converted_values.append(float(value))
                else:
                    converted_values.append(value)

            placeholders = ", ".join("?" for _ in columns)
            connection.execute(
                f'INSERT INTO "{table}" VALUES ({placeholders})', converted_values
            )

    connection.execute("PRAGMA query_only = ON")
    return connection


def load_labels():
    labels_by_question = defaultdict(deque)
    with LABELS_PATH.open(encoding="utf-8-sig", newline="") as source:
        for line_number, row in enumerate(csv.DictReader(source), start=2):
            try:
                result = json.loads(row["result"])
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON label result on line {line_number} of {LABELS_PATH}"
                ) from error
            if not isinstance(result, list):
                raise ValueError(
                    f"Expected a JSON array label result on line {line_number} "
                    f"of {LABELS_PATH}"
                )
            labels_by_question[row["question"]].append(result)
    return labels_by_question


def score_rows(expected_rows, predicted_rows):
    expected = Counter(tuple(row) for row in expected_rows)
    predicted = Counter(tuple(row) for row in predicted_rows)
    true_positives = sum((expected & predicted).values())
    expected_count = sum(expected.values())
    predicted_count = sum(predicted.values())

    if expected_count == 0 and predicted_count == 0:
        precision = recall = 1.0
    elif expected_count == 0 or predicted_count == 0:
        precision = recall = 0.0
    else:
        precision = true_positives / predicted_count
        recall = true_positives / expected_count

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return precision, recall, f1, expected == predicted


def evaluate_prompt(prompt, predictions_path, connection, labels_by_question):
    scores = []
    errors = 0
    with predictions_path.open(encoding="utf-8-sig", newline="") as source:
        for line_number, row in enumerate(csv.DictReader(source), start=2):
            question = row["question"]
            if not labels_by_question[question]:
                raise ValueError(
                    f"No matching label question for prediction on line "
                    f"{line_number} of {predictions_path}: {question!r}"
                )

            expected_rows = labels_by_question[question].popleft()
            sql_error = ""
            try:
                predicted_rows = connection.execute(row["predicted_sql"]).fetchall()
                precision, recall, f1, exact_match = score_rows(
                    expected_rows, predicted_rows
                )
            except sqlite3.Error as error:
                sql_error = str(error)
                print(
                    f"SQL error in {predictions_path.name}, line {line_number}: "
                    f"{sql_error}"
                )
                precision = recall = f1 = 0.0
                exact_match = False
                errors += 1

            scores.append(
                {
                    "prompt": prompt,
                    "question": question,
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                    "exact_match": exact_match,
                    "sql_error": sql_error,
                }
            )

    unmatched_labels = sum(len(results) for results in labels_by_question.values())
    if unmatched_labels:
        raise ValueError(
            f"{unmatched_labels} label records had no corresponding prediction "
            f"in {predictions_path}"
        )
    if not scores:
        raise ValueError(f"No predictions found in {predictions_path}")

    return {
        "prompt": prompt,
        "questions": len(scores),
        "macro_precision": fmean(score["precision"] for score in scores),
        "macro_recall": fmean(score["recall"] for score in scores),
        "macro_f1": fmean(score["f1"] for score in scores),
        "exact_accuracy": fmean(score["exact_match"] for score in scores),
        "sql_errors": errors,
    }, scores


def write_results(summaries, details):
    summary_fields = [
        "prompt",
        "questions",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "exact_accuracy",
        "sql_errors",
    ]
    with SUMMARY_PATH.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summaries)

    detail_fields = [
        "prompt",
        "question",
        "precision",
        "recall",
        "f1",
        "exact_match",
        "sql_error",
    ]
    with DETAILS_PATH.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(details)

    report_lines = [
        "# Úloha 3: Porovnanie promptov pomocou makro F1",
        "",
        "## Metrika",
        "",
        "Táto metrika sa hodí, pretože úloha hodnotí SQL dotazy podľa riadkov, "
        "ktoré vrátia. Čiastočne správny výsledok získa čiastočné skóre, ak "
        "obsahuje niektoré, ale nie všetky očakávané riadky. Poradie riadkov "
        "nemá vplyv na správnosť, duplicitné riadky sa však započítavajú.",
        "",
        "Pri každej otázke sa výsledné riadky porovnávajú ako multimnožiny: "
        "na poradí nezáleží, ale duplicity sa započítavajú. Presnosť "
        "(precision) vyjadruje podiel správnych predikovaných riadkov; "
        "úplnosť (recall) vyjadruje podiel nájdených očakávaných riadkov. "
        "F1 je ich harmonický priemer. Uvedené makro skóre je nevážený "
        "priemer hodnôt vypočítaných pre jednotlivé otázky.",
        "",
        "Ak sú očakávaný aj predikovaný výsledok prázdne, presnosť, úplnosť "
        "aj F1 sú 1. Ak je prázdny iba jeden z nich, všetky tri skóre sú 0. "
        "Chyba pri vykonaní SQL dotazu dostane nulu vo všetkých troch "
        "metrikách. Pre porovnanie je uvedená aj presná zhoda, ktorá "
        "zodpovedá metrike typu všetko alebo nič z Úlohy 2.",
        "",
        "F1 dopĺňa presnú zhodu, nenahrádza ju: F1 udeľuje čiastočné skóre, "
        "ak sú niektoré výsledné riadky správne, zatiaľ čo presná zhoda "
        "započítava iba úplne zhodné množiny výsledkov.",
        "",
        "## Výsledky",
        "",
        "| Prompt | Počet otázok | Makro presnosť | Makro úplnosť | Makro F1 | Presná zhoda | Chyby SQL |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        report_lines.append(
            f"| {summary['prompt']} | {summary['questions']} "
            f"| {summary['macro_precision']:.4f} "
            f"| {summary['macro_recall']:.4f} "
            f"| {summary['macro_f1']:.4f} "
            f"| {summary['exact_accuracy']:.4f} "
            f"| {summary['sql_errors']} |"
        )
    partial_scores = sum(
        0 < detail["f1"] < 1 for detail in details
    )
    report_lines.extend(
        [
            "",
            f"V tomto behu získalo {partial_scores} otázok nenulové čiastočné "
            "F1 menšie ako 1. Makro F1 sa preto pri týchto súboroch predikcií "
            "rovná presnej zhode: každá odpoveď sa buď zhodovala presne, alebo "
            "nemala s očakávaným výsledkom žiadne spoločné riadky. F1 je "
            "naďalej užitočná doplnková metrika v prípadoch, keď sa časť "
            "výsledných riadkov zhoduje.",
            "",
            "Makro F1 neprikladá otázkam vyššiu váhu podľa počtu riadkov "
            "v správnej odpovedi. Skóre pre jednotlivé otázky nájdete v "
            "`f1_per_question.csv`; súhrnné hodnoty sú v `f1_results.csv`.",
            "",
            "Výsledky zo súborov CSV v Úlohe 2 môžete prepočítať spustením "
            "`python calculate_f1.py` z tohto priečinka.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(report_lines), encoding="utf-8")


def main():
    csv.field_size_limit(1_000_000_000)
    all_details = []
    summaries = []
    for prompt, predictions_path in PREDICTION_FILES.items():
        labels_by_question = load_labels()
        connection = load_database()
        try:
            summary, details = evaluate_prompt(
                prompt, predictions_path, connection, labels_by_question
            )
        finally:
            connection.close()
        summaries.append(summary)
        all_details.extend(details)

    write_results(summaries, all_details)
    print("Prompt       Macro F1   Exact accuracy   SQL errors")
    for summary in summaries:
        print(
            f"{summary['prompt']:<12} "
            f"{summary['macro_f1']:.4f}    "
            f"{summary['exact_accuracy']:.4f}           "
            f"{summary['sql_errors']}"
        )
    print(f"Wrote {SUMMARY_PATH}")
    print(f"Wrote {DETAILS_PATH}")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
