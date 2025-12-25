"""SPARQL query execution against the DBpedia endpoint."""
from __future__ import annotations

from typing import Any, Dict

from SPARQLWrapper import JSON, SPARQLWrapper

from src.config import Config


def execute_query(query: str, config: Config) -> Dict[str, Any]:
    """Execute a SPARQL query and return the parsed JSON results."""
    sparql = SPARQLWrapper(config.dbpedia_sparql_endpoint)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    sparql.setTimeout(config.request_timeout_sec)
    try:
        return sparql.query().convert()
    except Exception as exc:
        raise RuntimeError(f"SPARQL query failed: {exc}") from exc
