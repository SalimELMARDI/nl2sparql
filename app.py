from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src import executor, generator, linker, schema_store
from src.config import load_config

IMAGE_URL_RE = re.compile(r"https?://\S+\.(?:png|jpg)(?:[?#]\S+)?$", re.IGNORECASE)
CHAT_IMAGE_WIDTH = 320


def _looks_like_image_url(value: str) -> bool:
    return bool(IMAGE_URL_RE.match(value.strip()))


def _stringify_binding(binding: Dict[str, Any]) -> str:
    value = binding.get("value", "")
    lang = binding.get("xml:lang") or binding.get("lang")
    datatype = binding.get("datatype")
    if lang:
        return f"{value} (@{lang})"
    if datatype:
        short_type = datatype.rsplit("#", 1)[-1]
        return f"{value} ({short_type})"
    return str(value)


def _compact_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "surface": ent.get("surface_form", ""),
            "uri": ent.get("uri", ""),
            "types": ent.get("types", ""),
        }
        for ent in entities
    ]


def _compact_schema(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "label": item.get("label", ""),
            "prefixed": item.get("prefixed", ""),
            "uri": item.get("uri", ""),
        }
        for item in items
    ]


def _parse_results(results: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[str], List[str]]:
    if "boolean" in results:
        value = "true" if results.get("boolean") else "false"
        return [{"ASK": value}], ["ASK"], []

    head = results.get("head", {})
    vars_ = head.get("vars", [])
    bindings = results.get("results", {}).get("bindings", [])
    rows: List[Dict[str, str]] = []
    image_urls: List[str] = []

    for row in bindings:
        row_data: Dict[str, str] = {}
        for var in vars_:
            binding = row.get(var, {})
            value = binding.get("value", "")
            if isinstance(value, str) and _looks_like_image_url(value):
                image_urls.append(value)
            row_data[var] = _stringify_binding(binding)
        rows.append(row_data)

    image_urls = sorted(set(image_urls))
    return rows, vars_, image_urls


@st.cache_resource(show_spinner=False)
def _init_pipeline() -> Tuple[Any, Any, Any]:
    config = load_config()
    store = schema_store.SchemaStore(config)
    gen = generator.SparqlGenerator(config)
    return config, store, gen


def _render_message(message: Dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
            return

        if message.get("content"):
            st.markdown(message["content"])

        if message.get("error"):
            st.error(message["error"])

        if message.get("query"):
            st.code(message["query"], language="sparql")

        results = message.get("results")
        if results is not None:
            rows = results.get("rows", [])
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.info("No results.")

        if message.get("image_urls"):
            st.image(message["image_urls"], width=CHAT_IMAGE_WIDTH)


def _process_question(
    question: str, config: Any, store: Any, gen: Any
) -> Dict[str, Any]:
    errors: List[str] = []
    execution_error: Optional[str] = None
    results: Optional[Dict[str, Any]] = None
    query = ""

    with st.status("Processing...", expanded=False) as status:
        st.write("🔍 Identifying Entities...")
        entities = linker.link_entities(question, config)
        if not entities:
            errors.append("No entities found. Try adding a specific name or place.")

        st.write("📚 Retrieving Schema...")
        classes = store.retrieve_classes(question)
        properties = store.retrieve(question, entities=entities)

        st.write("Entities found")
        if entities:
            st.table(_compact_entities(entities))
        else:
            st.write("None")

        st.write("Schema used: Classes")
        st.table(_compact_schema(classes))
        st.write("Schema used: Properties")
        st.table(_compact_schema(properties))

        st.write("💡 Generating SPARQL...")
        query = gen.generate(question, entities, properties, classes)

        st.write("⚡ Executing query...")
        try:
            results = executor.execute_query(query, config)
            status.update(label="Done", state="complete")
        except Exception as exc:
            execution_error = str(exc)
            status.update(label="Execution failed", state="error")

    message: Dict[str, Any] = {
        "role": "assistant",
        "content": "Here's the generated SPARQL and results.",
        "query": query,
    }

    if execution_error:
        message["content"] = "I generated a SPARQL query, but the endpoint returned an error."
        message["error"] = execution_error
        return message

    if errors:
        message["error"] = " ".join(errors)

    if results is None:
        message["content"] = "I couldn't retrieve any results."
        return message

    rows, columns, image_urls = _parse_results(results)
    message["results"] = {"rows": rows, "columns": columns}
    if image_urls:
        message["image_urls"] = image_urls
    return message


def main() -> None:
    st.set_page_config(page_title="NL2SPARQL", page_icon="NL", layout="wide")

    with st.sidebar:
        st.title("NL2SPARQL")
        st.caption("NL2SPARQL: Query DBpedia using Natural Language.")
        if st.button("Reset Conversation"):
            st.session_state.messages = []
            st.rerun()

    st.title("NL2SPARQL Chat")
    st.caption("Ask questions in natural language and get DBpedia answers.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    try:
        config, store, gen = _init_pipeline()
    except ValueError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()

    for message in st.session_state.messages:
        _render_message(message)

    if prompt := st.chat_input("Ask a question about DBpedia..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        assistant_message = _process_question(prompt, config, store, gen)
        st.session_state.messages.append(assistant_message)
        _render_message(assistant_message)


if __name__ == "__main__":
    main()
