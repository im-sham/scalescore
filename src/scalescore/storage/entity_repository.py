from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from scalescore.config import settings
from scalescore.core.exceptions import DatabaseError
from scalescore.models.core import (
    BaseEntity,
    EntityType,
    Facility,
    Organization,
    System,
    Team,
    Vendor,
)

ENTITY_MODEL_BY_TYPE: dict[str, type[BaseEntity]] = {
    EntityType.ORGANIZATION.value: Organization,
    EntityType.TEAM.value: Team,
    EntityType.SYSTEM.value: System,
    EntityType.VENDOR.value: Vendor,
    EntityType.FACILITY.value: Facility,
}


class EntityRepository(Protocol):
    def upsert_entity(self, entity: BaseEntity, *, tenant_id: str) -> BaseEntity: ...

    def get_entity(
        self,
        entity_id: str,
        *,
        tenant_id: str,
        entity_type: str,
    ) -> BaseEntity | None: ...

    def list_entities(
        self,
        tenant_id: str,
        *,
        entity_type: str | None = None,
        org_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BaseEntity]: ...

    def delete_entity(
        self,
        entity_id: str,
        *,
        tenant_id: str,
        entity_type: str,
    ) -> bool: ...


class SQLiteEntityRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS entities (
                            tenant_id TEXT NOT NULL,
                            entity_type TEXT NOT NULL,
                            entity_id TEXT NOT NULL,
                            org_id TEXT,
                            name TEXT NOT NULL,
                            entity_data TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            PRIMARY KEY (tenant_id, entity_type, entity_id)
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_entities_tenant_type_org
                        ON entities (tenant_id, entity_type, org_id)
                        """
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to initialize entity storage", cause=err) from err

    def _entity_model(self, entity_type: str) -> type[BaseEntity]:
        return ENTITY_MODEL_BY_TYPE.get(entity_type, BaseEntity)

    def _coerce_entity(self, entity_type: str, payload: str) -> BaseEntity:
        model_cls = self._entity_model(entity_type)
        return model_cls.model_validate_json(payload)

    def _resolve_org_id(self, entity: BaseEntity) -> str | None:
        if entity.type == EntityType.ORGANIZATION:
            return entity.id
        org_id = getattr(entity, "org_id", None)
        return str(org_id) if org_id else None

    def upsert_entity(self, entity: BaseEntity, *, tenant_id: str) -> BaseEntity:
        entity_type = entity.type.value
        now = datetime.now(UTC).isoformat()
        org_id = self._resolve_org_id(entity)

        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO entities (
                            tenant_id,
                            entity_type,
                            entity_id,
                            org_id,
                            name,
                            entity_data,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(tenant_id, entity_type, entity_id) DO UPDATE SET
                            org_id = excluded.org_id,
                            name = excluded.name,
                            entity_data = excluded.entity_data,
                            updated_at = excluded.updated_at
                        """,
                        (
                            tenant_id,
                            entity_type,
                            entity.id,
                            org_id,
                            entity.name,
                            entity.model_dump_json(),
                            now,
                            now,
                        ),
                    )
        except sqlite3.Error as err:
            raise DatabaseError("Failed to persist entity", cause=err) from err

        persisted = self.get_entity(entity.id, tenant_id=tenant_id, entity_type=entity_type)
        if persisted is None:
            raise DatabaseError("Entity persistence failed unexpectedly")
        return persisted

    def get_entity(
        self,
        entity_id: str,
        *,
        tenant_id: str,
        entity_type: str,
    ) -> BaseEntity | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT entity_data
                    FROM entities
                    WHERE tenant_id = ? AND entity_type = ? AND entity_id = ?
                    """,
                    (tenant_id, entity_type, entity_id),
                ).fetchone()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to load entity", cause=err) from err

        if row is None:
            return None

        return self._coerce_entity(entity_type, row["entity_data"])

    def list_entities(
        self,
        tenant_id: str,
        *,
        entity_type: str | None = None,
        org_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BaseEntity]:
        clauses = ["tenant_id = ?"]
        params: list[str | int] = [tenant_id]
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if org_id:
            clauses.append("org_id = ?")
            params.append(org_id)
        params.extend([limit, offset])

        where_clause = " AND ".join(clauses)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT entity_type, entity_data
                    FROM entities
                    WHERE {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.Error as err:
            raise DatabaseError("Failed to list entities", cause=err) from err

        return [self._coerce_entity(row["entity_type"], row["entity_data"]) for row in rows]

    def delete_entity(
        self,
        entity_id: str,
        *,
        tenant_id: str,
        entity_type: str,
    ) -> bool:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    result = connection.execute(
                        """
                        DELETE FROM entities
                        WHERE tenant_id = ? AND entity_type = ? AND entity_id = ?
                        """,
                        (tenant_id, entity_type, entity_id),
                    )
                    return result.rowcount > 0
        except sqlite3.Error as err:
            raise DatabaseError("Failed to delete entity", cause=err) from err


@lru_cache
def get_entity_repository() -> SQLiteEntityRepository:
    return SQLiteEntityRepository(settings.storage.assessments_db_path)
