"""Entity linking via DBpedia Spotlight.

DBpedia Spotlight performs named-entity recognition and disambiguation
against DBpedia, turning surface forms into canonical URIs.
"""
from __future__ import annotations

from typing import Dict, List

import requests

from src.config import Config


def link_entities(question: str, config: Config) -> List[Dict[str, str]]:
    """Link surface forms in the question to DBpedia entities.

    The output is a compact list of entity URIs that can be used as grounded
    anchors for SPARQL generation.
    """
    params = {
        "text": question,
        "confidence": str(config.spotlight_confidence),
        "support": str(config.spotlight_support),
    }
    headers = {"Accept": "application/json", "User-Agent": "nl2sparql/1.0"}

    try:
        response = requests.get(
            config.spotlight_endpoint,
            params=params,
            headers=headers,
            timeout=config.request_timeout_sec,
        )
        response.raise_for_status()
    except requests.RequestException:
        # Fail softly; the downstream stages can still attempt to answer.
        return []

    data = response.json()
    resources = data.get("Resources", [])
    if not resources:
        return []

    entities: List[Dict[str, str]] = []
    seen = set()
    for res in resources:
        uri = res.get("@URI")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        try:
            similarity = float(res.get("@similarityScore", "0") or 0)
        except (TypeError, ValueError):
            similarity = 0.0
        try:
            support = int(res.get("@support", "0") or 0)
        except (TypeError, ValueError):
            support = 0
        if similarity < config.spotlight_confidence or support < config.spotlight_support:
            continue
        entities.append(
            {
                "surface_form": res.get("@surfaceForm", ""),
                "uri": uri,
                "types": res.get("@types", ""),
                "similarity_score": similarity,
                "support": support,
            }
        )

    entities.sort(
        key=lambda ent: (ent.get("similarity_score", 0), ent.get("support", 0)), reverse=True
    )
    return entities[: config.max_entities]
