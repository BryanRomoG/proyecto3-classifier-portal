"""Pydantic v2 models and invariants for the supported COCO dataset subset."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, PositiveInt, RootModel, field_validator, model_validator


class BoundingBox(RootModel[tuple[float, float, float, float]]):
    """COCO bounding box represented as ``[x, y, width, height]``."""

    @model_validator(mode="after")
    def validate_geometry(self) -> BoundingBox:
        x, y, width, height = self.root

        if x < 0 or y < 0:
            raise ValueError("bbox x and y coordinates must be non-negative")
        if width <= 0 or height <= 0:
            raise ValueError("bbox width and height must be greater than zero")

        return self


class CocoImage(BaseModel):
    """An image entry from a COCO annotations file."""

    model_config = ConfigDict(extra="allow")

    id: PositiveInt
    file_name: str
    width: PositiveInt
    height: PositiveInt

    @field_validator("file_name")
    @classmethod
    def file_name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("file_name must not be blank")
        return value


class CocoCategory(BaseModel):
    """A labeled object category from a COCO annotations file."""

    model_config = ConfigDict(extra="allow")

    id: PositiveInt
    name: str

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class CocoAnnotation(BaseModel):
    """An object annotation that references one image and one category."""

    model_config = ConfigDict(extra="allow")

    id: PositiveInt
    image_id: PositiveInt
    category_id: PositiveInt
    bbox: BoundingBox


class CocoDataset(BaseModel):
    """COCO entities plus cross-reference validation between their identifiers."""

    model_config = ConfigDict(extra="allow")

    images: list[CocoImage]
    annotations: list[CocoAnnotation]
    categories: list[CocoCategory]

    @model_validator(mode="after")
    def validate_identifiers_and_references(self) -> CocoDataset:
        image_ids = [image.id for image in self.images]
        category_ids = [category.id for category in self.categories]

        self._require_unique_ids(image_ids, "images")
        self._require_unique_ids(category_ids, "categories")
        self._require_unique_ids([annotation.id for annotation in self.annotations], "annotations")

        known_image_ids = set(image_ids)
        known_category_ids = set(category_ids)

        for annotation in self.annotations:
            if annotation.image_id not in known_image_ids:
                raise ValueError(
                    f"annotation id={annotation.id} references unknown "
                    f"image_id={annotation.image_id}"
                )
            if annotation.category_id not in known_category_ids:
                raise ValueError(
                    f"annotation id={annotation.id} references unknown "
                    f"category_id={annotation.category_id}"
                )

        return self

    @staticmethod
    def _require_unique_ids(ids: list[int], entity_name: str) -> None:
        if len(ids) != len(set(ids)):
            raise ValueError(f"{entity_name} contains duplicate id values")
