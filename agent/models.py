from pydantic import BaseModel, Field, field_validator
from datetime import date
import re


class PostFrontmatter(BaseModel):
    title: str = Field(min_length=10, max_length=120)
    date: date
    slug: str
    description: str = Field(min_length=20, max_length=300)
    tags: list[str] = Field(min_length=1, max_length=4)
    draft: bool = False

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', v):
            raise ValueError("Slug must be lowercase kebab-case")
        return v

    @field_validator("draft")
    @classmethod
    def must_not_be_draft(cls, v: bool) -> bool:
        if v is True:
            raise ValueError("draft must be false for published posts")
        return v
