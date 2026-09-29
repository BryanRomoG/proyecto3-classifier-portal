"""Source-image access: MariaDB ``images`` rows plus object-store bytes.

Both clients come from the existing centralized factories (``config.clients`` and
``storage.object_store``); this module adds no configuration, no credentials and no
direct boto3 usage. Callers depend on the ``SourceImageStore`` protocol, which is what
lets the whole test suite run against in-memory doubles — no MariaDB, no MinIO, no
Docker and no network.

The join is the same relation the ``analyze`` stage already relies on: COCO image ids
*are* the backend's ``images.id``, because the COCO export reuses the DB ids as-is. The
``images`` row gives the object-store ``storage_key``; the object gives the bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import text

from dataset_quality.config.clients import get_db_engine
from dataset_quality.config.settings import Settings
from dataset_quality.crops.errors import CropSourceUnavailableError
from dataset_quality.storage.object_store import ObjectStore

_SELECT_STORAGE_KEYS = "SELECT id, storage_key FROM images WHERE id IN :ids"


class SourceImageStore(Protocol):
    """Everything the crop generator needs from MariaDB plus object storage."""

    def storage_keys(self, image_ids: Sequence[int]) -> Mapping[int, str]:
        """The object-store key of each requested image id, in one round trip."""

        ...

    def read_bytes(self, storage_key: str) -> bytes:
        """The raw bytes of one stored object."""

        ...


@dataclass
class BackendImageStore:
    """``SourceImageStore`` backed by the backend's MariaDB and object store."""

    engine: Any
    object_store: ObjectStore

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> BackendImageStore:
        return cls(
            engine=get_db_engine(settings),
            object_store=ObjectStore.from_settings(settings),
        )

    def storage_keys(self, image_ids: Sequence[int]) -> Mapping[int, str]:
        requested = sorted(set(image_ids))
        if not requested:
            return {}

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(_SELECT_STORAGE_KEYS), {"ids": tuple(requested)}
            ).fetchall()

        keys_by_id: dict[int, str] = {}
        for row in rows:
            image_id, storage_key = row[0], row[1]
            if not isinstance(storage_key, str) or not storage_key.strip():
                raise CropSourceUnavailableError(
                    f"image id={image_id} has a blank storage_key in the images table"
                )
            keys_by_id[int(image_id)] = storage_key

        missing = [image_id for image_id in requested if image_id not in keys_by_id]
        if missing:
            raise CropSourceUnavailableError(
                f"images table is missing {len(missing)} of {len(requested)} referenced image "
                f"ids (e.g. {missing[:5]}): crops cannot be built against this DB. Restore the "
                "release bundle (scripts/restore-env.sh) or point the stage at a populated DB."
            )
        return keys_by_id

    def read_bytes(self, storage_key: str) -> bytes:
        try:
            return self.object_store.get_bytes(storage_key)
        except Exception as error:
            raise CropSourceUnavailableError(
                f"could not read {storage_key!r} from the object store: {error}"
            ) from error
