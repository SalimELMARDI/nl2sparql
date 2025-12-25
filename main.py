from __future__ import annotations

import argparse
import os
from typing import Dict, List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from src.config import Config, load_config
from src.executor import execute_query
from src.generator import SparqlGenerator
from src.linker import link_entities
from src.schema_store import SchemaStore

BANNER = r"""
 _   _ _     ____  ____   ____  ____   ___   ____  _     
| \ | | |   / ___||  _ \ / ___||  _ \ / _ \ / ___|| |    
|  \| | |   \___ \| |_) | |  _ | |_) | | | | |  _ | |    
| |\  | |___ ___) |  __/| |_| ||  _ <| |_| | |_| || |___ 
|_| \_|_____|____/|_|    \____||_| \_\\___/ \____||_____|
"""


def render_banner(console: Console) -> None:
    logo = Text(BANNER.strip("\n"), style="bold cyan")
    panel = Panel.fit(logo, border_style="blue", title="NL2SPARQL")
    console.print(panel)


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


def build_results_table(results: Dict[str, Any]) -> Table:
    if "boolean" in results:
        table = Table(title="Results", box=box.SIMPLE_HEAVY)
        table.add_column("ASK")
        table.add_row("true" if results.get("boolean") else "false")
        return table

    head = results.get("head", {})
    vars_ = head.get("vars", [])
    bindings = results.get("results", {}).get("bindings", [])
    table = Table(title="Results", box=box.SIMPLE_HEAVY, show_lines=False)
    if not vars_:
        table.add_column("Message")
        table.add_row("No results.")
        return table

    for var in vars_:
        table.add_column(var, overflow="fold")

    if not bindings:
        table.add_row(*(["No results."] * len(vars_)))
        return table

    for row in bindings:
        table.add_row(*[_stringify_binding(row.get(var, {})) for var in vars_])
    return table


def run_pipeline(
    question: str,
    console: Console,
    config: Config,
    schema_store: SchemaStore,
    generator: SparqlGenerator,
) -> None:
    execution_error: Optional[str] = None
    results: Optional[Dict[str, Any]] = None

    with console.status("[bold green]Thinking...", spinner="dots") as status:
        status: Status
        status.update("Step 1/4: Scanning user question for entities...")
        entities = link_entities(question, config)

        status.update(
            f"Step 2/4: Mapping schema constraints (found {len(entities)} entities)..."
        )
        classes = schema_store.retrieve_classes(question)
        properties = schema_store.retrieve(question, entities=entities)

        status.update("Step 3/4: Drafting SPARQL query...")
        query = generator.generate(question, entities, properties, classes)

        status.update("Step 4/4: Executing query...")
        try:
            results = execute_query(query, config)
        except Exception as exc:
            execution_error = str(exc)

    console.print()
    console.print("[bold]SPARQL Query[/bold]")
    console.print(Syntax(query, "sparql", theme="monokai", line_numbers=True))

    if execution_error:
        console.print(
            Panel(
                execution_error,
                border_style="red",
                title="Execution Error",
            )
        )
        return

    if results is None:
        console.print(Panel("No results returned.", border_style="red", title="Error"))
        return

    console.print(build_results_table(results))


def main() -> None:
    console = Console()
    parser = argparse.ArgumentParser(description="NL2SPARQL CLI")
    parser.add_argument("-q", "--question", help="Run a single question and exit.")
    args = parser.parse_args()

    try:
        config = load_config()
    except ValueError as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        raise SystemExit(1)

    schema_store = SchemaStore(config)
    generator = SparqlGenerator(config)

    banner_enabled = not os.getenv("NL2SPARQL_NO_BANNER")
    if args.question:
        if banner_enabled:
            render_banner(console)
        question = args.question.strip()
        if question:
            run_pipeline(question, console, config, schema_store, generator)
        return

    if banner_enabled:
        render_banner(console)
    console.print("[dim]Ask a question about DBpedia (type 'exit' to quit).[/dim]")

    while True:
        try:
            question = console.input("[bold cyan]>> [/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            console.print("[dim]Goodbye.[/dim]")
            break

        run_pipeline(question, console, config, schema_store, generator)


if __name__ == "__main__":
    main()
