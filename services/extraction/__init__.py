"""
Extraction Module

Provides content extraction from various file types using pluggable strategies.
"""

from searchium.services.extraction.basic_strategy import BasicExtractionStrategy
from searchium.services.extraction.extractor import ContentExtractor, get_extractor
from searchium.services.extraction.protocol import ExtractionStrategy
from searchium.services.extraction.tika_strategy import TikaExtractionStrategy

__all__ = [
    "ExtractionStrategy",
    "TikaExtractionStrategy",
    "BasicExtractionStrategy",
    "ContentExtractor",
    "get_extractor",
]
