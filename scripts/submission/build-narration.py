from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = ROOT / "artifacts" / "submission"
SEGMENTS = SUBMISSION / "narration-segments"
SCRIPT = ROOT / "docs" / "demo-script.md"
OUTPUT = SUBMISSION / "GhostChip_Demo_Narration.wav"
SUBTITLES = SUBMISSION / "GhostChip_Demo_Subtitles.srt"
SCRIPT_COPY = SUBMISSION / "GhostChip_Demo_Script.md"
PAUSE_SECONDS = 0.35
INTRO_SECONDS = 0.8
OUTRO_SECONDS = 0.8
# Keep the Runline Aura-2 Orion voice while tightening its delivery enough to
# leave safe headroom below the three-minute submission limit. FFmpeg's atempo
# filter changes timing without shifting pitch.
EDITORIAL_TEMPO = 1.05


def executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    fallback = (
        Path.home()
        / "AppData/Local/Microsoft/WinGet/Packages/"
        "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/"
        "ffmpeg-8.1-full_build/bin"
        / f"{name}.exe"
    )
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError(f"{name} was not found")


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            executable("ffprobe"),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def main() -> None:
    SUBMISSION.mkdir(parents=True, exist_ok=True)
    source = SCRIPT.read_text(encoding="utf-8")
    matches = re.findall(
        r"(?ms)^### (\d+) .*?\n\n(.*?)(?=\n\n###|\n\n## On-screen)", source
    )
    if len(matches) != 11:
        raise RuntimeError(f"Expected 11 narration segments, found {len(matches)}")

    paths = [SEGMENTS / f"segment-{int(number):02}.mp3" for number, _ in matches]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing narration segments: " + ", ".join(missing))

    inputs: list[str] = []
    filter_parts: list[str] = []
    labels: list[str] = []
    for index, path in enumerate(paths):
        inputs.extend(["-i", str(path)])
        filter_parts.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:"
            f"channel_layouts=stereo,atempo={EDITORIAL_TEMPO}[a{index}]"
        )
        labels.append(f"[a{index}]")
        if index < len(paths) - 1:
            filter_parts.append(
                f"anullsrc=r=48000:cl=stereo:d={PAUSE_SECONDS}[s{index}]"
            )
            labels.append(f"[s{index}]")
    filter_parts.append(f"anullsrc=r=48000:cl=stereo:d={INTRO_SECONDS}[intro]")
    filter_parts.append(f"anullsrc=r=48000:cl=stereo:d={OUTRO_SECONDS}[outro]")
    chain = "[intro]" + "".join(labels) + "[outro]"
    filter_parts.append(
        f"{chain}concat=n={len(labels) + 2}:v=0:a=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=7[aout]"
    )
    subprocess.run(
        [
            executable("ffmpeg"), "-y", *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[aout]", "-ar", "48000", "-ac", "2",
            "-c:a", "pcm_s16le", str(OUTPUT),
        ],
        check=True,
    )

    cues: list[str] = []
    cursor = INTRO_SECONDS
    cue_number = 1
    for (number, text), path in zip(matches, paths, strict=True):
        segment_duration = duration(path) / EDITORIAL_TEMPO
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if item.strip()]
        weights = [max(1, len(item)) for item in sentences]
        weight_total = sum(weights)
        local = cursor
        for sentence, weight in zip(sentences, weights, strict=True):
            span = segment_duration * weight / weight_total
            end = local + span
            cues.extend([
                str(cue_number),
                f"{srt_time(local)} --> {srt_time(end)}",
                sentence,
                "",
            ])
            cue_number += 1
            local = end
        cursor += segment_duration + PAUSE_SECONDS

    SUBTITLES.write_text("\n".join(cues), encoding="utf-8")
    SCRIPT_COPY.write_text(source, encoding="utf-8")
    print(f"Narration: {OUTPUT}")
    print(f"Duration: {duration(OUTPUT):.3f} seconds")
    print(f"Subtitles: {SUBTITLES}")


if __name__ == "__main__":
    main()
