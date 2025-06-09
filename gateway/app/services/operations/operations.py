import asyncio
import re
from typing import Any, Dict

from ..core.config import log, SPREADSHEET_URL
from ..core.connections import open_worksheet_sync, get_gs_creds
from ..core.utils import to_float
from googleapiclient.discovery import build
from peewee import DoesNotExist
from .task_storage import Task
import json


class Operations:
    def __init__(self, service):
        self.service = service
        self.ws = None
        self._init_ws()

    def _init_ws(self):
        result = open_worksheet_sync()
        if not isinstance(result, tuple) or len(result) != 3:
            raise ValueError(f"Expected tuple of length 3, got {type(result)}")
        self.ws, _, _ = result
        log.info("Worksheet initialized for Operations")

    def col_to_letter(self, col: int) -> str:
        letters = ""
        while col > 0:
            col, remainder = divmod(col - 1, 26)
            letters = chr(65 + remainder) + letters
        return letters

    def _normalize_value(self, value: str) -> str:
        """Нормализует строковое представление числа для сравнения."""
        value = value.replace(",", ".")
        try:
            return f"{float(value):.2f}"
        except ValueError:
            return value

    def _format_formula(self, amount: float, current_formula: str, operation: str = "add") -> str:
        value_str = f"{amount:.2f}"
        if operation == "add":
            if not current_formula:
                return f"={value_str.replace('.', ',')}"
            return f"{current_formula}+{value_str.replace('.', ',')}"
        else:  # remove
            if not current_formula:
                return ""
            # Разделяем формулу на части
            parts = current_formula.lstrip('=').split('+')
            # Нормализуем части и искомое значение
            normalized_parts = [self._normalize_value(part) for part in parts]
            normalized_value = self._normalize_value(value_str)
            if normalized_value in normalized_parts:
                index = normalized_parts.index(normalized_value)
                del parts[index]
            new_formula = "+".join(parts)
            return f"={new_formula}" if new_formula else ""

    async def _get_cell_value(self, row: int, col: int) -> str:
        cell = f"{self.col_to_letter(col)}{row}"
        return self.ws.acell(cell).value or ""

    async def _get_cell_note(self, row: int, col: int) -> str:
        cell = f"{self.col_to_letter(col)}{row}"
        svc = build("sheets", "v4", credentials=get_gs_creds())
        try:
            response = svc.spreadsheets().get(
                spreadsheetId=SPREADSHEET_URL,
                ranges=[f"{self.ws.title}!{cell}"],
                fields="sheets.data.rowData.values.note"
            ).execute()

            sheets = response.get("sheets", [])
            if not sheets:
                return ""

            data = sheets[0].get("data", [])
            if not data:
                return ""

            row_data = data[0].get("rowData", [])
            if not row_data or len(row_data) == 0:
                return ""

            values = row_data[0].get("values", [])
            if not values or len(values) == 0:
                return ""

            note = values[0].get("note", "")
            return note
        except Exception as e:
            log.error(f"Failed to get note for cell {cell}: {str(e)}")
            return ""

    async def _get_cell_formula(self, row: int, col: int) -> str:
        cell = f"{self.col_to_letter(col)}{row}"
        formula = self.ws.acell(cell, value_render_option='FORMULA').value or ""
        return formula

    async def _write_cell(self, row: int, col: int, value: float, comment: str | None, operation: str = "add"):
        cell = f"{self.col_to_letter(col)}{row}"

        # Получаем текущую формулу ячейки
        current_formula = await self._get_cell_formula(row, col)
        log.debug(f"Current formula in cell {cell}: {current_formula}")

        # Формируем новую формулу
        new_formula = self._format_formula(value, current_formula, operation)
        log.debug(f"New formula for cell {cell}: {new_formula}")
        if new_formula:
            self.ws.update_acell(cell, new_formula)
        else:
            self.ws.update_acell(cell, "")

        # Обновление комментария
        if operation == "add" and comment:
            current_comment = await self._get_cell_note(row, col)
            formatted_comment = f"✨{value:.2f} {comment}✨"
            new_comment = f"{current_comment}\n{formatted_comment}" if current_comment else formatted_comment
        elif operation == "remove":
            current_comment = await self._get_cell_note(row, col)
            comment_lines = current_comment.split('\n')
            if comment_lines:
                comment_lines.pop()  # Удаляем последний комментарий
            new_comment = "\n".join(comment_lines) if comment_lines else ""
        else:
            new_comment = None

        if new_comment is not None:
            row_index = row - 1
            col_index = col - 1
            request = {
                "updateCells": {
                    "range": {
                        "sheetId": self.ws.id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1
                    },
                    "rows": [{"values": [{"note": new_comment}]}],
                    "fields": "note"
                }
            }
            try:
                self.ws.spreadsheet.batch_update({"requests": [request]})
                log.debug(f"Updated comment in cell {cell}: {new_comment}")
            except Exception as e:
                log.error(f"Failed to update comment for cell {cell}: {str(e)}")
                raise

    async def execute_task(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, str]:
        log.info(f"Executing task {task_type} with payload: {payload}")

        if task_type.startswith("remove_"):
            task_id = payload.get("task_id")
            if not task_id:
                raise ValueError("task_id is required for remove operations")

            try:
                task = Task.get(Task.task_id == task_id)
            except DoesNotExist:
                raise ValueError(f"Task {task_id} not found")

            if task.status != "completed":
                raise ValueError(f"Cannot remove: task {task_id} is not completed (status: {task.status})")

            original_payload = json.loads(task.payload)
            original_task_type = task.task_type

            # Define valid original task types for each remove operation
            valid_original_tasks = {
                "remove_expense": "add_expense",
                "remove_income": "add_income",
                "remove_borrowing": "record_borrowing",
                "remove_repayment": "record_repayment",
                "remove_saving": "record_saving",
            }

            expected_task_type = valid_original_tasks.get(task_type)
            if not expected_task_type:
                raise ValueError(f"Unknown remove task type: {task_type}")

            if original_task_type != expected_task_type:
                raise ValueError(
                    f"Cannot remove: task {task_id} is of type {original_task_type}, expected {expected_task_type}"
                )

            payload = original_payload

        date = payload.get("date")
        if not date:
            raise ValueError("Date is required in payload")
        col = self.service.meta.meta["date_cols"].get(date)
        if not col:
            raise ValueError(f"Date {date} not found in metadata")

        if task_type == "add_expense":
            sec_code = payload.get("sec_code")
            cat_code = payload.get("cat_code")
            sub_code = payload.get("sub_code")
            amount = payload.get("amount")
            comment = payload.get("comment")

            if not all([sec_code, cat_code, sub_code, amount]):
                raise ValueError("Missing required fields: sec_code, cat_code, sub_code, amount")

            section = self.service.meta.meta["expenses"].get(sec_code)
            if not section:
                raise ValueError(f"Section {sec_code} not found")
            category = section.get("cats", {}).get(cat_code)
            if not category:
                raise ValueError(f"Category {cat_code} not found")
            subcategory = category.get("subs", {}).get(sub_code)
            if not subcategory:
                raise ValueError(f"Subcategory {sub_code} not found")

            row = subcategory["row"]
            await self._write_cell(row, col, amount, comment, operation="add")
            return {"status": "success", "message": f"Expense added for {date}"}

        elif task_type == "remove_expense":
            sec_code = payload.get("sec_code")
            cat_code = payload.get("cat_code")
            sub_code = payload.get("sub_code")
            amount = payload.get("amount")

            if not all([sec_code, cat_code, sub_code, amount]):
                raise ValueError("Missing required fields: sec_code, cat_code, sub_code, amount")

            section = self.service.meta.meta["expenses"].get(sec_code)
            if not section:
                raise ValueError(f"Section {sec_code} not found")
            category = section.get("cats", {}).get(cat_code)
            if not category:
                raise ValueError(f"Category {cat_code} not found")
            subcategory = category.get("subs", {}).get(sub_code)
            if not subcategory:
                raise ValueError(f"Subcategory {sub_code} not found")

            row = subcategory["row"]
            await self._write_cell(row, col, amount, None, operation="remove")
            return {"status": "success", "message": f"Expense removed for {date}"}

        elif task_type == "add_income":
            cat_code = payload.get("cat_code")
            amount = payload.get("amount")
            comment = payload.get("comment")

            if not all([cat_code, amount]):
                raise ValueError("Missing required fields: cat_code, amount")

            category = self.service.meta.meta["income"].get("cats", {}).get(cat_code)
            if not category:
                raise ValueError(f"Category {cat_code} not found")

            row = category["row"]
            await self._write_cell(row, col, amount, comment, operation="add")
            return {"status": "success", "message": f"Income added for {date}"}

        elif task_type == "remove_income":
            cat_code = payload.get("cat_code")
            amount = payload.get("amount")

            if not all([cat_code, amount]):
                raise ValueError("Missing required fields: cat_code, amount")

            category = self.service.meta.meta["income"].get("cats", {}).get(cat_code)
            if not category:
                raise ValueError(f"Category {cat_code} not found")

            row = category["row"]
            await self._write_cell(row, col, amount, None, operation="remove")
            return {"status": "success", "message": f"Income removed for {date}"}

        elif task_type == "record_borrowing":
            cred_code = payload.get("cred_code")
            amount = payload.get("amount")
            comment = payload.get("comment")

            if not all([cred_code, amount]):
                raise ValueError("Missing required fields: cred_code, amount")

            creditor = self.service.meta.meta["creditors"].get(cred_code)
            if not creditor:
                raise ValueError(f"Creditor {cred_code} not found")

            row = creditor["base"] + 1
            current_balance = self.service.numeric._cell(row, col)
            new_balance = current_balance + amount
            await self._write_cell(row, col, new_balance, comment, operation="add")
            return {"status": "success", "message": f"Borrowing recorded for {date}"}

        elif task_type == "remove_borrowing":
            cred_code = payload.get("cred_code")
            amount = payload.get("amount")

            if not all([cred_code, amount]):
                raise ValueError("Missing required fields: cred_code, amount")

            creditor = self.service.meta.meta["creditors"].get(cred_code)
            if not creditor:
                raise ValueError(f"Creditor {cred_code} not found")

            row = creditor["base"] + 1
            await self._write_cell(row, col, amount, None, operation="remove")
            return {"status": "success", "message": f"Borrowing removed for {date}"}

        elif task_type == "record_repayment":
            cred_code = payload.get("cred_code")
            amount = payload.get("amount")
            comment = payload.get("comment")

            if not all([cred_code, amount]):
                raise ValueError("Missing required fields: cred_code, amount")

            creditor = self.service.meta.meta["creditors"].get(cred_code)
            if not creditor:
                raise ValueError(f"Creditor {cred_code} not found")

            row = creditor["base"] + 2
            current_balance = self.service.numeric._cell(row, col)
            new_balance = current_balance + amount
            await self._write_cell(row, col, new_balance, comment, operation="add")
            return {"status": "success", "message": f"Repayment recorded for {date}"}

        elif task_type == "remove_repayment":
            cred_code = payload.get("cred_code")
            amount = payload.get("amount")

            if not all([cred_code, amount]):
                raise ValueError("Missing required fields: cred_code, amount")

            creditor = self.service.meta.meta["creditors"].get(cred_code)
            if not creditor:
                raise ValueError(f"Creditor {cred_code} not found")

            row = creditor["base"] + 2
            await self._write_cell(row, col, amount, None, operation="remove")
            return {"status": "success", "message": f"Repayment removed for {date}"}

        elif task_type == "record_saving":
            cred_code = payload.get("cred_code")
            amount = payload.get("amount")
            comment = payload.get("comment")

            if not all([cred_code, amount]):
                raise ValueError("Missing required fields: cred_code, amount")

            creditor = self.service.meta.meta["creditors"].get(cred_code)
            if not creditor:
                raise ValueError(f"Creditor {cred_code} not found")

            row = creditor["base"] + 3
            current_balance = self.service.numeric._cell(row, col)
            new_balance = current_balance + amount
            await self._write_cell(row, col, new_balance, comment, operation="add")
            return {"status": "success", "message": f"Saving recorded for {date}"}

        elif task_type == "remove_saving":
            cred_code = payload.get("cred_code")
            amount = payload.get("amount")

            if not all([cred_code, amount]):
                raise ValueError("Missing required fields: cred_code, amount")

            creditor = self.service.meta.meta["creditors"].get(cred_code)
            if not creditor:
                raise ValueError(f"Creditor {cred_code} not found")

            row = creditor["base"] + 3
            await self._write_cell(row, col, amount, None, operation="remove")
            return {"status": "success", "message": f"Saving removed for {date}"}

        raise ValueError(f"Unknown task type: {task_type}")
