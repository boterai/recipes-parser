
from sentence_transformers import SentenceTransformer
from src.models.page import Page
from typing import Callable
import json

EmbeddingFunction = Callable[[str], list[float]]


def prepare_text(page: Page, embedding_type: str = "main") -> str:
        """
        Подготовка текста для эмбеддинга в зависимости от типа коллекции
        
        Args:
            page: Объект страницы с рецептом
            collection_type: Тип коллекции (main, ingredients, instructions, descriptions)
            
        Returns:
            Подготовленный текст
        """
        if embedding_type == "ingredients":
            return page.ingredient_to_str()
        
        if embedding_type == "instructions":
            return page.step_by_step or ""
        
        if embedding_type == "descriptions":
            parts = []
            if page.dish_name:
                parts.append(page.dish_name)
            if page.description:
                parts.append(page.description)
            return ". ".join(parts)
        
        parts = []
        if page.dish_name:
            parts.append(page.dish_name)
        if page.description:
            parts.append(page.description)
        if page.ingredient:
            parts.append(f"Ingredients: {page.ingredient_to_str()}")
        if page.step_by_step:
            parts.append(f"Instructions: {page.step_by_step[:100]}")
        if page.notes:
            parts.append(page.notes[:100])
        return ". ".join(parts)

def get_embedding_function():
    # Варианты моделей (от меньшей к большей):
    # 1. 'sentence-transformers/all-MiniLM-L6-v2' - 80MB, 384 dimensions, только английский
    # 2. 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2' - 470MB, 384 dimensions, multilingual
    # 3. 'intfloat/multilingual-e5-small' - 470MB, 384 dimensions
    # 4. 'intfloat/multilingual-e5-base' - 1.1GB, 768 dimensions
    # 5. 'intfloat/multilingual-e5-large' - 2.2GB, 1024 dimensions (текущая)
    
    model = SentenceTransformer('intfloat/multilingual-e5-small')  # Меняем на small
    
    def embedding_func(text: str, is_query: bool = False):
        prefix = "query: " if is_query else "passage: "
        return model.encode(
            prefix + text,
            normalize_embeddings=True
        ).tolist()
    
    return embedding_func, 384  # Размерность для small модели
