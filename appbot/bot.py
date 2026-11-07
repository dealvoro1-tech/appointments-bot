"""Логіка діалогу: меню, календар, створення/редагування/скасування записів, налаштування."""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Iterable, Optional

from . import keyboards as K
from . import texts as T
from . import views as V
from .formatting import MONTHS_NOMINATIVE, format_date_long, format_price
from .models import Session
from .scheduling import Scheduler
from .telegram_api import TelegramError
from .timeutil import now_local
from .validators import (
    ValidationError,
    clean_client_name,
    clean_notes,
    clean_procedure,
    normalize_phone,
    parse_price,
    parse_reminder_hours,
    parse_time,
)

log = logging.getLogger(__name__)

NEW_STEPS = ("time", "procedure", "client", "price")
INPUT_STATES = {
    "new_time", "new_procedure", "new_client", "new_price", "new_phone", "new_notes",
    "edit_input", "set_hours",
}
# Колбеки, які працюють зі станом діалогу й не повинні його скидати
FLOW_KINDS = {"s", "sg", "df"}
EDIT_FIELD_KEYS = {
    "date": "date", "time": "time", "procedure": "procedure", "client": "client_name",
    "price": "price_kop", "phone": "phone", "notes": "notes",
}


@dataclass
class Ctx:
    user_id: int
    chat_id: int
    msg_id: Optional[int] = None   # повідомлення з кнопкою, яку натиснули (редагуємо його)
    cb_id: Optional[str] = None
    alert: Optional[str] = None


class Bot:
    def __init__(
        self,
        api,
        repo,
        scheduler: Scheduler,
        allowed_user_ids: Iterable[int],
        now_fn: Callable[[], datetime] = now_local,
    ):
        self.api = api
        self.repo = repo
        self.sched = scheduler
        self.allowed = frozenset(allowed_user_ids)
        self.now = now_fn

    # ==================================================================
    # Вхідна точка
    # ==================================================================
    def handle_update(self, update: dict) -> None:
        try:
            if "callback_query" in update:
                self._on_callback(update["callback_query"])
            elif "message" in update:
                self._on_message(update["message"])
        except Exception as exc:  # не валимо цикл опитування через одне оновлення
            self._report_error(exc, update)

    def _report_error(self, exc: Exception, update: dict) -> None:
        # У логах — лише тип помилки й місце (без тексту повідомлень та даних клієнтів).
        frame = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
        where = f"{frame.filename.split('/')[-1]}:{frame.lineno}" if frame else "?"
        log.error("Помилка обробки оновлення: %s (%s)", type(exc).__name__, where)
        log.debug("Деталі помилки", exc_info=True)
        try:
            cb = update.get("callback_query")
            if cb:
                self.api.answer_callback(cb["id"], T.ERROR, True)
            elif "message" in update:
                self.api.send_message(update["message"]["chat"]["id"], T.ERROR, K.main_menu(False))
        except Exception:
            pass

    # ==================================================================
    # Повідомлення
    # ==================================================================
    def _on_message(self, msg: dict) -> None:
        chat = msg.get("chat", {})
        sender = msg.get("from", {})
        user_id = sender.get("id")
        if chat.get("type") != "private" or user_id is None:
            return
        ctx = Ctx(user_id=user_id, chat_id=chat["id"])
        if user_id not in self.allowed:
            log.warning("Відмовлено у доступі: user_id=%s", user_id)
            self.api.send_message(ctx.chat_id, T.ACCESS_DENIED)
            return

        session = self.repo.get_session(user_id)
        text = msg.get("text")
        if text is None:
            if session.state in INPUT_STATES:
                self._prompt(ctx, session, error=T.NON_TEXT_INPUT)
            else:
                self._show(ctx, T.UNKNOWN_INPUT, K.main_menu(bool(session.draft)))
            return
        if text.startswith("/"):
            self._on_command(ctx, session, text)
            return
        self._on_text(ctx, session, text)

    def _on_command(self, ctx: Ctx, session: Session, text: str) -> None:
        cmd = text.split()[0].split("@")[0].lower()
        self._strip_old_prompt(ctx, session)
        if cmd in ("/start", "/menu"):
            self._go_idle(ctx, session)
            self.show_main_menu(ctx, session)
        elif cmd == "/help":
            self._show(ctx, T.HELP, K.only_nav())
        elif cmd == "/new":
            self._go_idle(ctx, session)
            self.start_new(ctx, session)
        elif cmd == "/cancel":
            session.data.pop("draft", None)
            session.data.pop("draft_state", None)
            self._go_idle(ctx, session)
            self._show(ctx, T.DRAFT_DISCARDED, K.main_menu(False))
        else:
            self._show(ctx, T.UNKNOWN_INPUT, K.main_menu(bool(session.draft)))

    def _on_text(self, ctx: Ctx, session: Session, text: str) -> None:
        if session.state not in INPUT_STATES:
            self._show(ctx, T.UNKNOWN_INPUT, K.main_menu(bool(session.draft)))
            return
        old_pm = session.data.get("pm")
        self._submit_text(ctx, session, text)
        if old_pm:
            self._strip_keyboard(ctx.chat_id, old_pm)

    # ==================================================================
    # Колбеки
    # ==================================================================
    def _on_callback(self, cb: dict) -> None:
        user_id = cb["from"]["id"]
        msg = cb.get("message")
        if msg is None or msg.get("chat", {}).get("type") != "private":
            self.api.answer_callback(cb["id"])
            return
        ctx = Ctx(user_id, msg["chat"]["id"], msg["message_id"], cb["id"])
        if user_id not in self.allowed:
            log.warning("Відмовлено у доступі: user_id=%s", user_id)
            self.api.answer_callback(cb["id"], T.ACCESS_DENIED, True)
            return
        try:
            self._dispatch(ctx, cb.get("data") or "")
        except ValidationError as exc:
            ctx.alert = str(exc)
        finally:
            try:
                self.api.answer_callback(ctx.cb_id, ctx.alert, bool(ctx.alert))
            except Exception:
                pass

    def _dispatch(self, ctx: Ctx, data: str) -> None:
        parts = data.split(":")
        kind = parts[0]
        session = self.repo.get_session(ctx.user_id)
        if kind not in FLOW_KINDS and session.state != "idle":
            self._go_idle(ctx, session)

        if kind in ("noop",):
            return
        if kind == K.PAST:
            ctx.alert = T.PAST_DATE_ALERT
        elif kind == "menu":
            self.show_main_menu(ctx, session)
        elif kind == "new":
            self.start_new(ctx, session)
        elif kind == "new!":
            session.data.pop("draft", None)
            session.data.pop("draft_state", None)
            self.repo.save_session(ctx.user_id, session)
            self.show_year(ctx, "n")
        elif kind == "cal":
            self.show_year(ctx, "v")
        elif kind == "up":
            self.show_upcoming(ctx)
        elif kind == "income":
            self.show_income_years(ctx)
        elif kind == "iy":
            self.show_income_year(ctx, int(parts[1]))
        elif kind == "im":
            self.show_income_month(ctx, int(parts[1]), int(parts[2]))
        elif kind == "y":
            self.show_year(ctx, parts[1])
        elif kind == "m":
            self.show_month(ctx, parts[1], int(parts[2]))
        elif kind == "d":
            self.show_day_grid(ctx, parts[1], int(parts[2]), int(parts[3]), parts[4])
        elif kind == "p":
            self.pick_day(ctx, session, parts[1], datetime.strptime(parts[2], "%Y%m%d").date())
        elif kind == "a":
            self.show_appointment(ctx, int(parts[1]))
        elif kind == "e":
            self.show_edit_menu(ctx, int(parts[1]))
        elif kind == "ef":
            self.edit_field(ctx, session, int(parts[1]), parts[2])
        elif kind == "x":
            self.ask_cancel(ctx, int(parts[1]))
        elif kind == "xy":
            self.do_cancel(ctx, int(parts[1]))
        elif kind == "set":
            self.show_settings(ctx)
        elif kind == "rt":
            enabled, _ = self.sched.reminder_settings()
            self.sched.set_reminders_enabled(not enabled)
            self.show_settings(ctx)
        elif kind == "rh":
            if parts[1] == "c":
                self._enter(ctx, session, "set_hours")
            else:
                self.sched.set_reminder_hours(int(parts[1]))
                self.show_settings(ctx)
        elif kind == "s":
            self.flow_action(ctx, session, parts[1])
        elif kind == "sg":
            self.use_suggestion(ctx, session, int(parts[1]))
        elif kind == "df":
            self.change_draft_field(ctx, session, parts[1])
        else:
            ctx.alert = T.STALE_BUTTON

    # ==================================================================
    # Допоміжне
    # ==================================================================
    def _show(self, ctx: Ctx, text: str, kb: Optional[dict] = None) -> int:
        """Редагує повідомлення з кнопкою (для колбеків) або надсилає нове."""
        if ctx.msg_id is not None:
            try:
                self.api.edit_message_text(ctx.chat_id, ctx.msg_id, text, kb)
                return ctx.msg_id
            except TelegramError as exc:
                if exc.not_modified:
                    return ctx.msg_id
                log.info("Не вдалося редагувати повідомлення (%s), надсилаю нове", exc.code)
        sent = self.api.send_message(ctx.chat_id, text, kb)
        return sent["message_id"]

    def _strip_keyboard(self, chat_id: int, message_id: int) -> None:
        try:
            self.api.remove_keyboard(chat_id, message_id)
        except Exception:
            pass

    def _strip_old_prompt(self, ctx: Ctx, session: Session) -> None:
        pm = session.data.pop("pm", None)
        if pm:
            self._strip_keyboard(ctx.chat_id, pm)

    def _go_idle(self, ctx: Ctx, session: Session) -> None:
        session.state = "idle"
        session.data.pop("edit", None)
        session.data.pop("edit_changes", None)
        self.repo.save_session(ctx.user_id, session)

    # ==================================================================
    # Екрани навігації
    # ==================================================================
    def show_main_menu(self, ctx: Ctx, session: Optional[Session] = None) -> None:
        session = session or self.repo.get_session(ctx.user_id)
        self._show(ctx, T.MAIN_MENU, K.main_menu(bool(session.draft)))

    def start_new(self, ctx: Ctx, session: Session) -> None:
        if session.draft:
            self._show(ctx, T.DRAFT_EXISTS, K.draft_exists_keyboard())
        else:
            self.show_year(ctx, "n")

    def show_year(self, ctx: Ctx, mode: str) -> None:
        kind, _ = K.parse_mode(mode)
        title = {"n": T.CHOOSE_YEAR_NEW, "v": T.CHOOSE_YEAR_VIEW}.get(kind, T.CHOOSE_YEAR_EDIT)
        self._show(ctx, title, K.year_picker(mode, self.now().date(), self.repo.year_counts()))

    def show_month(self, ctx: Ctx, mode: str, year: int) -> None:
        text = f"📅 <b>{year}</b>\nОберіть місяць:"
        counts = self.repo.month_counts(year)
        self._show(ctx, text, K.month_picker(mode, year, self.now().date(), counts))

    def show_day_grid(self, ctx: Ctx, mode: str, year: int, month: int, view: str) -> None:
        if not (2000 <= year <= 2100 and 1 <= month <= 12) or view not in ("g", "l"):
            ctx.alert = T.STALE_BUTTON
            return
        from .formatting import MONTHS_NOMINATIVE
        text = (
            f"📅 <b>{MONTHS_NOMINATIVE[month - 1].capitalize()} {year}</b>\nОберіть день:\n"
            f"<i>{T.CALENDAR_LEGEND}</i>"
        )
        counts = self.repo.day_counts(year, month)
        self._show(ctx, text, K.day_grid(mode, year, month, self.now().date(), counts, view))

    def pick_day(self, ctx: Ctx, session: Session, mode: str, d: date) -> None:
        kind, appt_id = K.parse_mode(mode)
        if kind == "v":
            self.show_day(ctx, d)
        elif kind == "n":
            self.sched.check_date_allowed(d)
            draft = session.draft or {}
            draft["date"] = d.isoformat()
            draft.pop("dup_ok", None)
            session.data["draft"] = draft
            self._enter(ctx, session, "new_time")
        elif kind == "e":
            self._apply_edit(ctx, session, appt_id, {"date": d.isoformat()})

    def show_day(self, ctx: Ctx, d: date) -> None:
        appts = self.repo.list_for_date(d.isoformat())
        can_add = d >= self.now().date()
        self._show(ctx, V.day_text(d, appts), K.day_view(d, appts, can_add))

    def show_upcoming(self, ctx: Ctx) -> None:
        appts = self.repo.upcoming(int(self.now().timestamp()), 10)
        self._show(ctx, V.upcoming_text(appts), K.upcoming_view(appts))

    def show_income_years(self, ctx: Ctx) -> None:
        years = list(self.repo.year_counts())
        current = self.now().year
        self._show(ctx, T.INCOME_YEARS, K.income_year_picker(years, current))

    def show_income_year(self, ctx: Ctx, year: int) -> None:
        if not 2000 <= year <= 2100:
            ctx.alert = T.STALE_BUTTON
            return
        monthly = self.repo.revenue_by_month(year)
        if not monthly:
            self._show(ctx, f"💰 <b>{year}</b>\n\n{T.INCOME_NO_DATA}", K.income_month_picker(year, {}))
            return
        total = sum(amount for amount, _ in monthly.values())
        count = sum(n for _, n in monthly.values())
        text = (
            f"💰 <b>Дохід за {year} рік</b>\n"
            f"Усього: <b>{format_price(total)}</b> · записів: {count}\n\n"
            "Оберіть місяць, щоб переглянути підсумок. Скасовані записи не враховуються."
        )
        self._show(ctx, text, K.income_month_picker(year, monthly))

    def show_income_month(self, ctx: Ctx, year: int, month: int) -> None:
        if not 2000 <= year <= 2100 or not 1 <= month <= 12:
            ctx.alert = T.STALE_BUTTON
            return
        amount, count = self.repo.revenue_for_month(year, month)
        title = f"{MONTHS_NOMINATIVE[month - 1].capitalize()} {year}"
        text = (
            f"💰 <b>{title}</b>\n\n"
            f"Сума за активними записами: <b>{format_price(amount)}</b>\n"
            f"Кількість записів: {count}\n\n"
            "Це сума за вказаними цінами записів, не позначка про фактичну оплату."
        )
        self._show(ctx, text, K.income_month_view(year, month))

    def show_appointment(self, ctx: Ctx, appt_id: int, title: Optional[str] = None) -> None:
        a = self.repo.get_appointment(appt_id)
        if a is None:
            ctx.alert = T.NOT_FOUND
            self.show_main_menu(ctx)
            return
        self._show(ctx, V.appointment_card(a, title), K.appointment_actions(a))

    def show_edit_menu(self, ctx: Ctx, appt_id: int) -> None:
        a = self.repo.get_appointment(appt_id)
        if a is None or not a.is_active:
            ctx.alert = T.NOT_FOUND
            self.show_main_menu(ctx)
            return
        text = "✏️ <b>Що змінити?</b>\n\n" + V.appointment_card(a)
        self._show(ctx, text, K.edit_menu(a))

    def ask_cancel(self, ctx: Ctx, appt_id: int) -> None:
        a = self.repo.get_appointment(appt_id)
        if a is None or not a.is_active:
            ctx.alert = T.NOT_FOUND
            self.show_main_menu(ctx)
            return
        text = f"{T.CANCEL_ASK}\n\n{V.appointment_card(a)}\n\n{T.CANCEL_ASK_HINT}"
        self._show(ctx, text, K.cancel_confirm(a))

    def do_cancel(self, ctx: Ctx, appt_id: int) -> None:
        a = self.sched.cancel(appt_id)
        if a is None:
            ctx.alert = T.NOT_FOUND
            self.show_main_menu(ctx)
            return
        self._show(ctx, V.appointment_card(a, T.CANCELLED_TITLE), K.only_nav(f"p:v:{a.date.replace('-', '')}"))

    def show_settings(self, ctx: Ctx) -> None:
        enabled, hours = self.sched.reminder_settings()
        self._show(ctx, V.settings_text(enabled, hours), K.settings_menu(enabled, hours))

    # ==================================================================
    # Стан діалогу й підказки (кроки введення)
    # ==================================================================
    def _enter(self, ctx: Ctx, session: Session, state: str, error: Optional[str] = None) -> None:
        session.state = state
        if state.startswith("new_"):
            session.data["draft_state"] = state
            if state == "new_confirm" and session.draft is not None:
                session.draft["_complete"] = True
        self._prompt(ctx, session, error)

    def _prompt(self, ctx: Ctx, session: Session, error: Optional[str] = None) -> None:
        text, kb = self._render_prompt(session)
        if error:
            text = f"❌ {V.e(error)}\n\n{text}"
        session.data["pm"] = self._show(ctx, text, kb)
        self.repo.save_session(ctx.user_id, session)

    def _render_prompt(self, session: Session) -> tuple:
        state = session.state
        data = session.data
        data.pop("sugg", None)
        if state.startswith("new_"):
            return self._render_new(session, state[4:])
        if state == "edit_input":
            edit = data["edit"]
            a = self.repo.get_appointment(edit["id"])
            field = edit["field"]
            current = {
                "time": a.time, "procedure": a.procedure, "client": a.client_name,
                "price": format_price(a.price_kop), "phone": a.phone or "—", "notes": a.notes or "—",
            }[field]
            prompts = {
                "time": "🕒 <b>Новий час?</b> Наприклад: 14:30.",
                "procedure": T.ASK_PROCEDURE, "client": T.ASK_CLIENT, "price": T.ASK_PRICE,
                "phone": T.ASK_PHONE, "notes": T.ASK_NOTES,
            }
            text = f"{prompts[field]}\n\nПоточне значення: <i>{V.e(current)}</i>"
            kb = K.step_keyboard(
                clear=field in ("phone", "notes") and current != "—",
                back=f"e:{a.id}", cancel=f"a:{a.id}",
            )
            return text, kb
        if state == "edit_dup":
            changes = data["edit_changes"]
            a = self.repo.get_appointment(data["edit_id"])
            d = date.fromisoformat(changes.get("date", a.date))
            t = time.fromisoformat(changes.get("time", a.time))
            conflicts = self.sched.conflicts(d, t, exclude_id=a.id)
            kb = K.duplicate_keyboard("✏️ Змінити інакше", cancel=f"a:{a.id}")
            return V.conflict_text(conflicts), kb
        if state == "set_hours":
            return T.SETTINGS_ASK_HOURS, K.only_nav("set")
        raise ValueError(f"unknown state {state}")

    def _render_new(self, session: Session, step: str) -> tuple:
        draft = session.draft
        d = date.fromisoformat(draft["date"])
        if step == "time":
            booked = {a.time for a in self.repo.list_for_date(draft["date"])}
            now = self.now()
            slots = [f"{h:02d}:00" for h in range(9, 20)]
            if d == now.date():
                slots = [s for s in slots if time.fromisoformat(s) > now.time()]
            labels = [("🔴 " if s in booked else "") + s for s in slots]
            session.data["sugg"] = slots
            text = f"🕒 <b>О котрій годині?</b>\n📅 {format_date_long(d)}\nОберіть час або введіть, наприклад: 14:30."
            if booked:
                text += "\n<i>🔴 — час уже зайнятий.</i>"
            keep = f"➡️ Залишити {draft['time']}" if draft.get("time") else None
            return text, K.step_keyboard(labels, 4, keep, back="s:back")
        if step == "procedure":
            items = self.repo.frequent_values("procedure")
            session.data["sugg"] = items
            keep = f"➡️ Залишити «{K.short(draft['procedure'], 20)}»" if draft.get("procedure") else None
            return T.ASK_PROCEDURE, K.step_keyboard([K.short(i) for i in items], 2, keep)
        if step == "client":
            items = self.repo.frequent_values("client_name")
            session.data["sugg"] = items
            keep = f"➡️ Залишити «{K.short(draft['client'], 20)}»" if draft.get("client") else None
            return T.ASK_CLIENT, K.step_keyboard([K.short(i) for i in items], 2, keep)
        if step == "price":
            labels, values = [], []
            last = self.repo.last_price_for(draft.get("procedure", ""))
            if last is not None:
                labels.append(format_price(last))
                values.append(format_price(last))
            session.data["sugg"] = values
            keep = f"➡️ Залишити {format_price(draft['price_kop'])}" if draft.get("price_kop") is not None else None
            return T.ASK_PRICE, K.step_keyboard(labels, 2, keep)
        if step == "confirm":
            return f"{T.CONFIRM_TITLE}\n\n{V.draft_card(draft)}", K.confirm_keyboard()
        if step in ("phone", "notes"):
            text = T.ASK_PHONE if step == "phone" else T.ASK_NOTES
            return text, K.step_keyboard(clear=bool(draft.get(step)), back="s:back")
        if step == "dup":
            conflicts = self.sched.conflicts(d, time.fromisoformat(draft["time"]))
            label = "🕒 Змінити час"
            return V.conflict_text(conflicts), K.duplicate_keyboard(label)
        raise ValueError(step)

    # -- введення тексту -----------------------------------------------
    def use_suggestion(self, ctx: Ctx, session: Session, idx: int) -> None:
        sugg = session.data.get("sugg") or []
        if session.state not in INPUT_STATES or not 0 <= idx < len(sugg):
            ctx.alert = T.STALE_BUTTON
            return
        self._submit_text(ctx, session, sugg[idx])

    def _submit_text(self, ctx: Ctx, session: Session, text: str) -> None:
        try:
            self._process_input(ctx, session, text)
        except ValidationError as exc:
            self._prompt(ctx, session, error=str(exc))

    def _process_input(self, ctx: Ctx, session: Session, text: str) -> None:
        state = session.state
        if state == "new_time":
            self._input_new_time(ctx, session, parse_time(text))
        elif state == "new_procedure":
            self._set_draft(ctx, session, "procedure", clean_procedure(text))
        elif state == "new_client":
            self._set_draft(ctx, session, "client", clean_client_name(text))
        elif state == "new_price":
            self._set_draft(ctx, session, "price_kop", parse_price(text))
        elif state == "new_phone":
            session.draft["phone"] = normalize_phone(text)
            self._enter(ctx, session, "new_confirm")
        elif state == "new_notes":
            session.draft["notes"] = clean_notes(text)
            self._enter(ctx, session, "new_confirm")
        elif state == "edit_input":
            self._input_edit(ctx, session, text)
        elif state == "set_hours":
            self.sched.set_reminder_hours(parse_reminder_hours(text))
            session.state = "idle"
            self.repo.save_session(ctx.user_id, session)
            enabled, hours = self.sched.reminder_settings()
            ctx.msg_id = None
            self._show(ctx, "✅ Час нагадування збережено.\n\n" + V.settings_text(enabled, hours),
                       K.settings_menu(enabled, hours))
        else:
            raise ValueError(state)

    def _after_field(self, draft: dict, field: str) -> str:
        if draft.get("_complete"):
            return "new_confirm"
        step = {"price_kop": "price"}.get(field, field)
        idx = NEW_STEPS.index(step)
        return "new_confirm" if idx == len(NEW_STEPS) - 1 else f"new_{NEW_STEPS[idx + 1]}"

    def _set_draft(self, ctx: Ctx, session: Session, field: str, value) -> None:
        session.draft[field] = value
        self._enter(ctx, session, self._after_field(session.draft, field))

    def _input_new_time(self, ctx: Ctx, session: Session, t: time) -> None:
        draft = session.draft
        d = date.fromisoformat(draft["date"])
        self.sched.check_slot(d, t)
        draft["time"] = t.strftime("%H:%M")
        if self.sched.conflicts(d, t) and draft.get("dup_ok") != draft["time"]:
            session.data["dup_ctx"] = "time"
            self._enter(ctx, session, "new_dup")
            return
        self._enter(ctx, session, self._after_field(draft, "time"))

    # -- дії кроків ----------------------------------------------------
    def change_draft_field(self, ctx: Ctx, session: Session, field: str) -> None:
        if not session.draft or session.state != "new_confirm":
            ctx.alert = T.STALE_BUTTON
            return
        mapping = {"time": "new_time", "procedure": "new_procedure", "client": "new_client",
                   "price": "new_price", "phone": "new_phone", "notes": "new_notes"}
        if field not in mapping:
            ctx.alert = T.STALE_BUTTON
            return
        self._enter(ctx, session, mapping[field])

    def flow_action(self, ctx: Ctx, session: Session, action: str) -> None:
        state = session.state
        if action == "resume":
            target = session.data.get("draft_state")
            if not session.draft or not target:
                ctx.alert = T.STALE_BUTTON
                self.show_main_menu(ctx, session)
                return
            self._enter(ctx, session, target)
        elif action == "abort":
            self.abort_flow(ctx, session)
        elif action == "back":
            self.go_back(ctx, session)
        elif action == "keep":
            self.keep_value(ctx, session)
        elif action == "clr":
            self.clear_value(ctx, session)
        elif action == "save":
            if state != "new_confirm" or not session.draft:
                ctx.alert = "Цей запис уже збережено або чернетку скасовано."
                return
            self.save_draft(ctx, session)
        elif action == "dup":
            self.confirm_duplicate(ctx, session)
        else:
            ctx.alert = T.STALE_BUTTON

    def abort_flow(self, ctx: Ctx, session: Session) -> None:
        if session.state.startswith("new_") or (session.state == "idle" and session.draft):
            session.data.pop("draft", None)
            session.data.pop("draft_state", None)
            self._go_idle(ctx, session)
            self._show(ctx, T.DRAFT_DISCARDED, K.main_menu(False))
        elif session.state in ("edit_input", "edit_dup"):
            appt_id = (session.data.get("edit") or {}).get("id") or session.data.get("edit_id")
            self._go_idle(ctx, session)
            self.show_appointment(ctx, appt_id)
        else:
            self._go_idle(ctx, session)
            self.show_main_menu(ctx, session)

    def go_back(self, ctx: Ctx, session: Session) -> None:
        state = session.state
        draft = session.draft
        if state.startswith("new_") and draft:
            if state == "new_time":
                d = date.fromisoformat(draft["date"])
                self._go_idle(ctx, session)
                self.show_day_grid(ctx, "n", d.year, d.month, "g")
            elif state in ("new_phone", "new_notes"):
                self._enter(ctx, session, "new_confirm")
            elif state == "new_dup":
                self._enter(ctx, session, "new_time")
            elif state == "new_confirm":
                self._enter(ctx, session, "new_price")
            elif draft.get("_complete"):
                self._enter(ctx, session, "new_confirm")
            else:
                step = state[4:]
                self._enter(ctx, session, f"new_{NEW_STEPS[NEW_STEPS.index(step) - 1]}")
        elif state in ("edit_input", "edit_dup"):
            appt_id = (session.data.get("edit") or {}).get("id") or session.data.get("edit_id")
            self._go_idle(ctx, session)
            self.show_edit_menu(ctx, appt_id)
        else:
            self._go_idle(ctx, session)
            self.show_main_menu(ctx, session)

    def keep_value(self, ctx: Ctx, session: Session) -> None:
        state, draft = session.state, session.draft
        if not state.startswith("new_") or not draft:
            ctx.alert = T.STALE_BUTTON
            return
        field = {"new_time": "time", "new_procedure": "procedure", "new_client": "client",
                 "new_price": "price_kop"}.get(state)
        if field is None or draft.get(field) is None:
            ctx.alert = T.STALE_BUTTON
            return
        if state == "new_time":  # дата могла змінитися — перевіряємо слот заново
            self._input_new_time(ctx, session, time.fromisoformat(draft["time"]))
        else:
            self._enter(ctx, session, self._after_field(draft, field))

    def clear_value(self, ctx: Ctx, session: Session) -> None:
        state = session.state
        if state in ("new_phone", "new_notes") and session.draft:
            session.draft.pop(state[4:], None)
            self._enter(ctx, session, "new_confirm")
        elif state == "edit_input" and session.data["edit"]["field"] in ("phone", "notes"):
            edit = session.data["edit"]
            self._apply_edit(ctx, session, edit["id"], {edit["field"]: None})
        else:
            ctx.alert = T.STALE_BUTTON

    # -- збереження ----------------------------------------------------
    def save_draft(self, ctx: Ctx, session: Session) -> None:
        draft = session.draft
        d = date.fromisoformat(draft["date"])
        t = time.fromisoformat(draft["time"])
        try:
            self.sched.check_slot(d, t)
        except ValidationError as exc:
            self._enter(ctx, session, "new_time", error=str(exc))
            return
        if self.sched.conflicts(d, t) and draft.get("dup_ok") != draft["time"]:
            session.data["dup_ctx"] = "save"
            self._enter(ctx, session, "new_dup")
            return
        self._finish_save(ctx, session)

    def _finish_save(self, ctx: Ctx, session: Session) -> None:
        appt = self.sched.create(session.draft, user_id=ctx.user_id)  # очищає сесію атомарно
        self._show(ctx, V.appointment_card(appt, T.SAVED_TITLE), K.saved_view(appt))

    def confirm_duplicate(self, ctx: Ctx, session: Session) -> None:
        state = session.state
        if state == "new_dup" and session.draft:
            draft = session.draft
            draft["dup_ok"] = draft["time"]
            if session.data.get("dup_ctx") == "save":
                self._finish_save(ctx, session)
            else:
                self._enter(ctx, session, self._after_field(draft, "time"))
        elif state == "edit_dup":
            self._apply_edit(ctx, session, session.data["edit_id"], session.data["edit_changes"], ack_dup=True)
        else:
            ctx.alert = T.STALE_BUTTON

    # ==================================================================
    # Редагування існуючого запису
    # ==================================================================
    def edit_field(self, ctx: Ctx, session: Session, appt_id: int, field: str) -> None:
        a = self.repo.get_appointment(appt_id)
        if a is None or not a.is_active or field not in EDIT_FIELD_KEYS:
            ctx.alert = T.NOT_FOUND
            self.show_main_menu(ctx, session)
            return
        if field == "date":
            d = a.date_obj
            today = self.now().date()
            d = max(d, today)
            self.show_day_grid(ctx, f"e{appt_id}", d.year, d.month, "g")
            return
        session.data["edit"] = {"id": appt_id, "field": field}
        self._enter(ctx, session, "edit_input")

    def _input_edit(self, ctx: Ctx, session: Session, text: str) -> None:
        edit = session.data["edit"]
        field = edit["field"]
        if field == "time":
            changes = {"time": parse_time(text).strftime("%H:%M")}
        elif field == "procedure":
            changes = {"procedure": clean_procedure(text)}
        elif field == "client":
            changes = {"client_name": clean_client_name(text)}
        elif field == "price":
            changes = {"price_kop": parse_price(text)}
        elif field == "phone":
            changes = {"phone": normalize_phone(text)}
        elif field == "notes":
            changes = {"notes": clean_notes(text)}
        else:
            raise ValueError(field)
        self._apply_edit(ctx, session, edit["id"], changes)

    def _apply_edit(self, ctx: Ctx, session: Session, appt_id: int, changes: dict, ack_dup: bool = False) -> None:
        a = self.repo.get_appointment(appt_id)
        if a is None or not a.is_active:
            ctx.alert = T.NOT_FOUND
            self._go_idle(ctx, session)
            self.show_main_menu(ctx, session)
            return
        if "date" in changes or "time" in changes:
            new_date = date.fromisoformat(changes.get("date", a.date))
            new_time = time.fromisoformat(changes.get("time", a.time))
            if not ack_dup:
                self.sched.check_slot(new_date, new_time)
                if self.sched.conflicts(new_date, new_time, exclude_id=a.id):
                    session.data["edit_id"] = a.id
                    session.data["edit_changes"] = changes
                    self._enter(ctx, session, "edit_dup")
                    return
        updated = self.sched.update(appt_id, **changes)
        session.state = "idle"
        session.data.pop("edit", None)
        session.data.pop("edit_changes", None)
        session.data.pop("edit_id", None)
        self.repo.save_session(ctx.user_id, session)
        if updated is None:
            ctx.alert = T.NOT_FOUND
            self.show_main_menu(ctx, session)
            return
        self._show(ctx, V.appointment_card(updated, T.UPDATED_TITLE), K.appointment_actions(updated))
