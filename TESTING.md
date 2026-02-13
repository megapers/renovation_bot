# End-to-End Testing Guide

A comprehensive, step-by-step walkthrough for testing the Renovation Chatbot. This guide follows a realistic use case: **renovating a two-bedroom apartment** — from first launch through project completion.

---

## Prerequisites

Before you begin, make sure everything is set up:

### 1. Start the database

```bash
docker compose up -d
```

Verify it's running:

```bash
docker compose ps
```

You should see `timescaledb` with status **Up** (or **running**).

### 2. Apply database migrations

```bash
cd C:\Projects\Chatbot
.venv\Scripts\activate
alembic upgrade head
```

Confirm with:

```bash
alembic current
```

You should see the latest revision marked as `(head)`.

### 3. Verify AI provider

```bash
python -c "from bot.config import settings; print(f'Provider: {settings.ai_provider}'); print(f'Chat model: {settings.effective_chat_model}'); print(f'Embedding model: {settings.effective_embedding_model}')"
```

Expected output (example for Azure):

```
Provider: azure
Chat model: gpt-5.2-chat-global
Embedding model: text-embedding-3-large
```

If this fails, check your `.env` file — see the **AI Provider Configuration** section in `README.md`.

### 4. Start the bot

```bash
python -m bot
```

Expected console output:

```
INFO     Starting Telegram bot (polling mode)...
INFO     Command scopes registered
INFO     Background scheduler started
INFO     Run polling for bot @YourBotName ...
```

> **"Command scopes registered"** means the bot has set up separate command menus for private and group chats. If you don't see this line, the bot may still work but the Telegram command menu might not show the right commands.

Keep this terminal running. Open Telegram on your phone or desktop to begin testing.

---

## Use Case: Renovating a Two-Bedroom Apartment

You're renovating a 75 m² apartment at "ул. Абая 10, кв. 42" in Almaty. The budget is 5,000,000 ₸. You're coordinating through a foreman named Ерлан. You've ordered a custom kitchen. You'll invite a team member, track expenses, and monitor stages.

---

### Part 1 — Registration

**What you're testing:** The bot recognizes you and creates your user account.

1. Open a **private chat** with your bot in Telegram (search for your bot's @username).

2. **Send:** `/start`

3. **What you should see:**

   ```
   👋 Добро пожаловать!
   
   Я — бот-помощник для управления ремонтом.
   Я помогу отслеживать этапы, сроки и бюджет вашего проекта.
   
   Команды:
   /newproject — создать новый проект
   /myprojects — мои проекты
   /stages — управление этапами
   ...
   ```

4. **Send:** `/start` again — you should see the same welcome message (no duplicate user error).

5. **Verify the command menu:** Tap the `/` button (or the menu icon ☰ next to the text input). You should see **12 commands** including `newproject`, `myprojects`, `stages`, `budget`, `expenses`, `report`, `status`, `team`, `invite`, `myrole`, `ask`, and `launch`.

> **What's happening under the hood:** The bot creates a `User` record with your Telegram ID and marks `is_bot_started = True`. This is required before the bot can send you private messages.

---

### Part 2 — Empty State Check

**What you're testing:** The bot handles having no projects gracefully.

1. **Send:** `/myprojects`

   **Expected:**
   ```
   У вас нет проектов.
   Создайте первый проект командой /newproject
   ```

2. **Send:** `/stages`

   **Expected:**
   ```
   У вас нет активных проектов.
   Создайте проект командой /newproject
   ```

3. Try `/budget`, `/report`, `/status` — same "no projects" message.

> **Why this matters:** Every command uses the unified project resolver. If you have zero projects, it always tells you to create one first instead of crashing.

---

### Part 3 — Create Your Renovation Project

**What you're testing:** The full 7-step project creation wizard with custom furniture.

1. **Send:** `/newproject`

   **Expected:** "🏗 Создание нового проекта ремонта — Шаг 1 из 7 — Введите название объекта"

2. **Type:** `Квартира на Абая`

   **Expected:** Prompts for address with a "Пропустить" (Skip) button.

3. **Type:** `ул. Абая 10, кв. 42, Алматы`

   **Expected:** Prompts for area in m².

4. **Type:** `75`

   **Expected:** Shows 4 inline buttons for renovation type: Косметический / Стандартный / Капитальный / Дизайнерский.

5. **Tap:** `Стандартный`

   **Expected:** Prompts for total budget.

6. **Type:** `5000000`

   **Expected:** "Кто координирует ремонт?" with 3 buttons: Самостоятельно / Прораб / Дизайнер.

7. **Tap:** `Прораб`

   **Expected:** Asks for foreman contact info.

8. **Type:** `Ерлан @erlan_master`

   **Expected:** "Есть ли второй владелец?" with Да/Нет buttons.

9. **Tap:** `Нет`

   **Expected:** Custom furniture picker with items: Кухня, Шкафы, Гардеробная, Двери на заказ. Each can be toggled, plus "Готово" and "Пропустить" buttons.

10. **Tap:** `Кухня` (it highlights), then tap `Готово`

    **Expected:** A full summary of everything you entered:

    ```
    📋 Проверьте данные проекта:
    
    🏠 Название: Квартира на Абая
    📍 Адрес: ул. Абая 10, кв. 42, Алматы
    📐 Площадь: 75.0 м²
    🔧 Тип: Стандартный
    💰 Бюджет: 5,000,000 ₸
    👷 Координатор: Прораб
       Контакт: Ерлан @erlan_master
    🪑 Мебель на заказ: Кухня
    
    Будет создано 13 основных этапов ремонта.
    + 5 параллельных этапов для мебели на заказ.
    ```

    Three buttons: **Подтвердить** / **Редактировать** / **Отменить**

11. **Tap:** `Подтвердить`

    **Expected:**
    - "✅ Проект создан!" with full details
    - A blue inline button: **"👥 Добавить бота в группу"**

    > **This is a deep link button.** When you tap it, Telegram will ask you to pick a group — the bot will automatically join that group and link it to this project. We'll test this in Part 7.

    **Don't tap the button yet** — first let's explore the project in private chat.

---

### Part 4 — Explore Your Project

**What you're testing:** All read-only commands work with a single project (auto-resolves without showing a picker).

#### 4.1 — My Projects

1. **Send:** `/myprojects`

   **Expected:**
   ```
   📋 Мои проекты:
   
   🟢 1. Квартира на Абая | 💰 5,000,000 ₸
   
   Всего проектов: 1
   ```

   > The 🟢 means the project is active. No "👥 Группа" tag yet because we haven't linked it to a group.

#### 4.2 — Stages

1. **Send:** `/stages`

   **Expected:** A list of all 13 standard stages plus 5 custom kitchen stages:
   ```
   📋 Этапы ремонта
   
   1. ⏳ Демонтаж
   2. ⏳ Электрика
   3. ⏳ Сантехника
   4. ⏳ Штукатурка
   ...
   13. ⏳ Финальная приёмка
   14. ⏳ Кухня — Замер
   15. ⏳ Кухня — Договор и предоплата
   16. ⏳ Кухня — Производство
   17. ⏳ Кухня — Доставка
   18. ⏳ Кухня — Установка
   ```

   Below the list you'll see clickable inline buttons for each stage.

2. **Tap any stage** (e.g., "Демонтаж")

   **Expected:** Stage detail view with action buttons:
   - 📅 Сроки (set dates)
   - 👤 Ответственный (assign person)
   - 💰 Бюджет этапа (set stage budget)
   - 📝 Подзадачи (sub-stages)
   - 🔄 Статус (change status)
   - ◀️ Назад (back to list)

#### 4.3 — Budget

1. **Send:** `/budget`

   **Expected:** Budget overview showing the total budget (5,000,000 ₸), spent amount (0 so far), and category breakdown. Plus action buttons:
   - ➕ Добавить расход
   - 📊 Все расходы
   - 📜 История изменений
   - 💳 Оплата этапов

#### 4.4 — Report & Status

1. **Send:** `/report`

   **Expected:** A full weekly-style report with project summary, stage progress, and budget status.

2. **Send:** `/status`

   **Expected:** A quick status summary showing how many stages are planned / in progress / completed.

#### 4.5 — Team & Role

1. **Send:** `/team`

   **Expected:** Shows you as the Owner.

2. **Send:** `/myrole`

   **Expected:**
   ```
   🏠 Квартира на Абая
   
   👤 Your Name
   Роль: Владелец
   ```

---

### Part 5 — Configure Stages

**What you're testing:** Setting dates, responsible persons, budgets, and sub-stages.

#### 5.1 — Set dates for the Demolition stage

1. **Send:** `/stages`

2. **Tap:** "Демонтаж"

3. **Tap:** 📅 **Сроки**

   **Expected:** "Как указать сроки?" with two options:
   - ⏱ По длительности (enter start date + number of days)
   - 📅 Точные даты (enter start + end date)

4. **Tap:** `По длительности`

   **Expected:** "Введите дату начала этапа (ДД.ММ.ГГГГ)"

5. **Type:** `01.03.2026`

   **Expected:** "✅ Дата начала: 01.03.2026 — Введите длительность этапа в днях"

6. **Type:** `14`

   **Expected:** "✅ Сроки установлены: 📅 01.03.2026 — 15.03.2026 (14 дн.)"

   Then automatically shows the stage detail again with the dates filled in.

#### 5.2 — Assign a responsible person

1. In the stage detail view, tap 👤 **Ответственный**

   **Expected:** "Введите имя и контакт ответственного"

2. **Type:** `Ерлан @erlan_master`

   **Expected:** "✅ Ответственный: Ерлан @erlan_master"

#### 5.3 — Set stage budget

1. Tap 💰 **Бюджет этапа**

2. **Type:** `200000`

   **Expected:** "✅ Бюджет этапа: 200,000 ₸"

#### 5.4 — Add sub-stages

1. Tap 📝 **Подзадачи**

   **Expected:** "Подзадач пока нет" with an "➕ Добавить" button.

2. **Tap:** `➕ Добавить`

   **Expected:** Instructions to enter sub-stage names, one per line.

3. **Type** (each on a new line):
   ```
   Снять плитку в ванной
   Демонтировать сантехнику
   Снести перегородку в коридоре
   Вынос мусора
   ```

4. **Expected:**
   ```
   ✅ Добавлено подзадач: 4
   
     1. Снять плитку в ванной
     2. Демонтировать сантехнику
     3. Снести перегородку в коридоре
     4. Вынос мусора
   ```

5. Tap ◀️ **Назад** to return to the stages list.

---

### Part 6 — Launch the Project

**What you're testing:** Project launch and stage status transitions.

1. **Send:** `/launch`

   **Expected:** A launch summary showing the project details, first stage info, and readiness status. With "🚀 Запустить" and "❌ Отмена" buttons.

   > If it says the project is not ready (missing dates on first stage), go back to Part 5 and set dates for at least the first stage.

2. **Tap:** `🚀 Запустить`

   **Expected:**
   ```
   🚀 Проект запущен!
   
   Первый этап «Демонтаж» переведён в статус 🔨 В работе.
   
   Используйте /stages для управления этапами.
   ```

3. **Send:** `/stages` — verify the first stage now shows 🔨 (in progress) instead of ⏳ (planned).

4. **Send:** `/nextstage`

   **Expected:** Shows the current stage (Демонтаж — in progress) and the next upcoming stage (Электрика — planned).

---

### Part 7 — Group Chat Integration

**What you're testing:** Linking a project to a group, deep links, and group command behavior.

#### 7.1 — Create a Telegram group

1. In Telegram, create a new group (e.g., "Ремонт Абая 10").
2. Add at least one other person (or just yourself for testing).

#### 7.2 — Add the bot via deep link

1. Go back to the private chat with the bot.
2. Scroll up to find the "✅ Проект создан!" message.
3. **Tap** the blue **"👥 Добавить бота в группу"** button.
4. Telegram shows a list of your groups — **pick "Ремонт Абая 10"**.

5. **Expected** (in the group chat):
   ```
   ✅ Группа автоматически привязана к проекту Квартира на Абая!
   
   Теперь бот будет отслеживать сообщения в этой группе для данного проекта.
   
   Доступные команды:
   /stages — этапы ремонта
   /budget — бюджет
   /team — команда проекта
   /status — статус проекта
   ```

   > **What happened:** The deep link URL (`t.me/bot?startgroup=proj_N`) added the bot to the group and the bot automatically linked the project by parsing the `proj_N` parameter.

#### 7.3 — Verify /myprojects shows group status

1. Go back to the **private chat** with the bot.
2. **Send:** `/myprojects`

   **Expected:**
   ```
   📋 Мои проекты:
   
   🟢 1. Квартира на Абая | 💰 5,000,000 ₸ | 👥 Группа
   ```

   > Note the new **"👥 Группа"** tag — this confirms the project is linked to a group.

#### 7.4 — Test commands in the group

1. Switch to the **group chat** "Ремонт Абая 10".

2. **Tap** the `/` button — you should see **9 commands** (different from private chat): `link`, `stages`, `budget`, `expenses`, `status`, `report`, `team`, `myrole`, `ask`.

3. **Send in the group:** `/stages`

   **Expected:** Same stage list as in private chat — but here it **auto-resolved** to the linked project without showing any picker.

4. **Send in the group:** `/budget`

   **Expected:** Budget overview for "Квартира на Абая".

5. **Send in the group:** `/team`

   **Expected:** Team list showing you as Owner.

6. **Send in the group:** `/myrole`

   **Expected:** "Роль: Владелец" — same as private chat.

#### 7.5 — Test an unlinked group

1. Create another Telegram group (e.g., "Тест группа").
2. Add the bot to this group manually (without the deep link).

3. **Expected message from bot:**
   ```
   👋 Бот подключён к группе!
   
   Группа: Тест группа
   
   Чтобы привязать эту группу к проекту ремонта, отправьте команду /link
   ```

4. **Send in this group:** `/stages`

   **Expected:**
   ```
   ❌ Эта группа не привязана к проекту.
   Используйте /link чтобы привязать группу к проекту.
   ```

5. You can link it using `/link` — but since your only project is already linked to the other group, it will say:
   ```
   Все ваши проекты уже привязаны к группам.
   ```

---

### Part 8 — Invite a Team Member

**What you're testing:** Role assignment and team management.

1. **In private chat, send:** `/invite`

   **Expected:** "Выберите роль для нового участника" with buttons: Совладелец, Прораб, Электрик, Сантехник, Плиточник, Дизайнер, Отмена.

2. **Tap:** `Прораб`

   **Expected:** Asks for contact — by @username, forwarded message, or name/phone.

3. **Type:** `@erlan_master`

   **Expected:** Confirmation screen:
   ```
   📩 Подтверждение приглашения
   
   Участник: @erlan_master
   Роль: Прораб
   
   Подтвердить?
   ```

4. **Tap:** `Подтвердить`

   **Expected:**
   ```
   ✅ @erlan_master добавлен(а) как Прораб!
   
   💡 Чтобы получать уведомления, участник должен отправить /start боту в личном чате.
   ```

5. **Send:** `/team`

   **Expected:** Now shows 2 members — you (Owner) and @erlan_master (Foreman).

---

### Part 9 — Track Expenses

**What you're testing:** The expense creation wizard and budget tracking.

#### 9.1 — Add a work expense

1. **Send:** `/expenses`

   **Expected:** "Выберите тип расхода" with buttons: 🔨 Работа / 🧱 Материалы / 💵 Предоплата / 🔨+🧱 Работа и материалы / ❌ Отмена.

2. **Tap:** `🔨 Работа`

   **Expected:** Category selector with: Электрика, Сантехника, Стены, Полы, Плитка, Потолки, Двери, Мебель, Другое.

3. **Tap:** `Стены`

   **Expected:** "Введите описание расхода"

4. **Type:** `Демонтаж перегородки в коридоре`

   **Expected:** "Введите стоимость работы (в тенге)"

5. **Type:** `45000`

   **Expected:**
   ```
   ✅ Расход добавлен!
   
   📂 Стены
   📝 Демонтаж перегородки в коридоре
   🔨 Работа: 45,000 ₸
   ```

   Then automatically shows the updated budget overview.

#### 9.2 — Add a combined work + materials expense

1. **Send:** `/expenses`

2. **Tap:** `🔨+🧱 Работа и материалы`

3. **Tap:** `Электрика`

4. **Type:** `Монтаж розеток и выключателей в гостиной`

5. **Enter work cost:** `80000`

6. **Enter material cost:** `35000`

   **Expected:**
   ```
   ✅ Расход добавлен!
   
   📂 Электрика
   📝 Монтаж розеток и выключателей в гостиной
   🔨 Работа: 80,000 ₸
   🧱 Материалы: 35,000 ₸
   ```

#### 9.3 — Check budget

1. **Send:** `/budget`

   **Expected:** Budget overview now shows:
   - Total budget: 5,000,000 ₸
   - Spent: 160,000 ₸ (45k + 80k + 35k)
   - Remaining: 4,840,000 ₸
   - Breakdown by category (Стены: 45k, Электрика: 115k)

2. **Tap:** 📊 **Все расходы**

   **Expected:** A list of your 2 expenses, clickable for detail.

3. **Tap** an expense to see its details, confirm or delete it.

#### 9.4 — Budget change history

1. From the budget overview, tap 📜 **История изменений**

   **Expected:** A log of all budget changes with dates.

---

### Part 10 — AI Features

**What you're testing:** RAG question answering, NLP parsing, voice/photo handling, and embeddings.

> These features require a working AI provider. If AI is not configured, you'll see "⚠️ AI-сервис не настроен."

#### 10.1 — Ask a question

1. **Send:** `/ask Какой у меня бюджет на электрику?`

   **Expected:** Bot shows "🤔 Анализирую...", then replaces it with an AI-generated answer based on your project data, e.g.:

   ```
   🤖 Ответ:
   
   По вашему проекту «Квартира на Абая» на электрику потрачено 115,000 ₸ 
   (работа: 80,000 ₸, материалы: 35,000 ₸). Это составляет 2.3% от общего 
   бюджета в 5,000,000 ₸.
   ```

2. **Send:** `/ask Какие этапы сейчас в работе?`

   **Expected:** AI answer referencing the Demolition stage being in progress.

#### 10.2 — Parse natural language

1. **Send:** `/parse Электрика займёт 10 дней: 3 дня штробление, 4 дня прокладка кабеля, 3 дня установка щитка`

   **Expected:** Parsed output showing:
   ```
   📊 Результат анализа
   
   📋 Этапы:
     • Электрика (10 дн.)
       ◦ Штробление — 3 дн.
       ◦ Прокладка кабеля — 4 дн.
       ◦ Установка щитка — 3 дн.
   ```

#### 10.3 — Voice message

1. **Record and send a voice message** in the private chat (say anything like "Демонтаж завершён, начинаем электрику").

   **Expected:** Bot replies with transcription:
   ```
   🎤 Распознано:
   Демонтаж завершён, начинаем электрику.
   ```

   > The voice message is stored in the database and embedded for future semantic search.

#### 10.4 — Photo message

1. **Send a photo** (e.g., a photo of construction work) with or without a caption.

   **Expected (with AI configured):**
   ```
   📸 Описание фото:
   [AI-generated description of the image in the context of renovation]
   ```

   **Expected (without AI):**
   ```
   📸 Фото сохранено.
   ```

#### 10.5 — Backfill embeddings

1. **Send:** `/backfill`

   **Expected:**
   ```
   ⏳ Обработка исторических сообщений...
   ```
   Then:
   ```
   ✅ Бэкфилл завершён
   
   Обработано сообщений: N
   ```

   > This creates vector embeddings for all previously stored messages that don't have them, improving future `/ask` answers.

---

### Part 11 — Quick Text Commands

**What you're testing:** Natural language shortcuts without the `/` prefix.

In **private chat**, just type these words (no slash):

| You type | What happens |
|---|---|
| `бюджет` | Same as `/budget` — shows budget overview |
| `этапы` | Same as `/stages` — shows stage list |
| `отчёт` | Same as `/report` — generates report |
| `статус` | Same as `/status` — shows status |
| `расходы` | Same as `/expenses` — starts expense wizard |
| `следующий этап` | Same as `/nextstage` — shows next stage |
| `мой этап` | Same as `/mystage` — shows your assigned stages |
| `дедлайн` | Same as `/deadline` — shows deadline report |
| `эксперт` | "Функция будет доступна в следующем обновлении" |

> These work because the bot's catch-all text handler recognizes common renovation-related Russian words and routes them to the appropriate command handler.

---

### Part 12 — Multi-Project Picker

**What you're testing:** When you have more than one project, the bot asks you to pick which one.

1. **Send:** `/newproject`

2. Create a second project quickly:
   - Name: `Дача в Караганде`
   - Skip address, area, and budget
   - Pick type: Косметический
   - Coordinator: Самостоятельно
   - No co-owner, no custom furniture
   - Confirm

3. Now **send:** `/stages`

   **Expected:** Instead of showing stages directly, the bot shows a project picker with two inline buttons:
   ```
   Выберите проект:
   [Квартира на Абая]    [Дача в Караганде]
   ```

4. **Tap:** "Квартира на Абая"

   **Expected:** Shows stages for that project.

5. **Send:** `/budget` — same picker appears. Select a project to see its budget.

6. **Send:** `/myprojects`

   **Expected:**
   ```
   📋 Мои проекты:
   
   🟢 1. Квартира на Абая | 💰 5,000,000 ₸ | 👥 Группа
   🟢 2. Дача в Караганде
   
   Всего проектов: 2
   ```

> **How the picker works:** The bot stores which command you used (the "intent") in FSM state. When you tap a project button, the callback handler checks the intent and dispatches to the correct function. This means `/stages`, `/budget`, `/report`, etc. all share the same picker but each routes correctly.

---

### Part 13 — Payment Tracking

**What you're testing:** The stage payment lifecycle.

1. **Send:** `/budget`

2. **Tap:** 💳 **Оплата этапов**

   **Expected:** List of all stages with their payment status.

3. **Tap** a stage (e.g., "Демонтаж")

   **Expected:** Payment detail showing current payment status and transition buttons. The lifecycle is:
   ```
   Записано → В работе → Проверено → Оплачено → Закрыто
   ```

4. **Tap** a new status to advance the payment. Each transition is logged in the change history.

---

### Part 14 — Reports

**What you're testing:** On-demand reporting with project data.

1. **Send:** `/report`

   **Expected:** A comprehensive weekly-style report including:
   - Project name and budget
   - Stage progress (completed / in progress / planned)
   - Budget summary (spent vs. remaining)
   - Category breakdown
   - Any warnings (overspending, delays)

2. **Send:** `/deadline`

   **Expected:** A deadline-focused report showing stages sorted by urgency — overdue first, then upcoming.

3. **Send:** `/mystage`

   **Expected:** Lists all stages assigned to you across all projects (in private chat). In a group chat, it only shows stages for the linked project.

---

### Part 15 — Database Verification

After completing all tests, verify the data was stored correctly:

```bash
docker compose exec timescaledb psql -U megapers -d renovbot
```

Run these queries:

```sql
-- Check your user
SELECT id, telegram_id, full_name, is_bot_started FROM users;

-- Check projects
SELECT id, name, renovation_type, total_budget, telegram_chat_id, is_active FROM projects;

-- Check stages (for first project)
SELECT id, name, status, sort_order, start_date, end_date, responsible_contact
FROM stages
WHERE project_id = (SELECT id FROM projects ORDER BY created_at LIMIT 1)
ORDER BY sort_order;

-- Check sub-stages
SELECT ss.name, ss."order", s.name as stage_name
FROM sub_stages ss
JOIN stages s ON ss.stage_id = s.id
ORDER BY s.sort_order, ss."order";

-- Check team roles
SELECT u.full_name, pm.role
FROM project_members pm
JOIN users u ON pm.user_id = u.id;

-- Check budget items
SELECT bi.description, bi.category, bi.work_cost, bi.material_cost, bi.is_confirmed
FROM budget_items bi
ORDER BY bi.created_at;

-- Check embeddings
SELECT id, LEFT(content, 60) as content_preview, vector_dims(embedding) as dims
FROM message_embeddings
LIMIT 10;

-- Check change logs
SELECT entity_type, field_name, old_value, new_value, created_at
FROM change_logs
ORDER BY created_at DESC
LIMIT 10;
```

Exit psql with `\q`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot doesn't respond at all | Bot process not running | Check terminal for errors; restart `python -m bot` |
| "Вы не зарегистрированы" | Haven't sent /start yet | Send `/start` in private chat |
| Commands show wrong menu | Command scopes not set | Restart bot; check for "Command scopes registered" in logs |
| Picker shows up with 1 project | Bug or stale state | Send `/start` and try again; FSM state may be stuck |
| "Эта группа не привязана" | Group not linked to project | Use `/link` in the group |
| Deep link button missing | Project created in group chat | Deep link only appears in private chat |
| AI commands return error | AI provider misconfigured | Run the provider check from Prerequisites step 3 |
| Voice not transcribed | Whisper model not deployed | Check AZURE_OPENAI_WHISPER_DEPLOYMENT in .env |
| Photo not described | Vision model not available | Requires GPT-4 Vision capability |
| Expense amounts look wrong | Comma/space in number | Bot strips spaces and commas; use plain digits |
| Bot ignores messages in group | Bot not admin or no permissions | Make bot a group admin, or ensure privacy mode is off in BotFather |

---

## Test Completion Checklist

Use this checklist to confirm you've tested everything:

- [ ] `/start` — registration works
- [ ] Empty state — proper "no projects" messages
- [ ] `/newproject` — full wizard with all 7 steps + custom items
- [ ] Project created — shows deep link button in private chat
- [ ] `/myprojects` — lists projects with budget and group status
- [ ] `/stages` — shows all stages with details
- [ ] Stage dates — both duration and exact date methods work
- [ ] Stage responsible person — can assign contact
- [ ] Stage budget — can set amount
- [ ] Sub-stages — can add multiple sub-stages
- [ ] `/launch` — project launches, first stage goes to "in progress"
- [ ] `/nextstage` — shows current and next stage
- [ ] Group deep link — bot joins group and auto-links project
- [ ] Group commands — auto-resolve to linked project
- [ ] Unlinked group — shows error and suggests /link
- [ ] `/link` — manual group linking works
- [ ] Command menus — 12 private, 9 group commands
- [ ] `/invite` — can invite team member with role
- [ ] `/team` — shows all team members
- [ ] `/myrole` — shows current user's role
- [ ] `/expenses` — full expense wizard (work, materials, combined)
- [ ] `/budget` — overview with categories and totals
- [ ] Budget confirmation — can confirm/delete items
- [ ] Change history — logged correctly
- [ ] Payment stages — status transitions work
- [ ] `/report` — weekly-style report generated
- [ ] `/status` — quick status summary
- [ ] `/deadline` — deadline-focused report
- [ ] `/mystage` — assigned stages shown
- [ ] `/ask` — AI answers project questions
- [ ] `/parse` — NLP extracts stages/expenses
- [ ] `/backfill` — embeddings created
- [ ] Voice message — transcribed and stored
- [ ] Photo message — described and stored
- [ ] Quick text commands — "бюджет", "этапы", etc. work
- [ ] Multi-project picker — appears with 2+ projects
- [ ] Database — all data verified via SQL queries
