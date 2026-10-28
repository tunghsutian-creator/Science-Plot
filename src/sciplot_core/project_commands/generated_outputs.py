"""An exact registered output's absent physical preimage, never a new owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .resources import ProjectionRead, _identity, _sha, resource_key


@dataclass(frozen=True)
class MissingGeneratedOutput:
    resource: str
    before_sha256: str
    mode: int
    owner_key: str | None = None
    owner_digest: str | None = None
    catalog: ProjectionRead | None = None
    parent_identity: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        resource_key(self.resource)
        command = self.owner_key is not None or self.owner_digest is not None
        if (not _sha(self.before_sha256) or type(self.mode) is not int or not 0 <= self.mode <= 0o777
                or command == (self.catalog is not None)
                or command and (not isinstance(self.owner_key, str) or not _identity(self.owner_key)
                                or not isinstance(self.owner_digest, str) or not _sha(self.owner_digest))
                or self.catalog is not None and not isinstance(self.catalog, ProjectionRead)
                or len(self.parent_identity) != 4 or not isinstance(self.parent_identity, tuple)
                or any(type(item) is not int or item < 0 for item in self.parent_identity)):
            raise ValueError("A missing generated output binds exact previous bytes/mode and one closed owner proof.")

    def to_payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {"resource": self.resource, "before_sha256": self.before_sha256, "mode": self.mode,
                "owner_key": self.owner_key, "owner_digest": self.owner_digest,
                "catalog": self.catalog.to_payload() if self.catalog is not None else None,
                "parent_identity": list(self.parent_identity)}

    @classmethod
    def from_payload(cls, value: Any) -> MissingGeneratedOutput:
        if not isinstance(value, dict) or set(value) != {
                "resource", "before_sha256", "mode", "owner_key", "owner_digest", "catalog", "parent_identity"}:
            raise ValueError("A missing generated output has unknown or missing fields.")
        catalog = value["catalog"]
        if catalog is not None:
            if not isinstance(catalog, dict) or set(catalog) != {"resource", "kind", "key", "sha256"}:
                raise ValueError("A generated output catalog requires its exact fixed projection.")
            catalog = ProjectionRead(**catalog)
        if not isinstance(value["parent_identity"], list):
            raise ValueError("A missing-output parent identity must be an exact descriptor observation.")
        return cls(value["resource"], value["before_sha256"], value["mode"],
                   value["owner_key"], value["owner_digest"], catalog, tuple(value["parent_identity"]))
