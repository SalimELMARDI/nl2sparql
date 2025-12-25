"""Schema retriever using dense embeddings and lightweight DBpedia lookups.

This module narrows candidate properties/classes to a small, relevant subset
before SPARQL generation to reduce hallucinations and improve accuracy.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from SPARQLWrapper import JSON, SPARQLWrapper
from sentence_transformers import SentenceTransformer

from src.config import Config


def uri_to_prefixed(uri: str) -> str:
    """Convert common DBpedia/RDF URIs to compact prefixed names."""
    prefixes = {
        "http://dbpedia.org/resource/": "dbr:",
        "http://dbpedia.org/ontology/": "dbo:",
        "http://dbpedia.org/property/": "dbp:",
        "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
        "http://xmlns.com/foaf/0.1/": "foaf:",
        "http://www.w3.org/2001/XMLSchema#": "xsd:",
    }
    for base, prefix in prefixes.items():
        if uri.startswith(base):
            return prefix + uri[len(base) :]
    return uri


def _label_from_uri(uri: str) -> str:
    token = uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    return token.replace("_", " ")


COMMON_PROPERTIES: List[Dict[str, str]] = [
    {
        "label": "type",
        "uri": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        "description": "class/type of an entity",
    },
    {
        "label": "abstract",
        "uri": "http://dbpedia.org/ontology/abstract",
        "description": "short textual summary of the entity",
    },
    {
        "label": "population",
        "uri": "http://dbpedia.org/ontology/populationTotal",
        "description": "total population of a place",
    },
    {
        "label": "area",
        "uri": "http://dbpedia.org/ontology/areaTotal",
        "description": "total area of a place",
    },
    {
        "label": "country",
        "uri": "http://dbpedia.org/ontology/country",
        "description": "country an entity belongs to",
    },
    {
        "label": "capital",
        "uri": "http://dbpedia.org/ontology/capital",
        "description": "capital city of a country",
    },
    {
        "label": "birth place",
        "uri": "http://dbpedia.org/ontology/birthPlace",
        "description": "place where a person was born",
    },
    {
        "label": "birth date",
        "uri": "http://dbpedia.org/ontology/birthDate",
        "description": "date of birth",
    },
    {
        "label": "death date",
        "uri": "http://dbpedia.org/ontology/deathDate",
        "description": "date of death",
    },
    {
        "label": "author",
        "uri": "http://dbpedia.org/ontology/author",
        "description": "author of a written work",
    },
    {
        "label": "director",
        "uri": "http://dbpedia.org/ontology/director",
        "description": "director of a film or series",
    },
    {
        "label": "starring",
        "uri": "http://dbpedia.org/ontology/starring",
        "description": "main cast of a film or series",
    },
    {
        "label": "release date",
        "uri": "http://dbpedia.org/ontology/releaseDate",
        "description": "release date of a film, game, or product",
    },
    {
        "label": "genre",
        "uri": "http://dbpedia.org/ontology/genre",
        "description": "genre category of a creative work",
    },
    {
        "label": "official language",
        "uri": "http://dbpedia.org/ontology/officialLanguage",
        "description": "official language of a place",
    },
    {
        "label": "leader name",
        "uri": "http://dbpedia.org/ontology/leaderName",
        "description": "leader or head of government",
    },
    {
        "label": "label",
        "uri": "http://www.w3.org/2000/01/rdf-schema#label",
        "description": "human-readable name",
    },
]


COMMON_CLASSES: List[Dict[str, str]] = [
    {
        "label": "person",
        "uri": "http://dbpedia.org/ontology/Person",
        "description": "human being",
    },
    {
        "label": "place",
        "uri": "http://dbpedia.org/ontology/Place",
        "description": "geographic location",
    },
    {
        "label": "city",
        "uri": "http://dbpedia.org/ontology/City",
        "description": "city or town",
    },
    {
        "label": "country",
        "uri": "http://dbpedia.org/ontology/Country",
        "description": "sovereign country",
    },
    {
        "label": "organization",
        "uri": "http://dbpedia.org/ontology/Organisation",
        "description": "organization or company",
    },
    {
        "label": "company",
        "uri": "http://dbpedia.org/ontology/Company",
        "description": "business entity",
    },
    {
        "label": "film",
        "uri": "http://dbpedia.org/ontology/Film",
        "description": "movie or film",
    },
    {
        "label": "book",
        "uri": "http://dbpedia.org/ontology/Book",
        "description": "book or written work",
    },
    {
        "label": "album",
        "uri": "http://dbpedia.org/ontology/Album",
        "description": "music album",
    },
    {
        "label": "song",
        "uri": "http://dbpedia.org/ontology/Song",
        "description": "song or single",
    },
    {
        "label": "university",
        "uri": "http://dbpedia.org/ontology/University",
        "description": "university or college",
    },
    {
        "label": "river",
        "uri": "http://dbpedia.org/ontology/River",
        "description": "river or waterway",
    },
    {
        "label": "mountain",
        "uri": "http://dbpedia.org/ontology/Mountain",
        "description": "mountain or peak",
    },
]


class SchemaStore:
    """Schema retriever backed by embeddings and light DBpedia lookups."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.model = SentenceTransformer(config.embedding_model)
        self._entity_property_cache: Dict[str, List[Dict[str, object]]] = {}
        self._static_properties = self._prepare_items(COMMON_PROPERTIES)
        self._static_classes = self._prepare_items(COMMON_CLASSES)

    def _prepare_items(self, items: List[Dict[str, str]]) -> List[Dict[str, object]]:
        prepared: List[Dict[str, object]] = []
        texts = []
        for item in items:
            label = item.get("label", "")
            description = item.get("description", "")
            text = " ".join(part for part in [label, description] if part).strip()
            texts.append(text or label or item.get("uri", ""))
        embeddings = self._embed_texts(texts)
        for item, text, emb in zip(items, texts, embeddings):
            prepared.append(
                {
                    "label": item.get("label", ""),
                    "uri": item.get("uri", ""),
                    "description": item.get("description", ""),
                    "prefixed": uri_to_prefixed(item.get("uri", "")),
                    "text": text,
                    "embedding": emb,
                }
            )
        return prepared

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(texts).tolist()
        normalized: List[List[float]] = []
        for emb in embeddings:
            vec = np.array(emb, dtype=float)
            norm = np.linalg.norm(vec)
            if norm == 0:
                normalized.append(vec.tolist())
            else:
                normalized.append((vec / norm).tolist())
        return normalized

    def _fetch_properties_for_entity(self, entity_uri: str) -> List[Dict[str, object]]:
        if entity_uri in self._entity_property_cache:
            return self._entity_property_cache[entity_uri]

        query = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?p ?label ?comment WHERE {\n"
            f"  <{entity_uri}> ?p ?o .\n"
            "  FILTER(\n"
            "    STRSTARTS(STR(?p), \"http://dbpedia.org/ontology/\") ||\n"
            "    STRSTARTS(STR(?p), \"http://dbpedia.org/property/\")\n"
            "  )\n"
            "  OPTIONAL { ?p rdfs:label ?label FILTER(lang(?label) = \"en\") }\n"
            "  OPTIONAL { ?p rdfs:comment ?comment FILTER(lang(?comment) = \"en\") }\n"
            "}\n"
            f"LIMIT {self.config.schema_entity_property_limit}"
        )

        sparql = SPARQLWrapper(self.config.dbpedia_sparql_endpoint)
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        sparql.setTimeout(self.config.request_timeout_sec)

        try:
            results = sparql.query().convert()
        except Exception:
            return []

        bindings = results.get("results", {}).get("bindings", [])
        candidates: List[Dict[str, object]] = []
        for row in bindings:
            uri = row.get("p", {}).get("value", "")
            if not uri:
                continue
            label = row.get("label", {}).get("value", "") or _label_from_uri(uri)
            comment = row.get("comment", {}).get("value", "")
            candidates.append(
                {
                    "label": label,
                    "uri": uri,
                    "description": comment,
                    "prefixed": uri_to_prefixed(uri),
                }
            )

        candidates = self._dedupe_items(candidates)
        texts = []
        for item in candidates:
            text = " ".join(
                part for part in [item.get("label", ""), item.get("description", "")] if part
            ).strip()
            texts.append(text or item.get("label", "") or item.get("uri", ""))
            item["text"] = text
        embeddings = self._embed_texts(texts)
        for item, emb in zip(candidates, embeddings):
            item["embedding"] = emb

        self._entity_property_cache[entity_uri] = candidates
        return candidates

    def _dedupe_items(self, items: List[Dict[str, object]]) -> List[Dict[str, object]]:
        by_uri: Dict[str, Dict[str, object]] = {}
        for item in items:
            uri = item.get("uri", "")
            if not uri:
                continue
            existing = by_uri.get(uri)
            if not existing:
                by_uri[uri] = dict(item)
                continue
            for key in ("label", "description", "prefixed", "text", "embedding"):
                if not existing.get(key) and item.get(key):
                    existing[key] = item.get(key)
        return list(by_uri.values())

    def _rank_items(
        self, question: str, items: List[Dict[str, object]], top_k: int
    ) -> List[Dict[str, str]]:
        if not items:
            return []
        question_embedding = self._embed_texts([question])[0]
        scored: List[Dict[str, object]] = []
        for item in items:
            embedding = item.get("embedding")
            if not embedding:
                text = item.get("text") or item.get("label") or item.get("uri")
                embedding = self._embed_texts([str(text)])[0]
            score = float(np.dot(np.array(question_embedding), np.array(embedding)))
            scored.append({**item, "score": score})

        scored.sort(key=lambda it: it.get("score", 0.0), reverse=True)
        min_sim = self.config.schema_min_similarity
        filtered = [item for item in scored if item.get("score", 0.0) >= min_sim]
        if not filtered:
            filtered = scored

        trimmed: List[Dict[str, str]] = []
        for item in filtered[:top_k]:
            trimmed.append(
                {
                    "label": str(item.get("label", "")),
                    "uri": str(item.get("uri", "")),
                    "description": str(item.get("description", "")),
                    "prefixed": str(item.get("prefixed", uri_to_prefixed(str(item.get("uri", ""))))),
                }
            )
        return trimmed

    def retrieve(
        self,
        question: str,
        entities: Optional[List[Dict[str, str]]] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """Return the top-K properties that best match the question."""
        k = top_k or self.config.schema_top_k
        candidates: List[Dict[str, object]] = list(self._static_properties)
        for ent in entities or []:
            uri = ent.get("uri", "")
            if not uri:
                continue
            candidates.extend(self._fetch_properties_for_entity(uri))
        candidates = self._dedupe_items(candidates)
        return self._rank_items(question, candidates, k)

    def retrieve_classes(self, question: str, top_k: Optional[int] = None) -> List[Dict[str, str]]:
        """Return a small list of likely classes for the question."""
        class_k = top_k or max(3, min(5, self.config.schema_top_k))
        return self._rank_items(question, list(self._static_classes), class_k)
