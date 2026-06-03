#!/usr/bin/env python3
"""Offline checks for firmware barge-in invariants.

This is intentionally lightweight: it verifies the critical source-level
contracts that make server-side abort/tts-stop tests meaningful on device.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def require(pattern: str, text: str, message: str, flags: int = re.S) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if not match:
        fail(message)
    return match


def main() -> None:
    application = read("main/application.cc")
    audio_service = read("main/audio/audio_service.cc")

    stop_branch = require(
        r'else if \(strcmp\(state->valuestring, "stop"\) == 0\) \{(?P<body>.*?)'
        r'else if \(strcmp\(state->valuestring, "sentence_start"\) == 0\)',
        application,
        "cannot find the tts stop branch in application.cc",
    ).group("body")

    require(
        r"GetDeviceState\(\) == kDeviceStateSpeaking",
        stop_branch,
        "tts stop must only clear active speaking playback",
    )
    require(
        r"!turn_id_str\.empty\(\) && !current_tts_turn_id_\.empty\(\) && "
        r"turn_id_str != current_tts_turn_id_",
        stop_branch,
        "tts stop must ignore stale turn_id when both sides provide one",
    )
    require(
        r"audio_service_\.ResetDecoder\(\)",
        stop_branch,
        "tts stop must reset decoder/playback queues before leaving speaking",
    )
    reset_pos = stop_branch.find("audio_service_.ResetDecoder()")
    state_pos = stop_branch.find("SetDeviceState(")
    if reset_pos == -1 or state_pos == -1 or reset_pos > state_pos:
        fail("tts stop must reset decoder/playback queues before SetDeviceState")
    require(
        r"current_tts_turn_id_\.clear\(\)",
        stop_branch,
        "tts stop must clear current_tts_turn_id_ after accepting stop",
    )

    start_branch = require(
        r'if \(strcmp\(state->valuestring, "start"\) == 0\) \{(?P<body>.*?)'
        r'\} else if \(strcmp\(state->valuestring, "stop"\) == 0\)',
        application,
        "cannot find the tts start branch in application.cc",
    ).group("body")
    require(
        r"current_tts_turn_id_ = turn_id_str",
        start_branch,
        "tts start must remember turn_id when provided",
    )
    require(
        r'auto turn_id = cJSON_GetObjectItem\(root, "turn_id"\)',
        application,
        "tts handler must parse optional turn_id",
    )
    require(
        r"cJSON_IsString\(turn_id\) \? turn_id->valuestring : \"\"",
        application,
        "missing/non-string turn_id must remain backward compatible",
    )

    reset_decoder = require(
        r"void AudioService::ResetDecoder\(\) \{(?P<body>.*?)\n\}",
        audio_service,
        "cannot find AudioService::ResetDecoder",
    ).group("body")
    for queue in (
        "timestamp_queue_",
        "audio_decode_queue_",
        "audio_playback_queue_",
        "audio_testing_queue_",
    ):
        require(
            rf"{queue}\.clear\(\)",
            reset_decoder,
            f"ResetDecoder must clear {queue}",
        )
    require(
        r"audio_queue_cv_\.notify_all\(\)",
        reset_decoder,
        "ResetDecoder must notify queue waiters after clearing playback",
    )

    abort_speaking = require(
        r"void Application::AbortSpeaking\(AbortReason reason\).*?"
        r"\n\}",
        application,
        "cannot find Application::AbortSpeaking",
    ).group(0)
    require(
        r"protocol_->SendAbortSpeaking\(reason\)",
        abort_speaking,
        "AbortSpeaking must send abort to the server",
    )
    require(
        r"state == kDeviceStateSpeaking",
        abort_speaking,
        "AbortSpeaking must only clear local playback while speaking",
    )
    require(
        r"audio_service_\.ResetDecoder\(\)",
        abort_speaking,
        "AbortSpeaking must clear local decoder/playback queues while speaking",
    )
    require(
        r"ListeningMode Application::GetDefaultListeningMode\(\) const \{.*?"
        r"aec_mode_ == kAecOff \? kListeningModeAutoStop : kListeningModeRealtime",
        application,
        "device/server AEC must default to realtime listening mode",
    )

    print("PASS: firmware barge-in source invariants hold")


if __name__ == "__main__":
    main()
