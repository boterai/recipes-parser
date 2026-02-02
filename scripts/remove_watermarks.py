"""
Удаление водяных знаков с изображений через LaMa inpainting.
"""

import logging
import warnings
from pathlib import Path
from typing import Optional, Union
from io import BytesIO
import easyocr
import cv2
import numpy as np
from PIL import Image, ImageDraw
import requests
import asyncio
import sys
import base64
from simple_lama_inpainting import SimpleLama
import torch
from diffusers import StableDiffusionXLInpaintPipeline

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.gpt.client import GPTClient

logger = logging.getLogger(__name__)

MODEL_ID = "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"  # один из популярных SDXL-inpaint чекпойнтов


class WatermarkRemover:
    """Удаление водяных знаков через LaMa inpainting"""
    
    def __init__(self, device: str = "cuda", use_sdxl: bool = True, max_image_size: int = 1024):
        """
        Args:
            device: "cuda" или "cpu"
            use_sdxl: Использовать SDXL вместо LaMa (лучше качество, но требует больше памяти)
            max_image_size: Максимальный размер изображения (для экономии памяти)
        """
        self.device = device
        self.use_sdxl = use_sdxl
        self.max_image_size = max_image_size
        self._model = None
        self._sdxl_model = None

    def sdxl_inpaint(self, pil_image_rgb: Image.Image, pil_mask_l: Image.Image) -> Image.Image:
        # Уменьшаем разрешение если нужно (для экономии памяти)
        orig_size = pil_image_rgb.size
        if max(orig_size) > self.max_image_size:
            ratio = self.max_image_size / max(orig_size)
            new_size = (int(orig_size[0] * ratio), int(orig_size[1] * ratio))
            pil_image_rgb = pil_image_rgb.resize(new_size, Image.Resampling.LANCZOS)
            pil_mask_l = pil_mask_l.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"Resized {orig_size} -> {new_size} to save memory")
        
        prompt = "photo of food, high detail, no watermark, no logo"
        negative = "text, watermark, logo, letters, signature, blurry"
        
        # Очищаем кэш перед генерацией
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        out = self.sdxl_model(
            prompt=prompt,
            negative_prompt=negative,
            image=pil_image_rgb,
            mask_image=pil_mask_l,
            guidance_scale=6.5,
            num_inference_steps=20,  # Уменьшаем шаги для скорости
            strength=0.95,
        )
        
        result = out.images[0]
        
        # Возвращаем к оригинальному размеру если нужно
        if result.size != orig_size:
            result = result.resize(orig_size, Image.Resampling.LANCZOS)
        
        return result

    @property
    def sdxl_model(self):
        if self._sdxl_model is None:
            self._sdxl_model = StableDiffusionXLInpaintPipeline.from_pretrained(
                MODEL_ID,
                torch_dtype=torch.float16,
                variant="fp16",
            )
            
            # CPU offload для экономии памяти (модель загружается по частям)
            self._sdxl_model.enable_model_cpu_offload()
            
            # Memory-efficient attention (если установлен xformers)
            try:
                self._sdxl_model.enable_xformers_memory_efficient_attention()
                logger.info("xformers memory efficient attention enabled")
            except Exception:
                # xformers is optional - silently continue without it
                pass
            
            # VAE tiling для больших изображений (use new API)
            self._sdxl_model.vae.enable_tiling()
            
            logger.info("SDXL model loaded with memory optimizations")
        return self._sdxl_model
    
    @property
    def model(self):
        """Ленивая загрузка модели"""
        if self._model is None:
            self._model = SimpleLama(device=self.device)
            logger.info(f"LaMa model loaded on {self.device}")
        return self._model
    
    def load_image(self, source: Union[str, Path, Image.Image]) -> Image.Image:
        """Загружает изображение из URL, пути или PIL Image"""
        if isinstance(source, Image.Image):
            return source.convert("RGB")
        
        if isinstance(source, (str, Path)):
            source_str = str(source)
            if source_str.startswith(("http://", "https://")):
                response = requests.get(source_str, timeout=30)
                response.raise_for_status()
                return Image.open(BytesIO(response.content)).convert("RGB")
            else:
                return Image.open(source).convert("RGB")
        
        raise ValueError(f"Unsupported source type: {type(source)}")
    
    def detect_watermark_by_contrast(
        self,
        image: Image.Image,
        threshold: int = 240,
        min_area: int = 100
    ) -> Optional[Image.Image]:
        """
        Детектирует полупрозрачные водяные знаки через анализ контраста.
        
        Работает для светлых/белых водяных знаков на тёмном фоне.
        
        Args:
            image: PIL Image
            threshold: Порог яркости (пиксели выше этого = потенциальный водяной знак)
            min_area: Минимальная площадь области
        
        Returns:
            Маска или None
        """
        # Конвертируем в grayscale
        img_np = np.array(image)
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Ищем очень светлые области (потенциальные водяные знаки)
        _, bright_mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        
        # Морфологические операции для очистки
        kernel = np.ones((5, 5), np.uint8)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel)
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel)
        
        # Расширяем маску для лучшего покрытия
        bright_mask = cv2.dilate(bright_mask, kernel, iterations=2)
        
        # Проверяем, есть ли значимые области
        if np.sum(bright_mask > 0) < min_area:
            return None
        
        return Image.fromarray(bright_mask)
    
    def detect_watermark_by_text(
        self,
        image: Image.Image,
        expand_pixels: int = 10
    ) -> Optional[Image.Image]:
        """
        Детектирует текстовые водяные знаки через OCR (easyocr).
                
        Returns:
            Маска с обнаруженными текстовыми областями или None
        """
        
        reader = easyocr.Reader(['en'], gpu=self.device == "cuda")
        
        # Конвертируем в numpy
        img_np = np.array(image)
        
        # Детектируем текст
        results = reader.readtext(img_np)
        
        if not results:
            return None
        
        # Создаём маску
        w, h = image.size
        mask = Image.new("L", (w, h), 0)
        
        draw = ImageDraw.Draw(mask)
        
        for (bbox, _, confidence) in results:
            if confidence > 0.6:  # Фильтруем слабые детекции
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                x1, y1 = max(0, min(xs) - expand_pixels), max(0, min(ys) - expand_pixels)
                x2, y2 = min(w, max(xs) + expand_pixels), min(h, max(ys) + expand_pixels)
                draw.rectangle([x1, y1, x2, y2], fill=255)
        
        return mask
    
    async def detect_watermark_by_gpt(
        self,
        image: Image.Image,
        expand_pixels: int = 15
    ) -> Optional[Image.Image]:
        """
        Детектирует водяные знаки через GPT-4 Vision.
        
        GPT анализирует изображение и возвращает координаты водяных знаков.
        
        Args:
            image: PIL Image
            expand_pixels: Расширение области вокруг найденных водяных знаков
        
        Returns:
            Маска с обнаруженными водяными знаками или None
        """
        gpt_client = GPTClient()
        
        # Конвертируем изображение в base64
        buffered = BytesIO()
        image.save(buffered, format="JPEG", quality=85)
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{img_base64}"
        
        w, h = image.size
        
        system_prompt = """You are a watermark detection expert. Analyze the image and find ALL watermarks, logos, text overlays, or site URLs.

For each watermark found, return its bounding box as percentage of image dimensions (0-100).

Return JSON:
{
  "watermarks": [
    {
      "type": "text|logo|pattern|url",
      "description": "what the watermark shows",
      "bbox": {
        "x1_percent": 75,
        "y1_percent": 85,
        "x2_percent": 100,
        "y2_percent": 100
      },
      "confidence": 0.9
    }
  ],
  "has_watermark": true
}

If NO watermarks found, return:
{"watermarks": [], "has_watermark": false}

Common watermark locations:
- Bottom right corner (site URL, photographer name)
- Bottom center (copyright text)
- Center (stock photo watermarks like Shutterstock, Getty)
- Diagonal across image (repeating pattern)
- Top corners (logos)"""

        user_prompt = f"""Analyze this image ({w}x{h} pixels) and find ALL watermarks, logos, text overlays, or website URLs.

Be thorough - check corners, edges, center, and any semi-transparent overlays."""

        try:
            result = await gpt_client.async_request_with_images(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_urls=[image_url],
                temperature=0.1,
                max_tokens=500
            )
            
            if not result.get('has_watermark', False):
                logger.info("GPT detected no watermarks")
                return None
            
            watermarks = result.get('watermarks', [])
            if not watermarks:
                return None
            
            # Создаём маску
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            
            for wm in watermarks:
                bbox = wm.get('bbox', {})
                conf = wm.get('confidence', 0)
                
                if conf < 0.5:
                    continue
                
                # Конвертируем проценты в пиксели
                x1 = int(bbox.get('x1_percent', 0) / 100 * w) - expand_pixels
                y1 = int(bbox.get('y1_percent', 0) / 100 * h) - expand_pixels
                x2 = int(bbox.get('x2_percent', 100) / 100 * w) + expand_pixels
                y2 = int(bbox.get('y2_percent', 100) / 100 * h) + expand_pixels
                
                # Ограничиваем координаты
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                draw.rectangle([x1, y1, x2, y2], fill=255)
                logger.info(f"GPT detected watermark: {wm.get('type', 'unknown')} - {wm.get('description', 'N/A')} "
                           f"at [{x1}, {y1}, {x2}, {y2}] (conf={conf:.2f})")
            
            return mask
            
        except Exception as e:
            logger.error(f"GPT watermark detection failed: {e}")
            return None
    
    def remove_watermark(
        self,
        image: Union[str, Path, Image.Image],
        mask: Optional[Image.Image] = None,
        use_text_detection: bool = False,
        use_contrast_detection: bool = False,
        use_gpt_detection: bool = False,
        combine_masks: bool = True,
    ) -> Image.Image:
        """
        Удаляет водяной знак с изображения.
        
        Args:
            image: Изображение (URL, путь или PIL Image)
            mask: Готовая маска (белый = область для удаления)
            use_text_detection: Использовать OCR для детекции текста
            use_contrast_detection: Использовать анализ контраста
            use_gpt_detection: Использовать GPT Vision для детекции (наиболее точный)
            combine_masks: Объединять маски из разных методов
        
        Returns:
            Очищенное изображение
        """
        pil_image = self.load_image(image)
        
        masks_to_combine = []
        
        # Создаём или используем маску
        if mask is not None:
            masks_to_combine.append(mask)
        else:
            # GPT Vision детекция
            if use_gpt_detection:
                gpt_mask = asyncio.run(self.detect_watermark_by_gpt(pil_image))
                if gpt_mask is not None:
                    masks_to_combine.append(gpt_mask)
                    logger.info("Watermark detected via GPT Vision")
            
            # Текстовая детекция
            if use_text_detection:
                text_mask = self.detect_watermark_by_text(pil_image)
                if text_mask is not None:
                    masks_to_combine.append(text_mask)
                    logger.info("Text watermark detected via OCR")
            
            # Контрастная детекция
            if use_contrast_detection:
                contrast_mask = self.detect_watermark_by_contrast(pil_image)
                if contrast_mask is not None:
                    masks_to_combine.append(contrast_mask)
                    logger.info("Watermark detected via contrast analysis")
        
        # Объединяем маски
        if combine_masks and len(masks_to_combine) > 1:
            w, h = pil_image.size
            
            # Объединение (OR) - все области любой из масок
            combined = Image.new("L", (w, h), 0)  # Начинаем с черного
            for m in masks_to_combine:
                if m.size != (w, h):
                    m = m.resize((w, h))
                combined = Image.fromarray(np.maximum(np.array(combined), np.array(m)))
            logger.info(f"Combined {len(masks_to_combine)} masks using UNION")
            
            mask = combined
        else:
            mask = masks_to_combine[0] if masks_to_combine else self.detect_watermark_region(pil_image, position=position)
        
        # Проверяем, есть ли что inpaint'ить
        mask_np = np.array(mask)
        if mask_np.max() == 0:
            logger.info("No watermark region detected, returning original")
            return pil_image
        
        # Inpainting через SDXL или LaMa
        if self.use_sdxl:
            # Используем SDXL (лучше качество, но требует GPU)
            result = self.sdxl_inpaint(pil_image, mask)
            logger.info(f"Watermark removed using SDXL from image {pil_image.size}")
        else:
            # Используем LaMa (быстрее, меньше памяти)
            result = self.model(pil_image, mask)
            logger.info(f"Watermark removed using LaMa from image {pil_image.size}")
        
        # Очищаем кэш после обработки
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        return result
    
    def save_debug_mask(
        self,
        image: Union[str, Path, Image.Image],
        output_path: str = "debug_mask.png",
        use_text_detection: bool = False,
        use_contrast_detection: bool = False
    ):
        """
        Сохраняет маску для отладки (чтобы увидеть какие области будут обработаны).
        """
        pil_image = self.load_image(image)
        
        masks = []
        
        if use_text_detection:
            text_mask = self.detect_watermark_by_text(pil_image)
            if text_mask:
                masks.append(("text", text_mask))
        
        if use_contrast_detection:
            contrast_mask = self.detect_watermark_by_contrast(pil_image)
            if contrast_mask:
                masks.append(("contrast", contrast_mask))
        
        # Сохраняем комбинированную маску
        w, h = pil_image.size
        combined = Image.new("L", (w, h), 0)
        for name, m in masks:
            if m.size != (w, h):
                m = m.resize((w, h))
            combined = Image.fromarray( np.maximum(np.array(combined), np.array(m)))
            logger.info(f"Mask '{name}' added")
        
        combined.save(output_path)
        logger.info(f"Debug mask saved to {output_path}")


_remover: Optional[WatermarkRemover] = None

def get_watermark_remover(device: str = "cuda", use_sdxl: bool = True, max_image_size: int = 1024) -> WatermarkRemover:
    global _remover
    if _remover is None:
        _remover = WatermarkRemover(device=device, use_sdxl=use_sdxl, max_image_size=max_image_size)
    return _remover

if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    
    # Включаем управление фрагментацией памяти CUDA
    os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
    
    # Используем LaMa (экономит память) или SDXL (иногда чуть лучше качество, не касается сайта поваренок ид 5)
    remover = get_watermark_remover(
        device="cuda",
        use_sdxl=False,
        max_image_size=1024
    )
    
    image_path = "images/ffdfe31a43f8568c.jpg"
    
    # метод для сохранения маски для отладки
    remover.save_debug_mask(
        image_path,
        output_path="wm_img/debug_mask.png",
        use_text_detection=True,
        use_contrast_detection=True
    )
    logger.info("Check debug_mask.png to see which areas will be processed")

    # Вариант 1: Union (объединение всех масок) - удалит все что найдено любым методом
    cleaned_image = remover.remove_watermark(
        image_path,
        use_gpt_detection=False,
        use_text_detection=True,
        use_contrast_detection=True,
        combine_masks=True
    )
    cleaned_image.save("wm_img/cleaned.jpg", quality=100)
    
    """# Вариант 2: Только GPT детекция
    cleaned_image = remover.remove_watermark(
        image_path,
        use_gpt_detection=True,  # GPT Vision определит где водяной знак
        use_text_detection=False,
        use_contrast_detection=False,
        combine_masks=False
    )
    cleaned_image.save("cleaned_gpt_classic.jpg", quality=100)
    logger.info("Cleaned image (GPT) saved to cleaned_gpt.jpg")"""