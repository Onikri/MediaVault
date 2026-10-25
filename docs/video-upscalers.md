# Видеофильтры 5.6: что можно сравнить

Настройки плеера → Изображение → Улучшение. Переключение не меняет файл в Drive.
Все режимы бесплатны; обработка выполняется на устройстве зрителя.

| Вариант | Реализация | Когда пробовать |
| --- | --- | --- |
| Мобильный GPU | Catmull–Rom + ограниченное усиление яркостных деталей, WebGL | Телефон/планшет, экономный профиль |
| Lanczos3 | Настоящий separable 6×6 Lanczos3 kernel в одном WebGL pass | Естественный вид без нейросети; возможен звон на резких контрастах |
| AMD FSR1 | EASU edge-adaptive reconstruction + RCAS sharpening, два WebGL2 pass | Аниме и фильмы, широкий набор GPU; обычная и мягкая резкость |
| Anime4K M/L/VL/UL | Реальные CNN shader profiles anime4k.js, WebGPU | Аниме, производительный GPU; VL/UL существенно тяжелее |
| FSRCNN ×2 | Проверенные по хешу ONNX-веса, inference только WebGPU | Сравнение нейросетевого результата. Есть CPU readback для Y/chroma и ограничение входного размера; это не оптимальный путь для HD-видео |

FSR1 перенесён из AMD MIT-кода через mpv luma port agyild. EASU фильтрует
яркость, RCAS её усиливает; цветность восстанавливается из исходной RGB-текстуры.
Ограничители RCAS защищены от 0/0 на полностью чёрных/белых областях. Это SDR
путь, без HDR/PQ tone mapping. Качество задаёт предел выходной ширины:
1280/2560/3840, увеличение не более 2× по каждой оси. Низкий предел может
уменьшить исходный кадр. Работает на Intel/AMD/NVIDIA/совместимых мобильных GPU,
не только AMD. Нет CPU getImageData на каждом кадре в FSR/Lanczos.

График кадров/latency отражает обработку и отправку кадра из JS, а не точный
GPU timestamp. Название GPU доступно только если браузер его раскрывает.
`powerPreference: high-performance` запрашивается, но выбор дискретной карты
остаётся у браузера/ОС. Для Windows можно назначить браузеру «Высокая
производительность» в Параметры → Система → Дисплей → Графика и перезапустить
браузер. Сайт не может принудительно включить RTX VSR или сменить видеокарту.
После ошибки можно повторить на новом canvas; исходное видео продолжает работать.

## Почему другие популярные варианты не стали фиктивными пунктами меню

- [ArtCNN](https://github.com/Artoriuz/ArtCNN), [RAVU](https://github.com/bjin/mpv-prescalers)
  и [FSRCNNX](https://github.com/igv/FSRCNN-TensorFlow) часто упоминаются в
  [обсуждениях mpv](https://www.reddit.com/r/mpv/comments/1fra2xg/any_update_on_new_upscalers/).
  Готовый mpv GLSL не является готовым WebGPU renderer; нужен отдельный
  проверенный перенос. Они пока не заявлены как реализованные.
- [WebSR](https://github.com/sb2702/websr) имеет практичный WebGPU pipeline и
  новые веса для real-life/3D. Его опубликованные CNN-архитектуры происходят
  от Anime4K, поэтому его добавление само по себе не дало бы независимый от
  Anime4K алгоритм. Оставлен для отдельного сравнения скорости.
- FSR2/3 требуют motion vectors/depth/jitter из рендера игры. Обычный video
  элемент их не предоставляет. Для нашего плеера подходит spatial FSR1,
  а не обещание temporal FSR3.
- RTX Video Super Resolution — функция драйвера/браузера, не переносимый JS API.

Источники: [AMD FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR),
[mpv port](https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5),
[FSR vs FSRCNNX discussion](https://www.reddit.com/r/mpv/comments/18a7kap/any_4k_upscaler_shader_for_nonanime_movie/).
Полный MIT notice и исходник порта находятся в `src/vendor/fsr1/`; лицензия
также публикуется как `FSR1-LICENSE.txt`.

`test:gpu` компилирует и выполняет реальные GLSL, проверяет RGB/чёрный/белый,
размер, остановку и новый запуск для обоих FSR-профилей и Lanczos3 через
Chromium SwiftShader. Это проверка корректности, не benchmark физической GPU.
Скорость/артефакты нужно сравнить на своей карте и своём видео.
