"""Twilio's REST API over the standard library, for the dialler and the probe (DR-011, DR-025 section 12).

Why no SDK: the line needs a handful of calls (create a call, update it, read it, its recordings, a number's voice
URL), each a form POST or a GET with basic auth, and the standard library keeps the image small and every request
readable in one place. Why one machine-detection mode only: `place_call` can ask for answering machine detection
in one way, `DetectMessageEnd` with `AsyncAmd=true` and its callback, so the opening plays at once to a person and a
voicemail is left after the beep (fix 8); there is no parameter that turns on the synchronous mode. Why errors are
scrubbed: Twilio's error messages can quote the number dialled, and an error ends up in a log line.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from candidate_line.traces.store import mask_number

API = "https://api.twilio.com/2010-04-01/Accounts"
# Twilio's own default is 60 s of ringing; 30 s reaches a person who picks up and leaves a voicemail box to answer.
DEFAULT_RING_TIMEOUT_S = 30
# The call progress events the status callback hears: a person or machine answered, and the call ended.
STATUS_EVENTS = ("answered", "completed")
# A run of digits long enough to be a phone number, with the separators people and Twilio write between them.
_NUMBER_RUN = re.compile(r"[+(]?\d[\d\s().-]{5,}\d")

Opener = Callable[[urllib.request.Request, float], bytes]


def scrub_numbers(text: str) -> str:
    """The text with every phone-number-like run of digits in its masked form."""
    return _NUMBER_RUN.sub(lambda m: mask_number(m.group()) or "***", text)


class TwilioError(RuntimeError):
    """A refused or failed request. The message has every number in it masked, so it can be logged."""

    def __init__(self, status: int | None, code: int | None, message: str) -> None:
        super().__init__(scrub_numbers(message))
        self.status = status
        self.code = code


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class TwilioRest:
    """The REST calls the line and the probe make, over the account SID and auth token from settings."""

    def __init__(
        self, account_sid: str, auth_token: str, opener: Opener | None = None, timeout_s: float = 30.0
    ) -> None:
        self.sid = account_sid
        self._auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        self._open = opener or _urlopen
        self._timeout = timeout_s

    def __repr__(self) -> str:
        return "TwilioRest()"  # the account SID is an account id, kept out of logs

    def _request(
        self, method: str, path: str, data: Sequence[tuple[str, str]] | None = None, raw: bool = False
    ) -> Any:
        url = f"{API}/{self.sid}/{path}"
        body = urllib.parse.urlencode(list(data)).encode() if data else None
        request = urllib.request.Request(
            url, data=body, method=method, headers={"Authorization": f"Basic {self._auth}"}
        )
        try:
            payload = self._open(request, self._timeout)
        except urllib.error.HTTPError as error:
            raise _http_error(error) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TwilioError(None, None, f"Twilio could not be reached: {type(error).__name__}") from None
        if raw:
            return payload
        try:
            return json.loads(payload or b"{}")
        except ValueError:
            raise TwilioError(None, None, "Twilio answered with something that is not JSON") from None

    # Calls.

    def place_call(
        self,
        to: str,
        from_: str,
        *,
        url: str | None = None,
        twiml: str | None = None,
        status_callback: str | None = None,
        amd_callback: str | None = None,
        timeout_s: int | None = None,
        time_limit_s: int | None = None,
    ) -> str:
        """Creates one call and returns its CallSid. `url` or `twiml`, never both. `amd_callback` turns on the one
        detection mode the line uses (DetectMessageEnd, asynchronous); `status_callback` hears `answered` and
        `completed`."""
        if (url is None) == (twiml is None):
            raise ValueError("a call takes a Url or Twiml, one of the two")
        data: list[tuple[str, str]] = [("To", to), ("From", from_)]
        data.append(("Url", url) if url is not None else ("Twiml", str(twiml)))
        if status_callback is not None:
            data.append(("StatusCallback", status_callback))
            data.extend(("StatusCallbackEvent", event) for event in STATUS_EVENTS)
        if amd_callback is not None:
            data += [
                ("MachineDetection", "DetectMessageEnd"),
                ("AsyncAmd", "true"),
                ("AsyncAmdStatusCallback", amd_callback),
            ]
        if timeout_s is not None:
            data.append(("Timeout", str(int(timeout_s))))
        if time_limit_s is not None:
            data.append(("TimeLimit", str(int(time_limit_s))))
        call = self._request("POST", "Calls.json", data)
        if not isinstance(call, dict) or "sid" not in call:
            raise TwilioError(None, None, f"Twilio refused the call: {_message(call)}")
        return str(call["sid"])

    def update_call(self, call_sid: str, twiml: str) -> None:
        """Changes a call in progress to this TwiML: how a machine's verdict becomes a voicemail or a hang-up."""
        self._request("POST", f"Calls/{call_sid}.json", [("Twiml", twiml)])

    def hang_up(self, call_sid: str) -> None:
        self._request("POST", f"Calls/{call_sid}.json", [("Status", "completed")])

    def call_status(self, call_sid: str) -> str:
        return str(self._request("GET", f"Calls/{call_sid}.json").get("status"))

    # Recordings, for the probe's dual-channel measurement (DR-001).

    def start_recording(self, call_sid: str) -> str:
        rec = self._request("POST", f"Calls/{call_sid}/Recordings.json", [("RecordingChannels", "dual")])
        if not isinstance(rec, dict) or "sid" not in rec:
            raise TwilioError(None, None, f"Twilio refused the recording: {_message(rec)}")
        return str(rec["sid"])

    def recording_ready(self, recording_sid: str) -> bool:
        return self._request("GET", f"Recordings/{recording_sid}.json").get("status") == "completed"

    def download_recording(self, recording_sid: str, to: Path) -> None:
        to.write_bytes(self._request("GET", f"Recordings/{recording_sid}.wav?RequestedChannels=2", raw=True))

    def delete_recording(self, recording_sid: str) -> None:
        self._request("DELETE", f"Recordings/{recording_sid}.json")

    # A number's voice URL, which the probe's answer mode points at itself for its run and then puts back.

    def incoming_number(self, e164: str) -> dict[str, str]:
        """The account's number resource for this number: its sid, voice URL and voice method."""
        query = urllib.parse.urlencode({"PhoneNumber": e164})
        found = self._request("GET", f"IncomingPhoneNumbers.json?{query}").get("incoming_phone_numbers") or []
        if not found:
            raise TwilioError(None, None, "no number on this account matches")
        row = found[0]
        return {
            "sid": str(row.get("sid")),
            "voice_url": str(row.get("voice_url") or ""),
            "voice_method": str(row.get("voice_method") or "POST"),
        }

    def set_voice_url(self, number_sid: str, url: str, method: str = "POST") -> None:
        self._request(
            "POST", f"IncomingPhoneNumbers/{number_sid}.json", [("VoiceUrl", url), ("VoiceMethod", method)]
        )


def _message(body: Any) -> str:
    return str(body.get("message")) if isinstance(body, dict) else "no message"


def _http_error(error: urllib.error.HTTPError) -> TwilioError:
    try:
        body = json.loads(error.read() or b"{}")
    except (ValueError, OSError):
        body = {}
    code = body.get("code") if isinstance(body, dict) else None
    return TwilioError(
        error.code, code if isinstance(code, int) else None, f"HTTP {error.code}: {_message(body)}"
    )
