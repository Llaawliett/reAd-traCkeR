#!/usr/bin/env python3
"""
Reading Tracker — TUI-трекер чтения для терминала Linux.

Запуск:   python3 tracker.py            (или  python3 tracker.py --no-splash)
Нужно:    pip install textual           (Python 3.9+)
Данные:   ~/.local/share/reading-tracker/data.json
          (другой путь: переменная окружения READING_TRACKER_DATA)

Структура файла (классы):
    ── Модель ──────────────────────────────────────────────
    Book           одна книга (прогресс, ссылка на электронную версию)
    ReadingLog     дни, когда ты читал(а) → серия (streak)
    Storage        загрузка/сохранение JSON
    Library        фасад над книгами и журналом чтения
    ── Оформление ──────────────────────────────────────────
    Theme          цвета
    PurpleGradient тёмно-фиолетовый градиент фона
    CatFace        ASCII-арт кошко-девочки (с морганием)
    FireSimulation симуляция огня для streak-анимации
    Hotkey         описание горячей клавиши (бар и справка берут её отсюда)
    ── Виджеты ─────────────────────────────────────────────
    GradientPanel  базовая рамка с градиентным фоном
    CatBanner, StreakPanel, BookListPanel, DetailsPanel, HotkeyBar, SplashView
    ── Экраны ──────────────────────────────────────────────
    SplashScreen, MainScreen, BookFormScreen, PromptScreen, ConfirmScreen, HelpScreen
    ReadingTrackerApp
"""
from __future__ import annotations

import json
import os
import random
import sys
import webbrowser
from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, Label, Static


# ════════════════════════════════════════════════════════════════════
#  МОДЕЛЬ
# ════════════════════════════════════════════════════════════════════
@dataclass
class Book:
    """Одна книга. `url` — ссылка на электронную версию (любой сайт)."""

    title: str
    author: str = ""
    total_pages: int = 0
    current_page: int = 0
    url: str = ""
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    added_on: str = field(default_factory=lambda: date.today().isoformat())
    finished_on: str | None = None

    @property
    def progress(self) -> float:
        if self.total_pages <= 0:
            return 1.0 if self.is_finished else 0.0
        return min(1.0, self.current_page / self.total_pages)

    @property
    def is_finished(self) -> bool:
        return self.finished_on is not None

    def set_page(self, page: int) -> None:
        page = max(0, page)
        if self.total_pages:
            page = min(page, self.total_pages)
        self.current_page = page
        if self.total_pages and page >= self.total_pages:
            self.finished_on = self.finished_on or date.today().isoformat()
        else:
            self.finished_on = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Book":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class ReadingLog:
    """Дни, в которые ты отметил(а) «прочитал сегодня». Считает серии."""

    def __init__(self, days: list[str] | None = None) -> None:
        self._days: set[str] = set(days or [])

    def mark(self, day: date | None = None) -> bool:
        key = (day or date.today()).isoformat()
        is_new = key not in self._days
        self._days.add(key)
        return is_new

    def unmark(self, day: date | None = None) -> None:
        self._days.discard((day or date.today()).isoformat())

    def is_marked(self, day: date | None = None) -> bool:
        return (day or date.today()).isoformat() in self._days

    def current_streak(self, today: date | None = None) -> int:
        """Серия жива, если сегодня или вчера есть отметка."""
        today = today or date.today()
        cursor = today if self.is_marked(today) else today - timedelta(days=1)
        count = 0
        while self.is_marked(cursor):
            count += 1
            cursor -= timedelta(days=1)
        return count

    def best_streak(self) -> int:
        days = sorted(date.fromisoformat(d) for d in self._days)
        best = run = 0
        previous: date | None = None
        for d in days:
            run = run + 1 if previous and d - previous == timedelta(days=1) else 1
            best = max(best, run)
            previous = d
        return best

    def week_count(self, today: date | None = None) -> int:
        today = today or date.today()
        return sum(self.is_marked(today - timedelta(days=i)) for i in range(7))

    def to_list(self) -> list[str]:
        return sorted(self._days)


class Storage:
    """Читает и пишет JSON (запись атомарная — файл не повредится)."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            env = os.environ.get("READING_TRACKER_DATA")
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            path = Path(env) if env else base / "reading-tracker" / "data.json"
        self.path = path

    def load(self) -> tuple[list[Book], ReadingLog]:
        if not self.path.exists():
            return [], ReadingLog()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            books = [Book.from_dict(b) for b in raw.get("books", [])]
            return books, ReadingLog(raw.get("read_days", []))
        except (OSError, ValueError, TypeError):
            backup = self.path.with_suffix(".broken.json")
            self.path.replace(backup)  # не теряем битый файл, а откладываем в сторону
            return [], ReadingLog()

    def save(self, books: list[Book], log: ReadingLog) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "books": [b.to_dict() for b in books], "read_days": log.to_list()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


class Library:
    """Фасад: всё, что UI делает с данными, идёт через этот класс."""

    def __init__(self, storage: Storage | None = None) -> None:
        self.storage = storage or Storage()
        self.books, self.log = self.storage.load()

    def save(self) -> None:
        self.storage.save(self.books, self.log)

    def add_book(self, title: str, author: str = "", total_pages: int = 0, url: str = "") -> Book:
        book = Book(title=title.strip(), author=author.strip(), total_pages=max(0, total_pages),
                    url=normalize_url(url))
        self.books.append(book)
        self.save()
        return book

    def remove_book(self, book: Book) -> None:
        self.books = [b for b in self.books if b.id != book.id]
        self.save()

    def set_page(self, book: Book, page: int) -> bool:
        """Возвращает True, если прогресс вырос."""
        before = book.current_page
        book.set_page(page)
        self.save()
        return book.current_page > before

    def set_url(self, book: Book, url: str) -> None:
        book.url = normalize_url(url)
        self.save()

    def check_in_today(self) -> bool:
        is_new = self.log.mark()
        self.save()
        return is_new

    def undo_today(self) -> None:
        self.log.unmark()
        self.save()


# ════════════════════════════════════════════════════════════════════
#  ОФОРМЛЕНИЕ
# ════════════════════════════════════════════════════════════════════
class Theme:
    BORDER = "#9d6bff"
    TEXT = "#efe6ff"
    DIM = "#a592d6"
    ACCENT = "#ff7ad9"
    GOLD = "#ffd166"
    GREEN = "#7ee787"
    LINK = "#7dd3fc"
    SELECT_BG = "#6d28d9"


def lerp_hex(a: str, b: str, t: float) -> str:
    return Color.parse(a).blend(Color.parse(b), max(0.0, min(1.0, t))).hex


class PurpleGradient:
    """Вертикальный градиент: почти чёрно-фиолетовый сверху → насыщенный фиолетовый снизу."""

    TOP = "#0b0120"
    BOTTOM = "#4b1a8a"

    @classmethod
    @lru_cache(maxsize=512)
    def at(cls, row: int, total: int) -> str:
        return lerp_hex(cls.TOP, cls.BOTTOM, row / max(1, total - 1))


def progress_bar(progress: float, width: int) -> Text:
    filled = round(progress * width)
    bar = Text()
    for i in range(width):
        if i < filled:
            bar.append("█", Style(color=lerp_hex("#7c3aed", Theme.ACCENT, i / max(1, width - 1))))
        else:
            bar.append("░", Style(color="#5a4590"))
    return bar


def fit(text: Text, width: int) -> Text:
    out = text.copy()
    out.truncate(max(0, width), overflow="ellipsis")
    return out


def plural_days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


class CatFace:
    """ASCII-арт кошко-девочки. Рисуем левую половину, правую зеркалим — всегда симметрично."""

    MIRROR = str.maketrans("/\\`'()[]{}<>", "\\/'`)(][}{><")
    HALVES = [
        ("      /\\         ", " "),
        ("     /  \\________", "_"),
        ("    /   ,-~~~~~~~", "~"),
        ("   |   / ▄▄▄▄▄   ", " "),
        ("   |  |  █ E █   ", " "),
        ("   |  |  ▀▀▀▀▀   ", " "),
        ("   |   \\  ♥♥♥    ", "w"),
        ("    \\   `-.__    ", " "),
        ("     `-._   `-...", "."),
        ("        `---.____", "_"),
    ]
    OPEN, CLOSED = "◕", "─"

    @classmethod
    def lines(cls, blink: bool = False) -> list[str]:
        eye = cls.CLOSED if blink else cls.OPEN
        out = []
        for left, middle in cls.HALVES:
            right = left[::-1].translate(cls.MIRROR)
            out.append((left + middle + right).replace("E", eye))
        return out

    @classmethod
    def styled(cls, blink: bool, pulse: bool) -> list[Text]:
        heart = "#ff3fa4" if pulse else Theme.ACCENT
        rows = []
        for line in cls.lines(blink):
            t = Text()
            for ch in line:
                if ch in "◕─" and ch in (cls.OPEN, cls.CLOSED):
                    t.append(ch, Style(color=Theme.LINK, bold=True))
                elif ch == "♥" or ch == "w":
                    t.append(ch, Style(color=heart, bold=True))
                elif ch in "█▄▀":
                    t.append(ch, Style(color="#f4eaff"))
                else:
                    t.append(ch, Style(color="#d6b8ff"))
            rows.append(t)
        return rows

    WIDTH = 35
    HEIGHT = len(HALVES)


class FireSimulation:
    """Классический «огонек Doom»: тепло поднимается вверх и остывает случайным образом."""

    LUT_SIZE = 48
    STOPS = [(0.0, "#3a0606"), (0.28, "#b5160a"), (0.55, "#f06a0c"), (0.8, "#ffb703"), (1.0, "#fff1b8")]

    def __init__(self) -> None:
        self.w = self.h = 0
        self.heat: list[list[float]] = []
        self._lut = self._build_lut()

    @classmethod
    def _build_lut(cls) -> list[str]:
        lut = []
        for i in range(cls.LUT_SIZE):
            v = i / (cls.LUT_SIZE - 1)
            for (p0, c0), (p1, c1) in zip(cls.STOPS, cls.STOPS[1:]):
                if p0 <= v <= p1:
                    lut.append(lerp_hex(c0, c1, (v - p0) / (p1 - p0)))
                    break
        return lut

    def resize(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.heat = [[0.0] * w for _ in range(h)]

    def step(self, intensity: float) -> None:
        w, h = self.w, self.h
        if w <= 0 or h <= 1:
            return
        mid = (w - 1) / 2 or 1
        for x in range(w):
            edge = abs(x - mid) / mid  # 0 в центре → 1 на краю
            self.heat[h - 1][x] = min(1.0, intensity * (1 - 0.3 * edge ** 2) * (0.85 + random.random() * 0.3))
        for y in range(h - 1):
            row_below = self.heat[y + 1]
            for x in range(w):
                sx = min(w - 1, max(0, x + random.choice((-1, 0, 0, 1))))
                edge = abs(x - mid) / mid
                # по краям остываем быстрее → пламя широкое внизу и узкое вверху
                cooling = 0.03 + random.random() * 0.09 + 0.14 * edge ** 2
                self.heat[y][x] = max(0.0, row_below[sx] - cooling)

    def color(self, heat: float) -> str | None:
        if heat < 0.07:
            return None
        return self._lut[int(min(1.0, heat) * (self.LUT_SIZE - 1))]


@dataclass
class Spark:
    x: float
    y: float
    vx: float
    vy: float
    life: int
    char: str


@dataclass(frozen=True)
class Hotkey:
    keys: str
    label: str
    description: str
    in_bar: bool = True


HOTKEYS = [
    Hotkey("↑ ↓", "выбор", "Выбрать книгу в списке"),
    Hotkey("Space", "✔ прочитал", "Засчитать сегодняшний день — загорится огонёк серии"),
    Hotkey("p", "страница", "Записать, на какой ты странице (прогресс тоже засчитывает день)"),
    Hotkey("a", "новая книга", "Добавить книгу: название, автор, кол-во страниц, ссылка на книгу"),
    Hotkey("o", "открыть", "Открыть ссылку на электронную книгу в браузере"),
    Hotkey("e", "ссылка", "Изменить ссылку на электронную книгу"),
    Hotkey("d", "удалить", "Удалить выбранную книгу"),
    Hotkey("u", "отмена дня", "Снять отметку «прочитал» за сегодня", in_bar=False),
    Hotkey("g/G", "начало/конец", "Прыжок в начало / в конец списка", in_bar=False),
    Hotkey("?", "помощь", "Показать окно с подсказками"),
    Hotkey("q", "выход", "Выйти (всё уже сохранено<3)"),
]


# ════════════════════════════════════════════════════════════════════
#  ВИДЖЕТЫ
# ════════════════════════════════════════════════════════════════════
class GradientPanel(Widget):
    """
    Базовая панель: рисует рамку и фон-градиент строка за строкой.
    Градиент считается по абсолютной строке экрана, поэтому соседние панели
    сливаются в один плавный фон.
    Наследник переопределяет render_row().
    """

    DEFAULT_CSS = "GradientPanel { width: 1fr; height: 1fr; }"
    title: str = ""
    framed: bool = True

    def render_row(self, y: int, width: int, height: int) -> Text:
        return Text()

    def _compose_line(self, y: int, width: int, height: int) -> Text:
        if not self.framed:
            return self.render_row(y, width, height)
        border = Style(color=Theme.BORDER)
        if y == 0:
            label = f" {self.title} " if self.title else ""
            line = Text("╭─", border)
            line.append(label, Style(color=Theme.GOLD, bold=True))
            line.append("─" * max(0, width - 3 - cell_len(label)), border)
            line.append("╮", border)
            return line
        if y == height - 1:
            return Text("╰" + "─" * max(0, width - 2) + "╯", border)
        inner = self.render_row(y - 1, width - 4, height - 2)
        inner.truncate(max(0, width - 4), overflow="crop", pad=True)
        line = Text("│ ", border)
        line.append_text(inner)
        line.append(" │", border)
        return line

    def render_line(self, y: int) -> Strip:
        width, height = self.size
        if width <= 0:
            return Strip.blank(0)
        line = self._compose_line(y, width, height)
        line.truncate(width, overflow="crop", pad=True)
        bg = PurpleGradient.at(self.region.y + y, self.app.size.height)
        line.stylize_before(Style(bgcolor=bg))
        return Strip(list(line.render(self.app.console)), width)

    def row_bg(self, y: int) -> str:
        """Цвет фона для внутренней строки y (нужен тем, кто красит клетки сам)."""
        offset = 1 if self.framed else 0
        return PurpleGradient.at(self.region.y + y + offset, self.app.size.height)


class CatBanner(GradientPanel):
    title = "Reading Tracker ✧"
    PHRASES = ["Nyaa~ самое время почитать!", "Страничка за страничкой ♥", "Огонёк ждёт тебя — не дай ему погаснуть"]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._blink = False
        self._pulse = False
        self._tick_no = 0
        self._next_blink = 10
        self._phrase = random.choice(self.PHRASES)
        self._phrase_until = 0

    def on_mount(self) -> None:
        self.set_interval(0.25, self._tick)

    def say(self, phrase: str, seconds: float = 4.0) -> None:
        self._phrase = phrase
        self._phrase_until = self._tick_no + int(seconds / 0.25)
        self.refresh()

    def _tick(self) -> None:
        self._tick_no += 1
        self._pulse = (self._tick_no // 2) % 2 == 0
        self._blink = False
        self._next_blink -= 1
        if self._next_blink <= 0:
            self._blink = True
            self._next_blink = random.randint(10, 24)
        if self._phrase_until and self._tick_no > self._phrase_until:
            self._phrase = random.choice(self.PHRASES)
            self._phrase_until = 0
        self.refresh()

    def render_row(self, y: int, width: int, height: int) -> Text:
        art = CatFace.styled(self._blink, self._pulse)
        total = CatFace.HEIGHT + 2
        top = max(0, (height - total) // 2)
        i = y - top
        pad = " " * max(0, (width - CatFace.WIDTH) // 2)
        if 0 <= i < CatFace.HEIGHT:
            return Text(pad) + art[i]
        if i == CatFace.HEIGHT + 1:
            phrase = self._phrase
            left = max(0, (width - cell_len(phrase)) // 2)
            return Text(" " * left + phrase, Style(color=Theme.TEXT, italic=True))
        return Text()


class StreakPanel(GradientPanel):
    title = "Серия"
    TICK = 1 / 15
    SKY, DIGIT_ROWS, CAPTION_ROWS = 1, 3, 2
    DIGITS = {
        "0": ("█▀█", "█ █", "▀▀▀"), "1": ("▄█ ", " █ ", "▄█▄"), "2": ("▀▀█", "▄▀▀", "▀▀▀"),
        "3": ("▀▀█", " ▀█", "▀▀▀"), "4": ("█ █", "▀▀█", "  ▀"), "5": ("█▀▀", "▀▀█", "▀▀▀"),
        "6": ("█▀▀", "█▀█", "▀▀▀"), "7": ("▀▀█", "  █", "  ▀"), "8": ("█▀█", "█▀█", "▀▀▀"),
        "9": ("█▀█", "▀▀█", "▀▀▀"),
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.streak = 0
        self.best = 0
        self.checked_today = False
        self._sim = FireSimulation()
        self._intensity = 0.0
        self._burst = 0.0
        self._frame = 0
        self._sparks: list[Spark] = []

    def on_mount(self) -> None:
        self.set_interval(self.TICK, self._tick)

    def set_stats(self, streak: int, best: int, checked_today: bool) -> None:
        self.streak, self.best, self.checked_today = streak, best, checked_today
        self.refresh()

    def celebrate(self) -> None:
        """Вспышка огня + искры — вызывается при нажатии галочки."""
        self._burst = 3.0

    # --- геометрия ---
    def _fire_rows(self, inner_h: int) -> int:
        return max(2, inner_h - self.SKY - self.DIGIT_ROWS - self.CAPTION_ROWS)

    def _base_intensity(self) -> float:
        if self.streak == 0:
            return 0.0
        if not self.checked_today:
            return 0.32  # огонёк тлеет — серия в опасности
        return min(0.72, 0.5 + 0.025 * self.streak)

    def _tick(self) -> None:
        inner_w, inner_h = self.size.width - 4, self.size.height - 2
        if inner_w <= 0 or inner_h <= 0:
            return
        self._frame += 1
        sim_w, sim_h = min(inner_w, 16), self._fire_rows(inner_h) * 2
        if (self._sim.w, self._sim.h) != (sim_w, sim_h):
            self._sim.resize(sim_w, sim_h)
        if self._burst > 0:
            self._burst -= self.TICK
        target = 1.0 if self._burst > 0 else self._base_intensity()
        self._intensity += (target - self._intensity) * 0.2
        self._sim.step(self._intensity)
        self._update_sparks(inner_w, self.SKY + self._fire_rows(inner_h))
        self.refresh()

    def _update_sparks(self, inner_w: int, region_h: int) -> None:
        if self._burst > 0:
            for _ in range(random.randint(1, 3)):
                self._sparks.append(Spark(
                    x=inner_w / 2 + random.gauss(0, 3), y=region_h - 1.0,
                    vx=random.uniform(-0.25, 0.25), vy=-random.uniform(0.25, 0.8),
                    life=random.randint(8, 22), char=random.choice("✦*·+'")))
        alive = []
        for s in self._sparks:
            s.x += s.vx
            s.y += s.vy
            s.life -= 1
            if s.life > 0 and s.y >= 0:
                alive.append(s)
        self._sparks = alive

    # --- отрисовка ---
    def render_row(self, y: int, width: int, height: int) -> Text:
        fire_rows = self._fire_rows(height)
        fire_end = self.SKY + fire_rows
        if y < fire_end:
            return self._fire_row(y, width, fire_rows)
        y -= fire_end
        if y < self.DIGIT_ROWS:
            return self._digit_row(y, width)
        y -= self.DIGIT_ROWS
        return self._caption_row(y, width)

    def _fire_row(self, y: int, width: int, fire_rows: int) -> Text:
        bg = self.row_bg(y)
        cells: list[tuple[str, Style | None]] = [(" ", None)] * width
        r = y - self.SKY
        if r >= 0 and self._sim.w:
            pad = (width - self._sim.w) // 2
            for x in range(self._sim.w):
                top = self._sim.color(self._sim.heat[2 * r][x])
                bottom = self._sim.color(self._sim.heat[2 * r + 1][x])
                if top and bottom:
                    cells[pad + x] = ("▀", Style(color=top, bgcolor=bottom))
                elif top:
                    cells[pad + x] = ("▀", Style(color=top, bgcolor=bg))
                elif bottom:
                    cells[pad + x] = ("▄", Style(color=bottom, bgcolor=bg))
        for s in self._sparks:
            if int(s.y) == y and 0 <= int(s.x) < width:
                color = Theme.GOLD if s.life > 8 else "#ff9248" if s.life > 4 else "#ff5a3c"
                cells[int(s.x)] = (s.char, Style(color=color, bold=True))
        text = Text()
        for ch, style in cells:
            text.append(ch, style)
        return text

    def _digit_row(self, y: int, width: int) -> Text:
        digits = str(self.streak)
        glyph = "  ".join(self.DIGITS[d][y] for d in digits)
        if self._burst > 0:
            color = ("#fff1b8", Theme.GOLD, "#ff9248")[self._frame // 2 % 3]
        else:
            color = Theme.GOLD if self.streak else Theme.DIM
        pad = " " * max(0, (width - cell_len(glyph)) // 2)
        return Text(pad + glyph, Style(color=color, bold=True))

    def _caption_row(self, y: int, width: int) -> Text:
        if y == 0:
            line = f"{plural_days(self.streak)} подряд · рекорд {self.best}"
            style = Style(color=Theme.TEXT)
        elif self.checked_today:
            line, style = "сегодня засчитано ✔", Style(color=Theme.GREEN, bold=True)
        elif self.streak:
            line = "огонёк гаснет — нажми Space!"
            style = Style(color="#ff9248" if (self._frame // 8) % 2 else Theme.ACCENT, bold=True)
        else:
            line, style = "нажми Space, чтобы начать серию", Style(color=Theme.ACCENT)
        return Text(" " * max(0, (width - cell_len(line)) // 2) + line, style)


class BookListPanel(GradientPanel):
    title = "Книги"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.books: list[Book] = []
        self.index = 0

    def set_state(self, books: list[Book], index: int) -> None:
        self.books, self.index = books, index
        self.refresh()

    def _top(self, height: int) -> int:
        return max(0, min(self.index - height // 2, len(self.books) - height))

    def render_row(self, y: int, width: int, height: int) -> Text:
        if not self.books:
            lines = ["Пока здесь пусто ✧", "", "Нажми  a  — добавить первую книгу"]
            start = (height - len(lines)) // 2
            if 0 <= y - start < len(lines):
                return Text(lines[y - start].center(width), Style(color=Theme.DIM))
            return Text()
        i = self._top(height) + y
        if i >= len(self.books):
            return Text()
        book, selected = self.books[i], i == self.index
        line = Text()
        line.append(" ▶ " if selected else "   ", Style(color=Theme.ACCENT, bold=True))
        line.append("✔ " if book.is_finished else "· ", Style(color=Theme.GREEN if book.is_finished else Theme.DIM))
        line.append_text(progress_bar(book.progress, 10))
        line.append(f" {int(book.progress * 100):3d}% ", Style(color=Theme.DIM))
        line.append("↗ " if book.url else "  ", Style(color=Theme.LINK, bold=True))
        line.append(book.title, Style(color=Theme.TEXT, bold=selected))
        if book.author:
            line.append(" — " + book.author, Style(color=Theme.DIM, italic=True))
        line.truncate(width, overflow="ellipsis", pad=True)
        if selected:
            line.stylize(Style(bgcolor=Theme.SELECT_BG), 0, len(line))
        return line


class DetailsPanel(GradientPanel):
    title = "Детали"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.book: Book | None = None
        self.week = 0

    def set_state(self, book: Book | None, week: int) -> None:
        self.book, self.week = book, week
        self.refresh()

    def _lines(self, width: int) -> list[Text]:
        dim, txt = Style(color=Theme.DIM), Style(color=Theme.TEXT)
        b = self.book
        if b is None:
            return [Text("Выбери книгу слева", dim)]
        pages = f"{b.current_page} / {b.total_pages} стр." if b.total_pages else f"стр. {b.current_page}"
        status = (Text(f"✔ прочитана {b.finished_on}", Style(color=Theme.GREEN, bold=True)) if b.is_finished
                  else Text("● читаю сейчас", Style(color=Theme.GOLD)))
        if b.url:
            link = Text(b.url, Style(color=Theme.LINK, underline=True, link=b.url))
        else:
            link = Text("нет — нажми e, чтобы добавить", dim)
        return [
            fit(Text(b.title, Style(color=Theme.TEXT, bold=True)), width),
            fit(Text(b.author or "автор не указан", Style(color=Theme.DIM, italic=True)), width),
            Text(),
            progress_bar(b.progress, max(4, width - 2)),
            Text(f"{pages}  ({int(b.progress * 100)}%)", txt),
            status,
            Text(f"добавлена {b.added_on}", dim),
            Text(),
            Text("электронная книга  (o — открыть):", dim),
            fit(link, width),
            Text(),
            Text(f"за 7 дней читал(а): {self.week}/7", dim),
        ]

    def render_row(self, y: int, width: int, height: int) -> Text:
        lines = self._lines(width)
        return lines[y] if y < len(lines) else Text()


class HotkeyBar(GradientPanel):
    framed = False
    DEFAULT_CSS = "HotkeyBar { height: 2; }"

    def render_row(self, y: int, width: int, height: int) -> Text:
        rows: list[Text] = [Text()]
        for hk in (h for h in HOTKEYS if h.in_bar):
            item = Text()
            item.append(f" {hk.keys} ", Style(color="#1b0638", bgcolor=Theme.ACCENT, bold=True))
            item.append(f" {hk.label}  ", Style(color=Theme.TEXT))
            if rows[-1].cell_len + item.cell_len > width and rows[-1].cell_len:
                rows.append(Text())
            rows[-1].append_text(item)
        return rows[y] if y < len(rows) else Text()


class SplashView(GradientPanel):
    framed = False
    TITLE = "R E A D I N G   T R A C K E R"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tick_no = 0
        self._blink = False
        self._next_blink = 14

    def on_mount(self) -> None:
        self.set_interval(0.06, self._tick)

    def _tick(self) -> None:
        self._tick_no += 1
        self._blink = False
        self._next_blink -= 1
        if self._next_blink <= 0:
            self._blink = True
            self._next_blink = random.randint(25, 50)
        self.refresh()

    def _content(self, width: int) -> list[Text]:
        pulse = (self._tick_no // 8) % 2 == 0
        art = CatFace.styled(self._blink, (self._tick_no // 6) % 2 == 0)
        pad = " " * max(0, (width - CatFace.WIDTH) // 2)
        rows = [Text(pad) + line for line in art]
        shown = self.TITLE[: self._tick_no // 2]
        title = Text()
        for i, ch in enumerate(shown):
            title.append(ch, Style(color=lerp_hex(Theme.ACCENT, Theme.BORDER, i / len(self.TITLE)), bold=True))
        left = " " * max(0, (width - len(self.TITLE)) // 2)
        rows += [Text(), Text(left) + title, Text()]
        sub = "трекер чтения для терминала  ✧  серия, огонёк и котик"
        rows.append(Text(sub.center(width), Style(color=Theme.DIM, italic=True)))
        rows.append(Text())
        prompt = "нажми любую клавишу" if pulse else "· нажми любую клавишу ·"
        rows.append(Text(prompt.center(width), Style(color=Theme.GOLD if pulse else Theme.TEXT, bold=True)))
        return rows

    def render_row(self, y: int, width: int, height: int) -> Text:
        rows = self._content(width)
        i = y - max(0, (height - len(rows)) // 2)
        return rows[i] if 0 <= i < len(rows) else Text()


# ════════════════════════════════════════════════════════════════════
#  ЭКРАНЫ
# ════════════════════════════════════════════════════════════════════
class SplashScreen(Screen):
    def compose(self) -> ComposeResult:
        yield SplashView()

    def on_key(self, event) -> None:
        event.stop()
        self.app.pop_screen()

    def on_click(self) -> None:
        self.app.pop_screen()


class PromptScreen(ModalScreen[str | None]):
    """Маленькое окно с одним полем ввода."""

    BINDINGS = [Binding("escape", "cancel", "Отмена")]

    def __init__(self, title: str, value: str = "", placeholder: str = "", hint: str = "",
                 input_type: str = "text") -> None:
        super().__init__()
        self._title, self._value, self._placeholder = title, value, placeholder
        self._hint, self._type = hint, input_type

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._title, classes="dialog-title")
            yield Input(value=self._value, placeholder=self._placeholder, type=self._type, id="field")
            yield Label(self._hint or "Enter — сохранить · Esc — отмена", classes="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BookFormScreen(ModalScreen[dict | None]):
    """Форма добавления книги."""

    BINDINGS = [Binding("escape", "cancel", "Отмена")]
    FIELDS = ["f-title", "f-author", "f-pages", "f-url"]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Новая книга", classes="dialog-title")
            yield Label("Название", classes="field-label")
            yield Input(placeholder="Например: Мастер и Маргарита", id="f-title")
            yield Label("Автор", classes="field-label")
            yield Input(placeholder="Михаил Булгаков", id="f-author")
            yield Label("Страниц всего (можно 0)", classes="field-label")
            yield Input(placeholder="480", type="integer", id="f-pages")
            yield Label("Ссылка на электронную книгу (Флибуста, Книжное братство, любая другая)", classes="field-label")
            yield Input(placeholder="https://…", id="f-url")
            yield Label("Enter — следующее поле · на последнем Enter сохраняет · Esc — отмена", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#f-title", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        idx = self.FIELDS.index(event.input.id or "")
        if idx < len(self.FIELDS) - 1:
            self.query_one(f"#{self.FIELDS[idx + 1]}", Input).focus()
        else:
            self._submit()

    def _submit(self) -> None:
        title = self.query_one("#f-title", Input).value.strip()
        if not title:
            self.notify("Название не может быть пустым", severity="warning")
            self.query_one("#f-title", Input).focus()
            return
        pages = self.query_one("#f-pages", Input).value.strip()
        self.dismiss({
            "title": title,
            "author": self.query_one("#f-author", Input).value,
            "total_pages": int(pages) if pages.isdigit() else 0,
            "url": self.query_one("#f-url", Input).value,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("y", "yes", "Да"), Binding("n,escape", "no", "Нет")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._question, classes="dialog-title")
            yield Label("y — да · n / Esc — нет", classes="hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    def compose(self) -> ComposeResult:
        text = Text()
        for hk in HOTKEYS:
            text.append(f" {hk.keys:<9}", Style(color="#1b0638", bgcolor=Theme.ACCENT, bold=True))
            text.append(f"  {hk.description}\n", Style(color=Theme.TEXT))
        with Vertical(classes="dialog"):
            yield Label("Горячие клавиши", classes="dialog-title")
            yield Static(text)
            yield Label("любая клавиша — закрыть", classes="hint")

    def on_key(self, event) -> None:
        event.stop()
        self.dismiss(None)


class MainScreen(Screen):
    BINDINGS = [
        Binding("j,down", "move(1)", "Вниз", show=False),
        Binding("k,up", "move(-1)", "Вверх", show=False),
        Binding("g,home", "jump(0)", "В начало", show=False),
        Binding("G,end", "jump(-1)", "В конец", show=False),
        Binding("space", "check_in", "Прочитал", show=False),
        Binding("u", "undo_today", "Отменить", show=False),
        Binding("p", "set_page", "Страница", show=False),
        Binding("a", "add_book", "Новая", show=False),
        Binding("o", "open_link", "Открыть", show=False),
        Binding("e", "edit_link", "Ссылка", show=False),
        Binding("d", "delete_book", "Удалить", show=False),
        Binding("question_mark", "help", "Помощь", show=False),
        Binding("q", "quit_app", "Выход", show=False),
    ]

    def __init__(self, library: Library) -> None:
        super().__init__()
        self.library = library
        self.index = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield CatBanner(id="cat")
            yield StreakPanel(id="streak")
        with Horizontal(id="middle"):
            yield BookListPanel(id="books")
            yield DetailsPanel(id="details")
        yield HotkeyBar(id="hotkeys")

    def on_mount(self) -> None:
        self.sync()

    @property
    def selected(self) -> Book | None:
        books = self.library.books
        return books[self.index] if 0 <= self.index < len(books) else None

    def sync(self) -> None:
        books = self.library.books
        self.index = max(0, min(self.index, len(books) - 1))
        log = self.library.log
        self.query_one(BookListPanel).set_state(books, self.index)
        self.query_one(DetailsPanel).set_state(self.selected, log.week_count())
        self.query_one(StreakPanel).set_stats(log.current_streak(), log.best_streak(), log.is_marked())

    # --- навигация ---
    def action_move(self, delta: int) -> None:
        self.index += delta
        self.sync()

    def action_jump(self, where: int) -> None:
        self.index = 0 if where == 0 else len(self.library.books) - 1
        self.sync()

    # --- чтение / серия ---
    def _check_in(self, announce: bool = True) -> None:
        is_new = self.library.check_in_today()
        self.sync()
        streak = self.library.log.current_streak()
        self.query_one(StreakPanel).celebrate()
        cat = self.query_one(CatBanner)
        if is_new:
            cat.say(f"Умничка! ♥ Серия: {streak} {plural_days(streak)}")
            if announce:
                self.notify(f"Серия: {streak} {plural_days(streak)} подряд", title="Огонёк горит!")
        elif announce:
            cat.say("Сегодня уже засчитано — так держать!")
            self.notify("Сегодня уже засчитано", title="Огонёк горит")

    def action_check_in(self) -> None:
        if not self.library.books:
            self.notify("Сначала добавь книгу — клавиша a", severity="warning")
            return
        self._check_in()

    def action_undo_today(self) -> None:
        self.library.undo_today()
        self.sync()
        self.notify("Отметка за сегодня снята")

    # --- страницы ---
    def action_set_page(self) -> None:
        book = self.selected
        if not book:
            return
        limit = f" из {book.total_pages}" if book.total_pages else ""
        self.app.push_screen(
            PromptScreen(f"На какой ты странице{limit}?", str(book.current_page), input_type="integer"),
            self._on_page)

    def _on_page(self, value: str | None) -> None:
        book = self.selected
        if value is None or not book:
            return
        if not value.strip().isdigit():
            self.notify("Нужно число", severity="warning")
            return
        progressed = self.library.set_page(book, int(value))
        self.sync()
        if book.is_finished:
            self.notify(f"«{book.title}» прочитана!", title="Книга закончена ✔")
        if progressed:
            self._check_in(announce=not book.is_finished)

    # --- книги ---
    def action_add_book(self) -> None:
        self.app.push_screen(BookFormScreen(), self._on_book_added)

    def _on_book_added(self, data: dict | None) -> None:
        if not data:
            return
        self.library.add_book(**data)
        self.index = len(self.library.books) - 1
        self.sync()

    def action_delete_book(self) -> None:
        book = self.selected
        if not book:
            return
        self.app.push_screen(ConfirmScreen(f"Удалить «{book.title}»?"), self._on_delete)

    def _on_delete(self, confirmed: bool | None) -> None:
        book = self.selected
        if confirmed and book:
            self.library.remove_book(book)
            self.sync()

    # --- ссылка ---
    def action_open_link(self) -> None:
        book = self.selected
        if not book:
            return
        if not book.url:
            self.notify("У книги нет ссылки — нажми e", severity="warning")
            return
        try:
            opened = webbrowser.open(book.url)
        except webbrowser.Error:
            opened = False
        if opened:
            self.notify(book.url, title="Открываю в браузере")
        else:
            self.notify(f"Не смог открыть браузер. Ссылка: {book.url}", severity="warning", timeout=10)

    def action_edit_link(self) -> None:
        book = self.selected
        if not book:
            return
        self.app.push_screen(
            PromptScreen("Ссылка на электронную книгу", book.url, "https://…",
                         "Enter — сохранить · пустая строка удалит ссылку · Esc — отмена"),
            self._on_link)

    def _on_link(self, value: str | None) -> None:
        book = self.selected
        if value is None or not book:
            return
        self.library.set_url(book, value)
        self.sync()

    # --- прочее ---
    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_quit_app(self) -> None:
        self.app.exit()


class ReadingTrackerApp(App):
    TITLE = "Reading Tracker"
    CSS = """
    Screen { background: #0b0120; }
    #top { height: 17; }
    #cat { width: 1fr; height: 100%; }
    #streak { width: 36; height: 100%; }
    #middle { height: 1fr; }
    #books { width: 1fr; height: 100%; }
    #details { width: 44; height: 100%; }

    PromptScreen, BookFormScreen, ConfirmScreen, HelpScreen {
        align: center middle;
        background: rgba(8, 0, 20, 0.75);
    }
    .dialog {
        width: 78; height: auto; max-height: 90%;
        background: #1b0638; border: round #9d6bff; padding: 1 2;
    }
    .dialog-title { color: #ffd166; text-style: bold; }
    .field-label { color: #cdb7ff; margin-top: 1; }
    .hint { color: #a592d6; margin-top: 1; }
    Input { background: #2a0e52; border: tall #6d28d9; color: #f1e8ff; }
    Input:focus { border: tall #ff7ad9; }
    """

    def __init__(self, library: Library | None = None, splash: bool = True) -> None:
        super().__init__()
        self.library = library or Library()
        self.splash = splash

    def on_mount(self) -> None:
        self.push_screen(MainScreen(self.library))
        if self.splash:
            self.push_screen(SplashScreen())


def main() -> None:
    ReadingTrackerApp(splash="--no-splash" not in sys.argv).run()


if __name__ == "__main__":
    main()
