"""Command-line entry point for the NL2SPARQL pipeline.

The loop wires together entity linking, schema retrieval, LLM generation,
and SPARQL execution to provide an end-to-end RAG workflow.
"""
from __future__ import annotations

import os
import sys
import argparse
from typing import Any, Dict, List
from urllib.parse import urlparse

from src.config import load_config
from src.executor import execute_query
from src.generator import SparqlGenerator
from src.linker import link_entities
from src.schema_store import SchemaStore

LOGO_TEXT = "NL2SPARQL"
LOGO_HEIGHT = 5
LETTER_ART = {
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#####"],
    "2": ["#####", "    #", "#####", "#    ", "#####"],
    "S": ["#####", "#    ", "#####", "    #", "#####"],
    "P": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "R": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "Q": [" ### ", "#   #", "#   #", "#  ##", " ####"],
    " ": ["     ", "     ", "     ", "     ", "     "],
}

USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
SHOW_BANNER = os.getenv("NL2SPARQL_NO_BANNER") is None
ACCENT = "36"
DIM = "90"


def style(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def accent(text: str) -> str:
    return style(text, f"1;{ACCENT}")


def dim(text: str) -> str:
    return style(text, DIM)


def gradient(text: str, codes: List[str]) -> str:
    if not USE_COLOR:
        return text
    rendered: List[str] = []
    idx = 0
    for ch in text:
        if ch == " ":
            rendered.append(ch)
            continue
        code = codes[idx % len(codes)]
        rendered.append(f"\033[{code}m{ch}\033[0m")
        idx += 1
    return "".join(rendered)


def render_logo(text: str) -> List[str]:
    rows = [""] * LOGO_HEIGHT
    for ch in text:
        art = LETTER_ART.get(ch.upper(), LETTER_ART[" "])
        for idx in range(LOGO_HEIGHT):
            rows[idx] += art[idx] + "  "
    return [row.rstrip() for row in rows]


def render_banner(config: Any) -> None:
    logo_lines = render_logo(LOGO_TEXT)
    gradient_codes = ["34", "35", "36", "94", "95", "96"]
    host = urlparse(config.dbpedia_sparql_endpoint).netloc or config.dbpedia_sparql_endpoint
    tips = [
        "Ask in natural language; mention entities by name.",
        "Add constraints (time, place, type) for precision.",
        "Type 'exit' or 'quit' to stop.",
    ]
    subtitle = "DBpedia SPARQL console online"
    status = (
        f"Model: {config.groq_model} | Endpoint: {host} | Timeout: {config.request_timeout_sec}s"
    )
    width = max(
        max(len(line) for line in logo_lines),
        len(subtitle),
        len(status),
        len("Tips for getting started:"),
    )
    rule = dim("-" * width)

    print(rule)
    for line in logo_lines:
        print(gradient(line, gradient_codes))
    print(accent(subtitle))
    print()
    print(style("Tips for getting started:", "1"))
    for idx, tip in enumerate(tips, start=1):
        print(f"  {idx}. {tip}")
    print()
    print(dim(status))
    print(rule)


def print_stage(title: str) -> None:
    print(f"\n{accent(f'// {title}')}")


def format_entities(entities: List[Dict[str, str]]) -> str:
    if not entities:
        return "(none)"
    lines = []
    for ent in entities:
        types = ent.get("types", "")
        type_hint = f" | types={types}" if types else ""
        score = ent.get("similarity_score")
        support = ent.get("support")
        score_hint = ""
        if score is not None or support is not None:
            score_value = f"{float(score):.2f}" if score is not None else "n/a"
            support_value = f"{support}" if support is not None else "n/a"
            score_hint = f" | score={score_value} | support={support_value}"
        lines.append(
            f"- {ent.get('surface_form', '')} -> {ent.get('uri', '')}{type_hint}{score_hint}"
        )
    return "\n".join(lines)


def format_properties(properties: List[Dict[str, str]]) -> str:
    if not properties:
        return "(none)"
    lines = []
    for prop in properties:
        lines.append(
            f"- {prop.get('label', '')} -> {prop.get('prefixed', prop.get('uri', ''))}"
        )
    return "\n".join(lines)


def format_classes(classes: List[Dict[str, str]]) -> str:
    if not classes:
        return "(none)"
    lines = []
    for cls in classes:
        lines.append(f"- {cls.get('label', '')} -> {cls.get('prefixed', cls.get('uri', ''))}")
    return "\n".join(lines)


def print_results(data: Dict[str, Any], max_rows: int = 10) -> None:
    if "boolean" in data:
        print(f"ASK result: {data.get('boolean')}")
        return

    head = data.get("head", {})
    vars_ = head.get("vars", [])
    bindings = data.get("results", {}).get("bindings", [])

    if not vars_:
        print("No variables returned.")
        return

    print(f"Columns: {', '.join(vars_)}")
    if not bindings:
        print("No results.")
        return

    for idx, row in enumerate(bindings[:max_rows], start=1):
        rendered = []
        for var in vars_:
            value = row.get(var, {}).get("value", "")
            rendered.append(f"{var}={value}")
        print(f"  {idx:>2}. " + " | ".join(rendered))

    if len(bindings) > max_rows:
        print(f"... ({len(bindings) - max_rows} more rows)")


def process_question(
    question: str,
    config: Any,
    schema_store: SchemaStore,
    generator: SparqlGenerator,
    verbose: bool = False,
) -> None:
    entities = link_entities(question, config)
    classes = schema_store.retrieve_classes(question)
    properties = schema_store.retrieve(question, entities)
    query = generator.generate(question, entities, properties, classes)

    if verbose:
        print("\nLinked entities:")
        print(format_entities(entities))
        print("\nRetrieved classes:")
        print(format_classes(classes))
        print("\nRetrieved properties:")
        print(format_properties(properties))

    print("\nGenerated SPARQL:")
    print(query)

    try:
        results = execute_query(query, config)
        print("\nResults:")
        print_results(results)
    except Exception as exc:
        print(f"Execution error: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="NL2SPARQL for DBpedia")
    parser.add_argument("--question", "-q", help="Run a single query and exit")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show linking and schema retrieval details",
    )
    args = parser.parse_args()

    config = load_config()
    schema_store = SchemaStore(config)
    generator = SparqlGenerator(config)

    verbose = args.verbose or os.getenv("NL2SPARQL_VERBOSE") == "1"

    if args.question is not None:
        question = args.question.strip()
        if question:
            process_question(question, config, schema_store, generator, verbose=verbose)
        return

    if SHOW_BANNER:
        render_banner(config)
    while True:
        try:
            prompt = accent(">>") + " "
            question = input(f"\n{prompt}").strip()
        except EOFError:
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break

        process_question(question, config, schema_store, generator, verbose=verbose)


if __name__ == "__main__":
    main()
