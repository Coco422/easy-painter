from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Id = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Coordinate = Annotated[float, Field(ge=-10_000_000, le=10_000_000, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Viewport(StrictModel):
    x: Coordinate
    y: Coordinate
    scale: float = Field(ge=0.1, le=3, allow_inf_nan=False)


class Node(StrictModel):
    id: Id
    type: Literal["text", "image", "generation", "group"]
    title: str = Field(max_length=120)
    x: Coordinate
    y: Coordinate
    width: float = Field(ge=80, le=10_000, allow_inf_nan=False)
    height: float = Field(ge=60, le=10_000, allow_inf_nan=False)
    text: str | None = Field(default=None, max_length=20_000)
    assetId: Digest | None = None
    groupId: Id | None = None
    prompt: str | None = Field(default=None, max_length=20_000)
    model: str | None = Field(default=None, max_length=128)
    size: str | None = Field(default=None, max_length=32)
    count: Literal[1, 2, 4] | None = None


class Edge(StrictModel):
    id: Id
    from_: Id = Field(alias="from")
    to: Id


class Run(StrictModel):
    id: Id
    nodeId: Id
    sourceId: Id
    prompt: str = Field(max_length=20_000)
    model: str = Field(max_length=128)
    size: str = Field(max_length=32)
    referenceIds: list[Digest] = Field(max_length=100)
    uploadedIds: list[Id] = Field(max_length=100)
    jobId: Id | None = None
    assetId: Digest | None = None
    status: Literal[
        "preparing",
        "submitting",
        "queued",
        "processing",
        "succeeded",
        "failed",
        "unknown",
    ]
    error: str | None = Field(default=None, max_length=4000)
    mediaError: str | None = Field(default=None, max_length=4000)


class Document(StrictModel):
    schemaVersion: Literal[1]
    id: UUID
    ownerId: str = Field(max_length=64)
    title: str = Field(max_length=120)
    updatedAt: str = Field(max_length=40)
    revision: int = Field(ge=0)
    cloudVersion: int | None = Field(default=None, ge=1)
    cloudEnabled: bool
    viewport: Viewport
    nodes: list[Node] = Field(max_length=300)
    edges: list[Edge] = Field(max_length=1000)
    runs: list[Run] = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_references(self):
        nodes = {node.id: node for node in self.nodes}
        if (
            len(nodes) != len(self.nodes)
            or len({e.id for e in self.edges}) != len(self.edges)
            or len({r.id for r in self.runs}) != len(self.runs)
        ):
            raise ValueError("duplicate canvas identifiers")
        for edge in self.edges:
            if edge.from_ not in nodes or edge.to not in nodes or edge.from_ == edge.to:
                raise ValueError("invalid edge")
        for node in self.nodes:
            if node.groupId and (
                node.type == "group"
                or node.groupId not in nodes
                or nodes[node.groupId].type != "group"
            ):
                raise ValueError("invalid group")
        return self

    def asset_ids(self) -> set[str]:
        ids = {node.assetId for node in self.nodes if node.assetId}
        for run in self.runs:
            ids.update(run.referenceIds)
            if run.assetId:
                ids.add(run.assetId)
        return ids


class CreateCanvas(StrictModel):
    id: UUID
    title: str = Field(max_length=120)


class SaveCanvas(StrictModel):
    expected_version: int = Field(ge=0)
    document: Document
