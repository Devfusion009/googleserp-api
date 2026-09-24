"""Pydantic models matching the client's exact request/response schema."""
from pydantic import BaseModel, Field


class SerpRequest(BaseModel):
    url: str
    results: int = 10
    country: str = "US"
    language: str = "en"
    return_json: bool = True


class SubLink(BaseModel):
    title: str
    url: str | None = None


class OrganicItem(BaseModel):
    url: str | None = None
    title: str
    content: str | None = None
    sub_links: list[SubLink] = Field(default_factory=list)


class AioSection(BaseModel):
    title: str
    text: str


class AioSource(BaseModel):
    title: str | None = None
    url: str
    snippet: str | None = None


class AiOverview(BaseModel):
    intro: list[str] = Field(default_factory=list)
    sections: list[AioSection] = Field(default_factory=list)
    sources: list[AioSource] = Field(default_factory=list)


class KnowledgePanel(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None
    source_url: str | None = None
    facts: dict[str, str] = Field(default_factory=dict)


class PageResult(BaseModel):
    page: int
    paid: list[OrganicItem] = Field(default_factory=list)
    organic: list[OrganicItem] = Field(default_factory=list)
    ai_overview: AiOverview | None = None
    knowledge_panel: KnowledgePanel | None = None
    number_of_results: int | None = None
    suggestions: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)


class SerpResponse(BaseModel):
    status_code: int
    requests_used: int = 0
    elapsed_time: int = 0
    results: list[PageResult] = Field(default_factory=list)
    error: str | None = None
    error_message: str | None = None
