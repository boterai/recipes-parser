import sys
from pathlib import Path
from typing import Protocol, Literal, Optional

import numpy as np
from FlagEmbedding import BGEM3FlagModel
from sentence_transformers import SentenceTransformer
from qdrant_client.models import Document

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.models.page import Page


EmbeddingFunctionReturn = tuple[list[float] | list[list[float]], Optional[list[list[float]]]] # (dense_vector, colbert_vectors) при том, что colbert_vectors может быть None и тогда его надо опредлять
ContentType = Literal["full", "ingredients", "instructions", "descriptions", "description+name"]

class EmbeddingFunction(Protocol):
    """
    Протокол для функций эмбеддинга.
    
    Args:
        texts: Текст или список текстов для эмбеддинга
        is_query: True если это поисковый запрос, False если документ
        use_colbert: True для получения ColBERT multi-vector эмбеддингов
    
    Returns:
        tuple: (dense_vectors, colbert_vectors)
            - dense_vectors: list[float] или list[list[float]] - основные векторы
            - colbert_vectors: Optional[list[list[float]]] - ColBERT векторы (None если use_colbert=False)
    """
    def __call__(
        self, 
        texts: str | list[str], 
        is_query: bool = False, 
        use_colbert: bool = False
    ) -> EmbeddingFunctionReturn:
        ...

def get_content_types() -> list[str]:
    """
    get_content_types возвращает список доступных типов эмбеддингов
    """
    return [
        "full",
        "ingredients",
        "instructions",
        "descriptions",
        "description+name"
    ]


def prepare_text(page: Page, content_type: ContentType = "full") -> str:
    """
    prepare_text prepares the text for embedding based on the specified embedding type.
    Args:
        page: The Page object containing recipe data.
        embedding_type: The type of embedding to prepare.
    """
    match content_type:
        case "ingredients":
            return page.ingredient_to_str()
        
        case "instructions":
            return page.step_by_step or ""
        
        case "descriptions":
            parts = []
            if page.dish_name:
                parts.append(page.dish_name)
            if page.description:
                parts.append(page.description[:150])
            if page.tags:
                parts.append(page.tags[:100])
            return " ".join(parts)
        
        case "description+name":
            parts = []
            if page.dish_name:
                parts.append(page.dish_name)
            if page.description:
                parts.append(page.description[:200])
            if page.ingredient:
                parts.append(page.ingredient_to_str())
            if page.tags:
                parts.append(page.tags[:100])
            return " ".join(parts)
    
    # full - БЕЗ префиксов, tags в конце
    parts = []
    if page.dish_name:
        parts.append(page.dish_name)
    if page.description:
        parts.append(page.description[:300])
    if page.ingredient:
        parts.append(page.ingredient_to_str())
    if page.step_by_step:
        parts.append(page.step_by_step[:500])
    if page.tags:
        parts.append(page.tags[:150])
    
    return " ".join(parts)


def normalize_vector(vec: list[float]) -> list[float]:
    """
    normalize_vector нормализует вектор до единичной длины.
    Args:
        vec: Входной вектор.
    Returns:
        Нормализованный вектор.
    """
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    normalized = (np.array(vec) / norm).tolist()
    return normalized

def normalize_colbert_vectors(colbert_vecs: list[list[float]]) -> list[list[float]]:
    """
    normalize_colbert_vectors нормализует каждый вектор в последовательности ColBERT до единичной длины.
    Args:
        colbert_vecs: Список векторов ColBERT.
    Returns:
        Список нормализованных векторов ColBERT.
    """
    normalized_vecs = []
    for vec in colbert_vecs:
        norm = np.linalg.norm(vec)
        if norm == 0:
            normalized_vecs.append(vec)
        else:
            normalized_vecs.append((np.array(vec) / norm).tolist())
    return normalized_vecs

def get_embedding_function_multilingual(model_name: str = 'intfloat/multilingual-e5-large') -> tuple[EmbeddingFunction, int]:
    # Варианты моделей (от меньшей к большей):
    # 1. 'sentence-transformers/all-MiniLM-L6-v2' - 80MB, 384 dimensions, только английский
    # 2. 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2' - 470MB, 384 dimensions, multilingual
    # 3. 'intfloat/multilingual-e5-small' - 470MB, 384 dimensions
    # 4. 'intfloat/multilingual-e5-base' - 1.1GB, 768 dimensions
    # 5. 'intfloat/multilingual-e5-large' - 2.2GB, 1024 dimensions (текущая)
    # 6. 'BAAI/bge-m3' - только для dense для ColBERT используй get_embedding_function_bge_m3
    
    """
    ! Похоже эта модель работает лучше для многоязычных рецептов !
    Что делать если модель автоматически не скачивается скачать в путь ~/.cache/huggingface/hub/model_name/snapshots/commit_id/
    Например для intfloat/multilingual-e5-large можно скачать здесь: https://huggingface.co/intfloat/multilingual-e5-large

    Обязательные файлы для скачивания:
    - model.safetensors
    - config.json
    - tokenizer.json
    - tokenizer_config.json
    - special_tokens_map.json
    - sentence_bert_config.json
    - modules.json
    """
    
    model = SentenceTransformer(model_name)
    colbert_model = BGEM3FlagModel('BAAI/bge-m3')
    
    def embedding_func(texts: str, is_query: bool = False, use_colbert: bool = False) -> EmbeddingFunctionReturn:
        if isinstance(texts, str):
            texts = [texts]
        prefix = "query: " if is_query else "passage: "
        texts = [prefix + text for text in texts]
        dense_vecs = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=8
        ).tolist()

        colbert_vecs = None
        if use_colbert:
            encoded_data = colbert_model.encode(
                texts,
                batch_size=8,
                max_length=8192,
                return_dense=False,
                return_sparse=False,
                return_colbert_vecs=True,
            )
            colbert_vecs = encoded_data['colbert_vecs']
            
        return dense_vecs, colbert_vecs
    
    return embedding_func, 1024  # Размерность для small модели

def get_embedding_function_bge_m3() -> tuple[EmbeddingFunction, int]:
    """
    get_embedding_function_bge_m3 возвращает функцию эмбеддинга на основе модели BGE-M3 от BAAI.
    Модель поддерживает создание как dense векторов, так и ColBERT multi-vector эмбеддингов.
    """
    model = BGEM3FlagModel('BAAI/bge-m3')
    
    def embedding_func(texts: str|list[str], is_query: bool = False, use_colbert: bool = False) -> EmbeddingFunctionReturn:
        if isinstance(texts, str):
            texts = [texts]
        
        encoded_data = model.encode(
            texts,
            batch_size=8,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=use_colbert,
        )
        dense_vecs = encoded_data['dense_vecs']
        colbert_vecs = encoded_data.get('colbert_vecs', None)
        
        # Нормализация dense
        dense_norms = np.linalg.norm(dense_vecs, axis=1, keepdims=True)
        dense_normalized = dense_vecs / dense_norms

        if not use_colbert or colbert_vecs is None:
            return dense_normalized.tolist(), None
        
        # Нормализация ColBERT (каждого вектора в последовательности)
        colbert_normalized = []
        for colbert_seq in colbert_vecs:
            norms = np.linalg.norm(colbert_seq, axis=1, keepdims=True)
            colbert_normalized.append(colbert_seq / norms)
        
        return dense_normalized.tolist(), [c.tolist() for c in colbert_normalized]

    return embedding_func, 1024  # Размерность для bge-m3

if __name__ == "__main__":
    # предварительно перед передачец текст надо разбить на части по 8192 токенов, можно пока попробовать не нормализоавывать даныне и оставить так \
    # и лучше не разбивать, а передавать целиком, тк нужно сходвтсво именно цельного рецепта
    ef, _ = get_embedding_function_multilingual()
    emb, colbert = ef("Тесто для блинов: 2 яйца, 500 мл молока, 250 г муки, щепотка соли, 1 ст.л. сахара, 2 ст.л. растительного масла.",
                      is_query=False, use_colbert=True)
    model = BGEM3FlagModel('BAAI/bge-m3')
    text = "Тесто для блинов: 2 яйца, 500 мл молока, 250 г муки, щепотка соли, 1 ст.л. сахара, 2 ст.л. растительного масла."
    encoded_data = model.encode(
            [text],
            batch_size=12,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=True,
        )
    
    print(f"Dense embedding length: {len(encoded_data['dense_vecs'][0])}")
    print(f"Colbert embedding length: {len(encoded_data['colbert_vecs'][0])}")
    