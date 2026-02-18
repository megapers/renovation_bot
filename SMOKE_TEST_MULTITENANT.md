# Multi-Tenant Smoke Test

Test that two separate Telegram bots run independently, each serving its own group chat with isolated data.

---

## Setup

### 1. Create two bots via BotFather

Open Telegram, go to [@BotFather](https://t.me/BotFather), and create **two new bots**:

**Bot A:**
```
/newbot
Name: Remont Alpha
Username: remont_alpha_bot  (pick any available name)
```
Copy the token — e.g. `7000000001:AAH...`

**Bot B:**
```
/newbot
Name: Remont Beta
Username: remont_beta_bot  (pick any available name)
```
Copy the token — e.g. `7000000002:BBH...`

### 2. Configure your admin access

Add your Telegram user ID to `.env`:

```env
ADMIN_TELEGRAM_IDS=610379797
```

> Don't know your Telegram ID? Message [@userinfobot](https://t.me/userinfobot) on Telegram.

### 3. Start the bot and register the new bots

```bash
cd C:\Projects\Chatbot
.venv\Scripts\activate
python -m bot
```

Now open a **private chat** with your main bot (`@renovationakil_bot`) and register each new bot:

**Register Bot A:**
```
/addbot 7000000001:AAH...PASTE_FULL_TOKEN_A
```

**Expected:**
```
✅ Бот зарегистрирован!

🤖 Имя: Remont Alpha
👤 Username: @remont_alpha_bot
🆔 Tenant ID: 2

⚡ Перезапустите процесс (python -m bot), чтобы новый бот начал работать.
```

**Register Bot B:**
```
/addbot 7000000002:BBH...PASTE_FULL_TOKEN_B
```

**Verify all bots are registered:**
```
/listbots
```

**Expected:**
```
📋 Зарегистрированные боты:

🟢 Default Bot
   ID: 1 | @renovationakil_bot

🟢 Remont Alpha
   ID: 2 | @remont_alpha_bot

🟢 Remont Beta
   ID: 3 | @remont_beta_bot

Всего: 3
```

### 4. Restart the bot

Press `Ctrl+C` to stop, then start again:

```bash
python -m bot
```

**Expected in logs:**
```
INFO  Bot identity: @renovationakil_bot   (id=...) for tenant_id=1
INFO  Bot identity: @remont_alpha_bot     (id=...) for tenant_id=2
INFO  Bot identity: @remont_beta_bot      (id=...) for tenant_id=3
INFO  Running 3 bot(s)
```

### 5. Create two Telegram groups

- **Group A** — e.g. "Ремонт Альфа"
- **Group B** — e.g. "Ремонт Бета"

---

## Test 1 — Both bots respond independently

| Step | Action | Expected |
|------|--------|----------|
| 1a | Open private chat with **@remont_alpha_bot**, send `/start` | Welcome message from Alpha bot |
| 1b | Open private chat with **@remont_beta_bot**, send `/start` | Welcome message from Beta bot |

**Pass criteria:** Both bots respond. Each has its own name/identity in Telegram.

---

## Test 2 — Create a project on each bot

### Bot A

| Step | Action | Expected |
|------|--------|----------|
| 2a | Send `/newproject` to **Alpha bot** | Wizard starts |
| 2b | Name: `Квартира Альфа` | Prompts for address |
| 2c | Skip through wizard (skip address, area, pick any type, skip budget, Самостоятельно, no co-owner, skip furniture, confirm) | "✅ Проект создан!" |

### Bot B

| Step | Action | Expected |
|------|--------|----------|
| 2d | Send `/newproject` to **Beta bot** | Wizard starts |
| 2e | Name: `Офис Бета` | Prompts for address |
| 2f | Skip through wizard (same quick path, confirm) | "✅ Проект создан!" |

**Pass criteria:** Each bot created its own project independently.

---

## Test 3 — Add each bot to its own group

| Step | Action | Expected |
|------|--------|----------|
| 3a | In Alpha bot's private chat, tap **"👥 Добавить бота в группу"**, pick **Group A** | Alpha bot posts "✅ Группа привязана к проекту Квартира Альфа" in Group A |
| 3b | In Beta bot's private chat, tap **"👥 Добавить бота в группу"**, pick **Group B** | Beta bot posts "✅ Группа привязана к проекту Офис Бета" in Group B |

**Pass criteria:** Each bot auto-linked to its own group and project.

---

## Test 4 — Group commands are isolated

| Step | Action | Expected |
|------|--------|----------|
| 4a | In **Group A**, send `/stages` | Shows stages for "Квартира Альфа" |
| 4b | In **Group B**, send `/stages` | Shows stages for "Офис Бета" |
| 4c | In **Group A**, send `/budget` | Shows budget for "Квартира Альфа" |
| 4d | In **Group B**, send `/budget` | Shows budget for "Офис Бета" |

**Pass criteria:** Each group sees only its own project data. No cross-contamination.

---

## Test 5 — Expenses are isolated

### In Group A (via Alpha bot's private chat):

| Step | Action | Expected |
|------|--------|----------|
| 5a | Send `/expenses` to Alpha bot | Expense wizard starts |
| 5b | Pick: 🔨 Работа → Стены → `Штукатурка` → `50000` | "✅ Расход добавлен!" — Стены 50,000 ₸ |

### In Group B (via Beta bot's private chat):

| Step | Action | Expected |
|------|--------|----------|
| 5c | Send `/expenses` to Beta bot | Expense wizard starts |
| 5d | Pick: 🧱 Материалы → Электрика → `Кабель` → `25000` | "✅ Расход добавлен!" — Электрика 25,000 ₸ |

### Verify isolation:

| Step | Action | Expected |
|------|--------|----------|
| 5e | Send `/budget` to **Alpha bot** | Shows 50,000 ₸ spent (Стены only). No electrical expense. |
| 5f | Send `/budget` to **Beta bot** | Shows 25,000 ₸ spent (Электрика only). No walls expense. |

**Pass criteria:** Expenses from one bot don't appear in the other.

---

## Test 6 — Database verification

```bash
docker compose exec timescaledb psql -U megapers -d renovbot
```

```sql
-- Tenants
SELECT id, name, telegram_bot_username, is_active FROM tenants;

-- Projects scoped to tenants
SELECT p.id, p.name, p.tenant_id, t.name AS tenant_name
FROM projects p
LEFT JOIN tenants t ON p.tenant_id = t.id
ORDER BY p.id;

-- Budget items per tenant
SELECT bi.description, bi.work_cost, bi.material_cost, p.name AS project, t.name AS tenant
FROM budget_items bi
JOIN projects p ON bi.project_id = p.id
LEFT JOIN tenants t ON p.tenant_id = t.id
ORDER BY bi.id;

-- Messages per tenant
SELECT m.id, LEFT(m.transcribed_text, 40) AS text, m.tenant_id, t.name AS tenant
FROM messages m
LEFT JOIN tenants t ON m.tenant_id = t.id
ORDER BY m.id DESC
LIMIT 10;
```

**Pass criteria:**
- Each project has the correct `tenant_id`
- Budget items belong to the right project/tenant
- Messages are tagged with the correct `tenant_id`

---

## Test 7 — Bot stops cleanly

| Step | Action | Expected |
|------|--------|----------|
| 7a | Press `Ctrl+C` in the terminal | Bot logs "Stopping Telegram bot(s)..." and exits |
| 7b | Restart with `python -m bot` | All bots reconnect and respond to commands |

---

## Cleanup

After testing, deactivate the test bots via your main bot:

```
/removebot 2
/removebot 3
```

And delete the test bots in BotFather:
```
/deletebot → select each test bot
```

---

## Pass / Fail Summary

| # | Test | Result |
|---|------|--------|
| 1 | Both bots respond to /start | ☐ |
| 2 | Each bot creates its own project | ☐ |
| 3 | Each bot links to its own group | ☐ |
| 4 | Group commands show correct project | ☐ |
| 5 | Expenses are isolated between bots | ☐ |
| 6 | Database confirms tenant scoping | ☐ |
| 7 | Clean stop and restart | ☐ |

**All 7 pass = Option B is viable for production.**
