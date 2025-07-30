import os
import sys
import json
import random
import shutil
import time
import threading
import flet
from flet import (
    Page, TextField, ElevatedButton, Column, Row, Text, Icon,
    Tabs, Tab, Dropdown, dropdown, Switch, FilePicker,
    FilePickerResultEvent, Container, Colors, ThemeMode,
    Checkbox, alignment, border_radius, border, padding,
    SnackBar, IconButton, Icons, CupertinoAlertDialog, CupertinoDialogAction
)

# ─── 1) Определяем две разные директории ────────────────────────────
if getattr(sys, "frozen", False):
    # при --onefile PyInstaller распаковывает ресурсы в _MEIPASS
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    # а данные (настройки, слова) храним рядом с exe
    DATA_DIR     = os.path.dirname(sys.executable)
else:
    RESOURCE_DIR = os.path.dirname(__file__)
    DATA_DIR     = RESOURCE_DIR

# ─── 2) Пути к ресурсам и к данным ───────────────────────────────────
LANG_FILE     = os.path.join(RESOURCE_DIR,   "langs.json")
ICON_FILE     = os.path.join(RESOURCE_DIR,   "assets", "icon.png")

SETTINGS_FILE = os.path.join(DATA_DIR,       "settings.json")
WORDS_DIR     = os.path.join(DATA_DIR,       "words")
# ======================================

DEFAULT_SET = {
    "title": "Default Set",
    "cards": [
        {"word": "猫", "translation": "Cat", "romaji": "neko"},
        {"word": "犬", "translation": "Dog", "romaji": "inu"},
    ]
}

def load_translations():
    try:
        with open(LANG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

class FlashcardApp:
    def __init__(self, page: Page):
        self.page = page
        page.window_icon      = ICON_FILE
        page.title            = "KotoYon"
        page.window_maximized = True

        # i18n
        self.i18n = load_translations()

        # ensure words folder + template
        os.makedirs(WORDS_DIR, exist_ok=True)
        tpl = os.path.join(WORDS_DIR, "template.json")
        if not os.path.exists(tpl):
            with open(tpl, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SET, f, ensure_ascii=False, indent=2)

        # load settings
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({
                "theme": "light",
                "language": "en",
                "romaji_mode": False,
                "show_romaji": False,
                "direction_reversed": False,
                "selected_dict": "template.json",
                "selected_file": "template.json",
                "fat_mode": False,
                "tests_taken": 0,
                "correct_answers": 0,
                "total_questions": 0,
                "enable_hint": False,
                "hint_threshold": 5
                }, f, ensure_ascii=False, indent=2)
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            self.settings = json.load(f)
        # NEW SETTINGS ATTRIBUTES
        self.romaji_mode     = self.settings.get("romaji_mode", False)
        self.fat_mode        = self.settings.get("fat_mode", False)
        self.tests_taken     = self.settings.get("tests_taken", 0)
        self.correct_answers = self.settings.get("correct_answers", 0)
        self.total_questions = self.settings.get("total_questions", 0)

        # вот эти две — для подсказок
        self.enable_hint     = self.settings.get("enable_hint", False)
        self.hint_threshold  = self.settings.get("hint_threshold", 5)

        self.selected_file   = self.settings.get("selected_file", "template.json")
        self.lang            = self.settings["language"]
        page.theme_mode      = ThemeMode.DARK if self.settings["theme"]=="dark" else ThemeMode.LIGHT
        self.show_romaji     = self.settings["show_romaji"]
        self.direction_reversed = self.settings["direction_reversed"]


        # state
        self.vocab   = []
        self.results = []
        self.fields: list[TextField] = []

        # editor state
        self.word_rows     = None
        self.word_inputs   = []
        self.is_editing    = False
        self.editing_file  = None

        # FilePicker
        self.fp = FilePicker(on_result=self.file_picked)
        page.overlay.append(self.fp)

        # back button
        self.back_btn = ElevatedButton(self.t("back_home"), on_click=self.back_home)

        # build UI
        self.build_pages()
        self.build_tabs()

        # add to page
        page.add(self.tabs, self.test_page, self.results_page, self.words_page)

        # init labels/values
        self.refresh_labels()
        self.page.update()



    def toggle_hint(self, e):
        # 1) обновляем атрибут приложения
        self.enable_hint = e.control.value
        # 2) сохраняем в settings и на диск
        self.settings["enable_hint"] = self.enable_hint
        self.save_settings()
        # 3) перерисовываем страницу (чтобы переключатель оставался в новом положении)
        self.page.update()

    def show_hint_info(self, e):
        # Формируем текст с актуальным порогом из self.hint_threshold
        content_text = self.t("hint_info_content").format(threshold=self.hint_threshold)

        dlg = CupertinoAlertDialog(
            title=Text(self.t("hint_info_title")),
            content=Text(content_text),
            actions=[
                CupertinoDialogAction(self.t("ok"),
                                      on_click=lambda ev: self._dismiss(ev))
            ],
            open=True
        )
        self.page.overlay.append(dlg)
        self.page.update()


    def change_hint_threshold(self, e):
        # приходим сюда и по Enter, и при blur
        try:
            # от 1 до бесконечности
            v = max(1, int(e.control.value))
            # обновляем атрибут
            self.hint_threshold = v
            # сохраняем
            self.settings["hint_threshold"] = v
            self.save_settings()
        except:
            pass
        # приводим поле к корректному значению из атрибута
        e.control.value = str(self.hint_threshold)
        e.control.update()



    

    def _dismiss(self, e):
        e.control.page.overlay[-1].open = False
        e.control.page.update()






    def t(self, key):
        return self.i18n.get(self.lang, {}).get(key, f"<{key}>")

    def save_settings(self):
        self.settings.update({
            "theme": "dark" if self.page.theme_mode==ThemeMode.DARK else "light",
            "language": self.lang,
            "romaji_mode": self.romaji_mode,
            "show_romaji": self.show_romaji,
            "direction_reversed": self.direction_reversed,
            "selected_file": self.selected_file,
            "fat_mode": self.fat_mode,
            "tests_taken": self.tests_taken,
            "correct_answers": self.correct_answers,
            "total_questions": self.total_questions,
            "enable_hint": self.enable_hint,
            "hint_threshold": self.hint_threshold
        })
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)

    def _compute_columns(self, count: int) -> int:
        for c in (4,3,2):
            if count % c == 0:
                return c
        return min(count,4)
    


    # FILE PICKER IMPORT
    def file_picked(self, e: FilePickerResultEvent):
        if not e.files:
            return
        src = e.files[0].path
        dst = os.path.join(WORDS_DIR, os.path.basename(src))

        # Копируем временно в WORDS_DIR
        try:
            shutil.copy(src, dst)
        except Exception as ex:
            sb = SnackBar(Text(self.t("copy_error").format(error=ex)))
            self.page.snack_bar = sb; sb.open = True; self.page.update()
            return

        # ВАЛИДАЦИЯ импортированного файла
        valid = True
        err_msg = ""
        try:
            with open(dst, encoding="utf-8") as f:
                data = json.load(f)
            # проверяем, что есть ключ "cards" и это список
            cards = data.get("cards")
            if not isinstance(cards, list):
                valid = False
                err_msg = self.t("import_error_no_cards")
            else:
                # каждый элемент должен быть dict с word и translation
                for i, c in enumerate(cards):
                    if not isinstance(c, dict) or \
                    "word" not in c or not isinstance(c["word"], str) or \
                    "translation" not in c or not isinstance(c["translation"], str):
                        valid = False
                        err_msg = self.t("import_error_bad_card").format(idx=i+1)
                        break
        except Exception as ex:
            valid = False
            err_msg = self.t("import_error_json").format(error=ex)

        if not valid:
            # удаляем скопированный некорректный файл
            try:
                os.remove(dst)
            except:
                pass
            # показываем SnackBar с ошибкой
            sb = SnackBar(Text(err_msg))
            self.page.snack_bar = sb; sb.open = True; self.page.update()
            return

        # Если всё ок — регистрируем файл в списках
        opts = []
        for fn in os.listdir(WORDS_DIR):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(WORDS_DIR, fn), encoding="utf-8"))
                    title = d.get("title", fn)
                except:
                    title = fn
                opts.append(dropdown.Option(fn, text=title))

        new_name = os.path.basename(src)
        self.file_dd.options   = opts
        self.file_dd.value     = new_name
        self.selected_file     = new_name
        self.save_settings()
        self.file_dd.update()

    def file_changed(self, e):
        self.selected_file = e.control.value
        self.save_settings()

    def toggle_direction(self, e):
        self.direction_reversed = e.control.value; self.save_settings()
    def toggle_romaji(self, e):
        self.show_romaji = e.control.value; self.save_settings()
    def toggle_theme(self, e):
        self.page.theme_mode = ThemeMode.DARK if e.control.value else ThemeMode.LIGHT
        self.page.update(); self.save_settings()
    def change_language(self, e):
        self.lang = e.control.value; self.save_settings(); self.refresh_labels(); self.page.update()

    def back_home(self, e):
        self.test_page.visible    = False
        self.results_page.visible = False
        self.words_page.visible   = False
        self.tabs.visible         = True
        self.tabs.selected_index  = 0
        self.page.update()

    def on_answer(self, e, idx):
        tf = e.control
        if tf.disabled:
            return

        # 1) увеличиваем число попыток
        self.results[idx]["attempts"] += 1

        # 2) проверяем ответ
        key = "word" if self.direction_reversed else "translation"
        variants = [
            v.strip().lower()
            for v in self.vocab[idx][key].split(",")
            if v.strip()
        ]
        ent = tf.value.strip().lower()
        # если режим перевод→слово и включён ромадзи‑мод, добавляем варианты ромадзи
        if self.direction_reversed and self.romaji_mode:
            roms = [
                r.strip().lower()
                for r in self.vocab[idx].get("romaji", "").split(",")
                if r.strip()
            ]
            variants.extend(roms)

        corr = ent in variants

        self.results[idx]["entered"] = tf.value.strip()
        self.results[idx]["correct"] |= corr

        # 3) если ответ верный — учитываем статистику
        if corr and self.results[idx]["attempts"] == 1:
            self.correct_answers += 1
            self.save_settings()

        # 4) цвет поля
        if corr:
            tf.bgcolor = Colors.with_opacity(0.5, Colors.GREEN)
        else:
            tf.bgcolor = Colors.with_opacity(0.3, Colors.RED)
        tf.disabled = corr
        tf.update()

        # 5) подсказка после порога
        thr = self.hint_threshold
        if (not corr and self.enable_hint and self.results[idx]["attempts"] >= thr):
            # выбираем текст подсказки
            if self.direction_reversed and self.romaji_mode:
                hint_text = self.vocab[idx].get("romaji", "").strip()
            else:
                key2 = "translation" if not self.direction_reversed else "word"
                hint_text = self.vocab[idx].get(key2, "").strip()

            # показываем первую букву, если есть минимум 2 символа
            if len(hint_text) > 1:
                hint_letter = hint_text[0]
                prefix = self.t("hint_prefix")
                tf.label = f"{self.t('answer')} ({prefix}{hint_letter})"
                tf.update()

        # 6) фокус на следующее поле
        nxt = idx + 1
        if nxt < len(self.fields):
            self.fields[nxt].focus()
        else:
            tf.blur()
        self.page.update()


    # ─────────── BUILD PAGES ─────────────────────────────────────────────────────
    def build_pages(self):
        self.test_page    = Column(visible=False, expand=True, scroll="auto")
        self.results_page = Column(visible=False, expand=True, scroll="auto")
        self.words_page   = Column(visible=False, expand=True, scroll="auto")

        # Editor tab
        self.dict_selector = Dropdown(
            label=self.t("select_dictionary"),
            options=self.get_dict_options(),
            on_change=self.load_selected_dict,
            width=200
        )
        # кнопка + новый
        self.btn_new = IconButton(
            icon=Icons.ADD_CIRCLE_OUTLINED,
            tooltip=self.t("new_dict"),
            on_click=lambda e: self._start_new_dict()
        )
        # иконка удаления
        self.btn_delete = IconButton(
            icon=Icons.DELETE,
            tooltip=self.t("delete_dict"),
            on_click=self.confirm_delete_dict,
            icon_color=Colors.RED
        )

        self.new_dict_name = TextField(label=self.t("new_dict_name"), width=300)
        self.word_rows     = Column(controls=[], spacing=4, expand=True, scroll="auto")
        self.word_inputs   = []
        self.btn_add_word  = ElevatedButton(self.t("add_row"), icon=Icons.ADD, on_click=lambda e:self._add_word_row())
        self.btn_save_dict = ElevatedButton(
            self.t("create_dict"),
            icon=Icons.SAVE,
            on_click=lambda e: self.save_dict()   # e будет отброшен
        )


        # создаём чекбокс Sentence Mode (с учётом i18n)
        self.sentence_mode_cb = Checkbox(
            label=self.t("sentence_mode"),
            value=self.settings.get("sentence_mode", False),
            on_change=self.toggle_sentence_mode
        )


        self.create_tab = Container(
            content=Column([
                Row([self.dict_selector, self.btn_new, self.btn_delete], spacing=8),
                self.new_dict_name,
                Row([self.sentence_mode_cb], spacing=4),  
                self.word_rows,
                Row([self.btn_add_word, self.btn_save_dict], spacing=16)
            ], expand=True, spacing=10),
            padding=padding.all(20)
        )

    def get_dict_options(self):
        return [dropdown.Option(fn, text=os.path.splitext(fn)[0])
                for fn in os.listdir(WORDS_DIR) if fn.endswith(".json")]

    def _start_new_dict(self):
        # сброс режима редактирования
        self.is_editing    = False
        self.editing_file  = None

        # сбрасываем селектор редактора
        self.dict_selector.value = None
        self.dict_selector.update()

        # очищаем поля
        self.new_dict_name.value = ""
        self.word_rows.controls.clear()
        self.word_inputs.clear()

        # текст кнопки — «Создать»
        self.btn_save_dict.text = self.t("create_dict")
        self.page.update()



    def _add_word_row(self, word="", tr="", rom=""):
        # Создаём поля
        tf1 = TextField(label=self.t("word"),        expand=True, value=word)
        tf2 = TextField(label=self.t("translation"), expand=True, value=tr)
        tf3 = TextField(label=self.t("romaji"),      expand=True, value=rom)
        del_btn = IconButton(
            icon=Icons.DELETE,
            tooltip=self.t("remove_row"),
            icon_color=Colors.RED
        )

        # Вся строка
        row = Row([tf1, tf2, tf3, del_btn], spacing=8)

        # Кортеж для удобного удаления
        trio = (tf1, tf2, tf3)
        self.word_inputs.append(trio)
        self.word_rows.controls.append(row)

        # Колбэк: убираем и из контролов, и из списка данных
        def on_delete(e):
            if row in self.word_rows.controls:
                self.word_rows.controls.remove(row)
            if trio in self.word_inputs:
                self.word_inputs.remove(trio)
            self.word_rows.update()

        del_btn.on_click = on_delete

        # Обновляем интерфейс редактора
        self.word_rows.update()


    def load_selected_dict(self, e):
        fn = e.control.value
        if not fn:
            return

        path = os.path.join(WORDS_DIR, fn)
        # 1) Попытка загрузить JSON
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            # в случае ошибки заводим пустую структуру
            data = {
                "title": os.path.splitext(fn)[0],
                "cards": [],
                "sentence_mode": False
            }

        # 2) Устанавливаем режим редактирования и файл
        self.is_editing   = True
        self.editing_file = path

        # 3) Заполняем поля редактора
        self.new_dict_name.value = data.get("title", os.path.splitext(fn)[0])
        # синхронизируем чекбокс sentence_mode
        self.sentence_mode_cb.value = data.get("sentence_mode", False)
        self.sentence_mode_cb.update()

        # 4) Чистим старые строки и добавляем новые
        self.word_rows.controls.clear()
        self.word_inputs.clear()
        for c in data.get("cards", []):
            self._add_word_row(c.get("word",""),
                            c.get("translation",""),
                            c.get("romaji",""))

        # 5) Обновляем текст кнопки и сам селектор
        self.btn_save_dict.text     = self.t("save_dict")
        self.dict_selector.value    = fn
        self.dict_selector.update()

        # 6) Фрешим страницу
        self.page.update()


    def save_dict(self, e=None):
        # 1) Собираем название и карточки
        name = self.new_dict_name.value.strip()
        if not name:
            # Можно показать SnackBar с ошибкой:
            sb = SnackBar(Text(self.t("empty_name_error")))
            self.page.snack_bar = sb; sb.open = True; self.page.update()
            return

        cards = []
        for tf1, tf2, tf3 in self.word_inputs:
            w = tf1.value.strip()
            t = tf2.value.strip()
            if not w or not t:
                continue
            card = {"word": w, "translation": t}
            if tf3.value.strip():
                card["romaji"] = tf3.value.strip()
            cards.append(card)
        if not cards:
            sb = SnackBar(Text(self.t("empty_cards_error")))
            self.page.snack_bar = sb; sb.open = True; self.page.update()
            return

        # 2) Определяем путь: редактируем или создаём новый
        if self.is_editing and self.editing_file:
            path = self.editing_file
        else:
            filename = f"{name.replace(' ', '_')}.json"
            path = os.path.join(WORDS_DIR, filename)
            self.is_editing   = True
            self.editing_file = path
            self.selected_file = filename
            # сохраним, чтобы новая книжка сразу выбралась в главном табе
            self.save_settings()

        # 3) Собираем payload с флагом sentence_mode
        payload = {
            "title": name,
            "cards": cards,
            "sentence_mode": self.sentence_mode_cb.value
        }

        # 4) Записываем JSON на диск
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            sb = SnackBar(Text(self.t("save_error").format(error=ex)))
            self.page.snack_bar = sb; sb.open = True; self.page.update()
            return

        # 5) Обновляем выпадашки в main-tab и в editor-tab
        # — MAIN TAB
        main_opts = []
        for fn in os.listdir(WORDS_DIR):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(WORDS_DIR, fn), encoding="utf-8"))
                    txt = d.get("title", fn)
                except:
                    txt = fn
                main_opts.append(dropdown.Option(fn, text=txt))
        self.file_dd.options = main_opts
        self.file_dd.value   = self.selected_file

        # — EDITOR TAB
        self.dict_selector.options = self.get_dict_options()
        self.dict_selector.value   = os.path.basename(path)

        # 6) Пушим SnackBar об успехе
        sb = SnackBar(Text(self.t("saved_success").format(fname=os.path.basename(path))))
        self.page.snack_bar = sb; sb.open = True

        # 7) Обновляем UI
        self.page.update()


    def confirm_delete_dict(self, e):
        fn = self.dict_selector.value
        if not fn:
            return
        def on_dismiss(ev):
            cupertino_dialog.open = False
            ev.control.page.update()
        def on_confirm(ev):
            self._delete_dict(fn)
            on_dismiss(ev)

        cupertino_dialog = CupertinoAlertDialog(
            title=Text(self.t("confirm_delete")),
            content=Text(f"{self.t('really_delete')} {fn}?"),
            actions=[
                CupertinoDialogAction(self.t("yes"), is_destructive_action=True, on_click=on_confirm),
                CupertinoDialogAction(self.t("no"), on_click=on_dismiss),
            ],
        )
        self.page.overlay.append(cupertino_dialog)
        cupertino_dialog.open = True
        self.page.update()

    def _delete_dict(self, fn):
        path = os.path.join(WORDS_DIR, fn)
        if os.path.exists(path):
            os.remove(path)

        # обновляем главный dropdown
        main_opts = []
        for f in os.listdir(WORDS_DIR):
            if f.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(WORDS_DIR, f), encoding="utf-8"))
                    title = d.get("title", f)
                except:
                    title = f
                main_opts.append(dropdown.Option(f, text=title))
        self.file_dd.options = main_opts

        # если только что удалённый был выбран, сбросим selection
        if self.selected_file == fn:
            self.selected_file = None
            self.file_dd.value = None
        else:
            # сохраняем прежний выбор
            self.file_dd.value = self.selected_file

        self.file_dd.update()

        # сбрасываем форму редактора
        self.dict_selector.options = self.get_dict_options()
        self.dict_selector.value   = None
        self.dict_selector.update()

        self.new_dict_name.value = ""
        self.word_rows.controls.clear()
        self.word_inputs.clear()
        self.is_editing   = False
        self.editing_file = None

        # возвращаем текст кнопки
        self.btn_save_dict.text = self.t("create_dict")
        self.page.update()

    # BUILD TABS
    def build_tabs(self):
        logo  = Icon(Icons.SCHOOL, size=72, color=Colors.BLUE)
        title = Text("KotoYon", size=64, weight="bold", color=Colors.BLUE)
        self.start_btn      = ElevatedButton(self.t("start_test"), icon=Icons.PLAY_ARROW, on_click=self.start_test)
        self.view_words_btn = ElevatedButton(self.t("show_words"), icon=Icons.LIST, on_click=self.show_words)
        opts = []
        for fn in os.listdir(WORDS_DIR):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(WORDS_DIR, fn), encoding="utf-8"))
                    txt = d.get("title", fn)
                except:
                    txt = fn
                opts.append(dropdown.Option(fn, text=txt))
        self.file_dd      = Dropdown(options=opts, value=self.selected_file,
                                     on_change=self.file_changed, label=self.t("dictionary"))
        self.add_file_btn = ElevatedButton("+", tooltip=self.t("add_file"),
                                           on_click=lambda e: self.fp.pick_files())
        self.dir_switch   = Switch(label=self.t("reverse_test"), value=self.direction_reversed,
                                   on_change=self.toggle_direction)

        main_tab = Container(
            content=Column([
                Row([logo, title], alignment="center", spacing=20),
                Row([self.file_dd, self.add_file_btn], alignment="center", spacing=8),
                Row([self.start_btn, self.view_words_btn], alignment="center", spacing=20),
                Row([self.dir_switch], alignment="center"),
            ], alignment="center", horizontal_alignment="center", expand=True, spacing=30),
            padding=padding.all(20)
        )

        # settings
        self.settings_header = Text(self.t("settings"), size=24, weight="bold")
        self.theme_switch    = Switch(
            label=self.t("dark_theme"),
            value=(self.page.theme_mode == ThemeMode.DARK),
            on_change=self.toggle_theme
        )
        self.lang_dd         = Dropdown(
            label=self.t("lang_interface"), width=180,
            options=[dropdown.Option(k, text=k.upper()) for k in self.i18n.keys()],
            value=self.lang, on_change=self.change_language
        )
        # показывать ромадзи под словом/переводом
        self.romaji_cb       = Checkbox(
            label=self.t("show_romaji"),
            value=self.show_romaji,
            on_change=self.toggle_romaji
        )
        # режим ромадзи: ввод в ромадзи считается правильным (новый чекбокс)
        self.romaji_mode_cb  = Checkbox(
            label=self.t("romaji_mode"),  # убедись, что в langs.json есть ключ "romaji_mode"
            value=self.romaji_mode,
            on_change=lambda e: setattr(self, "romaji_mode", e.control.value) or self.save_settings()
        )
        # настройка подсказки
        self.hint_switch     = Switch(
            label=self.t("enable_hint"),
            value=self.settings.get("enable_hint", False),
            on_change=self.toggle_hint
        )
        # мини‑кнопка «i» для описания подсказки
        self.hint_info_btn   = IconButton(
            icon=Icons.INFO_OUTLINE,
            tooltip=self.t("hint_info_tooltip"),
            on_click=self.show_hint_info
        )
        self.hint_threshold_tf = TextField(
            label=self.t("hint_threshold_label"),
            width=100,
            value=str(self.settings.get("hint_threshold", 5)),
            on_submit=self.change_hint_threshold,
            on_blur=self.change_hint_threshold
        )

        self.donate_btn = ElevatedButton(
            "Donate ☕",
            tooltip="Support KotoYon on Ko‑fi",
            on_click=lambda e: self.page.launch_url("https://ko-fi.com/kotoyon_by_lezka")
        )

        settings_tab = Container(
            content=Column([
                self.settings_header,
                self.theme_switch,
                self.lang_dd,
                self.romaji_cb,
                self.romaji_mode_cb,
                Row([self.hint_switch, self.hint_info_btn], spacing=4),
                self.hint_threshold_tf,
                self.donate_btn,
            ], spacing=20, alignment="start", expand=True),
            padding=padding.all(20)
        )

        self.tabs = Tabs(tabs=[
            Tab(text=self.t("main_title"),   content=main_tab),
            Tab(text=self.t("settings"),     content=settings_tab),
            Tab(text=self.t("create_title"), content=self.create_tab),
        ], expand=True)

    # REFRESH LABELS
    def refresh_labels(self):
        # ── MAIN ──
        self.tabs.tabs[0].text      = self.t("main_title")
        self.start_btn.text         = self.t("start_test")
        self.view_words_btn.text    = self.t("show_words")
        self.file_dd.label          = self.t("dictionary")
        self.add_file_btn.tooltip   = self.t("add_file")
        self.file_dd.value          = self.selected_file
        self.dir_switch.label       = self.t("reverse_test")
        self.dir_switch.value       = self.direction_reversed

        # ── SETTINGS ──
        self.tabs.tabs[1].text        = self.t("settings")
        self.settings_header.value    = self.t("settings")
        self.theme_switch.label       = self.t("dark_theme")
        self.theme_switch.value       = (self.page.theme_mode == ThemeMode.DARK)
        self.lang_dd.label            = self.t("lang_interface")
        self.lang_dd.value            = self.lang
        self.romaji_cb.label          = self.t("show_romaji")
        self.romaji_cb.value          = self.show_romaji
        self.romaji_mode_cb.label     = self.t("romaji_mode")
        self.romaji_mode_cb.value     = self.romaji_mode
        self.hint_switch.label        = self.t("enable_hint")
        self.hint_switch.value        = self.enable_hint
        self.hint_info_btn.tooltip    = self.t("hint_info_tooltip")
        self.hint_threshold_tf.label  = self.t("hint_threshold_label")
        self.hint_threshold_tf.value  = str(self.hint_threshold)

        # ── EDITOR ──
        self.tabs.tabs[2].text         = self.t("create_title")
        self.dict_selector.label       = self.t("select_dictionary")
        self.new_dict_name.label       = self.t("new_dict_name")
        self.sentence_mode_cb.label    = self.t("sentence_mode")
        self.btn_new.tooltip           = self.t("new_dict")
        self.btn_delete.tooltip        = self.t("delete_dict")
        self.btn_add_word.text         = self.t("add_row")
        self.btn_save_dict.text        = (self.t("save_dict")
                                          if self.is_editing
                                          else self.t("create_dict"))

        # Обновляем ярлыки в уже добавленных строках
        for (tf_word, tf_tr, tf_rom), row in zip(self.word_inputs, self.word_rows.controls):
            tf_word.label = self.t("word")
            tf_tr.label   = self.t("translation")
            tf_rom.label  = self.t("romaji")
            # последний элемент — кнопка удаления
            delete_btn = row.controls[-1]
            delete_btn.tooltip = self.t("remove_row")

        # ── BACK ──
        self.back_btn.text = self.t("back_home")

        # ── TEST FIELDS ──
        for tf in self.fields:
            tf.label = self.t("answer")

        # Единоразовый апдейт страницы — самое надёжное
        self.page.update()




    # TEST / RESULTS / WORDS (with auto‑submit on focus)
    def start_test(self, e):
        # ЧИСТИМ старые страницы
        self.test_page.controls.clear()
        self.results_page.controls.clear()
        self.words_page.controls.clear()

        # Загружаем словарь
        fn = self.file_dd.value or "template.json"
        path = os.path.join(WORDS_DIR, fn)
        try:
            data = json.load(open(path, encoding="utf-8"))
            cards = data.get("cards", [])
            sentence_mode = data.get("sentence_mode", False)
        except:
            cards = DEFAULT_SET["cards"]
            sentence_mode = False

        random.shuffle(cards)
        self.vocab = cards
        self.results = [
            {"word": w["word"], "translation": w["translation"],
            "attempts": 0, "correct": False, "entered": ""}
            for w in cards
        ]
        self.fields.clear()

        # готовим UI‑карточки
        elems = []
        for i, w in enumerate(self.vocab):
            prompt = w["translation"] if self.direction_reversed else w["word"]
            tf = TextField(
                label=self.t("answer"),
                width=200 if not sentence_mode else None,
                on_blur=lambda ev, idx=i: self._submit_on_blur(ev, idx)
            )
            self.fields.append(tf)

            cont = Container(
                content=Column([
                    Text(prompt, size=20),
                    Text(w.get("romaji", ""), size=14,
                        visible=(self.show_romaji and not self.direction_reversed)),
                    tf
                ], spacing=5),
                padding=padding.all(10),
                border=border.all(1, Colors.GREY),
                border_radius=border_radius.all(5),
                width=None if sentence_mode else 220,
                height=None if sentence_mode else 140,
                expand=sentence_mode
            )
            elems.append(cont)

        # Выбираем лэйаут: один столбец full-width или сетка
        if sentence_mode:
            test_layout = Column(elems, spacing=20, expand=True)
        else:
            test_layout = Row(elems, wrap=True, spacing=20, alignment="start")

        # Кнопка «Результаты»
        results_btn = ElevatedButton(self.t("results_btn"), on_click=self.show_results)

        # Собираем страницу теста
        self.test_page.controls = [
            test_layout,
            Container(
                results_btn,
                alignment=alignment.center,
                padding=padding.only(top=20, bottom=20)
            )
        ]

        # Статистика
        self.tests_taken += 1
        self.total_questions += len(self.vocab)
        self.save_settings()

        # Переключаем вкладки
        self.tabs.visible = False
        self.test_page.visible = True
        self.results_page.visible = False
        self.words_page.visible = False
        self.page.update()

        # Фокус на первое поле
        if self.fields:
            self.fields[0].focus()

    def toggle_sentence_mode(self, e):
        self.settings["sentence_mode"] = e.control.value
        self.save_settings()




    def _submit_on_blur(self, e, idx):
        tf = e.control
        # если поле уже проверено — выходим
        if tf.disabled:
            return
        # считаем попытку только
        #  если текст есть
        if not tf.value.strip():
            return
        # эмулируем событие on_submit
        class E: control = tf
        self.on_answer(E(), idx)

    def show_results(self, e):
        # 1) Заголовок
        title = Container(
            Text(self.t("results_title"), size=32, weight="bold", text_align="center"),
            alignment=alignment.center,
            padding=padding.only(top=20, bottom=10)
        )

        # 2) Считаем «чисто правильные» (correct=True и attempts==1)
        total = len(self.results)
        correct_zero_errors = sum(1 for r in self.results if r["correct"] and r["attempts"] == 1)

        stats = Container(
            Text(f"{correct_zero_errors} / {total}", size=20, weight="bold", text_align="center"),
            alignment=alignment.center,
            padding=padding.only(bottom=20)
        )

        # 3) Загружаем флаг sentence_mode
        fn = self.file_dd.value or "template.json"
        path = os.path.join(WORDS_DIR, fn)
        try:
            data = json.load(open(path, encoding="utf-8"))
            sentence_mode = data.get("sentence_mode", False)
        except:
            sentence_mode = False

        # 4) Собираем карточки
        cards_ui = []
        for idx, r in enumerate(self.results):
            # вопрос и ключ
            if self.direction_reversed:
                question = r["translation"]
                key = "word"
            else:
                question = r["word"]
                key = "translation"

            # формат ответа
            variants = [v.strip() for v in r[key].split(",") if v.strip()]
            entered = r["entered"].strip()
            main = entered or (variants[0] if variants else "")
            others = [v for v in variants if v.lower() != main.lower()]
            answer_display = main + (f" ({', '.join(others)})" if others else "")

            # статус по той же логике, что и в copy
            mistakes = r["attempts"] - 1
            if r["correct"]:
                if mistakes == 0:
                    status = "🟢"
                else:
                    status = f"🔴{mistakes}"
            else:
                status = "❌"

            # ромадзи
            rom = ""
            if self.show_romaji and not self.direction_reversed:
                rom = next((w.get("romaji","") for w in self.vocab if w["word"]==r["word"]), "").strip()

            # собираем элементы карточки
            txt_q = Text(f"{status} {question}", size=20, weight="bold", text_align="center")
            txt_a = Text(answer_display, size=16, text_align="center")
            col_items = [txt_q, txt_a]
            if rom:
                col_items.append(Text(rom, size=14, italic=True, text_align="center"))

            cont = Container(
                content=Column(
                    col_items,
                    spacing=6,
                    alignment="center",
                    horizontal_alignment="center"
                ),
                padding=padding.all(12),
                border=border.all(1, Colors.GREY),
                border_radius=border_radius.all(5),
                width=None if sentence_mode else 220,
                expand=sentence_mode,
                alignment=alignment.center
            )
            cards_ui.append(cont)

        # 5) Кнопка копирования
        copy_btn = ElevatedButton(
            self.t("copy_results"),
            icon=Icons.FILE_COPY,
            on_click=self._copy_results_handler
        )

        # 6) Layout карточек
        if sentence_mode:
            results_layout = Column(cards_ui, spacing=20, expand=True)
        else:
            rows = [
                Row(cards_ui[i:i+4], spacing=20, alignment="center")
                for i in range(0, len(cards_ui), 4)
            ]
            results_layout = Column(rows, spacing=20)

        # 7) Футер
        footer = Container(
            content=Row([copy_btn, self.back_btn], alignment="center", spacing=20),
            padding=padding.only(top=20, bottom=20),
            alignment=alignment.center
        )

        # 8) Собираем страницу
        self.results_page.controls = [
            title,
            stats,
            results_layout,
            footer
        ]
        self.tabs.visible         = False
        self.test_page.visible    = False
        self.results_page.visible = True
        self.words_page.visible   = False
        self.page.update()



    def _copy_results_handler(self, ev):
        # 1) Заголовок
        fn = self.file_dd.value or "template.json"
        try:
            d = json.load(open(os.path.join(WORDS_DIR, fn), encoding="utf-8"))
        except:
            d = DEFAULT_SET
        title = d.get("title", os.path.splitext(fn)[0])

        # 2) Начинаем формировать строки
        lines = [title]
        items = []
        for idx, r in enumerate(self.results):
            # сколько ошибок было
            mistakes = r["attempts"] - 1

            # статус
            if r["correct"]:
                if mistakes == 0:
                    status = "🟢"
                else:
                    status = f"🔴{mistakes}"
            else:
                status = "❌"

            # левый и правый фрагмент
            if self.direction_reversed:
                left = r["translation"].split(",")[0].strip()
                if self.romaji_mode:
                    ans = r["entered"].strip() or self.vocab[idx].get("romaji", "").split(",")[0].strip()
                else:
                    ans = r["entered"].strip() or r["word"]
            else:
                left = r["word"]
                ans = r["entered"].strip() or r["translation"].split(",")[0].strip()

            items.append(f"{left}-{ans}-{status}")

        # 3) Разбиваем на колонки
        cols = self._compute_columns(len(items))
        for i in range(0, len(items), cols):
            lines.append("  ".join(items[i:i+cols]))

        # 4) Финальная строка
        lines.append("by KotoYon")
        text = "\n".join(lines)

        # 5) Копируем в буфер и анимируем кнопку
        self.page.set_clipboard(text)
        btn = ev.control
        orig = btn.bgcolor
        btn.bgcolor = Colors.GREEN
        btn.update()
        def reset():
            time.sleep(0.5)
            btn.bgcolor = orig
            btn.update()
        threading.Thread(target=reset, daemon=True).start()




    def show_words(self, e):
        # 1) Заголовок
        header = Container(
            Text(self.t("word_list_title"), size=28, weight="bold"),
            alignment=alignment.center,
            padding=padding.only(top=20, bottom=10)
        )

        # 2) Загружаем словарь и режим sentence_mode
        fn = self.file_dd.value or "template.json"
        path = os.path.join(WORDS_DIR, fn)
        try:
            data = json.load(open(path, encoding="utf-8"))
            cards = data.get("cards", [])
            sentence_mode = data.get("sentence_mode", False)
        except:
            cards = DEFAULT_SET["cards"]
            sentence_mode = False

        # 3) Собираем UI‑карточки
        cards_ui = []
        for w in cards:
            # формат переводов
            vars_ = [v.strip() for v in w["translation"].split(",") if v.strip()]
            main = vars_[0] if vars_ else ""
            others = vars_[1:]
            disp = main + (f" ({', '.join(others)})" if others else "")

            # ромадзи (если включено)
            rom = ""
            if self.show_romaji and w.get("romaji","").strip():
                rom = w["romaji"].strip()

            # создаём текстовые элементы
            txt_w = Text(w["word"], size=20, weight="bold", text_align="center")
            txt_t = Text(disp,     size=16,                           text_align="center")
            col_items = [txt_w, txt_t]
            if rom:
                col_items.append(Text(rom, size=14, italic=True, text_align="center"))

            # оборачиваем в Container
            cont = Container(
                content=Column(
                    col_items,
                    spacing=8,
                    alignment="center",
                    horizontal_alignment="center"
                ),
                padding=padding.all(12),
                border=border.all(1, Colors.GREY),
                border_radius=border_radius.all(5),
                width=None if sentence_mode else 200,
                expand=sentence_mode,
                alignment=alignment.center
            )
            cards_ui.append(cont)

        # 4) Лэйаут точно как в show_results
        if sentence_mode:
            # один столбец full‑width
            word_layout = Column(cards_ui, spacing=20, expand=True)
        else:
            # жёстко 4 в ряд
            rows = [
                Row(cards_ui[i:i+4], spacing=20, alignment="center")
                for i in range(0, len(cards_ui), 4)
            ]
            word_layout = Column(rows, spacing=20)

        # 5) Кнопка «Назад»
        back_container = Container(
            self.back_btn,
            alignment=alignment.center,
            padding=padding.only(top=20, bottom=20)
        )

        # 6) Пушим на страницу
        self.words_page.controls = [
            header,
            word_layout,
            back_container
        ]
        self.tabs.visible         = False
        self.test_page.visible    = False
        self.results_page.visible = False
        self.words_page.visible   = True
        self.page.update()








# ENTRY POINT
def main(page: Page):
    page.window_icon      = "icon.png"
    page.title            = "KotoYon"
    page.window_maximized = True
    page.update()

    FlashcardApp(page)

if __name__ == "__main__":
    flet.app(target=main, assets_dir="assets")

