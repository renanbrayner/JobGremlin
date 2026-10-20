from __future__ import annotations

import importlib
import json
import re
from typing import Mapping

from career_ops.catalog import registered_commands
from conftest import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "help-catalog.schema.json"


def _validate(instance: object, schema: Mapping[str, object], root: Mapping[str, object], path: str = "$") -> None:
    """Validate the JSON-Schema subset used by the help catalog schema."""
    if "$ref" in schema:
        reference = str(schema["$ref"])
        assert reference.startswith("#/$defs/"), reference
        definitions = root["$defs"]
        assert isinstance(definitions, Mapping)
        schema = definitions[reference.removeprefix("#/$defs/")]
        assert isinstance(schema, Mapping)

    if "const" in schema:
        assert instance == schema["const"], f"{path}: expected {schema['const']!r}"
    if "enum" in schema:
        members = schema["enum"]
        assert isinstance(members, list)
        assert instance in members, f"{path}: {instance!r} not in {members!r}"

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        checks = {
            "object": lambda value: isinstance(value, Mapping),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "null": lambda value: value is None,
        }
        assert any(checks[str(item)](instance) for item in types), (
            f"{path}: {type(instance).__name__} is not {types!r}"
        )

    if isinstance(instance, Mapping):
        properties = schema.get("properties", {})
        assert isinstance(properties, Mapping)
        required = schema.get("required", [])
        assert isinstance(required, list)
        for name in required:
            assert name in instance, f"{path}: missing required property {name!r}"
        additional = schema.get("additionalProperties", True)
        for name, value in instance.items():
            if name in properties:
                child = properties[name]
                assert isinstance(child, Mapping)
                _validate(value, child, root, f"{path}.{name}")
            else:
                assert additional is not False, f"{path}: unexpected property {name!r}"

    if isinstance(instance, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int):
            assert len(instance) >= min_items, f"{path}: too few items"
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(instance):
                _validate(item, items, root, f"{path}[{index}]")

    if isinstance(instance, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int):
            assert len(instance) >= min_length, f"{path}: too short"
        pattern = schema.get("pattern")
        if pattern is not None:
            assert re.search(str(pattern), instance), f"{path}: {instance!r} !~ {pattern}"


def _catalog(run) -> dict:
    result = run("career-ops-help", "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_help_shows_every_command_and_states_the_parallel_isolation(run):
    result = run("career-ops-help")

    assert result.returncode == 0, result.stderr
    text = result.stdout
    for command in registered_commands():
        assert command.name in text
        assert command.summary in text
    assert "parallel" in text.lower()
    for untouched in ("Hermes", "cron", "allowlist", "~/.local/bin", "career-ops checkout"):
        assert untouched in text
    assert "career-ops-help --json" in text


def test_the_json_catalog_is_valid_against_its_schema(run):
    catalog = _catalog(run)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    _validate(catalog, schema, schema)

    assert catalog["command"] == "career-ops-help"
    assert catalog["schema_version"] == 1
    assert catalog["isolation"]["parallel"] is True


def test_the_catalog_is_generated_from_the_command_registry(run):
    catalog = _catalog(run)
    registered = registered_commands()

    assert [command["name"] for command in catalog["commands"]] == [
        command.name for command in registered
    ]

    package = REPO_ROOT / "src" / "career_ops"
    command_names = set()
    for path in sorted(package.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(f"career_ops.{path.stem}")
        if hasattr(module, "COMMAND"):
            command_names.add(module.COMMAND)
    assert {command["name"] for command in catalog["commands"]} == command_names


def test_every_catalog_entry_documents_the_full_command_contract(run):
    catalog = _catalog(run)
    commands = {command["name"]: command for command in catalog["commands"]}

    for command in commands.values():
        assert command["summary"]
        assert command["description"]
        assert command["usage"].startswith("usage:")
        assert isinstance(command["arguments"], list)
        assert command["options"]
        assert command["examples"]
        assert command["exit_codes"]
        assert all(isinstance(item["code"], int) for item in command["exit_codes"])
        assert all(item["meaning"] for item in command["exit_codes"])
        output = command["output"]
        assert output["format"]
        assert output["schema"]["type"] == "object"
        assert output["schema"]["properties"]
        assert output["schema"]["required"]

    run_options = {option["name"]: option for option in commands["career-ops-run"]["options"]}
    assert run_options["--job"]["type"] == "string"
    assert run_options["--job"]["required"] is False
    assert run_options["--job"]["help"]
    assert run_options["--target"]["type"] == "integer"
    assert run_options["--target"]["default"] == 1
    assert run_options["--cv"]["metavar"] is None

    help_options = {option["name"]: option for option in commands["career-ops-help"]["options"]}
    assert help_options["--json"]["type"] == "boolean"
    assert help_options["--json"]["action"] == "store_true"

    for command in commands.values():
        options = {option["name"]: option for option in command["options"]}
        assert options["--help"]["action"] == "help"
        assert options["--help"]["type"] == "boolean"


def test_every_registered_command_accepts_help_with_usage_and_examples(run):
    for command in registered_commands():
        result = run(command.name, "--help")

        assert result.returncode == 0, f"{command.name}: {result.stderr}"
        assert "usage:" in result.stdout.lower()
        assert "Examples:" in result.stdout
        assert f"{command.name} --help" in result.stdout


def test_catalog_examples_are_the_ones_shown_by_each_command_help(run):
    for command in _catalog(run)["commands"]:
        help_result = run(command["name"], "--help")

        assert help_result.returncode == 0
        for example in command["examples"]:
            assert example in help_result.stdout
