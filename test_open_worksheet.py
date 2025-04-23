# test_open_worksheet.py
import json
from gateway.app.services.core.connections import open_worksheet_sync
from gateway.app.services.core import log

def test_open_worksheet():
    log.info(f"Initial type of open_worksheet_sync: {type(open_worksheet_sync)}")
    log.info("Testing open_worksheet_sync")
    try:
        sheet, rows, notes = open_worksheet_sync()
        log.info(f"Post-call type of open_worksheet_sync: {type(open_worksheet_sync)}")
        log.info(f"Successfully loaded worksheet: {sheet.title}")
        log.info(f"Rows count: {len(rows)}")
        log.info(f"Notes count: {len(notes)}")
        log.info(f"First 5 rows: {rows[:5]}")
        log.info(f"Notes sample: {dict(list(notes.items())[:5])}")

        # Сохраняем результат в файл для анализа
        result = {
            "sheet_title": sheet.title,
            "rows_count": len(rows),
            "rows_sample": rows[:5],
            "notes_count": len(notes),
            "notes_sample": dict(list(notes.items())[:5])
        }
        with open("tests/open_worksheet_result.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)
        log.info("Results saved to tests/open_worksheet_result.json")
    except Exception as e:
        log.error(f"Failed to run open_worksheet_sync: {e}")
        raise

if __name__ == "__main__":
    test_open_worksheet()