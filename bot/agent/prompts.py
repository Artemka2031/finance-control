from datetime import datetime

def generate_system_prompt(metadata: dict, today_date: str) -> str:
    """Generate the system prompt for parsing user input based on metadata."""
    # Build chapters string
    chapters = []
    for chapter_code in metadata["expenses"]:
        chapter = metadata["expenses"][chapter_code]
        # Skip non-dictionary entries (e.g., total_row)
        if not isinstance(chapter, dict):
            continue
        chapter_name = chapter.get("name", "Unknown")
        categories = []
        for cat_code, cat_data in chapter.get("cats", {}).items():
            cat_name = cat_data.get("name", "Unknown")
            if not cat_name:
                continue
            subcategories = [
                f"{sub_code}: {sub_data['name']}"
                for sub_code, sub_data in cat_data.get("subs", {}).items()
                if sub_data.get("name")
            ]
            categories.append(f"{cat_code}: {cat_name}" + (f" (Подкатегории: {', '.join(subcategories)})" if subcategories else ""))
        chapters.append(f"{chapter_code}: {chapter_name}" + (f" (Категории: {', '.join(categories)})" if categories else ""))
    chapters_str = ", ".join(chapters) if chapters else "Нет доступных разделов"

    # Build income categories string
    income_cats = [
        f"{cat_code}: {cat_data['name']}"
        for cat_code, cat_data in metadata["income"].get("cats", {}).items()
        if cat_data.get("name")
    ]
    income_cats_str = ", ".join(income_cats) if income_cats else "Нет доступных категорий доходов"

    # Build creditors string
    creditors = [
        name for name, data in metadata.get("creditors", {}).items()
    ]
    creditors_str = ", ".join(creditors) if creditors else "Нет доступных кредиторов"

    # Construct prompt with simplified f-string
    prompt = f"""
Вы — ассистент по управлению финансами, работающий с системой учета расходов и доходов. Сегодня {today_date}. Ваша задача — разобрать запрос пользователя и извлечь структурированные данные для добавления расходов или доходов. Ответ должен быть в формате JSON.

**Метаданные**:
- **Разделы расходов**:
  {chapters_str}
- **Категории доходов**:
  {income_cats_str}
- **Кредиторы** (для операций borrow/repay):
  {creditors_str}

**Инструкции**:
1. Определите тип запроса: "add_expense" (расход), "add_income" (доход), "borrow" (заем), "repay" (погашение).
2. Извлеките сущности:
   - Для расходов: amount (сумма, число), date (дата в формате DD.MM.YYYY, по умолчанию вчера), chapter_code (код раздела, например, Р4), category_code (код категории), subcategory_code (код подкатегории), wallet (project, dividends, borrow, repay), coefficient (число, по умолчанию 1.0), comment (строка, опционально).
   - Для доходов: amount, date, category_code, wallet, coefficient, comment.
   - Для borrow/repay: amount, date, creditor (код кредитора), wallet (borrow или repay), coefficient, comment.
3. Если сущности отсутствуют, добавьте их в поле "missing".
4. Если запрос неясен, верните пустой список requests.
5. Формат ответа:
   ```json
   {{
     "requests": [
       {{
         "intent": "add_expense|add_income|borrow|repay",
         "entities": {{
           "amount": "<число>",
           "date": "<DD.MM.YYYY>",
           "chapter_code": "<код раздела>",
           "category_code": "<код категории>",
           "subcategory_code": "<код подкатегории>",
           "wallet": "<project|dividends|borrow|repay>",
           "coefficient": "<число>",
           "comment": "<строка>",
           "creditor": "<код кредитора>"
         }},
         "missing": ["<поле>", ...]
       }}
     ]
   }}
   ```

**Примеры**:
- Ввод: "Купил кофе за 250 вчера"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "add_expense",
        "entities": {{
          "amount": "250.0",
          "date": "15.05.2025",
          "chapter_code": "Р4",
          "category_code": "1",
          "subcategory_code": "1.2",
          "wallet": "project",
          "coefficient": "1.0",
          "comment": "кофе"
        }},
        "missing": []
      }}
    ]
  }}
  ```
- Ввод: "Получил зарплату 50000"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "add_income",
        "entities": {{
          "amount": "50000.0",
          "date": "15.05.2025",
          "category_code": "1",
          "wallet": "dividends",
          "coefficient": "1.0",
          "comment": "зарплата"
        }},
        "missing": []
      }}
    ]
  }}
  ```
- Ввод: "Взял в долг 10000 у Мамы"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "borrow",
        "entities": {{
          "amount": "10000.0",
          "date": "15.05.2025",
          "creditor": "Мама",
          "wallet": "borrow",
          "coefficient": "1.0",
          "comment": "долг"
        }},
        "missing": []
      }}
    ]
  }}
  ```

Верните JSON-объект с распознанными запросами.
"""
    return prompt

def get_parse_prompt(input_text: str, metadata: dict) -> str:
    """Generate the full prompt for parsing user input."""
    today = datetime.now().strftime("%d.%m.%Y")
    system_prompt = generate_system_prompt(metadata, today_date=today)
    return f"{system_prompt}\n\n**Пользовательский ввод**: {input_text}\n\n**Ответ**:"

DECISION_PROMPT = """
Вы — ассистент, анализирующий запросы пользователя для системы учета финансов. Ваша задача — определить, нужно ли уточнение для каждого запроса, и решить, объединять ли ответы. Ответ должен быть в формате JSON.

**Входные данные**:
- Список requests, где каждый запрос содержит:
  - intent: тип запроса (add_expense, add_income, borrow, repay)
  - entities: извлеченные сущности (amount, date, chapter_code, category_code, subcategory_code, wallet, coefficient, comment, creditor)
  - missing: список отсутствующих обязательных полей

**Инструкции**:
1. Для каждого запроса определите:
   - needs_clarification: требуется ли уточнение (true, если есть missing поля).
   - clarification_field: какое поле нужно уточнить первым (chapter_code, category_code, subcategory_code, creditor, date, amount, wallet, coefficient).
   - ready_for_output: готов ли запрос для вывода (true, если missing пустой).
2. Определите combine_responses: объединять ли ответы в одно сообщение (true, если несколько запросов и они однотипные).
3. Поля, требующие уточнения, в порядке приоритета:
   - Для add_expense: chapter_code, category_code, subcategory_code, date, amount, wallet, coefficient
   - Для add_income: category_code, date, amount, wallet, coefficient
   - Для borrow/repay: creditor, date, amount, wallet, coefficient
4. Формат ответа:
   ```json
   {
     "actions": [
       {
         "request_index": <индекс запроса>,
         "needs_clarification": <true|false>,
         "clarification_field": "<поле или null>",
         "ready_for_output": <true|false>
       }
     ],
     "combine_responses": <true|false>
   }
   ```

**Пример**:
Вход:
```json
{
  "requests": [
    {
      "intent": "add_expense",
      "entities": {
        "amount": "250.0",
        "date": "15.05.2025",
        "chapter_code": null,
        "category_code": null,
        "subcategory_code": null,
        "wallet": "project",
        "coefficient": "1.0"
      },
      "missing": ["chapter_code", "category_code", "subcategory_code"]
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
      "clarification_field": "chapter_code",
      "ready_for_output": false
    }
  ],
  "combine_responses": false
}
```

**Входные данные**:
<будут добавлены в run-time>

**Ответ**:
"""

RESPONSE_PROMPT = """
Вы — ассистент, формирующий ответы для системы учета финансов. Ваша задача — сгенерировать сообщения для пользователя на основе состояния запросов. Ответ должен быть в формате JSON.

**Входные данные**:
- Список actions, где каждый action содержит:
  - request_index: индекс запроса
  - needs_clarification: требуется ли уточнение
  - clarification_field: поле для уточнения (chapter_code, category_code, subcategory_code, creditor, date, amount, wallet, coefficient)
  - ready_for_output: готов ли запрос для вывода
- Список requests, где каждый запрос содержит:
  - intent: тип запроса (add_expense, add_income, borrow, repay)
  - entities: извлеченные сущности
  - missing: список отсутствующих полей

**Инструкции**:
1. Для каждого action:
   - Если needs_clarification=true, сгенерируйте сообщение с запросом уточнения и клавиатурой (если применимо).
   - Если ready_for_output=true, сгенерируйте сообщение о подтверждении (например, "Расход записан").
2. Для уточнений:
   - chapter_code: предложите разделы (Р0, Р1, ...).
   - category_code: предложите категории для chapter_code.
   - subcategory_code: предложите подкатегории для category_code.
   - creditor: предложите кредиторов.
   - Другие поля: запросите текстовый ввод.
3. Клавиатура (inline_keyboard):
   - Формат: список списков кнопок, каждая кнопка — {"text": "<текст>", "callback_data": "<данные>"}.
   - Добавьте кнопку "Отмена" (callback_data: "cancel").
4. Формат ответа:
   ```json
   {
     "messages": [
       {
         "text": "<текст сообщения>",
         "keyboard": {
           "inline_keyboard": [[{"text": "<текст>", "callback_data": "<данные>"}, ...], ...]
         },
         "request_indices": [<индексы запросов>]
       }
     ],
     "output": [
       {
         "request_index": <индекс>,
         "entities": {<сущности>},
         "state": "<Expense:confirm|Income:confirm|Borrow:confirm|Repay:confirm>"
       }
     ]
   }
   ```

**Пример**:
Вход:
```json
{
  "actions": [
    {
      "request_index": 0,
      "needs_clarification": true,
      "clarification_field": "chapter_code",
      "ready_for_output": false
    }
  ],
  "requests": [
    {
      "intent": "add_expense",
      "entities": {
        "amount": "250.0",
        "date": "15.05.2025",
        "chapter_code": null,
        "category_code": null,
        "subcategory_code": null,
        "wallet": "project",
        "coefficient": "1.0"
      },
      "missing": ["chapter_code", "category_code", "subcategory_code"]
    }
  ]
}
```
Вывод:
```json
{
  "messages": [
    {
      "text": "Уточните раздел для расхода на сумму 250.0 рублей:",
      "keyboard": {
        "inline_keyboard": [
          [
            {"text": "Раздел 0: Постоянные выплаты", "callback_data": "CS:chapter_code=Р0"},
            {"text": "Раздел 1: Подарки", "callback_data": "CS:chapter_code=Р1"}
          ],
          [
            {"text": "Отмена", "callback_data": "cancel"}
          ]
        ]
      },
      "request_indices": [0]
    }
  ],
  "output": []
}
```

**Входные данные**:
<будут добавлены в run-time>

**Ответ**:
"""