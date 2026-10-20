"""Command registry and catalog behind ``career-ops-help``.

Every command module owns its contract: the argparse parser supplies the usage,
arguments and options, while the module constants ``SUMMARY``, ``EXAMPLES``,
``EXIT_CODES`` and ``OUTPUT_SCHEMA`` supply the rest.  ``REGISTRY`` is the one
list of command modules; the human help and the JSON catalog are both rendered
from it, so neither can drift from the CLI on its own.
"""

from __future__ import annotations

import argparse
import importlib
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Protocol, Sequence, cast

CATALOG_SCHEMA_VERSION = 1
HELP_COMMAND = "career-ops-help"

REGISTRY: tuple[str, ...] = (
    "career_ops.cli",
    "career_ops.reply_cli",
    "career_ops.report_cli",
    "career_ops.help_cli",
)

ISOLATION: dict[str, object] = {
    "parallel": True,
    "summary": (
        "JobGremlin runs in parallel and in isolation. It never changes Hermes, "
        "the cron job, the allowlist, ~/.local/bin or the current career-ops "
        "checkout."
    ),
    "does_not_change": [
        "Hermes",
        "cron",
        "allowlist",
        "~/.local/bin",
        "current career-ops checkout",
    ],
    "writes": ["config/", "data/", "output/"],
}

_ACTION_NAMES = {
    "_AppendAction": "append",
    "_HelpAction": "help",
    "_StoreAction": "store",
    "_StoreTrueAction": "store_true",
}


class CommandModule(Protocol):
    """The metadata a module must expose to join the registry."""

    COMMAND: str
    SUMMARY: str
    EXAMPLES: tuple[str, ...]
    EXIT_CODES: tuple[tuple[int, str], ...]
    OUTPUT_SCHEMA: Mapping[str, object]

    def build_parser(self) -> argparse.ArgumentParser: ...


@dataclass(frozen=True)
class Parameter:
    """One positional argument or option, derived from an argparse action."""

    name: str
    names: tuple[str, ...]
    dest: str
    required: bool
    type: str
    action: str
    default: object
    choices: tuple[str, ...] | None
    metavar: str | None
    help: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "names": list(self.names),
            "dest": self.dest,
            "required": self.required,
            "type": self.type,
            "action": self.action,
            "default": self.default,
            "choices": list(self.choices) if self.choices is not None else None,
            "metavar": self.metavar,
            "help": self.help,
        }


@dataclass(frozen=True)
class CommandInfo:
    """The complete documented contract of one registered command."""

    name: str
    summary: str
    description: str
    usage: str
    arguments: tuple[Parameter, ...]
    options: tuple[Parameter, ...]
    examples: tuple[str, ...]
    exit_codes: tuple[tuple[int, str], ...]
    output: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "summary": self.summary,
            "description": self.description,
            "usage": self.usage,
            "arguments": [argument.as_dict() for argument in self.arguments],
            "options": [option.as_dict() for option in self.options],
            "examples": list(self.examples),
            "exit_codes": [
                {"code": code, "meaning": _one_line(meaning)}
                for code, meaning in self.exit_codes
            ],
            "output": dict(self.output),
        }


@lru_cache(maxsize=None)
def registered_commands() -> tuple[CommandInfo, ...]:
    """Return every command in ``REGISTRY``, ordered as registered."""
    return tuple(_command_info(module_name) for module_name in REGISTRY)


def build_catalog() -> dict[str, object]:
    """Build the machine-readable catalog printed by ``--json``."""
    return {
        "command": HELP_COMMAND,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "isolation": dict(ISOLATION),
        "commands": [command.as_dict() for command in registered_commands()],
    }


def render_text() -> str:
    """Render the human overview of the registered commands."""
    width = max(len(command.name) for command in registered_commands())
    lines = [
        f"{HELP_COMMAND} — discover the JobGremlin CLI",
        "",
        *textwrap.wrap(str(ISOLATION["summary"]), width=88),
        "",
        "Commands:",
    ]
    lines.extend(
        f"  {command.name:<{width}}  {command.summary}"
        for command in registered_commands()
    )
    lines.extend(
        [
            "",
            "Run `<command> --help` for one command's usage and examples.",
            "Run `career-ops-help --json` for the machine-readable catalog:",
            "arguments, options, examples, exit codes and output schema.",
        ]
    )
    return "\n".join(lines) + "\n"


def format_examples(examples: Sequence[str]) -> str:
    """Format examples for an argparse epilog."""
    return "".join(f"  {example}\n" for example in examples)


def build_epilog(
    body: str,
    exit_codes: Sequence[tuple[int, str]],
    examples: Sequence[str],
    *,
    footer: str = "",
) -> str:
    """Build the shared help epilog sections in one place."""
    parts = [
        body.rstrip("\n"),
        "",
        "Exit codes:",
        format_exit_codes(exit_codes).rstrip("\n"),
        "",
        "Examples:",
        format_examples(examples).rstrip("\n"),
    ]
    if footer:
        parts.extend(["", footer.rstrip("\n")])
    return "\n".join(parts) + "\n"


def format_exit_codes(exit_codes: Sequence[tuple[int, str]]) -> str:
    """Format exit codes for an argparse epilog, preserving wrapped meanings."""
    lines = []
    for code, meaning in exit_codes:
        wrapped = meaning.replace("\n", "\n     ")
        lines.append(f"  {code}  {wrapped}\n")
    return "".join(lines)


def _command_info(module_name: str) -> CommandInfo:
    module = cast(CommandModule, importlib.import_module(module_name))
    parser = module.build_parser()
    arguments, options = _parameters(parser)
    return CommandInfo(
        name=module.COMMAND,
        summary=module.SUMMARY,
        description=parser.description or "",
        usage=parser.format_usage().strip(),
        arguments=arguments,
        options=options,
        examples=module.EXAMPLES,
        exit_codes=module.EXIT_CODES,
        output=module.OUTPUT_SCHEMA,
    )


def _parameters(
    parser: argparse.ArgumentParser,
) -> tuple[tuple[Parameter, ...], tuple[Parameter, ...]]:
    arguments: list[Parameter] = []
    options: list[Parameter] = []
    for action in parser._actions:
        parameter = _parameter(action)
        if action.option_strings:
            options.append(parameter)
        else:
            arguments.append(parameter)
    return tuple(arguments), tuple(options)


def _parameter(action: argparse.Action) -> Parameter:
    is_option = bool(action.option_strings)
    names = tuple(action.option_strings) if is_option else (action.dest,)
    canonical = next((name for name in names if name.startswith("--")), names[0])
    return Parameter(
        name=canonical,
        names=names,
        dest=action.dest,
        required=bool(action.required) if is_option else action.nargs not in ("?", "*"),
        type=_type_name(action),
        action=_ACTION_NAMES.get(type(action).__name__, "store"),
        default=_default(action),
        choices=tuple(str(choice) for choice in action.choices) if action.choices else None,
        metavar=str(action.metavar) if action.metavar is not None else None,
        help=str(action.help) if action.help is not None else None,
    )


def _type_name(action: argparse.Action) -> str:
    if action.nargs == 0:
        return "boolean"
    if action.type is int:
        return "integer"
    if action.type is float:
        return "number"
    if action.type is str:
        return "string"
    if action.type is None:
        return "string"
    return getattr(action.type, "__name__", None) or "string"


def _default(action: argparse.Action) -> object:
    value = action.default
    if value is argparse.SUPPRESS:
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "HELP_COMMAND",
    "ISOLATION",
    "REGISTRY",
    "CommandInfo",
    "Parameter",
    "build_catalog",
    "build_epilog",
    "format_examples",
    "format_exit_codes",
    "registered_commands",
    "render_text",
]
