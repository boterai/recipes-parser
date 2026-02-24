"""
Data models
"""

from .site import Site
from .page import Page
from .recipe import Recipe
from .merged_recipe import merged_recipe_images  # Импортируем промежуточную таблицу для регистрации в metadata

__all__ = ['Site', 'Page', "Recipe", 'merged_recipe_images']
