from ..services.operations import GoogleSheetsService

async def get_sheets_service() -> GoogleSheetsService:
    return await GoogleSheetsService.get_instance()