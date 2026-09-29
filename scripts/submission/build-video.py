from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUBMISSION = ROOT / "artifacts" / "submission"
CLIPS = SUBMISSION / "raw-clips"
SEGMENTS = SUBMISSION / "narration-segments"
AUDIO = SUBMISSION / "GhostChip_Demo_Narration.wav"
OUTPUT = SUBMISSION / "GhostChip_Demo_Final.mp4"
PAUSE = 0.35
INTRO = 0.8
OUTRO = 0.8
EDITORIAL_TEMPO = 1.05

# Offsets remove recorder setup/teardown while retaining every real interaction.
START_OFFSETS = [2.8, 2.5, 0.0, 0.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]


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
            executable("ffprobe"), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    clips = [CLIPS / f"clip-{index:02}.webm" for index in range(1, 12)]
    speech = [SEGMENTS / f"segment-{index:02}.mp3" for index in range(1, 12)]
    required = [*clips, *speech, AUDIO]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing media: " + ", ".join(missing))

    segment_durations = [duration(path) / EDITORIAL_TEMPO + PAUSE for path in speech]
    segment_durations[0] += INTRO
    segment_durations[-1] += OUTRO - PAUSE

    args = [executable("ffmpeg"), "-y"]
    for clip in clips:
        args.extend(["-i", str(clip)])
    args.extend(["-i", str(AUDIO)])

    filters: list[str] = []
    labels: list[str] = []
    for index, (offset, span) in enumerate(zip(START_OFFSETS, segment_durations, strict=True)):
        filters.append(
            f"[{index}:v]trim=start={offset:.3f}:duration={span:.3f},"
            "setpts=PTS-STARTPTS,scale=1920:1080:flags=lanczos,"
            f"fps=30,format=yuv420p[v{index}]"
        )
        labels.append(f"[v{index}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[vout]")

    args.extend(
        [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", f"{len(clips)}:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-shortest", str(OUTPUT),
        ]
    )
    subprocess.run(args, check=True)
    print(f"Final video: {OUTPUT}")
    print(f"Duration: {duration(OUTPUT):.3f} seconds")


if __name__ == "__main__":
    main()
