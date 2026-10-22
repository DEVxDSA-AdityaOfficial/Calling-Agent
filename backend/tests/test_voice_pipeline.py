import asyncio
import base64

import pytest

from app.speech.audio import tone_ulaw
from app.speech.base import STTConnectionError, TranscriptEvent
from app.voice import pipeline as pl
from app.voice.pipeline import VoicePipeline, split_sentences

START = {"event": "start", "streamSid": "MZ1", "start": {"streamSid": "MZ1", "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}}


class FakeSTT:
    provider = "fake"

    def __init__(self, fail_after=None):
        self.audio = []
        self.closed = False
        self.fail_after = fail_after

    async def start(self):
        pass

    async def send_audio(self, chunk):
        if self.fail_after is not None and len(self.audio) >= self.fail_after:
            raise STTConnectionError("stream dropped")
        self.audio.append(chunk)
        await asyncio.sleep(0)

    async def close(self):
        self.closed = True


class FakeTTS:
    def __init__(self, delay=0.0):
        self.texts = []
        self.delay = delay

    async def stream(self, text):
        self.texts.append(text)
        for i in range(3):
            await asyncio.sleep(self.delay)
            yield f"{text[:4]}{i}".encode()


class FakeModel:
    name = "fake"

    def __init__(self, replies, delay=0.0):
        self.replies = list(replies)
        self.seen = []
        self.delay = delay

    async def stream(self, messages):
        self.seen.append(messages)
        text = self.replies.pop(0) if self.replies else "Okay."
        for word in text.split(" "):
            await asyncio.sleep(self.delay)
            yield word + " "

    async def complete(self, messages):
        return ""

    async def complete_json(self, messages):
        return {}


class Harness:
    def __init__(self, replies=(), begin="Hi {{customer_name}}, I'm an AI assistant.", tts_delay=0.0, model_delay=0.0, **kw):
        self.sent, self.hangups, self.saved = [], 0, []
        self.tts = FakeTTS(tts_delay)
        self.model = FakeModel(replies, model_delay)
        self.stt = FakeSTT(kw.pop("fail_after", None))

        async def send(msg):
            self.sent.append(msg)

        async def hangup():
            self.hangups += 1

        async def persist(t):
            self.saved.append([dict(x) for x in t])

        self.p = VoicePipeline(prompt="You are an agent for {{customer_name}}.", begin_message=begin,
                               variables={"customer_name": "Sam"}, model=self.model, tts=self.tts, send=send,
                               hangup=hangup, persist=persist, max_duration_s=kw.pop("max_s", 60), **kw)

    def events(self, kind):
        return [m for m in self.sent if m["event"] == kind]

    async def echo_marks(self):
        for m in list(self.events("mark")):
            await self.p.on_mark(m["mark"]["name"])


def final(text, seg=None):
    return TranscriptEvent("final", "fake", text=text, segment_id=seg, latency_ms=120)


def test_split_sentences():
    assert split_sentences("Hello there. How are") == (["Hello there."], "How are")
    assert split_sentences("नमस्ते। आप कैसे हैं") == (["नमस्ते।"], "आप कैसे हैं")
    assert split_sentences("no end yet") == ([], "no end yet")


def test_greeting_transcript_reply_and_end_call():
    async def main():
        h = Harness(replies=["Great question. It costs 2,499 rupees a month. Goodbye! [END_CALL]"])
        await h.p.start(START, h.stt)
        await asyncio.sleep(0.05)
        assert h.tts.texts == ["Hi Sam, I'm an AI assistant."]  # variables rendered
        assert h.events("media")[0]["streamSid"] == "MZ1"
        assert base64.b64decode(h.events("media")[0]["media"]["payload"]) == b"Hi S0"
        await h.echo_marks()

        h.p.on_media(base64.b64encode(tone_ulaw(300, 20)).decode())
        await asyncio.sleep(0.02)
        assert h.stt.audio == [tone_ulaw(300, 20)]  # Twilio audio reaches STT unconverted

        await h.p.on_transcript(final("Kitna price hai?", "u0"))
        await asyncio.sleep(0.1)
        # The transcript reached the conversation engine…
        assert h.model.seen[-1][-1] == {"role": "user", "content": "Kitna price hai?"}
        assert "Sam" in h.model.seen[-1][0]["content"]
        # …and the reply was spoken sentence by sentence, without the END_CALL token.
        assert h.tts.texts[1:] == ["Great question.", "It costs 2,499 rupees a month.", "Goodbye!"]
        assert h.hangups == 0  # waits until Twilio confirms the goodbye played
        await h.echo_marks()
        assert h.hangups == 1 and h.p.ended
        await h.p.close()
        assert h.stt.closed and h.saved[-1][-1]["content"].endswith("Goodbye!")
        assert h.p.diag.utterances == 1 and h.p.diag.stt_latencies_ms == [120]

    asyncio.run(main())


def test_barge_in_clears_audio_and_cancels_reply():
    async def main():
        h = Harness(replies=["One. Two. Three. Four. Five. Six.", "Sure, go ahead."], begin=None, tts_delay=0.05, model_delay=0.01)
        await h.p.start(START, h.stt)  # no begin message: the model writes the opening
        await asyncio.sleep(0.12)
        assert h.p.agent_speaking
        await h.p.on_transcript(TranscriptEvent("partial", "fake", text="wait"))  # one word: no barge-in
        assert not h.events("clear")
        await h.p.on_transcript(TranscriptEvent("partial", "fake", text="wait a second"))
        assert len(h.events("clear")) == 1 and not h.p.agent_speaking
        assert h.p.diag.interruptions == 1
        spoken_before = len(h.tts.texts)
        await asyncio.sleep(0.2)
        assert len(h.tts.texts) == spoken_before  # cancelled reply stopped speaking
        assert h.p.transcript[-1]["content"].endswith("…")  # partially heard reply kept, marked cut off
        await h.p.on_transcript(final("Actually, I have a question"))
        await asyncio.sleep(0.3)
        assert h.tts.texts[-1] == "Sure, go ahead."
        await h.p.close()

    asyncio.run(main())


def test_duplicate_finals_and_backpressure():
    async def main():
        h = Harness(replies=["Okay.", "Okay again."])
        await h.p.start(START, h.stt)
        await asyncio.sleep(0.02)
        await h.p.on_transcript(final("Haan bolo", "u1"))
        await h.p.on_transcript(final("Haan bolo", "u1"))  # same segment re-sent
        await h.p.on_transcript(final("haan bolo!", "u2"))  # same words within the window
        await asyncio.sleep(0.05)
        assert [t["content"] for t in h.p.transcript if t["role"] == "user"] == ["Haan bolo"]
        assert h.p.diag.duplicates_suppressed == 2

        h.p._pump.cancel()  # simulate a stalled STT connection
        for _ in range(pl.AUDIO_QUEUE_FRAMES + 25):
            h.p.on_media(base64.b64encode(b"\xff" * 160).decode())
        assert h.p._queue.qsize() == pl.AUDIO_QUEUE_FRAMES and h.p.diag.dropped_frames == 25
        h.p.on_media("%%%not-base64%%%")
        assert "malformed media payload" in h.p.diag.errors
        await h.p.close()
        assert h.p._queue.empty() and h.stt.closed

    asyncio.run(main())


def test_stt_failure_mid_call_says_goodbye_and_hangs_up():
    async def main():
        h = Harness(fail_after=1)
        await h.p.start(START, h.stt)
        await asyncio.sleep(0.02)
        await h.echo_marks()
        for _ in range(3):
            h.p.on_media(base64.b64encode(b"\xff" * 160).decode())
        await asyncio.sleep(0.05)
        assert pl.TECHNICAL_GOODBYE in h.tts.texts and h.p.ended
        await h.echo_marks()
        assert h.hangups == 1
        await h.p.on_transcript(final("hello?"))  # ignored after the call ended
        assert not any(t["content"] == "hello?" for t in h.p.transcript)
        await h.p.close()

    asyncio.run(main())


def test_silence_reminders_then_polite_end():
    async def main():
        h = Harness(replies=["Are you still there?", "Hello? Can you hear me?"], silence_reminder_s=0.3)
        await h.p.start(START, h.stt)
        await asyncio.sleep(0.05)
        for _ in range(12):
            await h.echo_marks()
            await asyncio.sleep(0.25)
        assert h.p.diag.reminders == 2
        assert h.tts.texts[-1].startswith("It seems this isn't a good time")
        await h.echo_marks()
        assert h.hangups == 1
        await h.p.close()

    asyncio.run(main())


def test_close_during_reply_cancels_everything():
    async def main():
        h = Harness(replies=["A long reply. " * 20], tts_delay=0.05)
        await h.p.start(START, h.stt)
        await asyncio.sleep(0.05)
        await h.p.on_transcript(final("tell me everything"))
        await asyncio.sleep(0.05)
        await h.p.close()
        assert h.p._response.done() and h.p._pump.done() and h.p._watchdog.done()
        count = len(h.tts.texts)
        await asyncio.sleep(0.2)
        assert len(h.tts.texts) == count  # nothing keeps speaking after the call is torn down
        await h.p.close()  # idempotent

    asyncio.run(main())


def test_rejects_non_mulaw_stream():
    async def main():
        h = Harness()
        bad = {"event": "start", "start": {"mediaFormat": {"encoding": "audio/l16", "sampleRate": 16000, "channels": 1}}}
        with pytest.raises(ValueError):
            await h.p.start(bad, h.stt)

    asyncio.run(main())
