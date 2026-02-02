"""
Удаление водяных знаков с изображений через LaMa inpainting.

Установка:
    pip install simple-lama-inpainting
    # или для GPU: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
"""

import logging
from pathlib import Path
from typing import Optional, Union
from io import BytesIO
import easyocr
import cv2
import numpy as np
from PIL import Image, ImageDraw
import requests
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from simple_lama_inpainting import SimpleLama
logger = logging.getLogger(__name__)


class WatermarkRemover:
    """Удаление водяных знаков через LaMa inpainting"""
    
    def __init__(self, device: str = "cuda"):
        """
        Args:
            device: "cuda" или "cpu"
        """
        self.device = device
        self._model = None
    
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
    
    def detect_watermark_region(
        self,
        image: Image.Image,
        position: str = "auto",
        margin_ratio: float = 0.15
    ) -> Image.Image:
        """
        Создаёт маску для типичных позиций водяных знаков.
        
        Args:
            image: PIL Image
            position: "auto", "bottom-right", "bottom-left", "bottom", "center", 
                      "corners", "diagonal", "full-center", "top", "all", "none"
            margin_ratio: размер области (доля от размера изображения)
        
        Returns:
            Маска (белый = область для inpainting)
        """
        w, h = image.size
        mask = Image.new("L", (w, h), 0)  # Чёрная маска
        
        if position == "none":
            return mask  # Пустая маска
        
        margin_w = int(w * margin_ratio)
        margin_h = int(h * margin_ratio)
        
        draw = ImageDraw.Draw(mask)
        
        if position == "bottom-right" or position == "auto":
            # Правый нижний угол — самое частое место
            draw.rectangle([w - margin_w * 2, h - margin_h, w, h], fill=255)
        
        if position == "bottom-left" or position == "auto":
            draw.rectangle([0, h - margin_h, margin_w * 2, h], fill=255)
        
        if position == "bottom" or position == "auto":
            # Нижняя полоса по центру
            draw.rectangle([margin_w, h - margin_h, w - margin_w, h], fill=255)
        
        if position == "top":
            # Верхняя полоса
            draw.rectangle([0, 0, w, margin_h], fill=255)
        
        if position == "center":
            # Центральный водяной знак (небольшой)
            cx, cy = w // 2, h // 2
            draw.rectangle([
                cx - margin_w, cy - margin_h // 2,
                cx + margin_w, cy + margin_h // 2
            ], fill=255)
        
        if position == "full-center":
            # Большой центральный водяной знак (как у стоков)
            cx, cy = w // 2, h // 2
            draw.rectangle([
                cx - int(w * 0.3), cy - int(h * 0.15),
                cx + int(w * 0.3), cy + int(h * 0.15)
            ], fill=255)
        
        if position == "diagonal":
            # Диагональный водяной знак (как у Shutterstock, Getty)
            # Рисуем полосу по диагонали
            thickness = int(min(w, h) * 0.12)
            for i in range(-thickness, thickness):
                draw.line([(0, i), (w, h + i)], fill=255, width=3)
        
        if position == "corners":
            # Все углы
            draw.rectangle([0, 0, margin_w, margin_h], fill=255)
            draw.rectangle([w - margin_w, 0, w, margin_h], fill=255)
            draw.rectangle([0, h - margin_h, margin_w, h], fill=255)
            draw.rectangle([w - margin_w, h - margin_h, w, h], fill=255)
        
        if position == "all":
            # Все типичные места сразу (агрессивный режим)
            # Нижняя полоса
            draw.rectangle([0, h - margin_h, w, h], fill=255)
            # Верхняя полоса
            draw.rectangle([0, 0, w, int(margin_h * 0.7)], fill=255)
            # Центр
            cx, cy = w // 2, h // 2
            draw.rectangle([
                cx - int(w * 0.25), cy - int(h * 0.1),
                cx + int(w * 0.25), cy + int(h * 0.1)
            ], fill=255)
            # Углы
            draw.rectangle([0, 0, margin_w, margin_h], fill=255)
            draw.rectangle([w - margin_w, 0, w, margin_h], fill=255)
        
        return mask
    
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
        from PIL import ImageDraw
        draw = ImageDraw.Draw(mask)
        
        for (bbox, text, confidence) in results:
            if confidence > 0.5:  # Фильтруем слабые детекции
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
        from src.common.gpt.client import GPTClient
        import base64
        from io import BytesIO
        
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
            from PIL import ImageDraw
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
    
    def detect_watermark_by_gpt_sync(
        self,
        image: Image.Image,
        expand_pixels: int = 15
    ) -> Optional[Image.Image]:
        """
        Синхронная обёртка для detect_watermark_by_gpt.
        """
        import asyncio
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если уже в async контексте
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.detect_watermark_by_gpt(image, expand_pixels)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.detect_watermark_by_gpt(image, expand_pixels)
                )
        except RuntimeError:
            return asyncio.run(self.detect_watermark_by_gpt(image, expand_pixels))
    
    def remove_watermark(
        self,
        image: Union[str, Path, Image.Image],
        mask: Optional[Image.Image] = None,
        position: str = "auto",
        use_text_detection: bool = False,
        use_contrast_detection: bool = False,
        use_gpt_detection: bool = False,
        combine_masks: bool = True
    ) -> Image.Image:
        """
        Удаляет водяной знак с изображения.
        
        Args:
            image: Изображение (URL, путь или PIL Image)
            mask: Готовая маска (белый = область для удаления)
            position: Позиция водяного знака: "auto", "bottom", "center", 
                      "full-center", "diagonal", "corners", "all", "top"
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
            # GPT Vision детекция (самая точная, но платная)
            if use_gpt_detection:
                gpt_mask = self.detect_watermark_by_gpt_sync(pil_image)
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
            
            # Позиционная маска (если ничего не нашли или как дополнение)
            if not masks_to_combine or position != "none":
                position_mask = self.detect_watermark_region(pil_image, position=position)
                masks_to_combine.append(position_mask)
        
        # Объединяем маски
        if combine_masks and len(masks_to_combine) > 1:
            w, h = pil_image.size
            combined = Image.new("L", (w, h), 0)
            for m in masks_to_combine:
                # Убеждаемся что размеры совпадают
                if m.size != (w, h):
                    m = m.resize((w, h))
                combined = Image.fromarray(np.maximum(np.array(combined), np.array(m)))
            mask = combined
        else:
            mask = masks_to_combine[0] if masks_to_combine else self.detect_watermark_region(pil_image, position=position)
        
        # Проверяем, есть ли что inpaint'ить
        mask_np = np.array(mask)
        if mask_np.max() == 0:
            logger.info("No watermark region detected, returning original")
            return pil_image
        
        # Inpainting через LaMa
        result = self.model(pil_image, mask)
        
        logger.info(f"Watermark removed from image {pil_image.size}")
        return result
    
    def save_debug_mask(
        self,
        image: Union[str, Path, Image.Image],
        output_path: str = "debug_mask.png",
        position: str = "auto",
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
        
        position_mask = self.detect_watermark_region(pil_image, position=position)
        masks.append(("position", position_mask))
        
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

def get_watermark_remover(device: str = "cuda") -> WatermarkRemover:
    global _remover
    if _remover is None:
        _remover = WatermarkRemover(device=device)
    return _remover

def remove_watermark(
    image: Union[str, Path, Image.Image],
    mask: Optional[Image.Image] = None,
    position: str = "auto",
    device: str = "cuda"
) -> Image.Image:
    """
    Быстрая функция для удаления водяного знака.
    
    Примеры:
        # Из URL
        clean = remove_watermark("https://example.com/image.jpg")
        
        # Из файла
        clean = remove_watermark("photo.jpg")
        
        # С указанием позиции
        clean = remove_watermark("photo.jpg", position="bottom-right")
        
        # С кастомной маской
        mask = Image.open("mask.png")
        clean = remove_watermark("photo.jpg", mask=mask)
    """
    remover = get_watermark_remover(device)
    return remover.remove_watermark(image, mask=mask, position=position)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    remover = get_watermark_remover(device="cuda")
    
    image_path = "images/ffb135f242cdc67c.jpg"
    
    # Сначала сохраним маску для отладки (чтобы увидеть какие области будут обработаны)
    """ remover.save_debug_mask(
        image_path,
        output_path="debug_mask.png",
        position="all",  # Попробуй разные: "auto", "full-center", "diagonal", "all"
        use_text_detection=True,
        use_contrast_detection=True
    )
    logger.info("Check debug_mask.png to see which areas will be processed")"""


    cleaned_image = remover.remove_watermark(
        image_path,
        position="auto",
        use_gpt_detection=False,
        use_text_detection=True,
        use_contrast_detection=True,
        combine_masks=True
    )
    cleaned_image.save("cleaned_no_gpt.jpg", quality=95)
    
    # Теперь удаляем водяной знак
    # Вариант 1: Только GPT детекция (самый точный, но платный ~$0.01 за изображение)
    cleaned_image = remover.remove_watermark(
        image_path,
        position="none",  # Отключаем позиционную маску, полагаемся на GPT
        use_gpt_detection=True,  # GPT Vision определит где водяной знак
        use_text_detection=False,
        use_contrast_detection=False,
        combine_masks=False
    )
    cleaned_image.save("cleaned_gpt.jpg", quality=95)
    logger.info("Cleaned image (GPT) saved to cleaned_gpt.jpg")
    
    # Вариант 2: Комбинированный (GPT + все остальные методы)
    # cleaned_image = remover.remove_watermark(
    #     image_path,
    #     position="auto",
    #     use_gpt_detection=True,  # GPT Vision
    #     use_text_detection=True,  # OCR
    #     use_contrast_detection=True,  # Анализ контраста
    #     combine_masks=True
    # )
    # cleaned_image.save("cleaned_combined.jpg", quality=95)