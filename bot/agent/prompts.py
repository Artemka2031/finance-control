from datetime import datetime
from typing import Dict


def generate_system_prompt(metadata: Dict, today_date: str) -> str:
    """Generate the system prompt for parsing user input based on metadata."""
    # Process expense chapters
    chapters = []
    for chapter_code, chapter_data in metadata.get("expenses", {}).items():
        if not isinstance(chapter_data, dict):
            continue
        chapter_name = chapter_data.get("name", "Unknown")
        if not chapter_name:
            continue
        categories = []
        for cat_code, cat_data in chapter_data.get("cats", {}).items():
            cat_name = cat_data.get("name", "")
            if not cat_name:
                continue
            subcategories = [
                f"{sub_code}: {sub_data['name']}"
                for sub_code, sub_data in cat_data.get("subs", {}).items()
                if sub_data.get("name")
            ]
            categories.append(
                f"{cat_code}: {cat_name}" +
                (f" (Подкатегории: {', '.join(subcategories)})" if subcategories else "")
            )
        chapters.append(
            f"{chapter_code}: {chapter_name}" +
            (f" (Категории: {', '.join(categories)})" if categories else "")
        )
    chapters_str = ", ".join(chapters) if chapters else "Нет доступных разделов"

    # Process income categories
    income_cats = []
    for cat_code, cat_data in metadata.get("incomes", {}).items():
        cat_name = cat_data.get("name", "Unknown")
        if cat_name:
            income_cats.append(f"{cat_code}: {cat_name}")
    income_cats_str = ", ".join(income_cats) if income_cats else "Нет доступных категорий доходов"

    # Process creditors
    creditors = metadata.get("creditors", {})
    creditors_str = ", ".join(
        f"{cred_code}: {cred_data.get('name', 'Unknown')}"
        for cred_code, cred_data in creditors.items()
        if cred_data.get("name")
    ) if creditors else "Кредиторы не найдены"

    prompt = f"""
Вы — ассистент по управлению финансами, предназначенный для учёта операций Артёма Олеговича. Сегодня {today_date}. 
Ваша задача — разобрать запрос пользователя и извлечь структурированные данные для добавления операций. 
Ответ должен быть в формате JSON.

**Метаданные**:
- **Разделы расходов**:
  {chapters_str}
- **Категории доходов**:
  {income_cats_str}
- **Кредиторы**:
  {creditors_str}

**Инструкции**:
1. Определите тип запроса:
   - "add_income": доход (например, зачисление, приход, поступление оплаты, подарки).
   - "add_expense": обычный расход (кошелёк "project").
   - "borrow": взять в долг (кошелёк "borrow").
   - "repay": вернуть долг (кошелёк "repay").
2. Ключевые слова для распознавания:
   - **Доходы ("add_income")**: "зачисление", "приход", "поступление", "оплата по договору", "подарок", "зарплата", "премия", "доход".
   - **Взятие в долг ("borrow")**: "за счёт", "в часть", "беру в долг у", "занимаю", "взял у".
   - **Возврат долга ("repay")**: "отдал долг", "вернул", "передал", "возврат долга", "погасил".
3. Извлеките сущности для каждого запроса:
   - amount: сумма (число, например, 250.0). Ищите числа рядом с "руб", "рублей", "р".
   - date: дата в формате DD.MM.YYYY. Если указаны "сегодня" или нет даты, используйте {today_date}. Если "вчера", используйте предыдущий день.
   - category_code: код категории дохода (например, "5"). Требуется для "add_income". Сопоставьте с метаданными.
   - chapter_code: код раздела (например, "Р1"). Требуется для "add_expense" и "borrow".
   - category_code (для расходов): код категории (например, "2"). Требуется для "add_expense" и "borrow".
   - subcategory_code: код подкатегории (например, "2.5"). Требуется для "add_expense" и "borrow".
   - wallet: "project" для "add_expense", "borrow" для "borrow", "repay" для "repay". Для "add_income" не требуется.
   - creditor: код кредитора (например, "Крипта"). Требуется для "borrow" и "repay".
   - coefficient: число (по умолчанию 1.0 для "add_expense", "repay", "add_income"; для "borrow" извлекайте, например, "0.87").
   - comment: краткий комментарий (например, "Зарплата за май"). Исключите сумму, дату, предлоги ("на", "за").
4. **Обработка категорий**:
   - Для "add_income": ищите категорию дохода по ключевым словам (например, "зарплата" → "1", "подарок" → "5").
   - Для "add_expense" и "borrow": сначала ищите подкатегорию, затем категорию, затем раздел.
   - Если категория не найдена, добавьте в "missing": ["category_code"] (для доходов) или ["chapter_code", "category_code", "subcategory_code"] (для расходов).
5. **Обработка кредиторов** (для "borrow" и "repay"):
   - Ищите имена кредиторов (например, "Крипта", "Мама"). Сопоставьте с метаданными.
   - Если кредитор не найден, добавьте "creditor" в "missing".
6. **Обработка коэффициента** (для "borrow"):
   - Ищите число 0.0–1.0 (например, "коэффициент 0.87").
   - Если не указано, установите 1.0.
7. **Обработка составных запросов**:
   - Если в запросе несколько операций (например, "зарплата 50000 и долг у Крипты 1000"), разделите на отдельные запросы.
8. **Валидация**:
   - Если amount <= 0 или не число, добавьте "amount" в "missing".
   - Если date не в формате DD.MM.YYYY, добавьте "date" в "missing".
   - Для "add_income": если category_code не валиден, добавьте "category_code" в "missing".
   - Для "add_expense" и "borrow": если chapter_code, category_code, subcategory_code не валидны, добавьте их в "missing".
   - Для "borrow" и "repay": если creditor не валиден, добавьте "creditor" в "missing".
9. Если запрос неясен, верните пустой список requests.
10. Формат ответа:
   ```json
   {{
     "requests": [
       {{
         "intent": "<add_income|add_expense|borrow|repay>",
         "entities": {{
           "amount": "<число>",
           "date": "<DD.MM.YYYY>",
           "category_code": "<код категории>",
           "chapter_code": "<код раздела>",
           "category_code": "<код категории расходов>",
           "subcategory_code": "<код подкатегории>",
           "wallet": "<project|borrow|repay>",
           "creditor": "<код кредитора>",
           "coefficient": "<число>",
           "comment": "<строка>"
         }},
         "missing": ["<поле>", ...]
       }}
     ]
   }}
   ```

**Примеры**:
- Ввод: "Получил зарплату 50000 рублей сегодня"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "add_income",
        "entities": {{
          "amount": "50000.0",
          "date": "22.05.2025",
          "category_code": "1",
          "chapter_code": "",
          "category_code": "",
          "subcategory_code": "",
          "wallet": "",
          "creditor": "",
          "coefficient": "1.0",
          "comment": "Зарплата"
        }},
        "missing": []
      }}
    ]
  }}
  ```
- Ввод: "Подарок от мамы 1000 рублей"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "add_income",
        "entities": {{
          "amount": "1000.0",
          "date": "22.05.2025",
          "category_code": "5",
          "chapter_code": "",
          "category_code": "",
          "subcategory_code": "",
          "wallet": "",
          "creditor": "",
          "coefficient": "1.0",
          "comment": "Подарок от мамы"
        }},
        "missing": []
      }}
    ]
  }}
  ```
- Ввод: "Беру в долг у Крипты 2000 рублей на SkillBox с коэффициентом 0.9"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "borrow",
        "entities": {{
          "amount": "2000.0",
          "date": "22.05.2025",
          "category_code": "",
          "chapter_code": "Р0",
          "category_code": "2",
          "subcategory_code": "2.1",
          "wallet": "borrow",
          "creditor": "Крипта",
          "coefficient": "0.9",
          "comment": "SkillBox"
        }},
        "missing": []
      }}
    ]
  }}
  ```
- Ввод: "Вернул долг Маме 1500 рублей"
  Вывод:
  ```json
  {{
    "requests": [
      {{
        "intent": "repay",
        "entities": {{
          "amount": "1500.0",
          "date": "22.05.2025",
          "category_code": "",
          "chapter_code": "",
          "category_code": "",
          "subcategory_code": "",
          "wallet": "repay",
          "creditor": "Мама",
          "coefficient": "1.0",
          "comment": "Возврат долга Маме"
        }},
        "missing": []
      }}
    ]
  }}
  ```

Верните JSON-объект с распознанными запросами.
"""
    return prompt


def get_parse_prompt(input_text: str, metadata: Dict) -> str:
    """Generate the full prompt for parsing user input."""
    today = datetime.now().strftime("%d.%m.%Y")
    system_prompt = generate_system_prompt(metadata, today_date=today)
    return f"{system_prompt}\n\n**Пользовательский ввод**: {input_text}\n\n**Ответ**:"


DECISION_PROMPT = """
Вы — ассистент, анализирующий запросы пользователя для системы учета финансов Артёма Олеговича. 
Ваша задача — определить, нужно ли уточнение для каждого запроса, и решить, объединять ли ответы. 
Ответ должен быть в формате JSON.

**Входные данные**:
- Список requests, где каждый запрос содержит:
  - intent: тип запроса ("add_income", "add_expense", "borrow", "repay")
  - entities: извлеченные сущности (amount, date, category_code, chapter_code, category_code, subcategory_code, wallet, creditor, coefficient, comment)
  - missing: список отсутствующих обязательных полей

**Инструкции**:
1. Для каждого запроса определите:
   - needs_clarification: требуется ли уточнение (true, если есть missing поля).
   - clarification_field: первое поле для уточнения (category_code, chapter_code, category_code, subcategory_code, date, amount, wallet, creditor, coefficient).
   - ready_for_output: готов ли запрос для вывода (true, если missing пустой).
2. Поля, требующие уточнения, в порядке приоритета:
   - Для "add_income": category_code, date, amount
   - Для "add_expense" и "borrow": chapter_code, category_code, subcategory_code, date, amount, wallet, creditor, coefficient
   - Для "repay": date, amount, wallet, creditor
3. Установите combine_responses=false для запросов, требующих уточнения.
   Установите combine_responses=true только для готовых запросов одного типа.
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
      "intent": "add_income",
      "entities": {
        "amount": "50000.0",
        "date": "22.05.2025",
        "category_code": null,
        "chapter_code": "",
        "category_code": "",
        "subcategory_code": "",
        "wallet": "",
        "creditor": "",
        "coefficient": "1.0",
        "comment": "Зарплата"
      },
      "missing": ["category_code"]
    },
    {
      "intent": "repay",
      "entities": {
        "amount": "1000.0",
        "date": "22.05.2025",
        "category_code": "",
        "chapter_code": "",
        "category_code": "",
        "subcategory_code": "",
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

**Входные данные**:
<будут добавлены в run-time>

**Ответ**:
"""

RESPONSE_PROMPT = """
Вы — ассистент, формирующий ответы для системы учета финансов Артёма Олеговича. 
Ваша задача — сгенерировать сообщения для пользователя на основе состояния запросов. 
Ответ должен быть в формате JSON. Клавиатуры формируются через заглушки API.

**Входные данные**:
- Список actions, где каждый action содержит:
  - request_index: индекс запроса
  - needs_clarification: требуется ли уточнение
  - clarification_field: поле для уточнения (chapter_code, category_code, subcategory_code, date, amount, wallet, creditor, coefficient)
  - ready_for_output: готов ли запрос для вывода
- Список requests, где каждый запрос содержит:
  - intent: тип запроса ("add_expense", "borrow", "repay")
  - entities: извлеченные сущности
  - missing: список отсутствующих полей

**Инструкции**:
1. Для каждого action:
   - Если needs_clarification=true, сгенерируйте сообщение с запросом уточнения.
   - Если ready_for_output=true, сгенерируйте сообщение о подтверждении (например, "Операция готова к записи").
2. Для уточнений:
   - chapter_code: "Уточните раздел для расхода на сумму {amount} рублей:"
   - category_code: "Уточните категорию для раздела {chapter_name} (сумма {amount} рублей):"
   - subcategory_code: "Уточните подкатегорию для категории {category_name} (сумма {amount} рублей):"
   - creditor: "Уточните кредитора для операции на сумму {amount} рублей:"
   - date: "Уточните дату в формате ДД.ММ.ГГГГ для операции на сумму {amount} рублей:"
   - amount: "Уточните сумму в рублях:"
   - wallet: "Уточните кошелёк (Проект, Взять в долг, Вернуть долг):"
   - coefficient: "Уточните коэффициент (0.0–1.0) для долга на сумму {amount} рублей:"
3. Клавиатура (для chapter_code, category_code, subcategory_code, creditor):
   - Зглушка: `API:fetch:<поле>:<request_index>`.
   - Кнопка "Отмена": "cancel:<request_index>".
4. Для date, amount, wallet, coefficient запросите текстовый ввод (без клавиатуры).
5. Замените wallet: "project" → "Проект", "borrow" → "Взять в долг", "repay" → "Вернуть долг".
6. Не объединяйте сообщения для запросов, требующих уточнения.
7. Формат ответа:
   ```json
   {
     "messages": [
       {
         "text": "<текст сообщения>",
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
         "state": "Expense:confirm"
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
      "clarification_field": "creditor",
      "ready_for_output": false
    }
  ],
  "requests": [
    {
      "intent": "borrow",
      "entities": {
        "amount": "1000.0",
        "date": "20.05.2025",
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
          [
            {"text": "API:fetch:creditor:0", "callback_data": "API:fetch:creditor:0"}
          ],
          [
            {"text": "Отмена", "callback_data": "cancel:0"}
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
