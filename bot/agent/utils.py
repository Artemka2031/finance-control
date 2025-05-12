from fuzzywuzzy import process
from .config import OPENAI_API_KEY, BACKEND_URL
from ..utils.logging import configure_logger

logger = configure_logger("[AGENT_UTILS]", "cyan")

def fuzzy_match(text: str, choices: list, threshold: int = 80) -> tuple[str, int]:
    """Perform fuzzy matching on text against choices."""
    if not text or not choices:
        return None, 0
    match, score = process.extractOne(text, choices)
    return match, score if score >= threshold else 0