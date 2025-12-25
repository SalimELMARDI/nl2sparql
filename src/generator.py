"""LLM-driven SPARQL generation constrained by retrieved schema.

The prompt strictly limits the model to retrieved entities, properties, and
classes, which reduces hallucinations and keeps queries executable.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set

from groq import Groq

from src.config import Config
from src.schema_store import uri_to_prefixed


DEFAULT_PREFIXES = """PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX dbp: <http://dbpedia.org/property/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

FALLBACK_QUERY = f"{DEFAULT_PREFIXES}ASK {{ FILTER(false) }}\n"

_PREFIXED_TOKEN_RE = re.compile(r"\b(?:dbo|dbp|dbr|rdf|rdfs|foaf|xsd):[A-Za-z_][\w-]*\b")
_URI_RE = re.compile(r"<([^>]+)>")


class SparqlGenerator:
    """Generates SPARQL queries using Groq with strict schema constraints."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = Groq(api_key=config.groq_api_key)

    def _build_system_prompt(self) -> str:
        return (
            "You are a DBpedia SPARQL generator.\n"
            "Rules you must follow:\n"
            "- Use ONLY properties listed under Allowed Properties.\n"
            "- Use ONLY entities listed under Allowed Entities.\n"
            "- Use ONLY classes listed under Allowed Classes.\n"
            "- Use rdf:type only with Allowed Classes.\n"
            "- Do NOT invent properties, entities, or classes.\n"
            "- If the request cannot be answered with the allowed items, output a query that returns no results using FILTER(false).\n"
            "- Output only valid SPARQL with PREFIX declarations. No markdown or explanations.\n"
            f"- For SELECT queries, include LIMIT {self.config.default_select_limit} unless the user asks for all results.\n"
            "- Use the following prefixes when relevant:\n"
            f"{DEFAULT_PREFIXES}"
        )

    def _build_user_prompt(
        self,
        question: str,
        entities: List[Dict[str, str]],
        properties: List[Dict[str, str]],
        classes: List[Dict[str, str]],
    ) -> str:
        entity_lines = []
        for ent in entities:
            uri = ent.get("uri", "")
            prefixed = uri_to_prefixed(uri) if uri else ""
            surface = ent.get("surface_form", "")
            types = ent.get("types", "")
            type_hint = f" | types='{types}'" if types else ""
            entity_lines.append(f"- {prefixed} | {uri} | surface='{surface}'{type_hint}")

        property_lines = []
        for prop in properties:
            prefixed = prop.get("prefixed", uri_to_prefixed(prop.get("uri", "")))
            label = prop.get("label", "")
            uri = prop.get("uri", "")
            description = prop.get("description", "")
            desc_hint = f" | desc='{description}'" if description else ""
            property_lines.append(f"- {prefixed} | {uri} | label='{label}'{desc_hint}")

        class_lines = []
        for cls in classes:
            prefixed = cls.get("prefixed", uri_to_prefixed(cls.get("uri", "")))
            label = cls.get("label", "")
            uri = cls.get("uri", "")
            description = cls.get("description", "")
            desc_hint = f" | desc='{description}'" if description else ""
            class_lines.append(f"- {prefixed} | {uri} | label='{label}'{desc_hint}")

        entities_block = "\n".join(entity_lines) if entity_lines else "- (none)"
        properties_block = "\n".join(property_lines) if property_lines else "- (none)"
        classes_block = "\n".join(class_lines) if class_lines else "- (none)"

        return (
            f"Question: {question}\n\n"
            "Allowed Entities:\n"
            f"{entities_block}\n\n"
            "Allowed Classes:\n"
            f"{classes_block}\n\n"
            "Allowed Properties:\n"
            f"{properties_block}\n"
        )

    def _extract_query(self, text: str) -> str:
        """Best-effort extraction in case the model adds extra text."""
        stripped = text.strip()
        tokens = ["PREFIX", "SELECT", "ASK", "CONSTRUCT", "DESCRIBE"]
        for token in tokens:
            idx = stripped.find(token)
            if idx != -1:
                return stripped[idx:]
        return stripped

    def _ensure_prefixes(self, query: str) -> str:
        lines = query.strip().splitlines()
        existing: Set[str] = set()
        for line in lines:
            if line.lstrip().upper().startswith("PREFIX"):
                parts = line.split()
                if len(parts) >= 2:
                    existing.add(parts[1].strip())
        missing = []
        for prefix_line in DEFAULT_PREFIXES.strip().splitlines():
            parts = prefix_line.split()
            if len(parts) >= 2 and parts[1].strip() not in existing:
                missing.append(prefix_line)
        if missing:
            return "\n".join(missing + lines).strip() + "\n"
        return query.strip() + "\n"

    def _ensure_select_limit(self, query: str) -> str:
        if re.search(r"\bSELECT\b", query, re.IGNORECASE) and not re.search(
            r"\bLIMIT\b", query, re.IGNORECASE
        ):
            return f"{query.rstrip()}\nLIMIT {self.config.default_select_limit}\n"
        return query

    def _extract_identifiers(self, query: str) -> Set[str]:
        body = "\n".join(
            line for line in query.splitlines() if not line.lstrip().upper().startswith("PREFIX")
        )
        identifiers = set(_URI_RE.findall(body))
        identifiers.update(_PREFIXED_TOKEN_RE.findall(body))
        return identifiers

    def _allowed_identifiers(
        self,
        entities: List[Dict[str, str]],
        properties: List[Dict[str, str]],
        classes: List[Dict[str, str]],
    ) -> Set[str]:
        allowed: Set[str] = set()
        for ent in entities:
            uri = ent.get("uri", "")
            if uri:
                allowed.add(uri)
                allowed.add(uri_to_prefixed(uri))
        for prop in properties:
            uri = prop.get("uri", "")
            if uri:
                allowed.add(uri)
                allowed.add(prop.get("prefixed", uri_to_prefixed(uri)))
        for cls in classes:
            uri = cls.get("uri", "")
            if uri:
                allowed.add(uri)
                allowed.add(cls.get("prefixed", uri_to_prefixed(uri)))
        allowed.update(
            {
                "rdf:type",
                "rdfs:label",
                "dbo:abstract",
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                "http://www.w3.org/2000/01/rdf-schema#label",
                "http://dbpedia.org/ontology/abstract",
            }
        )
        return allowed

    def _is_valid_query(
        self,
        query: str,
        entities: List[Dict[str, str]],
        properties: List[Dict[str, str]],
        classes: List[Dict[str, str]],
    ) -> bool:
        if not re.search(r"\b(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", query, re.IGNORECASE):
            return False
        identifiers = self._extract_identifiers(query)
        allowed = self._allowed_identifiers(entities, properties, classes)
        for ident in identifiers:
            if ident in allowed:
                continue
            if ident.startswith("xsd:") or ident.startswith("http://www.w3.org/2001/XMLSchema#"):
                continue
            return False
        return True

    def generate(
        self,
        question: str,
        entities: List[Dict[str, str]],
        properties: List[Dict[str, str]],
        classes: List[Dict[str, str]],
    ) -> str:
        """Generate a SPARQL query grounded in the retrieved entities and schema.

        If the context is empty, we return a safe query that yields no results
        instead of letting the model improvise.
        """
        if not entities and not properties and not classes:
            return FALLBACK_QUERY

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(question, entities, properties, classes)

        try:
            response = self.client.chat.completions.create(
                model=self.config.groq_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=600,
            )
        except Exception:
            return FALLBACK_QUERY

        content = response.choices[0].message.content or ""
        query = self._extract_query(content)
        query = self._ensure_prefixes(query)
        query = self._ensure_select_limit(query)
        if not self._is_valid_query(query, entities, properties, classes):
            return FALLBACK_QUERY
        return query.strip()
