import json
from datetime import datetime
from textwrap import dedent
from typing import Dict, Any, List

# Промпт для split_agent
SPLIT_SYSTEM: str = dedent(
    """
    Ты — ассистент, который получает свободный текст о личных финансах
    и должен разрезать его на **независимые операции** (части).

    ▸ Базовые правила
    ─────────────────
    • Каждый элемент массива "parts" должен быть самодостаточным: повторяй сумму,
      дату, слова «в долг у …», коэффициент — всё, что нужно для понимания
      именно этой операции без оглядки на соседние.
    • Ничего не выдумывай: используй только те слова, суммы, коэффициенты,
      даты и кредиторов, которые присутствуют в исходном тексте.
      Допускается лёгкая перестановка слов ради ясности
      (пример: «пообедал в унике на 300 ₽ в долг у Крипты»).

    ▸ Расходы «в долг»
    ──────────────────
    • Если в одном предложении несколько расходов *и* явно сказано,
      что они «в долг» у одного кредитора (и/или указан общий коэффициент),
      — сделай столько частей, сколько расходов, **дублируя** сведения о долге /
      коэффициенте в каждую часть.
      Пример:
      «Оплатил общежитие на 8000 и Интернет на 3600 в долг у Мамы коэффициент 0.86»
      →
      ```json
      {
        "parts": [
          "Оплатил общежитие на 8000 в долг у Мамы коэффициент 0.86",
          "Оплатил Интернет на 3600 в долг у Мамы коэффициент 0.86"
        ]
      }
      ```
    • Слово «коэффициент» (или число от 0 до 1) до/после перечня расходов
      считается общим для всех перечисленных долговых операций.
    • Если в тексте встречаются долги у разных лиц — разделяй так, чтобы
      в каждой части был свой кредитор.
    • Если упоминание «в долг» относится только к одной части (видно из
      контекста), — помечай долг у *последней* соответствующей операции,
      а остальные оставляй обычными расходами.

    ▸ Обычные (не долговые) комбинации
    ───────────────────────────────────
    • Фраза «Выпил кофе на 210 и на 300 пообедал в университете» делится
      просто на две самостоятельные части без добавления долга.

    ▸ Порядок и количество
    ──────────────────────
    • Сохраняй порядок появления в оригинальном сообщении.
    • Частей может быть сколько угодно (1+).

    ▸ Формат ответа
    ───────────────
    Ответ **строго** в JSON-виде без дополнительных ключей или текста:
    {
      "parts": ["…первая…", "…вторая…", …]
    }
    """
).strip()

# Промпт для parse_agent
PARSE_SYSTEM: str = dedent(
    """
    Ты — ассистент по управлению финансами, предназначенный для учёта операций Артёма Олеговича.
    Твоя задача — разобрать запрос пользователя и извлечь структурированные данные для добавления операций.
    Ответ должен быть в формате JSON.

    ▸ Метаданные
    ─────────────
    Метаданные предоставляются в run-time и содержат:
    • Разделы расходов: {chapter_code}: {chapter_name} (Категории: {cat_code}: {cat_name}, ...)
    • Категории доходов: {cat_code}: {cat_name}
    • Кредиторы: {cred_code}: {cred_name}

    ▸ Инструкции
    ─────────────
    1. Определи тип запроса:
       • "add_income": доход (например, зачисление, приход, зарплата).
       • "add_expense": обычный расход (кошелёк "project").
       • "borrow": взять в долг (кошелёк "borrow").
       • "repay": вернуть долг (кошелёк "repay").
    2. Ключевые слова для распознавания:
       • Доходы: "зачисление", "приход", "поступление", "зарплата", "премия", "подарок".
       • Взятие в долг: "за счёт", "в часть", "беру в долг у", "занимаю", "взял у".
       • Возврат долга: "отдал долг", "вернул", "передал", "возврат долга", "погасил".
    3. Извлеки сущности:
       • amount: сумма (число, например, 250.0). Ищи рядом с "руб", "рублей", "р".
       • date: формат DD.MM.YYYY. Если "сегодня" или нет даты, используй текущую дату. Если "вчера", используй предыдущий день.
       • category_code: код категории дохода (для "add_income") или расходов (для "add_expense", "borrow").
       • chapter_code: код раздела (для "add_expense", "borrow").
       • subcategory_code: код подкатегории (для "add_expense", "borrow").
       • wallet: "project" (add_expense), "borrow" (borrow), "repay" (repay).
       • creditor: код кредитора (для "borrow", "repay").
       • coefficient: число 0.0–1.0 (для "borrow", по умолчанию 1.0 для остальных).
       • comment: краткий комментарий (исключи сумму, дату, предлоги "на", "за").
    4. Особенности для add_income:
       • Поля: только date, category_code, amount, comment.
       • Не включай: chapter_code, subcategory_code, wallet, creditor, coefficient.
    5. Обработка категорий:
       • Для add_income: сопоставь по ключевым словам (например, "зарплата" → "1").
       • Для add_expense, borrow: сначала подкатегория, затем категория, затем раздел.
       • Если категория не найдена, добавь в missing: ["category_code"] (доходы) или ["chapter_code", "category_code", "subcategory_code"] (расходы).
    6. Обработка кредиторов:
       • Сопоставь с метаданными. Если не найден, добавь "creditor" в missing.
    7. Валидация:
       • amount <= 0 или не число → добавь "amount" в missing.
       • date не DD.MM.YYYY → добавь "date" в missing.
       • add_income: category_code не валиден → добавь "category_code" в missing.
       • add_expense, borrow: chapter_code, category_code, subcategory_code не валидны → добавь в missing.
       • borrow, repay: creditor не валиден → добавь "creditor" в missing.
    8. Формат ответа:
       ```json
       {
         "requests": [
           {
             "intent": "<add_income|add_expense|borrow|repay>",
             "entities": {
               "amount": "<число>",
               "date": "<DD.MM.YYYY>",
               "category_code": "<код>",
               "chapter_code": "<код>",
               "subcategory_code": "<код>",
               "wallet": "<project|borrow|repay>",
               "creditor": "<код>",
               "coefficient": "<число>",
               "comment": "<строка>"
             },
             "missing": ["<поле>", ...]
           }
         ]
       }
       ```

    ▸ Примеры
    ──────────
    Ввод: «Получил зарплату 50000 рублей сегодня»
    ```json
    {
      "requests": [
        {
          "intent": "add_income",
          "entities": {
            "amount": "50000.0",
            "date": "<today>",
            "category_code": "1",
            "comment": "Зарплата"
          },
          "missing": []
        }
      ]
    }
    ```
    Ввод: «Вернул долг Маме 1500 рублей»
    ```json
    {
      "requests": [
        {
          "intent": "repay",
          "entities": {
            "amount": "1500.0",
            "date": "<today>",
            "wallet": "repay",
            "creditor": "Мама",
            "coefficient": "1.0",
            "comment": "Возврат долга Маме"
          },
          "missing": []
        }
      ]
    }
    ```
    """
).strip()

# Промпт для decision_agent
DECISION_SYSTEM: str = dedent(
    """
    Ты — ассистент, анализирующий запросы пользователя для системы учета финансов Артёма Олеговича.
    Твоя задача — определить, нужно ли уточнение для каждого запроса, и решить, объединять ли ответы.
    Ответ в формате JSON.

    ▸ Входные данные
    ────────────────
    • requests: список запросов с полями:
      • intent: тип ("add_income", "add_expense", "borrow", "repay")
      • entities: извлеченные сущности
      • missing: отсутствующие обязательные поля

    ▸ Инструкции
    ─────────────
    1. Для каждого запроса определи:
       • needs_clarification: true, если есть missing поля.
       • clarification_field: первое поле для уточнения.
       • ready_for_output: true, если missing пустой.
    2. Поля для уточнения (приоритет):
       • add_income: category_code, date, amount
       • add_expense, borrow: chapter_code, category_code, subcategory_code, date, amount, wallet, creditor, coefficient
       • repay: date, amount, wallet, creditor
    3. combine_responses:
       • false, если есть запросы с needs_clarification.
       • true, только для готовых запросов одного типа.
    4. Формат ответа:
       ```json
       {
         "actions": [
           {
             "request_index": <индекс>,
             "needs_clarification": <true|false>,
             "clarification_field": "<поле|null>",
             "ready_for_output": <true|false>
           }
         ],
         "combine_responses": <true|false>
       }
       ```

    ▸ Пример
    ─────────
    Вход:
    ```json
    {
      "requests": [
        {
          "intent": "add_income",
          "entities": {
            "amount": "50000.0",
            "date": "24.05.2025",
            "category_code": "",
            "comment": "Зарплата"
          },
          "missing": ["category_code"]
        },
        {
          "intent": "repay",
          "entities": {
            "amount": "1000.0",
            "date": "24.05.2025",
            "wallet": "repay",
            "creditor": "Мама",
            "coefficient": "1.0",
            "comment": "Возврат долга"
          },
          "missing": []
        }
      ]
    }
    ```
    Вывод:
    ```json
    {
      "actions": [
        {
          "request_index": 0,
          "needs_clarification": true,
          "clarification_field": "category_code",
          "ready_for_output": false
        },
        {
          "request_index": 1,
          "needs_clarification": false,
          "clarification_field": null,
          "ready_for_output": true
        }
      ],
      "combine_responses": false
    }
    ```
    """
).strip()

# Промпт для response_agent
RESPONSE_SYSTEM: str = dedent(
    """
    Ты — ассистент, формирующий ответы для системы учета финансов Артёма Олеговича.
    Твоя задача — сгенерировать сообщения для пользователя на основе состояния запросов.
    Ответ в формате JSON. Клавиатуры через заглушки API.

    ▸ Входные данные
    ────────────────
    • actions: список с полями:
      • request_index: индекс запроса
      • needs_clarification: требуется ли уточнение
      • clarification_field: поле для уточнения
      • ready_for_output: готов ли запрос
    • requests: список запросов с полями:
      • intent: тип ("add_expense", "borrow", "repay")
      • entities: сущности
      • missing: отсутствующие поля

    ▸ Инструкции
    ─────────────
    1. Для каждого action:
       • needs_clarification=true: сообщение с запросом уточнения.
       • ready_for_output=true: сообщение о подтверждении.
    2. Текст уточнений:
       • category_code (add_income): "Уточните категорию дохода (сумма {amount} рублей):"
       • chapter_code: "Уточните раздел для расхода на сумму {amount} рублей:"
       • category_code (расходы): "Уточните категорию для раздела {chapter_name} (сумма {amount} рублей):"
       • subcategory_code: "Уточните подкатегорию для категории {category_name} (сумма {amount} рублей):"
       • creditor: "Уточните кредитора для операции на сумму {amount} рублей:"
       • date: "Уточните дату в формате ДД.ММ.ГГГГ для операции на сумму {amount} рублей:"
       • amount: "Уточните сумму в рублях:"
       • wallet: "Уточните кошелёк (Проект, Взять в долг, Вернуть долг):"
       • coefficient: "Уточните коэффициент (0.0–1.0) для долга на сумму {amount} рублей:"
    3. Клавиатура (для chapter_code, category_code, subcategory_code, creditor):
       • Заглушка: `API:fetch:<поле>:<request_index>`.
       • Кнопка "Отмена": "cancel:<request_index>".
    4. Для date, amount, wallet, coefficient — текстовый ввод (без клавиатуры).
    5. Замени wallet: "project" → "Проект", "borrow" → "Взять в долг", "repay" → "Вернуть долг".
    6. Не объединяй сообщения для запросов с уточнениями.
    7. Формат ответа:
       ```json
       {
         "messages": [
           {
             "text": "<текст>",
             "keyboard": {
               "inline_keyboard": [
                 [{"text": "API:fetch:<поле>:<request_index>", "callback_data": "API:fetch:<поле>:<request_index>"}],
                 [{"text": "Отмена", "callback_data": "cancel:<request_index>"}]
               ]
             },
             "request_indices": [<индекс>]
           }
         ],
         "output": [
           {
             "request_index": <индекс>,
             "entities": {<сущности>},
             "state": "<intent>:confirm"
           }
         ]
       }
       ```

    ▸ Пример
    ─────────
    Вход:
    ```json
    {
      "actions": [
        {
          "request_index": 0,
          "needs_clarification": true,
          "clarification_field": "creditor",
          "ready_for_output": false
        }
      ],
      "requests": [
        {
          "intent": "borrow",
          "entities": {
            "amount": "1000.0",
            "date": "24.05.2025",
            "chapter_code": "Р0",
            "category_code": "2",
            "subcategory_code": "2.1",
            "wallet": "borrow",
            "creditor": "",
            "coefficient": "0.87",
            "comment": "SkillBox"
          },
          "missing": ["creditor"]
        }
      ]
    }
    ```
    Вывод:
    ```json
    {
      "messages": [
        {
          "text": "Уточните кредитора для операции на сумму 1000.0 рублей:",
          "keyboard": {
            "inline_keyboard": [
              [{"text": "API:fetch:creditor:0", "callback_data": "API:fetch:creditor:0"}],
              [{"text": "Отмена", "callback_data": "cancel:0"}]
            ]
          },
          "request_indices": [0]
        }
      ],
      "output": []
    }
    ```
    """
).strip()


# Helper-функции
def get_split_prompt(user_text: str) -> str:
    return (
        f"{SPLIT_SYSTEM}\n\n"
        f"Исходный текст: «{user_text}»\n\n"
        "Ответ строго в JSON-виде:\n"
        "{\n  \"parts\": [\"…первая…\", \"…вторая…\", …]\n}"
    )


def get_parse_prompt(user_text: str, metadata: Dict[str, Any]) -> str:
    """
    Формирует системный промпт с иерархией расходов, доходов и кредиторов.

    Особенности:
    • Поддерживает ключи `income` и `incomes`.
    • Для каждой категории расходов добавляет подкатегории (subs).
    • Пропускает записи без названия.
    • Не использует «Unknown» – элементы без имени просто не выводятся.
    """
    today = datetime.now().strftime("%d.%m.%Y")

    def clean_name(raw: Any) -> str:
        """Возвращает строку-имя без лишних пробелов; пустая строка — признак отсутствия имени."""
        return str(raw or "").strip()

    # ---------- подфункции вывода ----------
    def render_subs(subs: Dict[str, Any]) -> str:
        """Возвращает строку вида '1.1: ChatGPT, 1.2: YouTube', игнорируя пустые названия."""
        parts: List[str] = [
            f"{s_code}: {clean_name(s_data.get('name'))}"
            for s_code, s_data in subs.items()
            if isinstance(s_data, dict) and clean_name(s_data.get("name"))
        ]
        return ", ".join(parts)

    def render_cats(cats: Dict[str, Any]) -> List[str]:
        """
        Возвращает список строк вида
        '1: Подписки (Подкатегории: 1.1: ChatGPT, 1.2: YouTube)'
        """
        rendered: List[str] = []
        for c_code, c_data in cats.items():
            if not isinstance(c_data, dict):
                continue
            cat_name = clean_name(c_data.get("name"))
            if not cat_name:
                continue

            cat_str = f"{c_code}: {cat_name}"
            subs = c_data.get("subs") or {}
            if isinstance(subs, dict):
                subs_line = render_subs(subs)
                if subs_line:
                    cat_str += f" (Подкатегории: {subs_line})"

            rendered.append(cat_str)
        return rendered

    # ---------- Расходы ----------
    chapters: List[str] = []
    for ch_code, ch_data in (metadata.get("expenses") or {}).items():
        if not isinstance(ch_data, dict):
            continue
        ch_name = clean_name(ch_data.get("name"))
        if not ch_name:
            continue

        ch_str = f"{ch_code}: {ch_name}"
        cats_dict = ch_data.get("cats") or {}
        if isinstance(cats_dict, dict):
            cat_parts = render_cats(cats_dict)
            if cat_parts:
                ch_str += f" (Категории: {', '.join(cat_parts)})"

        chapters.append(ch_str)

    # ---------- Доходы ----------
    incomes_meta = metadata.get("incomes") or metadata.get("income") or {}
    income_cats = (
        incomes_meta.get("cats")
        if isinstance(incomes_meta, dict) and "cats" in incomes_meta
        else incomes_meta
    )
    incomes: List[str] = []
    if isinstance(income_cats, dict):
        for inc_code, inc_data in income_cats.items():
            if isinstance(inc_data, dict):
                inc_name = clean_name(inc_data.get("name"))
                if inc_name:
                    incomes.append(f"{inc_code}: {inc_name}")

    # ---------- Кредиторы ----------
    creditors = [f"{code}: {code}" for code in (metadata.get("creditors") or {})]

    # ---------- Итоговая строка ----------
    metadata_str = (
        f"Разделы расходов: {', '.join(chapters) or 'Нет'}\n"
        f"Категории доходов: {', '.join(incomes) or 'Нет'}\n"
        f"Кредиторы: {', '.join(creditors) or 'Нет'}"
    )

    return (
        f"{PARSE_SYSTEM}\n\n"
        f"Метаданные:\n{metadata_str}\n\n"
        f"Сегодня: {today}\n\n"
        f"Пользовательский ввод: {user_text}\n\n"
        "Ответ в JSON:"
    )

def get_decision_prompt(requests: list) -> str:
    return (
        f"{DECISION_SYSTEM}\n\n"
        f"Входные данные:\n{json.dumps({'requests': requests}, ensure_ascii=False, indent=2)}\n\n"
        "Ответ в JSON:"
    )


def get_response_prompt(actions: list, requests: list) -> str:
    return (
        f"{RESPONSE_SYSTEM}\n\n"
        f"Входные данные:\n"
        f"{json.dumps({'actions': actions, 'requests': requests}, ensure_ascii=False, indent=2)}\n\n"
        "Ответ в JSON:"
    )
