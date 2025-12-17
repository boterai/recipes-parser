import sys
from pathlib import Path
from typing import Protocol, Literal, Optional

from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

EmbeddingFunctionReturn = list[list[float]] # (dense_vector, colbert_vectors) при том, что colbert_vectors может быть None и тогда его надо опредлять
ContentType = Literal["full", "ingredients", "instructions", "descriptions", "description+name"]
MODEL = 'BAAI/bge-large-en-v1.5'


class EmbeddingFunction(Protocol):
    """
    Протокол для функций эмбеддинга.
    
    Args:
        texts: Текст или список текстов для эмбеддинга
        is_query: True если это поисковый запрос, False если документ
        use_colbert: True для получения ColBERT multi-vector эмбеддингов
    
    Returns:
        - dense_vectors: list[float] или list[list[float]] - основные векторы
    """
    def __call__(
        self, 
        texts: str | list[str], 
        is_query: bool = False, 
        use_colbert: bool = False
    ) -> EmbeddingFunctionReturn:
        ...

def get_embedding_function(model_name: str = MODEL, batch_size: int=8) -> tuple[EmbeddingFunction, int]:
    """
    Создает функцию эмбеддинга для указанной модели
    
    По умолчанию: BAAI/bge-large-en-v1.5
    - 1.34GB, 1024 dimensions
    - Лучшая опенсорс модель для английского языка
    - Специализирована на semantic search
    
    Другие варианты (от меньшей к большей):
    1. 'sentence-transformers/all-MiniLM-L6-v2' - 80MB, 384 dims, только EN
    2. 'BAAI/bge-small-en-v1.5' - 133MB, 384 dims, только EN
    3. 'BAAI/bge-base-en-v1.5' - 438MB, 768 dims, только EN
    4. 'BAAI/bge-large-en-v1.5' - 1.34GB, 1024 dims, только EN ✅ ЛУЧШАЯ ДЛЯ EN
    5. 'intfloat/multilingual-e5-large' - 2.2GB, 1024 dims, multilingual
    6. 'BAAI/bge-m3' - 2.2GB, 1024 dims, multilingual + ColBERT
    
    Что делать если модель автоматически не скачивается:
    Скачать вручную в путь ~/.cache/huggingface/hub/models--{org}--{model}/snapshots/{commit_id}/
    
    Например для BAAI/bge-large-en-v1.5:
    https://huggingface.co/BAAI/bge-large-en-v1.5
    
    Обязательные файлы:
    - model.safetensors или pytorch_model.bin
    - config.json
    - tokenizer.json
    - tokenizer_config.json
    - special_tokens_map.json
    - sentence_bert_config.json (опционально)
    - modules.json (опционально)
    """
    
    model = SentenceTransformer(model_name)
    
    # Определяем размерность модели
    embedding_dimension = model.get_sentence_embedding_dimension()
    
    def embedding_func(texts: str | list[str], is_query: bool = False) -> EmbeddingFunctionReturn:
        """
        Генерирует эмбеддинги для текстов
        
        Args:
            texts: Текст или список текстов
            is_query: True для поисковых запросов (добавляет префикс "Represent this sentence for searching relevant passages:")
            use_colbert: Игнорируется (bge-large-en-v1.5 не поддерживает ColBERT)
        
        Returns:
            Список dense векторов (ColBERT не поддерживается)
        """
        if isinstance(texts, str):
            texts = [texts]
        
        # BGE модели используют специальный префикс для query
        if is_query and model_name.startswith('BAAI/bge'):
            # Для BGE моделей рекомендуется добавлять инструкцию для query
            instruction = "Represent this sentence for searching relevant passages: "
            texts = [instruction + text for text in texts]
        
        dense_vecs = model.encode(
            texts,
            normalize_embeddings=True,  # Важно для косинусного сходства
            batch_size=batch_size,
            show_progress_bar=False
        ).tolist()
        
        return dense_vecs
    
    return embedding_func, embedding_dimension

if __name__ == "__main__":
    ef, dims = get_embedding_function()
    print(f"Эмбеддинги созданы. Размерность: {dims}")
    