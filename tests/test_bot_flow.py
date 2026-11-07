import unittest

from appbot import texts as T
from tests.helpers import OWNER, BotTestCase, Chat


class Base(BotTestCase):
    def go_to_time_prompt(self, day="20261110"):
        c = self.chat
        c.send("/start")
        c.press("new")
        c.press("m:n:2026")
        c.press("d:n:2026:11:g")
        c.press(f"p:n:{day}")

    def fill(self, time="14:30", procedure="Манікюр", client="Олена Петренко", price="500 грн"):
        c = self.chat
        c.send(time)
        c.send(procedure)
        c.send(client)
        c.send(price)


class CreateFlowTests(Base):
    def test_full_happy_path_and_confirmation(self):
        c = self.chat
        c.send("/start")
        self.assertIn("Головне меню", self.api.last_text)
        self.go_to_time_prompt()
        self.assertIn("вівторок, 10 листопада 2026", self.api.last_text)
        self.fill()
        # екран підтвердження перед збереженням
        self.assertIn("Перевірте запис", self.api.last_text)
        self.assertEqual(self.repo.list_for_date("2026-11-10"), [])
        c.press("s:save")
        text = self.api.last_text
        for part in ["Запис збережено", "вівторок, 10 листопада 2026", "14:30", "Манікюр",
                     "Олена Петренко", "500 грн"]:
            self.assertIn(part, text)
        (appt,) = self.repo.list_for_date("2026-11-10")
        self.assertEqual((appt.time, appt.procedure, appt.client_name, appt.price_kop, appt.phone, appt.notes),
                         ("14:30", "Манікюр", "Олена Петренко", 50000, None, None))
        self.assertEqual(self.repo.get_session(OWNER).state, "idle")

    def test_quick_dates_today_and_tomorrow(self):
        c = self.chat
        c.send("/new")
        c.press("p:n:20261108")  # «Завтра»
        self.assertIn("неділя, 8 листопада 2026", self.api.last_text)

    def test_double_tap_on_save_does_not_duplicate(self):
        self.go_to_time_prompt()
        self.fill()
        self.chat.press("s:save")
        self.chat.press("s:save", check=False)
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 1)
        self.assertIn("уже збережено", self.chat.last_alert())

    def test_optional_phone_and_notes(self):
        c = self.chat
        self.go_to_time_prompt()
        self.fill()
        c.press("df:phone")
        c.send("050 123 45 67")
        self.assertIn("+380501234567", self.api.last_text)
        c.press("df:notes")
        c.send("Алергія на гель-лак")
        c.press("s:save")
        (a,) = self.repo.list_for_date("2026-11-10")
        self.assertEqual((a.phone, a.notes), ("+380501234567", "Алергія на гель-лак"))
        self.assertIn("+380501234567", self.api.last_text)

    def test_invalid_inputs_show_ukrainian_errors_and_stay_on_step(self):
        c = self.chat
        self.go_to_time_prompt()
        c.send("25:99")
        self.assertIn("Такого часу не існує", self.api.last_text)
        c.send("не час")
        self.assertIn("Невірний формат часу", self.api.last_text)
        c.send("14:30")
        c.send("   ")
        self.assertIn("не може бути порожньою", self.api.last_text)
        c.send("Манікюр")
        c.send("О")
        self.assertIn("щонайменше 2 символи", self.api.last_text)
        c.send("Олена")
        c.send("багато")
        self.assertIn("Невірний формат ціни", self.api.last_text)
        c.send("-5")
        self.assertIn("від’ємною", self.api.last_text)
        c.send("500")
        self.assertIn("Перевірте запис", self.api.last_text)
        c.press("df:phone")
        c.send("123")
        self.assertIn("Невірний номер телефону", self.api.last_text)
        self.assertEqual(self.repo.get_session(OWNER).state, "new_phone")

    def test_past_date_is_rejected_with_alert(self):
        c = self.chat
        c.send("/new")
        c.press("m:n:2026")
        c.press("d:n:2026:11:g")
        c.press("pst")
        self.assertEqual(c.last_alert(), T.PAST_DATE_ALERT)
        c.press("p:n:20261106", check=False)  # навіть якщо кнопку обійшли
        self.assertIn("минуло", c.last_alert())
        self.assertFalse(self.repo.get_session(OWNER).draft)

    def test_past_time_today_is_rejected(self):
        c = self.chat
        c.send("/new")
        c.press("p:n:20261107")
        c.send("11:00")
        self.assertIn("Цей час уже минув", self.api.last_text)
        c.send("18:00")
        self.assertIn("Яка процедура", self.api.last_text)

    def test_quick_buttons_minimise_typing(self):
        c = self.chat
        self.add(procedure="Манікюр", client="Олена Петренко", price=65000, date="2026-11-12", time="10:00")
        self.go_to_time_prompt()
        c.press("sg:5")  # 14:00 (09,10,11,12,13,14…)
        self.assertIn("Яка процедура", self.api.last_text)
        c.press("sg:0")  # «Манікюр»
        c.press("sg:0")  # «Олена Петренко»
        self.assertIn("Вартість", self.api.last_text)
        c.press("sg:0")  # остання ціна для процедури
        self.assertIn("650 грн", self.api.last_text)
        c.press("s:save")
        (a,) = self.repo.list_for_date("2026-11-10")
        self.assertEqual((a.time, a.procedure, a.price_kop), ("14:00", "Манікюр", 65000))

    def test_html_in_user_input_is_escaped(self):
        c = self.chat
        self.go_to_time_prompt()
        self.fill(client="<b>Ол&ена</b>", procedure="<i>x</i>")
        self.assertNotIn("<b>Ол", self.api.last_text)
        self.assertIn("&lt;b&gt;Ол&amp;ена&lt;/b&gt;", self.api.last_text)

    def test_back_navigation_through_steps_and_calendar(self):
        c = self.chat
        self.go_to_time_prompt()
        c.send("14:30")
        c.press("s:back")
        self.assertIn("О котрій годині", self.api.last_text)
        c.press("s:keep")
        self.assertIn("Яка процедура", self.api.last_text)
        c.send("Масаж")
        c.press("s:back")
        self.assertIn("Яка процедура", self.api.last_text)
        c.press("s:keep")
        c.press("s:back")
        c.press("s:back")
        self.assertIn("О котрій годині", self.api.last_text)
        c.press("s:back")  # назад до календаря
        self.assertIn("Оберіть день", self.api.last_text)

    def test_cancel_discards_draft_but_keeps_appointments(self):
        self.add()
        c = self.chat
        self.go_to_time_prompt()
        c.send("15:00")
        c.press("s:abort")
        self.assertIn("скасовано", self.api.last_text)
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 1)
        self.assertIsNone(self.repo.get_session(OWNER).draft)


class DuplicateTests(Base):
    def test_warns_and_allows_continue(self):
        self.add(time="14:30", client="Ірина")
        c = self.chat
        self.go_to_time_prompt()
        c.send("14:30")
        self.assertIn("уже є запис", self.api.last_text)
        self.assertIn("Ірина", self.api.last_text)
        c.press("s:dup")
        self.assertIn("Яка процедура", self.api.last_text)
        c.send("Педикюр"); c.send("Олена"); c.send("600")
        c.press("s:save")
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 2)

    def test_can_choose_other_time_instead(self):
        self.add(time="14:30")
        c = self.chat
        self.go_to_time_prompt()
        c.send("14:30")
        c.press("s:back")
        c.send("15:00")
        self.assertIn("Яка процедура", self.api.last_text)
        self.assertNotIn("уже є запис", self.api.last_text)

    def test_conflict_created_after_time_entry_is_caught_on_save(self):
        c = self.chat
        self.go_to_time_prompt()
        self.fill()
        self.add(time="14:30", client="Раптовий")  # хтось зайняв слот, поки заповнювали
        c.press("s:save")
        self.assertIn("Раптовий", self.api.last_text)
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 1)
        c.press("s:dup")
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 2)

    def test_booked_slots_are_marked(self):
        self.add(time="10:00")
        self.go_to_time_prompt()
        self.assertTrue(any(b["text"] == "🔴 10:00" for b in self.api.buttons()))

    def test_cancelled_slot_is_free(self):
        a = self.add(time="14:30")
        self.sched.cancel(a.id)
        self.go_to_time_prompt()
        self.chat.send("14:30")
        self.assertNotIn("уже є запис", self.api.last_text)


class InterruptedFlowTests(Base):
    def test_draft_survives_restart_and_can_be_resumed(self):
        a = self.add(date="2026-11-12")
        c = self.chat
        self.go_to_time_prompt()
        c.send("14:30"); c.send("Масаж")           # зупинилися на кроці «клієнт»
        self.restart()
        self.chat.send("/start")
        self.assertIn("s:resume", self.api.callbacks())
        self.chat.press("s:resume")
        self.assertIn("Ім’я клієнта", self.api.last_text)
        self.chat.send("Марія"); self.chat.send("700")
        self.chat.press("s:save")
        self.assertEqual(len(self.repo.list_for_date("2026-11-10")), 1)
        self.assertIsNotNone(self.repo.get_appointment(a.id))

    def test_menu_mid_flow_keeps_draft(self):
        c = self.chat
        self.go_to_time_prompt()
        c.send("14:30")
        c.press("menu")
        self.assertIn("s:resume", self.api.callbacks())
        c.send("випадковий текст")  # не має «з'їстися» чернеткою
        self.assertIn("Не зрозумів", self.api.last_text)
        self.assertEqual(self.repo.get_session(OWNER).draft["time"], "14:30")

    def test_new_while_draft_exists_asks_first(self):
        c = self.chat
        self.go_to_time_prompt()
        c.press("menu")
        c.press("new")
        self.assertIn("незавершений", self.api.last_text)
        c.press("new!")
        self.assertIn("Оберіть рік", self.api.last_text)
        self.assertIsNone(self.repo.get_session(OWNER).draft)

    def test_stale_buttons_do_nothing_harmful(self):
        c = self.chat
        c.send("/start")
        for data in ("s:save", "s:dup", "s:keep", "s:clr", "sg:0", "df:time", "s:resume"):
            c.press(data, check=False)
        self.assertEqual(self.repo.list_for_date("2026-11-10"), [])
        c.press("zzz", check=False)  # невідомі дані
        self.assertEqual(c.last_alert(), T.STALE_BUTTON)

    def test_slash_cancel_command(self):
        c = self.chat
        self.go_to_time_prompt()
        c.send("/cancel")
        self.assertIsNone(self.repo.get_session(OWNER).draft)


class BrowseTests(Base):
    def test_browse_year_month_day_and_open_appointment(self):
        a = self.add(time="16:00", client="Пізня")
        b = self.add(time="09:00", client="Рання")
        c = self.chat
        c.send("/start")
        c.press("cal")
        self.assertIn("2026 (2)", [x["text"] for x in self.api.buttons()])
        c.press("m:v:2026")
        self.assertIn("листопад (2)", [x["text"] for x in self.api.buttons()])
        c.press("d:v:2026:11:g")
        self.assertIn("10•", [x["text"] for x in self.api.buttons()])
        c.press("p:v:20261110")
        text = self.api.last_text
        self.assertLess(text.index("Рання"), text.index("Пізня"))  # хронологічно
        c.press(f"a:{b.id}")
        for part in ["Рання", "Манікюр", "500 грн", "Створено", "10 листопада 2026"]:
            self.assertIn(part, self.api.last_text)

    def test_past_day_viewable_and_empty_day_message(self):
        self.add(date="2026-11-03")
        self.chat.send("/start")
        self.chat.press("p:v:20261103", check=False)
        self.assertIn("Манікюр", self.api.last_text)
        self.chat.press("p:v:20261104", check=False)
        self.assertIn("записів немає", self.api.last_text)

    def test_upcoming(self):
        self.add(date="2026-11-03", client="Минула")
        self.add(date="2026-11-09", client="Майбутня")
        self.chat.send("/start")
        self.chat.press("up")
        self.assertIn("Майбутня", self.api.last_text)
        self.assertNotIn("Минула", self.api.last_text)


class EditCancelTests(Base):
    def open_edit(self, a, field):
        c = self.chat
        c.send("/start")
        c.press(f"p:v:{a.date.replace('-', '')}", check=False)
        c.press(f"a:{a.id}")
        c.press(f"e:{a.id}")
        c.press(f"ef:{a.id}:{field}")

    def test_edit_price_procedure_client(self):
        a = self.add()
        self.open_edit(a, "price")
        self.chat.send("750,50")
        self.assertIn("Зміни збережено", self.api.last_text)
        self.assertIn("750,50 грн", self.api.last_text)
        self.open_edit(a, "procedure"); self.chat.send("Педикюр")
        self.open_edit(a, "client"); self.chat.send("Марина")
        b = self.repo.get_appointment(a.id)
        self.assertEqual((b.price_kop, b.procedure, b.client_name), (75050, "Педикюр", "Марина"))

    def test_edit_time_validation_and_conflict(self):
        a = self.add(time="14:30")
        other = self.add(time="16:00", client="Інша")
        self.open_edit(a, "time")
        self.chat.send("99:99")
        self.assertIn("Такого часу не існує", self.api.last_text)
        self.chat.send("16:00")
        self.assertIn("Інша", self.api.last_text)           # попередження про дубль
        self.assertEqual(self.repo.get_appointment(a.id).time, "14:30")
        self.chat.press("s:dup")
        self.assertEqual(self.repo.get_appointment(a.id).time, "16:00")

    def test_edit_time_without_conflict_ignores_itself(self):
        a = self.add(time="14:30")
        self.open_edit(a, "time")
        self.chat.send("14:30")  # той самий час — не конфлікт із самим собою
        self.assertIn("Зміни збережено", self.api.last_text)

    def test_reschedule_date_via_calendar(self):
        a = self.add(date="2026-11-10")
        self.open_edit(a, "date")
        self.assertIn("Оберіть день", self.api.last_text)
        self.chat.press("pst", check=False)
        self.chat.press("p:e%d:20261120" % a.id)
        self.assertEqual(self.repo.get_appointment(a.id).date, "2026-11-20")
        self.assertIn("20 листопада 2026", self.api.last_text)

    def test_reschedule_to_past_rejected(self):
        a = self.add(date="2026-11-10")
        self.open_edit(a, "date")
        self.chat.press("p:e%d:20261101" % a.id, check=False)
        self.assertIn("минуло", self.chat.last_alert())
        self.assertEqual(self.repo.get_appointment(a.id).date, "2026-11-10")

    def test_clear_optional_fields(self):
        a = self.add(phone="+380501234567", notes="x")
        self.open_edit(a, "phone")
        self.chat.press("s:clr")
        self.open_edit(a, "notes")
        self.chat.press("s:clr")
        b = self.repo.get_appointment(a.id)
        self.assertEqual((b.phone, b.notes), (None, None))

    def test_cancel_requires_confirmation(self):
        a = self.add()
        c = self.chat
        c.send("/start")
        c.press(f"a:{a.id}", check=False)
        c.press(f"x:{a.id}")
        self.assertIn("Скасувати цей запис?", self.api.last_text)
        self.assertTrue(self.repo.get_appointment(a.id).is_active)      # ще не скасовано
        c.press(f"a:{a.id}")                                           # «Ні, залишити»
        self.assertTrue(self.repo.get_appointment(a.id).is_active)
        c.press(f"x:{a.id}")
        c.press(f"xy:{a.id}")
        self.assertIn("Запис скасовано", self.api.last_text)
        self.assertFalse(self.repo.get_appointment(a.id).is_active)
        self.assertEqual(self.repo.list_for_date("2026-11-10"), [])

    def test_cancelled_appointment_cannot_be_edited(self):
        a = self.add()
        self.sched.cancel(a.id)
        self.chat.send("/start")
        self.chat.press(f"ef:{a.id}:price", check=False)
        self.assertEqual(self.chat.last_alert(), T.NOT_FOUND)


class SettingsTests(Base):
    def test_toggle_and_presets_and_custom(self):
        c = self.chat
        c.send("/start")
        c.press("set")
        self.assertIn("увімкнено", self.api.last_text)
        self.assertIn("24 год", self.api.last_text)
        c.press("rt")
        self.assertIn("вимкнено", self.api.last_text)
        c.press("rt")
        c.press("rh:48")
        self.assertEqual(self.sched.reminder_settings(), (True, 48))
        c.press("rh:c")
        c.send("500")
        self.assertIn("від 1 до 168", self.api.last_text)
        c.send("36")
        self.assertEqual(self.sched.reminder_settings(), (True, 36))
        self.assertIn("36 год", self.api.last_text)

    def test_settings_persist_after_restart(self):
        self.chat.send("/start"); self.chat.press("set"); self.chat.press("rh:2"); self.chat.press("rt")
        self.restart()
        self.assertEqual(self.sched.reminder_settings(), (False, 2))


class AccessTests(Base):
    def test_unauthorised_user_is_rejected_everywhere(self):
        intruder = Chat(self.bot, self.api, user_id=999)
        intruder.send("/start")
        self.assertEqual(self.api.last_text, T.ACCESS_DENIED)
        self.chat.send("/start")  # щоб був екран із кнопками
        intruder.press("new", check=False)
        self.assertEqual(self.api.answers[-1], (T.ACCESS_DENIED, True))
        intruder.send("500")
        self.assertEqual(self.repo.get_session(999).state, "idle")
        self.assertEqual(self.repo.list_for_date("2026-11-10"), [])

    def test_group_chats_ignored(self):
        before = len(self.api.sent)
        self.bot.handle_update({"update_id": 1, "message": {
            "message_id": 1, "from": {"id": OWNER}, "chat": {"id": -5, "type": "group"}, "text": "/start"}})
        self.assertEqual(len(self.api.sent), before)

    def test_non_text_message_is_handled(self):
        self.chat.send("/start")
        self.bot.handle_update({"update_id": 5, "message": {
            "message_id": 5, "from": {"id": OWNER}, "chat": {"id": OWNER, "type": "private"}, "photo": []}})
        self.assertIn("Не зрозумів", self.api.last_text)


class RobustnessTests(Base):
    def test_internal_error_does_not_crash_and_does_not_leak_details(self):
        def boom(*a, **k):
            raise RuntimeError("секретні дані клієнта")
        self.repo.upcoming = boom
        self.chat.send("/start")
        self.chat.press("up")
        self.assertEqual(self.api.answers[-1], (T.ERROR, True))
        self.assertNotIn("секретні", str(self.api.answers))
        self.chat.send("/start")  # бот і далі працює
        self.assertIn("Головне меню", self.api.last_text)

    def test_logs_do_not_contain_client_data(self):
        with self.assertLogs("appbot", level="DEBUG") as logs:
            import logging
            logging.getLogger("appbot.bot").info("probe")
            self.go_to_time_prompt()
            self.fill(client="Секретна Клієнтка", procedure="Секретна процедура")
            self.chat.press("s:save")
        joined = "\n".join(logs.output)
        self.assertNotIn("Секретна", joined)

    def test_help_and_unknown_command(self):
        self.chat.send("/help")
        self.assertIn("Довідка", self.api.last_text)
        self.chat.send("/whatever")
        self.assertIn("Не зрозумів", self.api.last_text)


if __name__ == "__main__":
    unittest.main()
