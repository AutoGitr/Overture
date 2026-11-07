lazy from sqlmodel import SQLModel

lazy from overture.db.tables import table_description, table_models, table_of


def test_every_table_is_found_and_says_what_its_rows_are() -> None:
    models = table_models()

    assert {table_of(model).name for model in models} == set(SQLModel.metadata.tables)
    assert [model.__name__ for model in models if not table_description(model)] == []
