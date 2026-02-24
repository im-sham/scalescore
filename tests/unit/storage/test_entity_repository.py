from scalescore.models.core import Organization, Team
from scalescore.storage.entity_repository import SQLiteEntityRepository


def test_upsert_and_get_organization(tmp_path) -> None:
    repository = SQLiteEntityRepository(tmp_path / "entities.sqlite3")
    organization = Organization(
        id="org_1",
        name="Acme",
        headcount_current=100,
        revenue_current=1_000_000,
        burn_rate_monthly=50_000,
        runway_months=18,
    )

    repository.upsert_entity(organization, tenant_id="tenant_a")
    loaded = repository.get_entity(
        "org_1",
        tenant_id="tenant_a",
        entity_type="organization",
    )

    assert loaded is not None
    assert loaded.id == "org_1"
    assert loaded.name == "Acme"


def test_list_entities_filters_by_type_and_org(tmp_path) -> None:
    repository = SQLiteEntityRepository(tmp_path / "entities.sqlite3")
    repository.upsert_entity(
        Team(
            id="team_1",
            org_id="org_1",
            name="Engineering",
            function="engineering",
            headcount_current=20,
        ),
        tenant_id="tenant_a",
    )
    repository.upsert_entity(
        Team(
            id="team_2",
            org_id="org_2",
            name="Sales",
            function="sales",
            headcount_current=15,
        ),
        tenant_id="tenant_a",
    )

    filtered = repository.list_entities(
        "tenant_a",
        entity_type="team",
        org_id="org_1",
        limit=50,
        offset=0,
    )

    assert len(filtered) == 1
    assert filtered[0].id == "team_1"


def test_delete_entity_is_tenant_scoped(tmp_path) -> None:
    repository = SQLiteEntityRepository(tmp_path / "entities.sqlite3")
    repository.upsert_entity(
        Team(
            id="team_1",
            org_id="org_1",
            name="Engineering",
            function="engineering",
            headcount_current=20,
        ),
        tenant_id="tenant_a",
    )

    deleted_wrong_tenant = repository.delete_entity(
        "team_1",
        tenant_id="tenant_b",
        entity_type="team",
    )
    assert deleted_wrong_tenant is False

    deleted = repository.delete_entity(
        "team_1",
        tenant_id="tenant_a",
        entity_type="team",
    )
    assert deleted is True


def test_upsert_entity_accepts_string_entity_type_from_validated_payload(tmp_path) -> None:
    repository = SQLiteEntityRepository(tmp_path / "entities.sqlite3")
    payload = {
        "id": "org_str",
        "type": "organization",
        "name": "String Type Org",
        "headcount_current": 10,
    }
    organization = Organization.model_validate(payload)

    repository.upsert_entity(organization, tenant_id="tenant_a")
    loaded = repository.get_entity(
        "org_str",
        tenant_id="tenant_a",
        entity_type="organization",
    )

    assert loaded is not None
    assert loaded.id == "org_str"
    assert loaded.name == "String Type Org"
