# 📚 Reading Tracker

> Терминальный трекер чтения для Linux — с хоткеями, стриками и прогрессом по книгам.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Linux-informational)
![Status](https://img.shields.io/badge/status-in%20development-yellow)
![License](https://img.shields.io/badge/license-MIT-green)

---

## О проекте

Консольное TUI-приложение для учёта прочитанных книг прямо в терминале — без браузера, без лишнего.
Хранит список книг, процент прочитанного, ведёт стрик (дни чтения подряд) и позволяет держать для
каждой книги ссылку на источник.

## Features

- 🖥 **TUI-интерфейс** на [Textual](https://github.com/Textualize/textual) — тёмно-фиолетовая цветовая схема
- 🔥 **Стрик чтения** — анимация огонька при отметке «прочитал сегодня»
- 📊 **Прогресс по книгам** — текущая страница / всего страниц, статус (планирую / читаю / прочитано)
- 🔗 **Ссылка на книгу** для каждой записи (своя электронная библиотека)
- 🧱 **ООП-архитектура** — чистые классы `Book` и `Library`, независимые от интерфейса
- ⌨️ **Полностью с клавиатуры** — без мыши
- 💾 **Локальное хранение** в JSON, без облака и аккаунтов

## Demo

<!-- Запишите термобат через `vhs` или `asciinema` и вставьте сюда GIF -->
<!-- ![demo](docs/demo.gif) -->

## Быстрый старт

```bash
git clone https://github.com/<ваш-юзернейм>/reading-tracker.git
cd reading-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### Запуск из Neovim

Добавьте в свой конфиг (`init.lua`) биндинг на запуск в плавающем терминале:

```lua
vim.keymap.set("n", "<leader>rt", function()
  vim.cmd("vsplit | terminal python ~/projects/reading-tracker/app.py")
end, { desc = "Open Reading Tracker" })
```

## Горячие клавиши

| Клавиша | Действие                          |
| ------- | ---------------------------------- |
| `a`     | Добавить книгу                     |
| `d`     | Удалить выбранную книгу            |
| `e`     | Редактировать книгу                |
| `r`     | Отметить «прочитал сегодня» 🔥     |
| `l`     | Открыть ссылку на книгу            |
| `↑ / ↓` | Навигация по списку                |
| `q`     | Выйти                              |

## Структура проекта

```
reading-tracker/
├── app.py            # Textual-приложение, экраны, хоткеи
├── models.py         # Классы Book и Library (бизнес-логика)
├── data.json          # Локальное хранилище (создаётся автоматически)
├── requirements.txt
└── README.md
```

## Стек

- **Python 3.10+**
- **Textual** — TUI-фреймворк
- Хранение — JSON (без внешних БД и зависимостей от сети)

## Roadmap

- [ ] Статистика по месяцам/годам
- [ ] Экспорт библиотеки в CSV
- [ ] Цветовые темы помимо фиолетовой
- [ ] Напоминания о ежедневном чтении

## License

MIT — делайте с кодом, что хотите, но будет приятно, если оставите ссылку на автора.

---

Автор: **#Brownie** · [GitHub](https://github.com/Llaawliett) · [резюме](#)
