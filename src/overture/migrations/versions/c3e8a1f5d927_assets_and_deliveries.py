"""Keep every artwork slot and theme as an asset, with a delivery per place.

Art slots and the theme columns of titles and collections become ``assets``
rows: the selection, the content Overture holds for it, and a stored status.
Each place the content has to be becomes an ``asset_deliveries`` row: a
title's local folder, or each server copy of a collection, holding what was
last seen there. A selection's content is the file Overture wrote or
verified for it, else the recorded file, as the app took it to be. A Plex
collection theme Overture uploaded was never hashed, so its content is named
by its video until it is uploaded again. Every title, season and collection
gets its assets, so a status is stored for each.

Revision ID: c3e8a1f5d927
Revises: b7d2f9a4c681
Create Date: 2026-11-20 21:34:41.649747

"""

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

# revision identifiers, used by Alembic.
revision: str = "c3e8a1f5d927"
down_revision: str | Sequence[str] | None = "b7d2f9a4c681"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "poster",
                "background",
                "season_poster",
                "theme",
                name="serverasset",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("url", auto_string(), nullable=True),
        sa.Column("upload_hash", auto_string(), nullable=True),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column(
            "poster_style",
            sa.Enum(
                "individual",
                "matte",
                "overlay",
                name="collectionposterstyle",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "generated_style",
            sa.Enum("dark", "light", "accent", name="artstyle", native_enum=False),
            nullable=True,
        ),
        sa.Column("generated_title_only", sa.Boolean(), nullable=False),
        sa.Column(
            "youtube_id_source",
            sa.Enum(
                "download",
                "embedded_id",
                "source_url",
                "metadata_url",
                "selection",
                name="themeidsource",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("provenance_cleared", sa.Boolean(), nullable=False),
        sa.Column("content_hash", auto_string(), nullable=True),
        sa.Column("fingerprint", auto_string(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("needed", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "complete", "partial", "missing", name="assetstatus", native_enum=False
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'season_poster') = (season_id IS NOT NULL)",
            name="ck_assets_season_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'theme' AND url IS NULL AND upload_hash IS NULL) OR (kind != "
            "'theme' AND youtube_id IS NULL)",
            name="ck_assets_selection_kind",
        ),
        sa.CheckConstraint(
            "(poster_style IS NOT NULL) = (collection_id IS NOT NULL AND kind = "
            "'poster' AND url IS NOT NULL)",
            name="ck_assets_collection_poster_style",
        ),
        sa.CheckConstraint(
            "generated_style IN ('dark', 'light', 'accent')",
            name="ck_assets_generated_style",
        ),
        sa.CheckConstraint(
            "kind IN ('poster', 'background', 'season_poster', 'theme')",
            name="ck_assets_kind",
        ),
        sa.CheckConstraint(
            "poster_style IN ('individual', 'matte', 'overlay')",
            name="ck_assets_poster_style",
        ),
        sa.CheckConstraint(
            "status IN ('complete', 'partial', 'missing')", name="ck_assets_status"
        ),
        sa.CheckConstraint(
            "youtube_id_source IN ('download', 'embedded_id', 'source_url', "
            "'metadata_url', 'selection')",
            name="ck_assets_youtube_id_source",
        ),
        sa.CheckConstraint(
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL) + (collection_id "
            "IS NOT NULL) = 1",
            name="ck_assets_owner",
        ),
        sa.CheckConstraint(
            "(url IS NOT NULL) + (upload_hash IS NOT NULL) + (youtube_id IS NOT NULL) "
            "<= 1",
            name="ck_assets_selection",
        ),
        sa.CheckConstraint(
            "NOT generated_title_only OR generated_style IS NOT NULL",
            name="ck_assets_generated_title_only",
        ),
        sa.CheckConstraint(
            "generated_style IS NULL OR upload_hash IS NOT NULL",
            name="ck_assets_generated",
        ),
        sa.CheckConstraint(
            "youtube_id_source IS NULL OR youtube_id IS NOT NULL",
            name="ck_assets_theme_source",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "kind", name="uq_assets_collection"),
        sa.UniqueConstraint("media_item_id", "kind", name="uq_assets_media_item"),
        sa.UniqueConstraint("season_id", "kind", name="uq_assets_season"),
    )
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assets_collection_id"), ["collection_id"], unique=False
        )
        batch_op.create_index("ix_assets_kind_status", ["kind", "status"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_assets_media_item_id"), ["media_item_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_assets_season_id"), ["season_id"], unique=False
        )

    op.create_table(
        "asset_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("server_item_id", auto_string(), nullable=True),
        sa.Column(
            "channel",
            sa.Enum("file", "upload", name="deliverychannel", native_enum=False),
            nullable=False,
        ),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("observed_hash", auto_string(), nullable=True),
        sa.Column("observed_ref", auto_string(), nullable=True),
        sa.Column("file_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("fingerprint", auto_string(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "channel IN ('file', 'upload')", name="ck_asset_deliveries_channel"
        ),
        sa.CheckConstraint(
            "server_id IS NOT NULL OR channel = 'file'",
            name="ck_asset_deliveries_local_file",
        ),
        sa.CheckConstraint(
            "(server_id IS NULL) = (server_item_id IS NULL)",
            name="ck_asset_deliveries_destination",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["server_id"], ["media_servers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id", "server_id", "server_item_id", name="uq_asset_deliveries"
        ),
    )
    with op.batch_alter_table("asset_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_asset_deliveries_asset_id"), ["asset_id"], unique=False
        )
        batch_op.create_index(
            "ix_asset_deliveries_server", ["server_id", "server_item_id"], unique=False
        )
        batch_op.create_index(
            "uq_asset_deliveries_local",
            ["asset_id"],
            unique=True,
            sqlite_where=sa.text("server_id IS NULL"),
        )

    _convert()

    with op.batch_alter_table("art_slots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_art_slots_collection_id"))
        batch_op.drop_index(batch_op.f("ix_art_slots_media_item_id"))
        batch_op.drop_index(batch_op.f("ix_art_slots_season_id"))

    op.drop_table("art_slots")
    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.drop_column("youtube_duration")
        batch_op.drop_column("theme_file_duration")
        batch_op.drop_column("art_url")
        batch_op.drop_column("theme_file_hash")
        batch_op.drop_column("thumb_url")
        batch_op.drop_column("youtube_title")
        batch_op.drop_column("theme_file_mtime_ns")
        batch_op.drop_column("server_theme_id")
        batch_op.drop_column("youtube_id")
        batch_op.drop_constraint(
            "ck_media_collections_youtube_id_source", type_="check"
        )
        batch_op.drop_column("youtube_id_source")
        batch_op.drop_column("theme_file_size")

    with op.batch_alter_table("media_items", schema=None) as batch_op:
        batch_op.drop_column("youtube_duration")
        batch_op.drop_column("theme_file_duration")
        batch_op.drop_column("theme_file_hash")
        batch_op.drop_column("youtube_title")
        batch_op.drop_column("theme_provenance_cleared")
        batch_op.drop_column("theme_file_mtime_ns")
        batch_op.drop_column("theme_selection_hash")
        batch_op.drop_column("youtube_id")
        batch_op.drop_constraint("ck_media_items_youtube_id_source", type_="check")
        batch_op.drop_column("youtube_id_source")
        batch_op.drop_column("theme_file_size")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("media_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("theme_file_size", sa.INTEGER(), nullable=True))
        batch_op.add_column(
            sa.Column("youtube_id_source", sa.VARCHAR(length=12), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_media_items_youtube_id_source",
            "youtube_id_source IN ('download', 'embedded_id', 'source_url', "
            "'metadata_url', 'selection')",
        )
        batch_op.add_column(sa.Column("youtube_id", sa.VARCHAR(), nullable=True))
        batch_op.add_column(
            sa.Column("theme_selection_hash", sa.VARCHAR(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("theme_file_mtime_ns", sa.INTEGER(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "theme_provenance_cleared",
                sa.BOOLEAN(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("youtube_title", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("theme_file_hash", sa.VARCHAR(), nullable=True))
        batch_op.add_column(
            sa.Column("theme_file_duration", sa.INTEGER(), nullable=True)
        )
        batch_op.add_column(sa.Column("youtube_duration", sa.INTEGER(), nullable=True))

    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("theme_file_size", sa.INTEGER(), nullable=True))
        batch_op.add_column(
            sa.Column("youtube_id_source", sa.VARCHAR(length=14), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_media_collections_youtube_id_source",
            "youtube_id_source IN ('overturedb', 'themerrdb', 'youtube_search')",
        )
        batch_op.add_column(sa.Column("youtube_id", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("server_theme_id", sa.VARCHAR(), nullable=True))
        batch_op.add_column(
            sa.Column("theme_file_mtime_ns", sa.INTEGER(), nullable=True)
        )
        batch_op.add_column(sa.Column("youtube_title", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("thumb_url", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("theme_file_hash", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("art_url", sa.VARCHAR(), nullable=True))
        batch_op.add_column(
            sa.Column("theme_file_duration", sa.INTEGER(), nullable=True)
        )
        batch_op.add_column(sa.Column("youtube_duration", sa.INTEGER(), nullable=True))

    op.create_table(
        "art_slots",
        sa.Column("id", sa.INTEGER(), nullable=False),
        sa.Column("media_item_id", sa.INTEGER(), nullable=True),
        sa.Column("season_id", sa.INTEGER(), nullable=True),
        sa.Column("collection_id", sa.INTEGER(), nullable=True),
        sa.Column("art_type", sa.VARCHAR(length=13), nullable=False),
        sa.Column("url", sa.VARCHAR(), nullable=True),
        sa.Column("file_hash", sa.VARCHAR(), nullable=True),
        sa.Column("phash", sa.VARCHAR(), nullable=True),
        sa.Column("width", sa.INTEGER(), nullable=True),
        sa.Column("height", sa.INTEGER(), nullable=True),
        sa.Column("file_mtime_ns", sa.INTEGER(), nullable=True),
        sa.Column("file_size", sa.INTEGER(), nullable=True),
        sa.Column("upload_hash", sa.VARCHAR(), nullable=True),
        sa.Column("generated_style", sa.VARCHAR(length=6), nullable=True),
        sa.Column(
            "generated_title_only",
            sa.BOOLEAN(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("selection_hash", sa.VARCHAR(), nullable=True),
        sa.Column("poster_style", sa.VARCHAR(length=10), nullable=True),
        sa.CheckConstraint(
            "(poster_style IS NOT NULL) = (collection_id IS NOT NULL AND art_type = "
            "'poster' AND url IS NOT NULL)",
            name=op.f("ck_art_slots_collection_poster_style"),
        ),
        sa.CheckConstraint(
            "art_type IN ('poster', 'background', 'season_poster')",
            name=op.f("ck_art_slots_art_type"),
        ),
        sa.CheckConstraint(
            "generated_style IN ('dark', 'light', 'accent')",
            name=op.f("ck_art_slots_generated_style"),
        ),
        sa.CheckConstraint(
            "poster_style IN ('individual', 'matte', 'overlay')",
            name=op.f("ck_art_slots_poster_style"),
        ),
        sa.CheckConstraint(
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL) + (collection_id "
            "IS NOT NULL) = 1",
            name=op.f("ck_art_slots_owner"),
        ),
        sa.CheckConstraint(
            "NOT generated_title_only OR generated_style IS NOT NULL",
            name=op.f("ck_art_slots_generated_title_only"),
        ),
        sa.CheckConstraint(
            "generated_style IS NULL OR upload_hash IS NOT NULL",
            name=op.f("ck_art_slots_generated"),
        ),
        sa.CheckConstraint(
            "url IS NULL OR upload_hash IS NULL", name=op.f("ck_art_slots_selection")
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id", "art_type", name=op.f("uq_art_slots_collection")
        ),
        sa.UniqueConstraint(
            "media_item_id", "art_type", name=op.f("uq_art_slots_media_item")
        ),
        sa.UniqueConstraint("season_id", "art_type", name=op.f("uq_art_slots_season")),
    )
    with op.batch_alter_table("art_slots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_art_slots_season_id"), ["season_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_art_slots_media_item_id"), ["media_item_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_art_slots_collection_id"), ["collection_id"], unique=False
        )

    _restore()

    with op.batch_alter_table("asset_deliveries", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_asset_deliveries_local", sqlite_where=sa.text("server_id IS NULL")
        )
        batch_op.drop_index("ix_asset_deliveries_server")
        batch_op.drop_index(batch_op.f("ix_asset_deliveries_asset_id"))

    op.drop_table("asset_deliveries")
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assets_season_id"))
        batch_op.drop_index(batch_op.f("ix_assets_media_item_id"))
        batch_op.drop_index("ix_assets_kind_status")
        batch_op.drop_index(batch_op.f("ix_assets_collection_id"))

    op.drop_table("assets")


def _table(name: str, columns: Mapping[str, object]) -> sa.TableClause:
    """A lightweight table naming just *columns*, to insert or update them."""
    return sa.table(
        name, *(sa.column(column, sa.types.NullType()) for column in columns)
    )


def _status(
    selected: bool, content: str | None, deliveries: list[tuple[bool, object]]
) -> str:
    """The app's status rule: every required delivery holds the content."""
    required = [observed for needed, observed in deliveries if needed]
    if selected and (
        not required or (content is not None and all(o == content for o in required))
    ):
        return "complete"
    started = selected or content is not None or any(o for _, o in deliveries)
    return "partial" if started else "missing"


def _insert(
    connection: sa.Connection,
    owner: dict[str, int | None],
    kind: str,
    asset: dict[str, object],
    deliveries: list[dict[str, object]],
) -> None:
    selected = any(asset.get(key) for key in ("url", "upload_hash", "youtube_id"))
    content = asset.get("content_hash")
    status = _status(
        selected,
        content if isinstance(content, str) else None,
        [(True, d.get("observed_hash")) for d in deliveries],
    )
    columns = {
        "media_item_id": None,
        "season_id": None,
        "collection_id": None,
        **owner,
        "kind": kind,
        "url": None,
        "upload_hash": None,
        "youtube_id": None,
        "poster_style": None,
        "generated_style": None,
        "generated_title_only": False,
        "youtube_id_source": None,
        "youtube_title": None,
        "youtube_duration": None,
        "provenance_cleared": False,
        "content_hash": None,
        "fingerprint": None,
        "width": None,
        "height": None,
        "duration": None,
        **asset,
        "needed": True,
        "status": status,
    }
    assets = _table("assets", {**columns, "id": None})
    asset_id = connection.execute(
        sa.insert(assets).values(columns).returning(assets.c.id)
    ).scalar_one()
    for delivery in deliveries:
        row = {
            "asset_id": asset_id,
            "server_id": None,
            "server_item_id": None,
            "channel": "file",
            "required": True,
            "observed_hash": None,
            "observed_ref": None,
            "file_mtime_ns": None,
            "file_size": None,
            "fingerprint": None,
            "width": None,
            "height": None,
            "duration": None,
            "checked_at": None,
            **delivery,
        }
        connection.execute(sa.insert(_table("asset_deliveries", row)).values(row))


def _local(row: sa.RowMapping, prefix: str, *, folder: bool) -> list[dict[str, object]]:
    """The local folder's delivery, holding the recorded file, for a title with one."""
    if not folder:
        return []
    observed = row[f"{prefix}hash"]
    return [
        {
            "observed_hash": observed,
            "file_mtime_ns": row[f"{prefix}mtime_ns"] if observed else None,
            "file_size": row[f"{prefix}size"] if observed else None,
            **(
                {
                    "fingerprint": row["phash"],
                    "width": row["width"],
                    "height": row["height"],
                }
                if prefix == "file_" and observed
                else {}
            ),
            **(
                {"duration": row["theme_file_duration"]}
                if prefix == "theme_file_" and observed
                else {}
            ),
        }
    ]


def _convert() -> None:
    connection = op.get_bind()
    folders = {
        item_id: folder is not None
        for item_id, folder in connection.execute(
            sa.text("SELECT id, folder_path FROM media_items")
        )
    }
    season_items = dict(
        connection.execute(sa.text("SELECT id, media_item_id FROM seasons")).all()
    )
    server_types = {
        server_id: server_type
        for server_id, server_type, _ in connection.execute(
            sa.text("SELECT id, server_type, position FROM media_servers")
        )
    }
    lead_server = connection.execute(
        sa.text(
            "SELECT id FROM media_servers WHERE position IS NOT NULL "
            "ORDER BY position LIMIT 1"
        )
    ).scalar()
    copies: dict[int, list[tuple[int, str]]] = {}
    for collection_id, server_id, server_item_id in connection.execute(
        sa.text(
            "SELECT DISTINCT collection_id, server_id, server_item_id "
            "FROM collection_libraries WHERE server_item_id IS NOT NULL "
            "ORDER BY collection_id, server_id"
        )
    ):
        copies.setdefault(collection_id, []).append((server_id, server_item_id))
    collections = {
        row["id"]: row
        for row in connection.execute(sa.text("SELECT * FROM media_collections"))
        .mappings()
        .all()
    }
    slots: dict[tuple[str, int, str], sa.RowMapping] = {}
    for row in connection.execute(sa.text("SELECT * FROM art_slots")).mappings():
        owner = (
            ("media_item_id", row["media_item_id"])
            if row["media_item_id"] is not None
            else ("season_id", row["season_id"])
            if row["season_id"] is not None
            else ("collection_id", row["collection_id"])
        )
        slots[(owner[0], owner[1], row["art_type"])] = row

    def art(owner: str, owner_id: int, kind: str) -> dict[str, object]:
        row = slots.get((owner, owner_id, kind))
        if row is None:
            return {}
        selected = row["url"] is not None or row["upload_hash"] is not None
        content = row["selection_hash"] or (row["file_hash"] if selected else None)
        facts = (
            {
                "fingerprint": row["phash"],
                "width": row["width"],
                "height": row["height"],
            }
            if content is not None and content == row["file_hash"]
            else {}
        )
        return {
            "url": row["url"],
            "upload_hash": row["upload_hash"],
            "poster_style": row["poster_style"],
            "generated_style": row["generated_style"],
            "generated_title_only": row["generated_title_only"],
            "content_hash": content,
            **facts,
        }

    for item in (
        connection.execute(sa.text("SELECT * FROM media_items")).mappings().all()
    ):
        folder = folders[item["id"]]
        owner = {"media_item_id": item["id"]}
        for kind in ("poster", "background"):
            row = slots.get(("media_item_id", item["id"], kind))
            _insert(
                connection,
                owner,
                kind,
                art("media_item_id", item["id"], kind),
                _local(row, "file_", folder=folder)
                if row is not None
                else ([{}] if folder else []),
            )
        selected = item["youtube_id"] is not None
        _insert(
            connection,
            owner,
            "theme",
            {
                "youtube_id": item["youtube_id"],
                "youtube_id_source": item["youtube_id_source"],
                "youtube_title": item["youtube_title"],
                "youtube_duration": item["youtube_duration"],
                "provenance_cleared": item["theme_provenance_cleared"],
                "content_hash": item["theme_selection_hash"]
                or (item["theme_file_hash"] if selected else None),
                "duration": item["theme_file_duration"],
            },
            _local(item, "theme_file_", folder=folder),
        )
    for season_id, item_id in season_items.items():
        row = slots.get(("season_id", season_id, "season_poster"))
        folder = folders.get(item_id, False)
        _insert(
            connection,
            {"season_id": season_id},
            "season_poster",
            art("season_id", season_id, "season_poster"),
            _local(row, "file_", folder=folder)
            if row is not None
            else ([{}] if folder else []),
        )
    for collection_id, collection in collections.items():
        held = copies.get(collection_id, [])
        owner = {"collection_id": collection_id}
        for kind, server_url in (
            ("poster", collection["thumb_url"]),
            ("background", collection["art_url"]),
        ):
            asset = art("collection_id", collection_id, kind)
            uploaded = asset.get("content_hash")
            _insert(
                connection,
                owner,
                kind,
                asset,
                [
                    {
                        "server_id": server_id,
                        "server_item_id": server_item_id,
                        "channel": "upload",
                        "observed_hash": uploaded,
                        "observed_ref": server_url
                        if server_id == lead_server
                        else None,
                    }
                    for server_id, server_item_id in held
                ],
            )
        video = collection["youtube_id"]
        content = collection["theme_file_hash"] or (
            f"youtube:{video}" if video and collection["server_theme_id"] else None
        )
        deliveries = _collection_theme_deliveries(
            collection, held, server_types, content
        )
        _insert(
            connection,
            owner,
            "theme",
            {
                "youtube_id": video,
                "youtube_id_source": "download" if video else None,
                "youtube_title": collection["youtube_title"],
                "youtube_duration": collection["youtube_duration"],
                "content_hash": content if video else None,
                "duration": collection["theme_file_duration"],
            },
            deliveries,
        )


def _collection_theme_deliveries(
    collection: sa.RowMapping,
    held: list[tuple[int, str]],
    server_types: Mapping[int, str | None],
    content: str | None,
) -> list[dict[str, object]]:
    """A collection theme's places: each Plex copy, and one folder per Jellyfin."""
    deliveries: list[dict[str, object]] = []
    folders_seen: set[int] = set()
    for server_id, server_item_id in held:
        server_type = server_types.get(server_id)
        if server_type == "plex":
            deliveries.append(
                {
                    "server_id": server_id,
                    "server_item_id": server_item_id,
                    "channel": "upload",
                    "observed_hash": content if collection["server_theme_id"] else None,
                    "observed_ref": collection["server_theme_id"],
                }
            )
        elif server_type == "jellyfin" and server_id not in folders_seen:
            folders_seen.add(server_id)
            deliveries.append(
                {
                    "server_id": server_id,
                    "server_item_id": server_item_id,
                    "channel": "file",
                    "observed_hash": collection["theme_file_hash"],
                    "file_mtime_ns": collection["theme_file_mtime_ns"],
                    "file_size": collection["theme_file_size"],
                    "duration": collection["theme_file_duration"],
                }
            )
    return deliveries


def _restore() -> None:
    """Write assets back as art slots and theme columns.

    What a slot recorded per server copy keeps only the lead copy's link, and
    a placeholder content name is dropped, as the earlier app kept them.
    """
    connection = op.get_bind()
    deliveries: dict[int, list[sa.RowMapping]] = {}
    for row in (
        connection.execute(
            sa.text("SELECT * FROM asset_deliveries ORDER BY server_id IS NOT NULL, id")
        )
        .mappings()
        .all()
    ):
        deliveries.setdefault(row["asset_id"], []).append(row)
    for asset in connection.execute(sa.text("SELECT * FROM assets")).mappings().all():
        rows = deliveries.get(asset["id"], [])
        local = next((row for row in rows if row["server_id"] is None), None)
        seen = next((row for row in rows if row["observed_hash"]), None)
        content = asset["content_hash"]
        if content is not None and content.startswith("youtube:"):
            content = None
        if asset["kind"] == "theme":
            table = "media_items" if asset["media_item_id"] else "media_collections"
            owner = asset["media_item_id"] or asset["collection_id"]
            values: dict[str, object] = {
                "youtube_id": asset["youtube_id"],
                "youtube_title": asset["youtube_title"],
                "youtube_duration": asset["youtube_duration"],
                "theme_file_hash": None,
                "theme_file_mtime_ns": None,
                "theme_file_size": None,
                "theme_file_duration": None,
            }
            file = (
                local
                if table == "media_items"
                else next((row for row in rows if row["channel"] == "file"), None)
            )
            if file is not None and file["observed_hash"]:
                values.update(
                    theme_file_hash=file["observed_hash"],
                    theme_file_mtime_ns=file["file_mtime_ns"],
                    theme_file_size=file["file_size"],
                    theme_file_duration=file["duration"],
                )
            if table == "media_items":
                values.update(
                    youtube_id_source=asset["youtube_id_source"],
                    theme_provenance_cleared=asset["provenance_cleared"],
                    theme_selection_hash=content,
                )
            else:
                upload = next((row for row in rows if row["channel"] == "upload"), None)
                values["server_theme_id"] = upload["observed_ref"] if upload else None
            owners = _table(table, {**values, "id": owner})
            connection.execute(
                sa.update(owners).where(owners.c.id == owner).values(values)
            )
            continue
        if asset["collection_id"] is not None:
            column = "thumb_url" if asset["kind"] == "poster" else "art_url"
            ref = next(
                (row["observed_ref"] for row in rows if row["observed_ref"]), None
            )
            owners = _table("media_collections", {column: ref, "id": 0})
            connection.execute(
                sa.update(owners)
                .where(owners.c.id == asset["collection_id"])
                .values({column: ref})
            )
            file_facts = {
                "file_hash": content if seen else None,
                "phash": asset["fingerprint"],
                "width": asset["width"],
                "height": asset["height"],
                "file_mtime_ns": 0 if seen else None,
                "file_size": 0 if seen else None,
            }
        else:
            observed = local["observed_hash"] if local else None
            file_facts = {
                "file_hash": observed,
                "phash": local["fingerprint"] if observed and local else None,
                "width": local["width"] if observed and local else None,
                "height": local["height"] if observed and local else None,
                "file_mtime_ns": local["file_mtime_ns"] if observed and local else None,
                "file_size": local["file_size"] if observed and local else None,
            }
        if not (asset["url"] or asset["upload_hash"] or file_facts["file_hash"]):
            continue
        row = {
            "media_item_id": asset["media_item_id"],
            "season_id": asset["season_id"],
            "collection_id": asset["collection_id"],
            "art_type": asset["kind"],
            "url": asset["url"],
            "upload_hash": asset["upload_hash"],
            "poster_style": asset["poster_style"],
            "generated_style": asset["generated_style"],
            "generated_title_only": asset["generated_title_only"],
            "selection_hash": content if asset["collection_id"] is None else None,
            **file_facts,
        }
        connection.execute(sa.insert(_table("art_slots", row)).values(row))
