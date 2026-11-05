"""Arm A's media session: Twilio frames in, Transcribe, one turn, Polly by sentence, Twilio frames out, barge-in.

Why one class with injected ears, mouth and brain: the whole loop is tested with fakes and no network, and the
same loop runs the real pair under `make dev`. Why barge-in is a `clear`: Twilio buffers what we send and plays
it; emptying that buffer is the only way to stop Gus mid-sentence (the WebSocket messages page, DR-005). What
counts as barge-in: a partial transcript with words other than fillers while Gus is speaking. On a call this file
writes the heard and spoken spans (card 03), because only the voice path knows the transcriber's confidence and
lag and the synthesis time.

On an outbound call (spec 9.6 and 9.7, DR-025 sections 12 and 14) the session opens with the PIN ask, because the
opening was already said by Twilio's `<Say>`, and until the PIN matches a transcript made only of hello words is
not a turn: it never barges in, never reaches the model, and gets the PIN ask once more by code, twice at most.
The call's length cap is the outbound one, and the dial's outcome is written off the event loop at the end.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

from candidate_line.brain import Brain, ToolSpec
from candidate_line.escalation import EscalationQueue
from candidate_line.hooks import MAX_HELLO_ASKS, Hooks, awaits_pin, is_hello
from candidate_line.persona import PIN_ASK, RECOVERY_LINE, length_line
from candidate_line.settings import DEFAULT_MAX_CALL_SECONDS
from candidate_line.telephony.audio import (
    decode_twilio_payload,
    encode_twilio_payload,
    frames,
    mulaw_to_pcm16,
    split_sentences,
)
from candidate_line.telephony.speech import Heard, Speaker, Transcriber
from candidate_line.text import FILLERS
from candidate_line.tools.ledger import Ledger
from candidate_line.traces.store import TraceStore
from candidate_line.turn import TurnContext, run_silence, run_turn

log = logging.getLogger("candidate_line.media")

# RECOVERY_LINE (persona.py) is said when a turn raises and the caller is still on the line; the exception is
# logged, the call goes on.
Send = Callable[[dict[str, Any]], Awaitable[None]]
OUT_CHUNK_BYTES = 4000  # half a second of mu-law per WebSocket message

# A final transcript is not the end of a thought. A caller who pauses mid-sentence gets a final at the pause, and
# answering it answers half a question (seen on both arms on the first dialled calls, 2026-11-02). So after a final
# the session waits a short grace for more speech: a partial inside it means the caller went on, and the finals are
# joined into one turn. The wait is short after a question mark, where the caller has handed over the turn, and
# longer after a full stop or no mark at all. The grace cannot be long enough on its own: on the dialled calls of
# 2026-11-02 the next sentence's first partial reached the line 1,234 ms after the previous final, and a grace that
# long on every statement is a slow Gus. So the grace is short, and a turn whose reply is still being made when the
# caller goes on is superseded: its reply is dropped, its words are carried into the next turn, and the caller never
# hears the half-answer. The cost is the grace on every turn plus one wasted model call when it happens; DR-006.
GRACE_AFTER_QUESTION_MS = 300
GRACE_OTHERWISE_MS = 600
GRACE_BACKSTOP_MS = 2000  # a partial that never becomes a final still releases the pending finals
# A caller who says nothing for this long gets the on_silence hook (card 06's holding line); the phone never ran
# it before the dry run of card 06 found the hole. It fires again after another such stretch.
SILENCE_AFTER_S = 6.0
_HANDOVER_MARKS = ("?", "!")

# "Uh huh" and "mm hmm" written as two words are still a caller's yes, and "huh?" asks Gus to say it again, so
# none of them is dropped even though each word alone is a filler.
_NOT_FILLER = re.compile(r"(?i)^\W*(?:uh\W*huh|mm\W*hmm|huh\W*\?)\W*$")

# A PIN reaches the transcript with or without the word PIN before it, and a transcript cannot tell a code from a
# PIN, so a span's text masks every run of three or more digits, written or spoken (spec section 5, Never 4; card
# 03, open decision 3). The code is still in the verify tool's span, where the store masks only the PIN. A time
# such as 9:30 and a date such as 5 November keep their digits, so a booking turn stays readable.
_DIGIT_WORD = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
_DIGIT_RUN = re.compile(r"\d(?:[ ,.\-]{0,2}\d){2,}")
_DIGIT_WORD_RUN = re.compile(rf"\b{_DIGIT_WORD}(?:[ ,.\-]{{1,2}}{_DIGIT_WORD}){{2,}}\b", re.IGNORECASE)


def is_filler(text: str) -> bool:
    """True when every word, without its punctuation and case, is a filler, or there is no word at all."""
    if _NOT_FILLER.match(text):
        return False
    words = ("".join(ch for ch in token if ch.isalnum()).casefold() for token in text.split())
    return all(word in FILLERS for word in words if word)


def mask_spoken_digits(text: str) -> str:
    """The text with each digit of a run of three or more, written or spoken, replaced by an asterisk."""
    text = _DIGIT_RUN.sub(lambda m: re.sub(r"\d", "*", m.group()), text)
    return _DIGIT_WORD_RUN.sub(lambda m: re.sub(_DIGIT_WORD, "*", m.group(), flags=re.IGNORECASE), text)


async def _settle(task: asyncio.Future, timeout: float, what: str) -> None:
    """Awaits a task with a bound and never awaits it past that: a shield keeps the timeout from cancelling into
    the CRT transport, which can hang a cancel after the far side has gone (2026-11-02)."""
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        task.cancel()
        log.warning("%s did not finish in %.0f s; left cancelled", what, timeout)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("%s failed", what)


class MediaSession:
    def __init__(
        self,
        send: Send,
        transcriber: Transcriber,
        speaker: Speaker,
        brain: Brain,
        hooks: Hooks,
        system: str,
        call_id: str,
        stream_sid: str,
        greeting: str | None = None,
        grace_ms: tuple[int, int] = (GRACE_AFTER_QUESTION_MS, GRACE_OTHERWISE_MS),
        store: TraceStore | None = None,
        escalations: EscalationQueue | None = None,
        silence_after_s: float = SILENCE_AFTER_S,
        ledger: Ledger | None = None,
        max_call_seconds: float = DEFAULT_MAX_CALL_SECONDS,
        tools: Sequence[ToolSpec] | None = None,
        outbound: Mapping[str, Any] | None = None,
        on_end: Callable[[TurnContext], object] | None = None,
    ) -> None:
        self._send = send
        self._transcriber = transcriber
        self._speaker = speaker
        self._brain = brain
        self._hooks = hooks
        self._greeting = greeting
        self.stream_sid = stream_sid
        self.ctx = TurnContext(
            call_id=call_id,
            channel="voice",
            system=system,
            store=store,
            escalations=escalations,
            ledger=ledger,
        )
        # None is the inbound line's tools (turn.TOOL_SPECS); an outbound call passes OUTBOUND_TOOL_SPECS.
        self._tools = tools
        # An outbound call's seed, from its dial record (app.py): the code, first name, dial id, attempt and the
        # number's HMAC, never the number.
        self._outbound = dict(outbound) if outbound else None
        if self._outbound is not None:
            self.ctx.data["outbound"] = dict(self._outbound)
        # The dial's outcome write, run in a worker thread once the call has ended (fix 5).
        self._on_end = on_end
        self._silence_after = silence_after_s
        # The per-call length cap (DR-021). The clock is the call's own, from ctx.started_at, and it is read only
        # between turns, so the cap never cuts Gus or the caller off mid-sentence.
        self._max_call_s = float(max_call_seconds)
        self._capped = False  # the length line has been said, so it is said once
        self._last_activity = time.monotonic()  # the caller's last words or the end of Gus's last line
        self._hang_up = (
            asyncio.Event()
        )  # set by a turn whose result says hang_up; the loop ends once Gus has finished
        self.speaking = False
        self.barge_ins = 0
        self.turns = 0
        self._interrupted = asyncio.Event()
        self._pending_marks: set[str] = set()
        self._speak_lock = asyncio.Lock()
        self._utterance_lock = asyncio.Lock()
        self._mark_seq = 0
        # Set when a final transcript arrives; cleared when the first reply byte goes out, for the turn-gap log line.
        self._turn_started: float | None = None
        self._grace_ms = grace_ms
        self._pending: list[str] = []  # finals waiting out the grace, joined into one turn when it ends
        self._grace: asyncio.Task | None = None
        self._thinking = False  # a turn's reply is being made and nothing has been spoken yet
        self._superseded = (
            False  # the caller went on talking during that; the reply is dropped when it arrives
        )
        self._carry = ""  # the superseded turn's words, prepended to the next turn's
        self.superseded = 0
        self._stopped = (
            False  # set when Twilio's stop arrives; a turn finishing after it is dropped, not an error
        )

    async def run(self, incoming: AsyncIterator[dict[str, Any]]) -> None:
        await self._transcriber.start()
        listener = asyncio.create_task(self._listen())
        greeter = asyncio.create_task(self.speak(self._greeting)) if self._greeting else None
        watcher = asyncio.create_task(self._watch_silence())
        try:
            async for message in incoming:
                if self._hang_up.is_set() and not self.speaking:
                    break  # the closing line has played; closing the stream ends the call
                event = message.get("event")
                if event == "media":
                    await self._transcriber.feed(
                        mulaw_to_pcm16(decode_twilio_payload(message["media"]["payload"]))
                    )
                elif event == "mark":
                    self._on_mark(message["mark"]["name"])
                elif event == "stop":
                    break
        finally:
            self._stopped = True
            # First, before anything can yield: the caller has gone, so a turn still waiting out its grace is
            # never made, and no model call is spent on it while the end is written.
            self._cancel_grace()
            outcome = f"{self.turns} turns, {self.barge_ins} barge-ins, {self.superseded} superseded"
            # The call's end in a worker thread (fix 5): the write-up and the dial's outcome take file locks and
            # post, and the other calls' audio shares this event loop. Shielded, so a session cancelled from
            # outside (a server stopping) still has its end written, in order, by the worker.
            cancelled: asyncio.CancelledError | None = None
            ending = asyncio.ensure_future(asyncio.to_thread(self._write_end, outcome))
            try:
                await asyncio.shield(ending)
            except asyncio.CancelledError as error:
                cancelled = error
            watcher.cancel()
            if cancelled is not None:
                # Nothing more is awaited on a cancelled session; the cancellation goes on once its tasks are told.
                self._transcriber_stop_soon()
                for task in (listener, greeter):
                    if task is not None:
                        task.cancel()
                raise cancelled
            # Close our side of the Transcribe stream first and let the listener drain; cancelling it mid-read
            # trips the CRT transport (an InvalidStateError on a cancelled body future, seen 2026-11-01).
            # Same rule as the probe: the CRT transport can hang a close or a cancel after Twilio has gone, so wait
            # with a bound, cancel what is left, and never await a task that may be stuck (2026-11-02).
            await _settle(
                asyncio.ensure_future(self._transcriber.stop()), 5.0, f"transcriber stop {self.ctx.call_id}"
            )
            for task, what in ((listener, "listener"), (greeter, "greeter")):
                if task is not None:
                    await _settle(task, 3.0, f"{what} {self.ctx.call_id}")

    def _write_end(self, outcome: str) -> None:
        """The call's end, in order: the call-end hook, then the dial's outcome, then the store's end. Each step
        is guarded, so one failing never keeps the next from running or breaks the hang-up."""
        try:
            self._hooks.on_call_end(self.ctx, outcome)
        except Exception:
            log.exception("on_call_end failed for %s", self.ctx.call_id)
        if self._on_end is not None:
            try:
                self._on_end(self.ctx)
            except Exception:
                log.exception("the dial's outcome write failed for %s", self.ctx.call_id)
        if self.ctx.store is not None:
            self.ctx.store.end_call(self.ctx.call_id, outcome)

    def _transcriber_stop_soon(self) -> None:
        """Asks the transcriber to stop without waiting for it, for a session that may await nothing more."""
        try:
            asyncio.ensure_future(self._transcriber.stop())
        except Exception:
            log.exception("transcriber stop failed for %s", self.ctx.call_id)

    async def _watch_silence(self) -> None:
        """Runs the on_silence hook when the caller has said nothing for a while and Gus is not busy."""
        while True:
            await asyncio.sleep(0.25)
            if self.speaking or self._thinking or self._pending or self._hang_up.is_set():
                continue
            if not self._mid_turn() and await self._end_at_length_cap():
                continue
            quiet_for = time.monotonic() - self._last_activity
            if quiet_for < self._silence_after:
                continue
            self._last_activity = time.monotonic()  # one line per stretch of silence
            reply = run_silence(self._hooks, self.ctx, round(quiet_for, 1))
            if reply.said:
                log.info("silence %.0f s %s -> %r", quiet_for, self.ctx.call_id, reply.said)
                await self.speak(reply.said)
            if reply.hang_up:
                # Set after the line is sent, as a closing turn does: the loop ends once its marks come back.
                log.info("silence hang-up %s", self.ctx.call_id)
                self._hang_up.set()

    def _mid_turn(self) -> bool:
        """A turn is being made or said, or the caller is mid-sentence (a partial armed the grace with no final
        yet). The length cap waits for neither, so it never talks over the caller."""
        return self._utterance_lock.locked() or (self._grace is not None and not self._grace.done())

    async def _end_at_length_cap(self) -> bool:
        """Once the call has run past its cap, says the length line and asks for the hang-up, as the hold-limit
        line does: the loop ends when its marks come back. True when it did."""
        if self._capped or self._hang_up.is_set():
            return False
        elapsed = time.monotonic() - self.ctx.started_at
        if elapsed < self._max_call_s:
            return False
        self._capped = True
        # Read by the call-end hook, which writes up a screen the cap left unfinished (spec section 7).
        self.ctx.data["length_capped"] = True
        log.info("length cap %s after %.0f s", self.ctx.call_id, elapsed)
        # A hook span and not a kill span: the line is open, and only this call has run its length.
        self._trace(
            "hook",
            "length-cap",
            text=f"the call passed its {self._max_call_s:.0f} s cap, so the line said goodbye between turns",
            seconds=round(elapsed, 1),
            meta={"max_call_seconds": self._max_call_s},
        )
        await self.speak(length_line(self._max_call_s))
        self._hang_up.set()
        return True

    async def _listen(self) -> None:
        try:
            async for heard in self._transcriber.events():
                if heard.is_partial:
                    log.debug("partial %s %r", self.ctx.call_id, mask_spoken_digits(heard.text[-60:]))
                    if self._hello_before_pin(heard.text):
                        # A person saying hello over the PIN ask has not heard it yet; cutting it off would make
                        # them wait for it twice (fix 2).
                        self._last_activity = time.monotonic()
                        continue
                    # A filler leaves the silence clock alone too: line noise transcribed as "Uh." must not hold
                    # a dead call open past the hold limit.
                    if not is_filler(heard.text):
                        self._last_activity = time.monotonic()
                        # Once the length line is queued the goodbye plays whole: a clear would empty it from
                        # Twilio's buffer, and the hang-up would then drop the caller mid-sentence, nothing said.
                        if self.speaking and not self._capped:
                            await self.barge_in()
                        elif self._thinking:
                            self._superseded = True
                        # The caller went on talking: the pending finals wait for the next final, with a backstop.
                        self._arm_grace(None)
                    continue
                filler = is_filler(heard.text)
                self._trace_final(heard, filler)
                if filler:
                    log.info("filler dropped %s %r", self.ctx.call_id, mask_spoken_digits(heard.text))
                    continue
                # Masked as the spans are: a log line is no place for a PIN or a phone number said aloud.
                log.info("final %s %r", self.ctx.call_id, mask_spoken_digits(heard.text))
                self._last_activity = time.monotonic()
                if not self._pending:
                    # The turn's clock starts at the first final, grace included.
                    self._turn_started = time.perf_counter()
                self._pending.append(heard.text)
                self._arm_grace(heard.text)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("listening failed for %s", self.ctx.call_id)
            raise

    def _trace(self, kind: str, name: str, **fields: Any) -> None:
        """Writes one span when the call has a store. A failed write is logged and the call goes on, because a
        trace is never worth a dropped turn or a silent caller."""
        if self.ctx.store is None:
            return
        try:
            self.ctx.store.span(self.ctx.call_id, kind, name, **fields)
        except Exception:
            log.exception("%s span failed for %s", kind, self.ctx.call_id)

    def _trace_final(self, heard: Heard, filler: bool) -> None:
        # Every final is traced, a dropped filler included, so the cockpit shows what the caller said that Gus let go.
        meta: dict[str, Any] = {}
        if heard.confidence is not None:
            meta["confidence"] = heard.confidence
        if filler:
            meta["dropped"] = "filler"
        self._trace(
            "transcribe", "final", text=mask_spoken_digits(heard.text), ms=heard.final_lag_ms, meta=meta
        )

    def _run_undo(self) -> None:
        """Takes back what a superseded turn's tools did, newest first, so a slot booked on half a question is
        free again before the whole question is answered. One reversal failing never stops the rest or the call."""
        undo = self.ctx.data.pop("undo", None) or []
        for reverse in reversed(undo):
            try:
                reverse()
            except Exception:
                log.exception("undo failed for %s", self.ctx.call_id)
        if undo:
            log.info("undid %d tool effects of the superseded turn %s", len(undo), self.ctx.call_id)
        # The dropped turn's tool and tier spans stay in the trace, so this one says they were never heard and
        # what they did was taken back; the cockpit and card 07's booking count read it.
        self._trace(
            "hook",
            "superseded",
            text="the caller kept talking, so this turn was not spoken and its tool effects were taken back",
            meta={"undone": len(undo)},
        )

    def _arm_grace(self, last_final: str | None) -> None:
        self._cancel_grace()
        if last_final is None:
            ms = GRACE_BACKSTOP_MS
        else:
            ms = self._grace_ms[0] if last_final.rstrip().endswith(_HANDOVER_MARKS) else self._grace_ms[1]
        self._grace = asyncio.create_task(self._end_of_turn(ms))

    def _cancel_grace(self) -> None:
        if self._grace is not None and not self._grace.done():
            self._grace.cancel()
        self._grace = None

    async def _end_of_turn(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)
        self._grace = None  # from here the task is a turn, and a later cancel must not reach the brain call
        text = " ".join(self._pending).strip()
        self._pending.clear()
        if not text:
            return
        try:
            await self.handle_utterance(text)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._stopped:
                # The caller hung up while the turn was being made (a goodbye, mostly); the socket is closed.
                log.info("turn dropped after the stop for %s (%s)", self.ctx.call_id, type(error).__name__)
            else:
                log.exception("turn failed for %s", self.ctx.call_id)
                # A failed turn (a model error, a tool raising on an argument it did not expect) used to leave the
                # caller in silence until they spoke again, with the only trace in the log. One fixed line keeps the
                # call alive; the exception is still logged above. Added 2026-11-03 night, before the room.
                try:
                    await self.speak(RECOVERY_LINE)
                except Exception:
                    log.exception("recovery line failed for %s", self.ctx.call_id)

    async def handle_utterance(self, text: str) -> None:
        async with self._utterance_lock:
            if self._capped or self._hang_up.is_set():
                # The closing line is out or on its way; words after it get no turn and no model call, and the
                # loop ends when its marks come back.
                log.info("turn after the closing line dropped %s", self.ctx.call_id)
                return
            if self._carry:
                text = f"{self._carry} {text}"
                self._carry = ""
            if self._hello_before_pin(text):
                await self._answer_hello()
                return
            if self._turn_started is None:
                self._turn_started = time.perf_counter()
            self._thinking, self._superseded = True, False
            history_before = len(self.ctx.history)  # a turn may append more than two messages once tools run
            try:
                # The tools ride as a keyword only on an outbound call, so an inbound turn is the call it always was.
                turn = run_turn if self._tools is None else functools.partial(run_turn, tools=self._tools)
                result = await asyncio.to_thread(turn, self._brain, self._hooks, self.ctx, text)
            finally:
                self._thinking = False
            if self._superseded:
                # The caller kept talking while this reply was being made: the reply is never spoken, the turn's
                # two messages come off the history, and its words lead the next turn, so one whole question is
                # answered once. The turn's clock keeps running from the first final.
                del self.ctx.history[history_before:]
                self._run_undo()
                self._carry = text
                self.superseded += 1
                log.info(
                    "turn superseded %s heard=%r (the caller kept talking)",
                    self.ctx.call_id,
                    mask_spoken_digits(text),
                )
                return
            self.turns += 1
            reply = getattr(result, "reply", None)
            log.info(
                "turn %d %s heard=%r reply=%r brain_ms=%s",
                self.turns,
                self.ctx.call_id,
                mask_spoken_digits(text),
                mask_spoken_digits(result.spoken),
                getattr(reply, "latency_ms", None),
            )
            if result.spoken:
                await self.speak(result.spoken)
            if getattr(result, "hang_up", False):
                self._hang_up.set()
            elif not self._interrupted.is_set():
                # The reply is out in full before the length line is queued behind it, so Twilio plays both whole.
                # A reply the caller cut into is left to the silence watcher, which waits for them to finish.
                await self._end_at_length_cap()

    def _hello_before_pin(self, text: str) -> bool:
        """An outbound call whose PIN is still wanted, hearing only hello words. `confirm_applicant` sets the
        call's `candidate` on the match, and after the match or the second miss hello is a word like any other."""
        if self._outbound is None or not awaits_pin(self.ctx):
            return False
        return is_hello(text, str(self._outbound.get("first_name") or ""))

    async def _answer_hello(self) -> None:
        """Hello words before the PIN are not a turn (spec 9.7): no model call, nothing in the history. The first
        two get the PIN ask again by code; after that they are let go and the silence lines take over."""
        asked = int(self.ctx.data.get("hello_asks") or 0)
        again = asked < MAX_HELLO_ASKS
        self._trace(
            "hook",
            "hello",
            text="hello words before the PIN; " + ("the PIN ask said again by code" if again else "let go"),
            meta={"hello_asks": asked + int(again)},
        )
        self._turn_started = None
        if again:
            self.ctx.data["hello_asks"] = asked + 1
            log.info("hello before the PIN %s; the PIN ask again", self.ctx.call_id)
            await self.speak(PIN_ASK)
        else:
            log.info("hello before the PIN %s let go after %d asks", self.ctx.call_id, asked)

    async def speak(self, text: str) -> None:
        async with self._speak_lock:
            self._interrupted.clear()
            self.speaking = True
            synth_ms = 0.0
            gap_ms: int | None = None
            for sentence in split_sentences(text):
                if self._interrupted.is_set():
                    break
                synth_started = time.perf_counter()
                mulaw = await asyncio.to_thread(self._speaker.say, sentence)
                synth_ms += (time.perf_counter() - synth_started) * 1000
                if self._interrupted.is_set():
                    break
                for chunk in frames(mulaw, OUT_CHUNK_BYTES):
                    if self._turn_started is not None:
                        gap_ms = int((time.perf_counter() - self._turn_started) * 1000)
                        log.info("turn %d %s first_audio_gap_ms=%d", self.turns, self.ctx.call_id, gap_ms)
                        self._turn_started = None
                    await self._send(
                        {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {"payload": encode_twilio_payload(chunk)},
                        }
                    )
                self._mark_seq += 1
                name = f"m{self._mark_seq}"
                self._pending_marks.add(name)
                await self._send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
            # Twilio is still playing what we sent; `speaking` clears when the last mark comes back.
            if not self._pending_marks:
                self.speaking = False
            # Written after the audio is out, so a slow store write never delays the caller's first byte.
            self._trace(
                "speech",
                "polly",
                text=mask_spoken_digits(text),
                chars=len(text),
                ms=round(synth_ms),
                meta={} if gap_ms is None else {"first_audio_gap_ms": gap_ms},
            )

    def _on_mark(self, name: str) -> None:
        self._pending_marks.discard(name)
        if not self._pending_marks:
            self.speaking = False
            self._last_activity = (
                time.monotonic()
            )  # the silence clock starts when Gus has finished, not when he began

    async def barge_in(self) -> None:
        self.barge_ins += 1
        log.info("barge-in %d %s", self.barge_ins, self.ctx.call_id)
        self._interrupted.set()
        self._pending_marks.clear()
        self.speaking = False
        await self._send({"event": "clear", "streamSid": self.stream_sid})
