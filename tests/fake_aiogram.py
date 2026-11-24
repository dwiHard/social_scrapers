"""aiogram TIRUAN untuk tes: meniru Bot (async context manager), send_message, send_photo, BufferedInputFile."""
import sys
import types


class BufferedInputFile:
    def __init__(self, file, filename, chunk_size=65536):
        self.file, self.filename = file, filename


class Bot:
    sent = []            # [(method, kwargs)]
    fail_photo = False
    fail_document = False
    fail_all = None      # exception untuk semua panggilan
    delay = 0.0
    sessions_closed = 0

    def __init__(self, token, default=None):
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        Bot.sessions_closed += 1
        return False

    async def _maybe_fail(self):
        import asyncio
        if Bot.delay:
            await asyncio.sleep(Bot.delay)
        if Bot.fail_all:
            raise Bot.fail_all

    async def send_message(self, chat_id, text, message_thread_id=None, **kw):
        await self._maybe_fail()
        Bot.sent.append(("send_message", dict(chat_id=chat_id, text=text, message_thread_id=message_thread_id)))

    async def send_photo(self, chat_id, photo, caption=None, message_thread_id=None, **kw):
        await self._maybe_fail()
        if Bot.fail_photo:
            raise RuntimeError("photo rejected")
        Bot.sent.append(("send_photo", dict(chat_id=chat_id, photo=photo, caption=caption,
                                            message_thread_id=message_thread_id)))

    async def send_document(self, chat_id, document, caption=None, message_thread_id=None, **kw):
        await self._maybe_fail()
        if Bot.fail_document:
            raise RuntimeError("document rejected")
        Bot.sent.append(("send_document", dict(chat_id=chat_id, document=document, caption=caption,
                                               message_thread_id=message_thread_id)))


def install():
    saved = {n: sys.modules.get(n) for n in ("aiogram", "aiogram.types")}
    pkg, types_mod = types.ModuleType("aiogram"), types.ModuleType("aiogram.types")
    pkg.Bot = Bot
    types_mod.BufferedInputFile = BufferedInputFile
    pkg.types = types_mod
    sys.modules["aiogram"], sys.modules["aiogram.types"] = pkg, types_mod
    reset()

    def uninstall():
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
    return uninstall


def reset():
    Bot.sent = []
    Bot.fail_photo = False
    Bot.fail_document = False
    Bot.fail_all = None
    Bot.delay = 0.0
    Bot.sessions_closed = 0
