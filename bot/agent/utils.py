# Bot/agent/utils.py
import logging
from typing import Dict, List, Any, Optional, Tuple

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from thefuzz import process
from typing_extensions import TypedDict

from .config import OPENAI_API_KEY, BACKEND_URL
from ..api_client import ApiClient, CodeName

# Cache for API responses
section_cache: List[CodeName] = []
category_cache: Dict[str, List[CodeName]] = {}
subcategory_cache: Dict[str, List[CodeName]] = {}
creditor_cache: List[CodeName] = []

# Initialize OpenAI client
logger.debug(f"Initializing OpenAI client with API key: {'*' * len(OPENAI_API_KEY[:-4]) + OPENAI_API_KEY[-4:]}")
try:
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise


# Logging setup
class NoMetadataFilter(logging.Filter):
    def filter(self, record):
        return not ("[METADATA] Fetched metadata" in record.getMessage())


def setup_logging():
    """Configure centralized logging with loguru."""
    logger.remove()  # Remove default handler
    logger.add(
        sink="logs/agent.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        rotation="10 MB",
        filter=lambda record: not ("[METADATA] Fetched metadata" in record["message"])
    )
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level="INFO",
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan> | <level>{message}</level>"
    )
    return logger


# Initialize logger
agent_logger = setup_logging()


# Data structures
class Request(TypedDict):
    intent: str
    entities: Dict[str, Optional[str]]
    missing: List[str]


class Action(TypedDict):
    request_index: int
    needs_clarification: bool
    clarification_field: Optional[str]
    ready_for_output: bool


class AgentState(BaseModel):
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    requests: List[Request] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    combine_responses: bool = False
    output: Dict = Field(default_factory=lambda: {"messages": [], "output": []})
    parse_iterations: int = Field(default=0)
    metadata: Optional[Dict] = Field(default=None)


# Tools
async def validate_category(category_name: str, chapter_code: str) -> Dict[str, Any]:
    """Validate category name against API and return category code."""
    agent_logger.info(f"[VALIDATE] Validating category: {category_name}, chapter: {chapter_code}")
    async with ApiClient(base_url=BACKEND_URL) as api_client:
        try:
            categories = category_cache.get(chapter_code)
            if not categories:
                agent_logger.debug(f"[VALIDATE] Fetching categories for chapter_code: {chapter_code}")
                categories = await api_client.get_categories(chapter_code)
                if not categories:
                    agent_logger.error(f"[VALIDATE] No categories found for chapter_code: {chapter_code}")
                    return {"category_code": None, "success": False, "error": "No categories available"}
                category_cache[chapter_code] = categories
            category_names = [cat.name for cat in categories]
            match, score = fuzzy_match(category_name, category_names)
            if score > 0.9:
                result = {"category_code": next(cat.code for cat in categories if cat.name == match), "success": True}
                agent_logger.info(f"[VALIDATE] Validation result: {result}")
                return result
            result = {"category_code": None, "success": False}
            agent_logger.info(f"[VALIDATE] Validation result: {result}")
            return result
        except Exception as e:
            agent_logger.exception(f"[VALIDATE] Error in validate_category: {e}")
            return {"category_code": None, "success": False, "error": str(e)}


tools = [
    {
        "name": "validate_category",
        "description": "Validate a category name against the API for a given chapter code.",
        "parameters": {
            "type": "object",
            "properties": {
                "category_name": {"type": "string", "description": "Name of the category to validate"},
                "chapter_code": {"type": "string", "description": "Chapter code (e.g., P4)"}
            },
            "required": ["category_name", "chapter_code"]
        }
    }
]

def fuzzy_match(query: str, choices: list) -> Tuple[Optional[str], float]:
    """Perform fuzzy matching of query against choices."""
    if not choices:
        agent_logger.warning(f"[FUZZY] No choices provided for query: {query}")
        return None, 0.0
    result = process.extractOne(query, choices)
    if result is None:
        agent_logger.warning(f"[FUZZY] No fuzzy match found for query: {query}")
        return None, 0.0
    match, score = result[0], result[1] / 100.0
    agent_logger.debug(f"[FUZZY] Fuzzy match: query={query}, match={match}, score={score}")
    return match, score