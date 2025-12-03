
from sentence_transformers import SentenceTransformer
from src.models.page import Page
from typing import Callable

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
            return page.ingredients_names or page.ingredients or ""
        
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
        if page.ingredients_names:
            parts.append(f"Ingredients: {page.ingredients_names}")
        elif page.ingredients:
            parts.append(f"Ingredients: {page.ingredients[:300]}")
        if page.step_by_step:
            parts.append(f"Instructions: {page.step_by_step[:100]}")
        if page.notes:
            parts.append(page.notes[:100])
        return ". ".join(parts)

def get_embedding_function(model_name: str = 'paraphrase-multilingual-MiniLM-L12-v2') -> tuple[EmbeddingFunction, int]:
    """
    Получение функции для создания эмбеддингов
    Примеры моделей:
    - 'all-MiniLM-L6-v2' (384 dim)
    - 'all-mpnet-base-v2' (768 dim)
    - 'paraphrase-multilingual-MiniLM-L12-v2' (384 dim)
    
    Returns:
        tuple: (embedding_function, embedding_dim)
    """

    
    model = SentenceTransformer(model_name)
    
    # Автоматически определяем размерность
    embedding_dim = model.get_sentence_embedding_dimension()
    print(f"  Модель: {model._model_card_vars.get('model_name', model_name)}")
    print(f"  Размерность векторов: {embedding_dim}")
    
    embedding_func:  EmbeddingFunction = lambda text: model.encode(text, convert_to_tensor=False).tolist()
    
    return embedding_func, embedding_dim


