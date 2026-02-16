"""
Telegram handlers for AI features (Phase 8).

Commands:
  /ask <question>    — ask the AI about the project (RAG)
  /parse <text>      — parse natural language for stage/expense info
  /backfill          — backfill embeddings for historical messages
  /summary           — summarize each participant's contributions

Message handlers:
  Voice messages     — transcribe via Whisper and store
  Photo messages     — describe via GPT-4 Vision and store

Every incoming user message (text, voice, image) is stored in the
messages table and embedded for semantic search.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message as TgMessage

from bot.db import repositories as repo
from bot.db.models import MessageType
from bot.db.session import async_session_factory
from bot.services.ai_client import is_ai_configured
from bot.services.embedding_service import embed_and_store
from bot.services.media_service import build_message_text, process_image, process_voice
from bot.services.nlp_parser import parse_message as nlp_parse
from bot.services.rag_service import ask_project, build_project_context

logger = logging.getLogger(__name__)
router = Router(name="ai_handlers")


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


async def _resolve_project_for_storage(
    message: TgMessage,
) -> tuple[int | None, int | None]:
    """
    Resolve project and user for message storage (voice/photo/text).

    This is a lightweight resolver that does NOT show a picker.
    For storage, we silently pick the best project:
      - Group chat → linked project
      - Private chat → first (newest) project

    Returns (user_id, project_id) — either can be None.
    """
    tg_user = message.from_user
    if tg_user is None:
        return None, None

    async with async_session_factory() as session:
        user = await repo.get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            return None, None

        # Group chat: use linked project
        if message.chat.type in ("group", "supergroup"):
            project = await repo.get_project_by_telegram_chat_id(
                session, message.chat.id
            )
            return user.id, project.id if project else None

        # Private chat: use first (newest) project
        projects = await repo.get_user_projects(session, user.id)
        if projects:
            return user.id, projects[0].id

        return user.id, None


async def _store_and_embed_message(
    *,
    project_id: int | None,
    user_id: int | None,
    chat_id: str,
    message_id: str | None,
    message_type: MessageType,
    raw_text: str | None,
    file_ref: str | None,
    transcribed_text: str | None,
):
    """Store a message in DB and create an embedding if applicable."""
    async with async_session_factory() as session:
        msg = await repo.create_message(
            session,
            project_id=project_id,
            user_id=user_id,
            platform="telegram",
            platform_chat_id=chat_id,
            platform_message_id=message_id,
            message_type=message_type,
            raw_text=raw_text,
            file_ref=file_ref,
            transcribed_text=transcribed_text,
        )

        # Embed the canonical text if we have a project
        canonical = build_message_text(
            message_type=message_type.value,
            raw_text=raw_text,
            transcribed_text=transcribed_text,
        )
        if project_id and canonical:
            await embed_and_store(
                session,
                project_id=project_id,
                content=canonical,
                metadata={
                    "source": "message",
                    "message_id": msg.id,
                    "message_type": message_type.value,
                    "user_id": user_id,
                },
            )

        await session.commit()
        return msg


# ═══════════════════════════════════════════════════════════════
# /ask — RAG question answering
# ═══════════════════════════════════════════════════════════════


@router.message(Command("ask"))
async def cmd_ask(message: TgMessage, state: FSMContext) -> None:
    """
    Answer a question about the project using RAG.

    Usage: /ask Какой бюджет на электрику?
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    # Extract question text after /ask
    question = (message.text or "").strip()
    if question.startswith("/ask"):
        question = question[4:].strip()

    if not question:
        await message.answer(
            "❓ <b>Задайте вопрос</b>\n\n"
            "Использование: /ask &lt;ваш вопрос&gt;\n"
            "Пример: /ask Какой бюджет на электрику?"
        )
        return

    if not is_ai_configured():
        await message.answer(
            "⚠️ AI-сервис не настроен.\n"
            "Обратитесь к администратору для настройки Azure OpenAI."
        )
        return

    # Resolve project (group → linked, private → single/first)
    from bot.adapters.telegram.fsm_states import ReportSelection
    from bot.adapters.telegram.project_resolver import resolve_project

    resolved = await resolve_project(
        message, state,
        intent="ask",
        picker_state=ReportSelection.selecting_project,
    )
    if not resolved:
        return

    async with async_session_factory() as session:
        # Build project context
        report_data = await repo.get_project_full_report_data(
            session, resolved.id
        )
        project_ctx = build_project_context(report_data)

        # Send thinking indicator
        thinking_msg = await message.answer("🤔 Анализирую...")

        # Get RAG answer
        answer = await ask_project(
            session,
            project_id=resolved.id,
            question=question,
            project_context=project_ctx,
        )

        # Edit the thinking message with the result
        try:
            await thinking_msg.edit_text(f"🤖 <b>Ответ:</b>\n\n{answer}")
        except Exception:
            await message.answer(f"🤖 <b>Ответ:</b>\n\n{answer}")


# ═══════════════════════════════════════════════════════════════
# /parse — NLP stage/expense extraction
# ═══════════════════════════════════════════════════════════════


@router.message(Command("parse"))
async def cmd_parse(message: TgMessage, state: FSMContext) -> None:
    """
    Parse natural language for stage/expense information.

    Usage: /parse Демонтаж займёт 2 недели: 3 дня плитка, 4 дня обои
    """
    text = (message.text or "").strip()
    if text.startswith("/parse"):
        text = text[6:].strip()

    if not text:
        await message.answer(
            "📝 <b>Распознавание текста</b>\n\n"
            "Использование: /parse &lt;описание работ&gt;\n"
            "Пример: /parse Демонтаж займёт 2 недели: "
            "3 дня убрать плитку, 4 дня снять обои"
        )
        return

    if not is_ai_configured():
        await message.answer(
            "⚠️ AI-сервис не настроен.\n"
            "Обратитесь к администратору для настройки Azure OpenAI."
        )
        return

    thinking_msg = await message.answer("🔍 Анализирую текст...")

    result = await nlp_parse(text)
    if result is None:
        await thinking_msg.edit_text("❌ Не удалось распознать текст.")
        return

    # Format the parsed result
    parts: list[str] = ["📊 <b>Результат анализа</b>\n"]
    parts.append(f"Намерение: <b>{result.intent}</b>")

    if result.raw_summary:
        parts.append(f"Резюме: {result.raw_summary}")

    if result.stages:
        parts.append("\n📋 <b>Этапы:</b>")
        for stage in result.stages:
            days_str = f" ({stage.total_days} дн.)" if stage.total_days else ""
            budget_str = f" — бюджет: {stage.estimated_budget:,.0f}₽" if stage.estimated_budget else ""
            parts.append(f"  • <b>{stage.stage_name}</b>{days_str}{budget_str}")
            for sub in stage.sub_stages:
                sub_days = f" — {sub.days} дн." if sub.days else ""
                parts.append(f"    ◦ {sub.name}{sub_days}")
            if stage.notes:
                parts.append(f"    💬 {stage.notes}")

    if result.expenses:
        parts.append("\n💰 <b>Расходы:</b>")
        for exp in result.expenses:
            exp_type = "материалы" if exp.is_materials else "работа"
            parts.append(
                f"  • {exp.description} — {exp.amount:,.0f}₽ "
                f"({exp.category}, {exp_type})"
            )

    if result.status_update:
        parts.append(f"\n📌 <b>Обновление статуса:</b> {result.status_update}")

    try:
        await thinking_msg.edit_text("\n".join(parts))
    except Exception:
        await message.answer("\n".join(parts))


# ═══════════════════════════════════════════════════════════════
# /backfill — embed historical messages
# ═══════════════════════════════════════════════════════════════


@router.message(Command("backfill"))
async def cmd_backfill(message: TgMessage, state: FSMContext) -> None:
    """
    Backfill embeddings for historical messages that don't have them yet.

    Owner-only command.
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    if not is_ai_configured():
        await message.answer("⚠️ AI-сервис не настроен.")
        return

    # Resolve project
    from bot.adapters.telegram.fsm_states import ReportSelection
    from bot.adapters.telegram.project_resolver import resolve_project

    resolved = await resolve_project(
        message, state,
        intent="backfill",
        picker_state=ReportSelection.selecting_project,
    )
    if not resolved:
        return

    async with async_session_factory() as session:
        # Check role — only owners can backfill
        roles = await repo.get_user_roles_in_project(
            session, resolved.user_id, resolved.id
        )
        from bot.db.models import RoleType
        if RoleType.OWNER not in roles:
            await message.answer("⛔ Только владелец проекта может запустить бэкфилл.")
            return

        status_msg = await message.answer("⏳ Обработка исторических сообщений...")

        messages = await repo.get_messages_without_embeddings(
            session, resolved.id
        )
        if not messages:
            await status_msg.edit_text("✅ Все сообщения уже обработаны.")
            return

        count = 0
        for msg in messages:
            canonical = build_message_text(
                message_type=msg.message_type.value,
                raw_text=msg.raw_text,
                transcribed_text=msg.transcribed_text,
            )
            if canonical:
                await embed_and_store(
                    session,
                    project_id=resolved.id,
                    content=canonical,
                    metadata={
                        "source": "backfill",
                        "message_id": msg.id,
                        "message_type": msg.message_type.value,
                        "user_id": msg.user_id,
                    },
                )
                count += 1

        await session.commit()

        await status_msg.edit_text(
            f"✅ <b>Бэкфилл завершён</b>\n\n"
            f"Обработано сообщений: {count}\n"
            f"Всего сообщений без эмбеддингов: {len(messages)}"
        )


# ═══════════════════════════════════════════════════════════════
# /summary — participant contribution summaries
# ═══════════════════════════════════════════════════════════════


@router.message(Command("summary"))
async def cmd_summary(message: TgMessage, state: FSMContext) -> None:
    """
    Generate an AI summary of each participant's contributions.

    Usage: /summary
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    if not is_ai_configured():
        await message.answer("⚠️ AI-сервис не настроен.")
        return

    from bot.adapters.telegram.fsm_states import ReportSelection
    from bot.adapters.telegram.project_resolver import resolve_project

    resolved = await resolve_project(
        message, state,
        intent="summary",
        picker_state=ReportSelection.selecting_project,
    )
    if not resolved:
        return

    status_msg = await message.answer("🔍 Анализирую вклад участников...")

    from bot.services.participant_service import summarize_all_participants

    async with async_session_factory() as session:
        summaries = await summarize_all_participants(
            session, project_id=resolved.id,
        )

    if not summaries:
        await status_msg.edit_text("📭 Нет сообщений участников для анализа.")
        return

    parts: list[str] = ["👥 <b>Вклад участников проекта</b>\n"]
    for s in summaries:
        parts.append(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>{s['user_name']}</b> ({s['message_count']} сообщ.)\n\n"
            f"{s['summary']}"
        )

    text = "\n\n".join(parts)
    # Telegram message limit is ~4096 chars; split if needed
    if len(text) > 4000:
        # Send in chunks per participant
        await status_msg.edit_text(parts[0])
        for part in parts[1:]:
            full_part = part.strip()
            if full_part:
                await message.answer(full_part)
    else:
        try:
            await status_msg.edit_text(text)
        except Exception:
            await message.answer(text)


# ═══════════════════════════════════════════════════════════════
# Voice message handler
# ═══════════════════════════════════════════════════════════════


@router.message(F.voice)
async def handle_voice_message(message: TgMessage, bot: Bot, **kwargs) -> None:
    """
    Handle incoming voice messages.

    1. Download the voice file from Telegram
    2. Transcribe via Whisper
    3. Store the message with transcribed text
    4. Create an embedding
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    voice = message.voice
    if voice is None:
        return

    silent = kwargs.get("gate_silent", False)
    user_id, project_id = await _resolve_project_for_storage(message)

    # Download and transcribe
    file_id = voice.file_id
    transcribed = None

    if is_ai_configured():
        try:
            file = await bot.get_file(file_id)
            if file.file_path:
                result = await bot.download_file(file.file_path)
                if result:
                    audio_bytes = result.read()
                    transcribed = await process_voice(
                        audio_bytes, filename="voice.ogg"
                    )
        except Exception as e:
            logger.error("Voice download/transcription failed: %s", e)

    # Store the message
    await _store_and_embed_message(
        project_id=project_id,
        user_id=user_id,
        chat_id=str(message.chat.id),
        message_id=str(message.message_id),
        message_type=MessageType.VOICE,
        raw_text=None,
        file_ref=file_id,
        transcribed_text=transcribed,
    )

    # Reply (skip when gate_silent — group message not directed at bot)
    if silent:
        return
    if transcribed:
        await message.reply(
            f"🎤 <b>Распознано:</b>\n{transcribed}"
        )
    else:
        await message.reply(
            "🎤 Голосовое сообщение сохранено."
            + ("" if is_ai_configured() else "\n⚠️ Транскрипция недоступна (AI не настроен).")
        )


# ═══════════════════════════════════════════════════════════════
# Photo/image message handler
# ═══════════════════════════════════════════════════════════════


@router.message(F.photo)
async def handle_photo_message(message: TgMessage, bot: Bot, **kwargs) -> None:
    """
    Handle incoming photo messages.

    1. Get the largest photo resolution
    2. Download the image from Telegram
    3. Describe via GPT-4 Vision
    4. Store the message with AI description
    5. Create an embedding
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    photos = message.photo
    if not photos:
        return

    # Get the largest photo
    photo = photos[-1]
    caption = message.caption

    silent = kwargs.get("gate_silent", False)
    user_id, project_id = await _resolve_project_for_storage(message)

    # Download and describe
    file_id = photo.file_id
    description = None

    if is_ai_configured():
        try:
            file = await bot.get_file(file_id)
            if file.file_path:
                result = await bot.download_file(file.file_path)
                if result:
                    image_bytes = result.read()
                    description = await process_image(
                        image_bytes, caption=caption
                    )
        except Exception as e:
            logger.error("Photo download/description failed: %s", e)

    # Combine caption + AI description
    transcribed = description
    if caption and description:
        transcribed = f"{caption}\n\n[AI описание]: {description}"
    elif caption and not description:
        transcribed = caption

    # Store the message
    await _store_and_embed_message(
        project_id=project_id,
        user_id=user_id,
        chat_id=str(message.chat.id),
        message_id=str(message.message_id),
        message_type=MessageType.IMAGE,
        raw_text=caption,
        file_ref=file_id,
        transcribed_text=transcribed,
    )

    # Reply (skip when gate_silent — group message not directed at bot)
    if silent:
        return
    if description:
        reply = f"📸 <b>Описание фото:</b>\n{description}"
    elif caption:
        reply = "📸 Фото сохранено."
    else:
        reply = (
            "📸 Фото сохранено."
            + ("" if is_ai_configured() else "\n⚠️ Описание недоступно (AI не настроен).")
        )

    await message.reply(reply)


# ═══════════════════════════════════════════════════════════════
# Text message storage (runs on all text messages for embedding)
# ═══════════════════════════════════════════════════════════════


@router.message(F.text & ~F.text.startswith("/"), flags={"store_message": True})
async def store_text_message(message: TgMessage, **kwargs) -> None:
    """
    Store every incoming text message for future RAG/embedding use.

    In group chats, messages that are NOT directed at the bot arrive
    with ``gate_silent=True`` (set by MentionGateMiddleware).  These are
    stored silently — no reply, no interaction — so the RAG system and
    participant-summary feature have full conversation history.

    Note: Commands are excluded at the filter level (not just inside the
    handler body) so that they can be matched by routers registered later
    (e.g. report_router for /report, /status, /nextstage, etc.).
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    text = message.text or ""

    # Skip very short messages (single characters, etc.)
    if len(text.strip()) < 3:
        return

    user_id, project_id = await _resolve_project_for_storage(message)

    await _store_and_embed_message(
        project_id=project_id,
        user_id=user_id,
        chat_id=str(message.chat.id),
        message_id=str(message.message_id),
        message_type=MessageType.TEXT,
        raw_text=text,
        file_ref=None,
        transcribed_text=text,
    )
