import logging
from typing import Dict, List, Any, Optional, Tuple

from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from thefuzz import process
from typing_extensions import TypedDict

from api_client import CodeName
from config import OPENAI_API_KEY

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
        level="DEBUG",
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan> | <level>{message}</level>"
    )
    return logger

# Initialize logger
agent_logger = setup_logging()

# Data structures
class Request(TypedDict):
    intent: str
    entities: Dict[str, Optional[str] | bool]
    missing: List[str]
    index: int

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
    current_stage: Optional[str] = Field(default=None)  # Текущий этап обработки
    parts: List[str] = Field(default_factory=list)


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