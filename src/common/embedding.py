import sys
from pathlib import Path
from typing import Protocol, Literal, Optional, Callable, Union
from contextlib import nullcontext

from sentence_transformers import SentenceTransformer
import open_clip
from PIL.Image import Image as PILImage

import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

EmbeddingFunctionReturn = list[list[float]] # (dense_vector, colbert_vectors) при том, что colbert_vectors может быть None и тогда его надо опредлять
ContentType = Literal["full", "ingredients", "instructions", "descriptions", "description+name"]
MODEL = 'BAAI/bge-large-en-v1.5'

ImageInput = Union[str, Path, "PILImage"]
ImageEmbeddingFunctionReturn = list[list[float]]


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
        is_query: bool = False
    ) -> EmbeddingFunctionReturn:
        ...

class ImageEmbeddingFunction(Protocol):
    """
    Протокол для функций эмбеддинга изображений.
    
    Args:
        images: Путь к изображению или список путей к изображениям
    
    Returns:
        - dense_vectors: list[float] или list[list[float]] - основные векторы
    """
    def __call__(
        self, 
        images: ImageInput | list[ImageInput]
    ) -> ImageEmbeddingFunctionReturn:
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


def get_image_embedding_function(
    model_name: str = "ViT-L-14",
    pretrained: str = "laion2b_s32b_b82k",
    device: Optional[str] = "cuda",
    batch_size: int = 32,
) -> tuple[ImageEmbeddingFunction, int]:
    """Создает функцию эмбеддинга изображений через OpenCLIP.
    
    Популярные модели:
    - "ViT-B-32" (512 dims)
    - "ViT-L-14" (768 dims)

    Args:
        model_name: имя архитектуры OpenCLIP (например "ViT-B-32", "ViT-L-14")
        pretrained: набор весов (например "laion2b_s34b_b79k", "openai")
        device: "cuda" | "cpu" | None (None -> авто)
        batch_size: размер батча по изображениям

    Returns:
        (embedding_func, embedding_dimension)
    """
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name,
        pretrained=pretrained,
        device=device,
    )
    model.eval()

    try:
        embedding_dimension = int(getattr(model, "text_projection").shape[1])
    except Exception:
        with torch.no_grad():
            dummy = torch.zeros(1, 3, 224, 224, device=device)
            out = model.encode_image(dummy)
            embedding_dimension = int(out.shape[-1])

    def _load_image(img: ImageInput) -> "PILImage":
        if isinstance(img, Image.Image):
            return img
        path = Path(img)
        return Image.open(path).convert("RGB")

    def _encode_image_batch(image_tensors: "torch.Tensor") -> "torch.Tensor":
        autocast_ctx = (
            torch.autocast(device_type="cuda", dtype=torch.float16)
            if device.startswith("cuda")
            else nullcontext()
        )
        with autocast_ctx:
            return model.encode_image(image_tensors)

    def embedding_func(images: ImageInput | list[ImageInput]) -> ImageEmbeddingFunctionReturn:
        if isinstance(images, (str, Path)) or hasattr(images, "size"):
            images_list = [images]
        else:
            images_list = list(images)

        pil_images = [_load_image(im) for im in images_list]
        results: list[list[float]] = []

        with torch.no_grad():
            for start in range(0, len(pil_images), batch_size):
                batch = pil_images[start:start + batch_size]
                image_tensors = torch.stack([preprocess(im) for im in batch]).to(device)

                feats = _encode_image_batch(image_tensors)

                feats = feats / feats.norm(dim=-1, keepdim=True)
                results.extend(feats.detach().float().cpu().tolist())

        return results

    return embedding_func, embedding_dimension

if __name__ == "__main__":
    # Проверка доступных моделей и весов
    print("\n=== Веса для ViT-L-14 ===")
    print(open_clip.list_pretrained_tags_by_model("ViT-L-14"))
    
    ef, dims = get_image_embedding_function()
    print(f"Размерность: {dims}")
