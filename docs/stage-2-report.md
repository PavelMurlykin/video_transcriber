# Этап 2. Автономный ASR

26.11.2026. Критерий приёмки выполнен. Русский WAV длительностью 15 минут
41,430 секунды распознан на RTX 5070 Laptop, итог сохранён в локальном JSON
при блокировке сети на уровне Windows. Использованы ранее подготовленные Large V3,
VAD и CUDA 12.8 в существующей `.venv`.

Команда `asr` поддерживает русский, английский и автоопределение языка.
`ASREngine` загружает Large V3 и pyannote VAD по локальным путям. Конфигурации
автономного ASR достаточно путей к этим двум ресурсам, манифесту, FFmpeg и
ffprobe. Параметры по умолчанию — CUDA, `float16`, батч 4 и `beam_size=5`.
Локальный список терминов передаётся как подсказки WhisperX.

Проект JSON v1 записывается после медиаподготовки и атомарно обновляется
после ASR. Версия со спикерами и таймкодами слов формируется обычной командой
`transcribe` после выравнивания и диаризации. ASR выполняется в отдельном
процессе. При выходе процесса освобождаются ресурсы GPU. При распознанной
ошибке выделения памяти CLI выдаёт одну подсказку для ручного повтора.
Профиль `memory` использует `int8_float16` на CUDA с батчем до 2.

## Проверки и замеры

| Запуск | Длина аудио | Время целиком, с | ASR, с | Пик VRAM, МиБ | Пик RSS на ASR, ГиБ | Результат |
|---|---:|---:|---:|---:|---:|---|
| Русский, CUDA float16, батч 4 | 15:41,430 | 96,81 | 94,93 | 7535 | 3,83 | 33 сегмента. Последний заканчивается на 15:41,048 |
| Авто, CUDA int8_float16, батч 2, файл терминов | 0:58,839 | 49,97 | 48,14 | 3933 | 3,70 | Определён русский язык, 3 сегмента |
| Английский, CUDA float16, батч 4 | 0:10,968 | 36,41 | 34,70 | 5410 | 3,46 | 1 сегмент, найдены ожидаемые английские слова |
| Полная обработка русского MP4 | 0:58,839 | 90,28 | 39,86 | 6140 | 3,37 | 2 назначенных спикера, 56 сегментов, 149 слов с таймкодами |

Замеры VRAM охватывают всю видеокарту. RSS измерен для дерева процессов.
Время ASR включает запуск worker, загрузку моделей, распознавание и выход
процесса. После выхода ASR worker измерено 957 МиБ общей VRAM для длинного
запуска и 885 МиБ для экономного профиля. Полный прогон затратил 20,52 с
на выравнивание и 27,00 с на диаризацию.

Длинная запись сделана из 16 повторов предоставленного MP3. Это проверка
обработки нужной длительности и записи сегментов до конца файла. Для оценки
точности на длинных разговорах нужны разные записи и эталонные транскрипции.
Английский WAV синтезирован установленным голосом Windows. В режиме
`auto` и `en` использована конфигурация с путями только к ресурсам ASR.
Обработка проверена с файлом подсказок. Влияние словаря на точность отдельно
не измерялось.

Все четыре прогона прошли в Windows AppContainer без сетевых разрешений.
До запуска TCP-пробы отклонены с `WinError 10013`, DNS недоступен.
Проверки подтвердили JSON v1, корректные границы сегментов и удаление рабочего
WAV. SHA-256 исходных MP3 и MP4 совпали с эталоном этапа 0. Медиа, результаты
и словарь хранятся локально в исключённых из Git каталогах.

**44 теста прошли**, `pip check` без конфликтов, компиляция модулей прошла.
Тесты проверяют передачу языка и подсказок в WhisperX, состав локальных
ресурсов, контрольные точки и обработку OOM. OOM воспроизведена тестовыми
исключениями PyTorch и CTranslate2, видеопамять специально не исчерпывалась.
CPU-профиль аппаратно не проверялся.

При подготовке английского WAV Windows Speech внутри AppContainer вернул
`NullReferenceException` на чтении списка голосов. Вне AppContainer тот же
установленный голос создал WAV локально. Само распознавание выполнено в
AppContainer. В одном запуске pytest после успешных тестов и перед завершением
интерпретатора `pyreadline3` сообщил об ошибке дескриптора консоли. Код выхода
тестов — 0.

## Команды проверки

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:debugging --durations=5
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q src scripts tests
.\.venv\Scripts\python.exe scripts\verify_offline.py --asr-only --language ru --input artifacts\stage2-fixtures\repeated-ru.wav --run-dir artifacts\stage2-ru-long --evidence artifacts\stage2-network-ru-long.json
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\stage2-ru-long --asr-only --expected-language ru
.\.venv\Scripts\python.exe scripts\verify_offline.py --config artifacts\stage2-fixtures\asr.local.json --asr-only --language auto --profile memory --terms-file artifacts\stage2-fixtures\terms.txt --input 'sample\Дуэт Да.mp4' --run-dir artifacts\stage2-auto-memory --evidence artifacts\stage2-network-auto.json
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\stage2-auto-memory --asr-only --expected-language ru
.\.venv\Scripts\python.exe scripts\verify_offline.py --config artifacts\stage2-fixtures\asr.local.json --asr-only --language en --input artifacts\stage2-fixtures\en.wav --run-dir artifacts\stage2-en --evidence artifacts\stage2-network-en.json
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\stage2-en --asr-only --expected-language en
.\.venv\Scripts\python.exe scripts\verify_offline.py --input 'sample\Дуэт Да.mp4' --run-dir artifacts\stage2-full-regression --evidence artifacts\stage2-network-full.json
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\stage2-full-regression --expected-speakers 2 --expected-language ru
```

Для нового прогона используйте новый каталог `--run-dir`. В [русском](user-manual.ru.md)
и [английском](user-manual.en.md) руководствах приведены команды, описание
контрольных точек, параметры языка, словаря и экономии памяти.

Тема коммита

```text
feat: добавить автономное распознавание речи на этапе 2
```
