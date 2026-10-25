"""MangaJaNai/IllustrationJaNai inference. Weights stay on the operator's disk."""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

from PIL import Image, ImageOps

MAX_PIXELS = 24_000_000
MAX_OUTPUT_PIXELS = 100_000_000
HEIGHTS = (1200, 1300, 1400, 1500, 1600, 1920, 2048)


class ProcessingCancelled(Exception):
    pass


def read_image(data):
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > MAX_PIXELS or getattr(source, 'n_frames', 1) != 1:
                raise ValueError()
            source.load()
            return ImageOps.exif_transpose(source).convert('RGB')
    except Exception:
        raise ValueError('Допустима одна страница JPG/PNG/WebP до 24 Мп.') from None


def model_catalog(directory):
    result = []
    root = Path(directory)
    for path in sorted(root.glob('**/*')):
        if not path.is_file() or path.suffix.lower() not in {'.pth', '.onnx', '.safetensors'}:
            continue
        if not re.match(r'^[124]x_(?:MangaJaNai|IllustrationJaNai)', path.stem, re.I):
            continue
        height = re.search(r'_(\d{4})p_', path.name)
        result.append({'id': path.relative_to(root).as_posix(), 'name': path.stem,
                       'scale': int(path.name[0]), 'color': 'illustration' in path.name.lower(),
                       'height': int(height[1]) if height else None, 'format': path.suffix[1:]})
    return result


def is_color(image):
    import numpy as np
    sample = np.asarray(image.resize((96, 96)), dtype=np.int16)
    # Sparse colored scan marks should not select an illustration model.
    chroma = sample.max(axis=2) - sample.min(axis=2)
    return float((chroma > 16).mean()) > .025


def select_model(models, image, scale=2, model='auto', content='auto'):
    if model != 'auto':
        found = next((m for m in models if m['id'] == model), None)
        if not found:
            raise ValueError('Выбранная модель MangaJaNai не установлена.')
        return found
    color = is_color(image) if content == 'auto' else content == 'color'
    choices = [m for m in models if m['scale'] == scale and m['color'] == color]
    if not choices:
        kind = 'цветных' if color else 'чёрно-белых'
        raise ValueError(f'Установи модель MangaJaNai {scale}× для {kind} страниц.')
    # Prefer current illustration models; grayscale uses closest training height.
    return min(choices, key=lambda m: (abs((m['height'] or image.height) - image.height),
                                      0 if 'V3' in m['name'] else 1,
                                      0 if 'FDAT_M' in m['name'] or 'SPAN' in m['name'] else 1,
                                      0 if m['format'] != 'onnx' else 1,
                                      m['name']))


class Upscaler:
    def __init__(self, directory, device='auto'):
        self.directory = Path(directory)
        self.device = device
        self._loaded = None

    def _load(self, model):
        path = (self.directory / model['id']).resolve()
        if not path.is_relative_to(self.directory.resolve()):
            raise ValueError('Некорректная модель.')
        identity = (str(path), path.stat().st_mtime_ns)
        if self._loaded and self._loaded[0] == identity:
            return self._loaded[1:]
        self._loaded = None
        if path.suffix == '.onnx':
            import onnxruntime as ort
            available = ort.get_available_providers()
            if self.device == 'cuda' and 'CUDAExecutionProvider' not in available:
                raise ValueError('Для ONNX CUDA установи onnxruntime-gpu и CUDA runtime.')
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if self.device != 'cpu' and 'CUDAExecutionProvider' in available else ['CPUExecutionProvider']
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
            inp = session.get_inputs()[0]
            dtype = 'float16' if inp.type == 'tensor(float16)' else 'float32'
            def infer(array):
                return session.run(None, {inp.name: array.astype(dtype)})[0]
            runtime = session.get_providers()[0]
            multiple = 64  # Supports ESRGAN, SPAN and window-attention models.
        else:
            import torch
            from spandrel import ImageModelDescriptor, ModelLoader
            device = 'cuda' if self.device == 'auto' and torch.cuda.is_available() else self.device
            if device == 'auto':
                device = 'cpu'
            if device == 'cuda' and not torch.cuda.is_available():
                raise ValueError('CUDA недоступна. Установи PyTorch CUDA или выбери CPU.')
            descriptor = ModelLoader(device=device).load_from_file(str(path))
            if not isinstance(descriptor, ImageModelDescriptor) or descriptor.input_channels != 3 or descriptor.output_channels != 3:
                raise ValueError('Нужна RGB-модель апскейла MangaJaNai.')
            if descriptor.scale != model['scale']:
                raise ValueError('Масштаб модели не совпадает с её именем.')
            descriptor.eval()
            def infer(array):
                with torch.inference_mode():
                    return descriptor(torch.from_numpy(array).to(device)).float().cpu().numpy()
            runtime = 'PyTorch ' + device
            multiple = math.lcm(16, descriptor.size_requirements.multiple_of)
        self._loaded = (identity, infer, runtime, multiple)
        return infer, runtime, multiple

    def run(self, image, options, progress=lambda _: None, cancelled=lambda: False):
        import numpy as np
        model = select_model(model_catalog(self.directory), image, options.get('scale', 2),
                             options.get('model', 'auto'), options.get('content', 'auto'))
        scale = model['scale']
        if image.width * image.height * scale * scale > MAX_OUTPUT_PIXELS:
            raise ValueError('Результат превышает 100 Мп. Раздели вебтун или выбери меньший масштаб.')
        progress('Загружаем ' + model['name'])
        infer, runtime, multiple = self._load(model)
        tile = int(options.get('tile', 256))
        overlap = 32
        output = Image.new('RGB', (image.width * scale, image.height * scale))
        total = math.ceil(image.width / tile) * math.ceil(image.height / tile)
        done = 0
        for y in range(0, image.height, tile):
            for x in range(0, image.width, tile):
                if cancelled():
                    raise ProcessingCancelled()
                right, bottom = min(x + tile, image.width), min(y + tile, image.height)
                left, top = max(0, x - overlap), max(0, y - overlap)
                farx, fary = min(image.width, right + overlap), min(image.height, bottom + overlap)
                array = np.asarray(image.crop((left, top, farx, fary)), dtype=np.float32) / 255
                h, w = array.shape[:2]
                array = np.pad(array, ((0, (-h) % multiple), (0, (-w) % multiple), (0, 0)), mode='edge')
                result = infer(np.ascontiguousarray(array.transpose(2, 0, 1)[None]))
                expected = (array.shape[0] * scale, array.shape[1] * scale)
                if result.ndim != 4 or result.shape[:2] != (1, 3) or result.shape[2:] != expected:
                    raise ValueError('Модель вернула несовместимый размер изображения.')
                if not np.isfinite(result).all():
                    raise ValueError('Модель вернула нечисловые значения. Выбери другую точность или runtime.')
                crop = result[0, :, (y-top)*scale:(bottom-top)*scale, (x-left)*scale:(right-left)*scale]
                pixels = np.rint(np.clip(crop.transpose(1, 2, 0), 0, 1) * 255).astype(np.uint8)
                output.paste(Image.fromarray(pixels), (x*scale, y*scale))
                done += 1
                progress(f'MangaJaNai · {done}/{total} тайлов · {runtime}')
        return output, {'model': model['name'], 'scale': scale, 'runtime': runtime,
                        'width': output.width, 'height': output.height}
