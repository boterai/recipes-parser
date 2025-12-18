from pydantic import BaseModel

class SearchQuery(BaseModel):
    """Модель поискового запроса для рецептов"""
    id: int
    query: str
    language: str
    url_count: int = 0
    recipe_url_count: int = 0
