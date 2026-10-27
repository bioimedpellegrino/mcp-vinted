from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhotoFile(StrictModel):
    download_url: str
    file_id: str
    mime_type: str = ""
    file_name: str = ""


class Listing(StrictModel):
    title: str = Field(min_length=5, max_length=100)
    description: str = Field(min_length=5, max_length=2000)
    price: Decimal = Field(gt=0, le=10000, decimal_places=2)
    currency: str = Field(default="EUR", pattern="^EUR$")
    catalog_id: int = Field(gt=0)
    brand_id: int = Field(gt=0)
    brand: str = Field(min_length=1, max_length=100)
    status_id: int = Field(gt=0)
    size_id: int | None = Field(default=None, gt=0)
    package_size_id: int = Field(gt=0)
    color_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=2)
    photo_ids: list[str] = Field(min_length=1, max_length=20)
    # Human labels are reviewed along with the API IDs. Never guess category IDs.
    category_label: str = Field(min_length=1, max_length=200)
    condition_label: str = Field(min_length=1, max_length=100)
    size_label: str = Field(min_length=1, max_length=100)
    package_label: str = Field(min_length=1, max_length=100)
