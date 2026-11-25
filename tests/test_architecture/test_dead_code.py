"""No function, method, class or import is left that nothing uses.

Consolidating two copies into one leaves the losing copy behind unless
something notices. Vulture reads the code for names nothing refers to; the
kinds of finding here are the ones that mean dead code, not fields and
settings, which frameworks read by name.
"""

lazy from pathlib import Path

lazy import vulture

ROOT = Path(__file__).resolve().parents[2]
#: The kinds of finding that mean code nothing runs.
DEAD = frozenset(
    {"function", "method", "class", "property", "import", "unreachable_code"}
)
#: Decorators that hand a function to a framework, which calls it by itself.
FRAMEWORK_DECORATORS = [
    "@router.*",
    "@*_router.*",
    "@app.*",
    "@field_validator",
    "@model_validator",
    "@field_serializer",
    "@model_serializer",
    "@computed_field",
    "@override",
    "@property",
    "@*.setter",
]
#: Names used where vulture cannot see, each with where and why.
USED_UNSEEN = {
    # Quoted in ``typing.cast`` for relationship loader options.
    "QueryableAttribute": "repositories/media_items.py, services/catalog/*.py",
    # The migrations call them; vulture does not read the migrations.
    "typed_columns": "migrations/versions/*.py",
    "auto_string": "migrations/versions/*.py",
    # Enums the database models and schemas annotate their fields with.
    "AutoAdvance": "db/models/settings.py",
    "Workflow": "db/models/settings.py",
    "PresetCategory": "schemas/collection_presets.py",
    # OvertureDB runs the vendored catalog contract with these.
    "validate_entries": "OvertureDB's scripts/catalog.py",
    "dump_catalog": "OvertureDB's scripts/catalog.py",
    "dump_presets": "OvertureDB's scripts/catalog.py",
    "preset_repo_path": "OvertureDB's scripts/catalog.py",
    "preset_image_url": "OvertureDB's scripts/preset_contribution.py",
    # A structural interface's member, which the WebSocket implements.
    "send_json": "protocols.ClientConnection",
    # Seams that let tests run a scheduled job, or wait for one, at once.
    "trigger_job": "tests of scheduled jobs",
    "wait_for_pending_runs": "tests of saved schedules",
}


def test_nothing_is_left_unused() -> None:
    scan = vulture.Vulture(
        ignore_names=list(USED_UNSEEN), ignore_decorators=FRAMEWORK_DECORATORS
    )
    scan.scavenge(
        [str(ROOT / "src/overture"), str(ROOT / "scripts")],
        exclude=["*/migrations/versions/*", "*/db/models/*", "*/schemas/*"],
    )
    unused = [
        f"{Path(item.filename).relative_to(ROOT)}:{item.first_lineno} {item.message}"
        for item in scan.get_unused_code(min_confidence=60)
        if item.typ in DEAD
    ]
    assert unused == [], "Remove what nothing uses, or name why it is used"
