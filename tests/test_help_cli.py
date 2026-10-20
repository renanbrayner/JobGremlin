from __future__ import annotations

import importlib
import json
import re
from typing import Mapping

from career_ops.catalog import registered_commands
from conftest import (
    FRONTEND_JD,
    REPO_ROOT,
    invoke,
    write_candidates,
    write_cv,
    write_jd_fixtures,
    write_jds,
)

SCHEMA_PATH = REPO_ROOT / "docs" / "schema" / "help-catalog.schema.json"

# The validator below implements exactly these keywords. Anything else fails the
# test instead of being silently ignored, so the checked-in schema cannot start
# relying on validation that this suite does not perform.
SUPPORTED_KEYWORDS = {
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "const",
    "description",
    "enum",
    "items",
    "minItems",
    "minLength",
    "minProperties",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
}


def _check_keywords(schema: Mapping[str, object], path: str) -> None:
    unknown = set(schema) - SUPPORTED_KEYWORDS
    assert not unknown, f"{path}: unsupported schema keywords {sorted(unknown)}"


def _validate(instance: object, schema: Mapping[str, object], root: Mapping[str, object], path: str = "$") -> None:
    """Validate the JSON-Schema subset used by the help catalog schema."""
    _check_keywords(schema, path)
    definitions = schema.get("$defs")
    if isinstance(definitions, Mapping):
        for name, definition in definitions.items():
            assert isinstance(definition, Mapping)
            _check_keywords(definition, f"{path}.$defs.{name}")
    if "$ref" in schema:
        reference = str(schema["$ref"])
        assert reference.startswith("#/$defs/"), reference
        definitions = root["$defs"]
        assert isinstance(definitions, Mapping)
        schema = definitions[reference.removeprefix("#/$defs/")]
        assert isinstance(schema, Mapping)
        _check_keywords(schema, path)

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
        min_properties = schema.get("minProperties")
        if isinstance(min_properties, int):
            assert len(instance) >= min_properties, f"{path}: too few properties"
        additional = schema.get("additionalProperties", True)
        for name, value in instance.items():
            if name in properties:
                child = properties[name]
                assert isinstance(child, Mapping)
                _validate(value, child, root, f"{path}.{name}")
            elif isinstance(additional, Mapping):
                _validate(value, additional, root, f"{path}.{name}")
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

    reply_options = {
        option["name"]: option for option in commands["career-ops-reply"]["options"]
    }
    assert reply_options["--answer"]["default"] == []
    assert reply_options["--answer"]["action"] == "append"

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


def test_published_output_schemas_accept_real_cli_output(run, workspace):
    catalog = _catalog(run)
    commands = {command["name"]: command for command in catalog["commands"]}

    def check(name: str, payload: object) -> None:
        schema = commands[name]["output"]["schema"]
        _validate(payload, schema, schema)

    check("career-ops-help", catalog)

    cv = write_cv(workspace)
    candidates = write_candidates(workspace, 1)
    jds = write_jd_fixtures(workspace, {"1": FRONTEND_JD})
    run_result, run_payload = invoke(
        run,
        "--candidates",
        str(candidates),
        "--jd-dir",
        str(jds),
        "--cv",
        str(cv),
        "--adapter",
        "fake",
        "--target",
        "1",
        "--run-id",
        "help-contract-run",
    )
    assert run_result.returncode == 0
    check("career-ops-run", run_payload)

    reply_result = run(
        "career-ops-reply",
        "--run-id",
        "no-such-run",
        "--job",
        "4411222",
        "--token",
        "no-such-token",
        "--answer",
        "question=answer",
    )
    assert reply_result.returncode == 3
    check("career-ops-reply", json.loads(reply_result.stdout))

    report_error = run("career-ops-report", "--run-id", "no-such-run", "--json")
    assert report_error.returncode == 1
    check("career-ops-report", json.loads(report_error.stdout))

    report_ok = run(
        "career-ops-report",
        "--run-id",
        "help-contract-run",
        "--json",
        "--no-prune",
    )
    assert report_ok.returncode == 0
    check("career-ops-report", json.loads(report_ok.stdout))


def test_published_reply_schema_accepts_a_successful_resume(run, workspace):
    catalog = _catalog(run)
    commands = {command["name"]: command for command in catalog["commands"]}

    waiting_result, waiting_payload = invoke(
        run,
        "--candidates",
        str(write_candidates(workspace, 1)),
        "--jd-dir",
        str(write_jds(workspace, 1)),
        "--cv",
        str(write_cv(workspace)),
        "--adapter",
        "fake",
        "--fake-scenario",
        "waiting_input",
        "--target",
        "1",
        "--run-id",
        "help-reply-run",
    )
    assert waiting_result.returncode == 6
    parked = waiting_payload["waiting_input"]

    reply_result = run(
        "career-ops-reply",
        "--run-id",
        parked["run_id"],
        "--job",
        parked["job"]["id"],
        "--token",
        parked["token"],
        "--answer",
        "Are you authorized to work?=Yes",
        "--adapter",
        "fake",
    )
    assert reply_result.returncode == 0
    schema = commands["career-ops-reply"]["output"]["schema"]
    _validate(json.loads(reply_result.stdout), schema, schema)
