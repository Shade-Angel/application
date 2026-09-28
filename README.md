# Executor Balancer — быстрый запуск

## Что понадобится

- Windows 10/11 и Docker Desktop с запущенным Docker Engine (Linux containers).
- Свободные порты `5173`, `8000`, `8001`, `5432` и `6379`.

## Запуск

Откройте PowerShell в папке проекта (там, где находится `docker-compose.yml`) и выполните:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build -d
docker compose ps
```

Первый запуск может занять несколько минут: Docker скачает образы и соберёт приложение. Затем откройте **http://localhost:5173**.

API и Swagger: http://localhost:8000/docs. Полная инструкция по функциям, демонстрационному сценарию и устранению проблем: [README_FULL.md](README_FULL.md).

Отчёт о соответствии кейсу организаторов: [docs/ORGANIZER_SUBMISSION.md](docs/ORGANIZER_SUBMISSION.md).

Остановить приложение, сохранив данные:

```powershell
docker compose down
```

Чтобы начать с пустой базой и удалить сохранённые данные, выполните `docker compose down -v`, затем снова `docker compose up --build -d`.
