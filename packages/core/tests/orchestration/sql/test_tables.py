"""The units store's schema."""

from sqlalchemy import create_engine, inspect

from agent_build_kit.orchestration.sql.tables import METADATA


def test_the_schema_creates_the_units_and_history_tables_with_their_keys() -> None:
    engine = create_engine("sqlite://")
    METADATA.create_all(engine)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == {"units", "unit_history"}
    assert inspector.get_pk_constraint("units")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("unit_history")["constrained_columns"] == [
        "unit_id",
        "sequence",
    ]
    foreign = inspector.get_foreign_keys("unit_history")[0]
    assert (foreign["referred_table"], foreign["referred_columns"]) == ("units", ["id"])
