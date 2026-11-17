# Этап 0 — отчёт

Дата: 17.11.2026. Основное ТЗ: `Local_Transcriber_Codex_Development_Plan.md`, версия 1.0.

**Этап 0 завершён.** Реальный CLI pipeline ASR → forced alignment → Community-1
diarization → JSON прошёл на предоставленных MP3 и MP4 с двумя говорящими и
смехом. Оба запуска выполнены без сети на RTX 5070. К следующим этапам,
интерфейсу, редактору, экспорту документов и упаковке разработка не переходила.

## Окружение и модели

- Windows 11 x64; Python **3.13.12**, изолированная `.venv`.
- NVIDIA GeForce RTX 5070 Laptop GPU, **8151 MiB**, драйвер **621.24**.
- Torch/torchaudio **2.8.0+cu128**, torchvision **0.23.0+cu128**; фактический
  CUDA runtime **12.8**, compute capability **12.0**, архитектура `sm_120`.
- WhisperX **3.8.6**, faster-whisper **1.2.0**, CTranslate2 **4.6.0**,
  transformers **4.57.6**, pyannote.audio **4.0.4**, torchcodec **0.7.0**.
- FFmpeg и ffprobe **9.0.2-essentials_build** находятся в `.tools` проекта.
- CUDA tensor/matmul test выполнен на GPU, результат конечный;
  `torch.cuda.is_available() == True`. CTranslate2 проверен реальным ASR,
  дополнительно подтверждена поддержка `float16` и `int8_float16`.
- [requirements.lock](../requirements.lock): **111** установленных дистрибутивов
  без самого проекта. Проверен именно Windows/Python 3.13. Отдельных прогонов
  на Python 3.11–3.12 не было.

Модели: `C:\Users\PAVEL\.lmstudio\models\local-transcriber`.
LM Studio как сервис не используется. Настройки абсолютных путей сохранены в
локальном, исключённом из Git `config.local.json`.

| Компонент | Источник | Проверенная ревизия |
|---|---|---|
| ASR | Systran/faster-whisper-large-v3 | `edaa852ec7e145841d8ffdb056a99866b5f0a478` |
| Alignment | jonatasgrosman/wav2vec2-large-xlsr-53-russian | `2329100508896c6d9b157019803ab5601e6f3406` |
| Diarization | pyannote/speaker-diarization-community-1 | `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee` |
| VAD | Отдельные bundled-веса WhisperX | выпуск `3.8.6`, SHA-256 в manifest |
| Sentence tokenizer | NLTK punkt_tab, включая russian/english | содержимое зафиксировано SHA-256 каждого файла |

Кэш Large V3 использован без повторного скачивания. HF snapshot содержит
символические ссылки на общие blobs: файлы материализованы в согласованном
каталоге, копия сверена по хешам. Исходный общий кэш сохранён, чтобы его ссылки
и другие потребители продолжали работать.

Точный [manifest использованных файлов](models-manifest.stage0.json) содержит
источники, ревизии, обязательные файлы, размеры, SHA-256 и лицензии/ссылки на
проверку лицензий. Его SHA-256:
`2a69e1294950bca1fcdeb142bfd7e66ef2df615ea90e5182db8ca96f0465fe88`.
Он совпадает с `models_manifest_sha256` в обоих результатах. VAD/NLTK имеют
явные `LicenseRef` для последующей проверки условий распространения; модели
и бинарники в Git и установщик не включались.

## Реальные результаты

Профиль: русский, Large V3, CUDA, `float16`, `batch_size=4`, `beam_size=5`,
`num_speakers=2`. Подготовленные WAV: **58,839 с**, 16 kHz, mono, PCM 16 bit.
Модели не заменялись; OOM и перехода на CPU не было.

| Проверка | MP3, первый запуск | MP4, повторный запуск |
|---|---:|---:|
| Весь pipeline, с проверкой хешей, с | **115,73** | **107,94** |
| Извлечение аудио, с | 0,146 | 0,184 |
| ASR, с | 53,55 | 45,63 |
| Alignment, с | 26,50 | 26,48 |
| Diarization, с | 31,61 | 32,36 |
| Сведение и запись JSON, с | 0,022 | 0,022 |
| Условных спикеров / назначенных спикеров | 2 / 2 | 2 / 2 |
| Сегментов | 57 | 56 |
| Слов с временными метками | 152 | 149 |
| Слов без alignment | 0 | 0 |
| Сегментов для ручной проверки | 31 | 29 |
| Сегментов с `unknown` | 17 | 16 |

Количество слов между двумя кодированными версиями записи различается.
Эталонная транскрипция и разметка спикеров не предоставлены; WER/CER/DER и
семантическая точность не измерялись. Флаги проверки отражают предсказанные
границы и пересечения спикеров, включая неоднозначное назначение. Смех не
классифицируется отдельным событием. Успешный pipeline не является гарантией
правильности всех реплик и говорящих.

| Фаза | Пик VRAM MP3 / MP4, MiB | Пик RSS дерева процессов MP3 / MP4, GiB |
|---|---:|---:|
| ASR | 5853 / 5821 | 3,70 / 3,42 |
| Alignment | 2923 / 2923 | 1,83 / 1,61 |
| Diarization | 3169 / 3169 | 1,79 / 1,78 |

VRAM — периодические измерения `nvidia-smi` всей видеокарты, включая другие
процессы; RSS — наблюдаемое дерево процессов. Интервал ожидания между пробами
0,5 с плюс время самой пробы; краткий пик может быть пропущен. Время модельных
фаз включает запуск worker, импорты, загрузку и освобождение модели. После
каждого worker наблюдалось **635 MiB общей VRAM**. Модельные процессы завершились
с кодом 0; стадии выполнялись последовательно. Torch allocator отдельно
зафиксирован в JSON и не включает память CTranslate2.

Технические данные без текста записи:
[окружение](stage-0-environment.json), [измерения](stage-0-metrics.json),
[доказательства сетевой изоляции](stage-0-network.json).

Приватные результаты на этой машине, исключённые из Git:

- MP3: `artifacts/mp3-first/transcript.json`, `metrics.json`, `validation.json`.
- MP4: `artifacts/mp4-offline/transcript.json`, `metrics.json`, `validation.json`.

Исходные MP3 и MP4 после двух прогонов повторно проверены по SHA-256:
**изменений нет**. Подготовленные WAV и промежуточные ASR/alignment/diarization
сохранены отдельно. Текст разговора и токен не включены в технический отчёт,
метрики или Git.

## Офлайн-проверка

Оба запуска выполнены в Windows AppContainer **без сетевых capabilities**.
До включения Python guard проверены настоящие сетевые вызовы: TCP к
`1.1.1.1:443` и `8.8.8.8:443` отклонён ОС с **WinError 10013**, DNS Hugging Face
недоступен. Дочерние процессы наследовали изоляцию. Системные адаптеры и
firewall пользователя не изменялись.

Каждый запуск использовал новый пустой HF/Torch cache в своём каталоге,
без модельных весов и runtime-токена. Включены `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`, отключены HF/pyannote/OpenTelemetry telemetry и
неявное чтение HF-токена; Python socket/DNS дополнительно блокируются.
FFmpeg допускает локальные протоколы `file,pipe`. Таким образом проверены
реальные inference и локальные ресурсы при блокировке сети на уровне ОС.
Перезагрузка машины в этапе 0 не проверялась.

## Команды и проверки

Все команды ниже действительно выполнены. Команды инференса требуют нового
`--run-dir`; существующие каталоги результатов не перезаписываются.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q -p no:debugging
.\.venv\Scripts\python.exe scripts\diagnose.py
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json verify-models
.\.venv\Scripts\python.exe scripts\verify_offline.py --config config.local.json --input 'sample\Дуэт Да.mp3' --run-dir artifacts\mp3-first --evidence artifacts\network-mp3.json
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\mp3-first --expected-speakers 2
.\.venv\Scripts\python.exe scripts\verify_offline.py --config config.local.json --input 'sample\Дуэт Да.mp4' --run-dir artifacts\mp4-offline --evidence artifacts\network-mp4.json
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\mp4-offline --expected-speakers 2
```

- **25 тестов пройдено**; финальный запуск — 0,98 с, без пропусков.
- `pip check`: **No broken requirements found**.
- `verify-models`: **completed**, отсутствующих/повреждённых ресурсов нет.
- Обе структурные проверки JSON: **completed**, `errors: []`.
- GPU tensor и два реальных CTranslate2/WhisperX + pyannote inference: **успех**.
- Проверены повреждённый вход, видео без аудио, кириллица/пробелы в путях,
  сохранность оригинала, LFS pointers, повреждение хешей, локальные пути,
  пропущенный текст/метки, смена спикеров, пересечения и конфиденциальность ошибок.

## Ошибки и принятые решения

| Наблюдение | Действие и результат |
|---|---|
| `py -0p` не видит установленный Python | Использован обнаруженный `python` 3.13.12, подходящий требованию >=3.11 и WhisperX <3.14. Создана отдельная `.venv`. |
| Подготовительная загрузка в сетевом sandbox: DNS error 11001 | Online-подготовка выполнена с разрешённым сетевым доступом; runtime отдельно проверен с настоящей блокировкой сети. |
| Полные большие HTTP-загрузки Torch/Wav2Vec2 не продвигались | Скачаны байтовыми диапазонами с возобновлением и сверкой опубликованных SHA-256. Хеш Torch `9e206468…307c8405`, Wav2Vec2 `d1cdb1a7…b2df0c1c` совпали. |
| Community-1 требует принятия условий и Read-токена | Пользователь выполнил скрипт со скрытым вводом; полный pipeline скачан. В runtime токен не нужен и не передавался. |
| В upstream Wav2Vec2 отсутствует `tokenizer_config.json` | Список обязательных файлов сверён с фактической ревизией. Локальные processor/tokenizer успешно загружены из config/vocab/special tokens. |
| Локальная сборка julius задерживалась в AppContainer | Подготовительная установка из проверенных архивов завершена вне AppContainer. Реальный inference проверен внутри AppContainer. |
| Нефатальные предупреждения подготовки | NLTK вывел предупреждение `pathsec.ZipFile`; распаковка прошла и все ресурсы проверены по хешам. CTranslate2 предупреждает об устаревании pkg_resources; совместимый setuptools 80.9.0 закреплён. |
| pytest/PDB импортирует pyreadline3 без интерактивной консоли | Первые тесты проходили с ignored WinError при завершении. Финальные 25 тестов выполнены с `-p no:debugging`, без этой ошибки; отключена только интеграция отладчика. |

Архитектура сохранена: три отдельные модели и отдельное сведение. Короткоживущий
worker на каждую фазу конкретизирует предусмотренную ТЗ границу процесса и
освобождение native CUDA ресурсов. Это не вводит GUI или HTTP-сервер.

## Изменённые файлы и ограничения

- `pyproject.toml`, `requirements.in`, vendor constraints, `requirements.lock`,
  README, AGENTS, пример конфигурации и исключения приватных данных в `.gitignore`.
- `src/local_transcriber`: CLI, конфигурация, media, model verification,
  offline guard, три модельных адаптера, сведение, GPU cleanup, pipeline и worker.
- `scripts`: FFmpeg/model preparation, безопасная подготовка Community-1,
  проверка моделей/сети/GPU/JSON, конфигурация и техническая сводка.
- `tests`: 25 проверок; `docs`: архитектура, подготовка, тестирование, этот
  отчёт, воспроизводимые технические JSON и оба пользовательских руководства:
  [русское](user-manual.ru.md), [English](user-manual.en.md).

Проверен один короткий разговор в двух контейнерах. Длинные записи, ручные
эталоны WER/CER/DER, режимы CPU/int8, автоматическое число говорящих,
управляемая отмена/восстановление, перезагрузка, UI и экспорт документов не
проверялись и не объявляются готовыми. Следующий этап требует отдельной задачи
пользователя. Файлы не добавлялись в индекс Git, коммит не создавался.

Готовая тема коммита:

```text
feat: реализовать офлайн CLI-прототип этапа 0
```
