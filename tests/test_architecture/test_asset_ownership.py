"""Only the ledger writes assets, so their stored status always follows their rows.

Every other module goes through ``overture.db.ledger``: it never builds an
asset or delivery row, never writes one with a SQL statement, and never
assigns a column only those rows have. Migrations are snapshots and keep
their own SQL.
"""

lazy import ast
lazy from pathlib import Path

lazy import overture
lazy from overture.db.models.asset import Asset, AssetDelivery

ROOT = Path(overture.__file__).parent
LEDGER = ROOT / "db" / "ledger.py"
MODELS = {Asset.__name__, AssetDelivery.__name__}

#: Columns only asset rows hold; assigning one anywhere else writes an asset.
_SHARED = {"id", "width", "height", "duration", "url", "fingerprint", "kind"}
OWNED = (
    {
        *(set(Asset.model_fields) | set(AssetDelivery.model_fields)),
    }
    - _SHARED
    - {
        # Columns other tables hold under the same name.
        "media_item_id",
        "season_id",
        "collection_id",
        "server_id",
        "server_item_id",
        "file_size",
        "status",
        "upload_hash",
        "poster_style",
        "generated_style",
        "generated_title_only",
        "youtube_id",
        "youtube_title",
        "youtube_duration",
        "asset_id",
        "checked_at",
        "required",
        "deliveries",
        "media_item",
        "season",
        "collection",
        "asset",
    }
)


def _modules() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.py")
        if "migrations" not in path.parts and path != LEDGER
    ]


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.id if isinstance(callee, ast.Name) else None
            if name in MODELS:
                found.append(f"{path}:{node.lineno} builds {name}")
            if name in {"insert", "update", "delete"} and any(
                isinstance(arg, ast.Name) and arg.id in MODELS for arg in node.args
            ):
                found.append(f"{path}:{node.lineno} writes assets with {name}()")
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        found.extend(
            f"{path}:{target.lineno} assigns {target.attr}"
            for target in targets
            if isinstance(target, ast.Attribute) and target.attr in OWNED
        )
    return found


def test_only_the_ledger_writes_assets() -> None:
    violations = [found for path in _modules() for found in _violations(path)]

    assert violations == []


def test_the_scan_sees_what_it_guards() -> None:
    """The columns it watches exist, so a renamed one cannot slip past."""
    assert {"content_hash", "observed_hash", "observed_ref", "needed"} <= OWNED
    assert _violations(LEDGER)
