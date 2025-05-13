from typing import Tuple, Optional
from thefuzz import process
from loguru import logger


def fuzzy_match(query: str, choices: list) -> Tuple[Optional[str], float]:
    """Perform fuzzy matching of query against choices."""
    if not choices:
        logger.warning(f"[FUZZY] No choices provided for query: {query}")
        return None, 0.0
    result = process.extractOne(query, choices)
    if result is None:
        logger.warning(f"[FUZZY] No fuzzy match found for query: {query}")
        return None, 0.0
    match, score = result[0], result[1] / 100.0
    logger.debug(f"[FUZZY] Fuzzy match: query={query}, match={match}, score={score}")
    return match, score
