"""Centralized configuration with environment loading."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Runtime settings for the NL2SPARQL pipeline."""

    groq_api_key: str
    groq_model: str
    embedding_model: str
    spotlight_endpoint: str
    spotlight_confidence: float
    spotlight_support: int
    dbpedia_sparql_endpoint: str
    schema_top_k: int
    schema_entity_property_limit: int
    schema_min_similarity: float
    request_timeout_sec: int
    max_entities: int
    default_select_limit: int


def load_config() -> Config:
    """Load environment variables and build a Config object.

    The dotenv file is optional; in production, env vars can be injected
    by the shell or container runtime.
    """
    load_dotenv()

    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY is required. Set it in .env or the environment.")

    return Config(
        groq_api_key=groq_api_key,
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        spotlight_endpoint=os.getenv(
            "SPOTLIGHT_ENDPOINT", "https://api.dbpedia-spotlight.org/en/annotate"
        ),
        spotlight_confidence=float(os.getenv("SPOTLIGHT_CONFIDENCE", "0.35")),
        spotlight_support=int(os.getenv("SPOTLIGHT_SUPPORT", "20")),
        dbpedia_sparql_endpoint=os.getenv(
            "DBPEDIA_SPARQL_ENDPOINT", "https://dbpedia.org/sparql"
        ),
        schema_top_k=int(os.getenv("SCHEMA_TOP_K", "6")),
        schema_entity_property_limit=int(os.getenv("SCHEMA_ENTITY_PROPERTY_LIMIT", "120")),
        schema_min_similarity=float(os.getenv("SCHEMA_MIN_SIMILARITY", "0.2")),
        request_timeout_sec=int(os.getenv("REQUEST_TIMEOUT_SEC", "15")),
        max_entities=int(os.getenv("MAX_ENTITIES", "4")),
        default_select_limit=int(os.getenv("DEFAULT_SELECT_LIMIT", "50")),
    )
