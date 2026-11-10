# Эксперимент: Crystal-Titan bridge × DeepSeek V4.1-Flash-1017

Лабораторный прогон из трёх вызовов через путь Titan `/chat` (коммит Titan `6b45854`). Основной Crystal и код песочницы Titan не менялись. `auto_save_memory=false`. PR не сливать.

Официальный идентификатор API — `deepseek-flash`; по [документации DeepSeek](https://api-docs.deepseek.com/) этот id сейчас обслуживается моделью DeepSeek-V4.1-Flash-1017. `GET /models` вернул только `deepseek-flash` и `deepseek-v4-pro`. Датированный id `deepseek-v4.1-flash-1017` в официальном списке отсутствует, поэтому в запрос ушёл `deepseek-flash`.

Режим thinking: `ChatRequest.deepseek_thinking=high` → в теле провайдера `thinking={"type":"enabled"}` и `reasoning_effort="high"`. Это проверено поддельным провайдером до живых вызовов (`preflight.json`).

Запуск (требует `DEEPSEEK_API_KEY` в окружении; ключ не пишется в артефакты):

```bash
python experiments/2026-11-10-deepseek-bridge/run_experiment.py
```

Повторный запуск сделает ещё три платных вызова. Не запускайте без новой явной авторизации.
