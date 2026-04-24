#!/usr/bin/env python3
"""
srt2md.py — Convert SRT subtitle files into Obsidian-friendly Markdown.

Each output file has YAML frontmatter (title, channel, date, URL) and a
transcript where every paragraph begins with a clickable timestamp link
that opens the YouTube video at that exact moment.

Usage:
    python3 srt2md.py subtitles/ChannelName/          # whole channel dir
    python3 srt2md.py subtitles/                      # all channels (--recursive)
    python3 srt2md.py some_video.it.srt               # single file
    python3 srt2md.py subtitles/ -o notes/transcripts # write to a different dir
    python3 srt2md.py subtitles/ --chunk 60           # 60-second paragraphs
"""

import argparse
import html
import re
import sys
from datetime import datetime
from pathlib import Path


_TIMECODE_PATTERN = re.compile(
    r'(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})'
    r'\s*-->\s*'
    r'(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})'
)
_SUBTITLE_SUFFIX_PATTERN = re.compile(
    r'(\.[A-Za-z]{2}(?:-[A-Za-z]{2,4})?)?\.srt$',
    flags=re.I,
)


def _ts_to_seconds(ts: str) -> float:
    ts = ts.replace(',', '.')
    parts = ts.split(':')
    if len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours, minutes, seconds = 0, *parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _clean(text: str) -> str:
    """Strip markup and normalize whitespace while preserving subtitle text."""
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    return ' '.join(text.split())


def _normalize_token(token: str) -> str:
    if token == '>>':
        return token
    token = token.casefold()
    return re.sub(r'^[^\w>]+|[^\w>]+$', '', token)


def _find_overlap(previous_tokens: list[str], current_tokens: list[str]) -> int:
    """Return the longest token overlap between transcript tail and cue head."""
    max_overlap = min(len(previous_tokens), len(current_tokens), 40)
    if max_overlap == 0:
        return 0

    previous_norm = [_normalize_token(token) for token in previous_tokens]
    current_norm = [_normalize_token(token) for token in current_tokens]

    for size in range(max_overlap, 0, -1):
        if previous_norm[-size:] == current_norm[:size]:
            return size
    return 0


def _dedupe_repeated_cues(cues: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Remove repeated SRT text caused by scrolling two-line captions."""
    filtered: list[tuple[float, str]] = []
    history_tokens: list[str] = []

    for start, text in cues:
        tokens = text.split()
        if not tokens:
            continue

        overlap = _find_overlap(history_tokens, tokens)
        novel_tokens = tokens[overlap:]
        if not novel_tokens:
            continue

        novel_text = ' '.join(novel_tokens)
        if filtered and filtered[-1][1] == novel_text:
            continue

        filtered.append((start, novel_text))
        history_tokens.extend(novel_tokens)
        history_tokens = history_tokens[-120:]

    return filtered


def parse_srt(content: str) -> list[tuple[float, str]]:
    """Return list of (start_seconds, cleaned_text) for each SRT cue."""
    cues: list[tuple[float, str]] = []
    blocks = re.split(r'\n\s*\n', content.replace('\r\n', '\n').strip())

    for block in blocks:
        lines = [line.strip() for line in block.splitlines()]
        timestamp_index = None
        timestamp_match = None

        for index, line in enumerate(lines):
            match = _TIMECODE_PATTERN.search(line)
            if match:
                timestamp_index = index
                timestamp_match = match
                break

        if timestamp_index is None or timestamp_match is None:
            continue

        text_lines = [line for line in lines[timestamp_index + 1 :] if line]
        if not text_lines:
            continue

        start = _ts_to_seconds(timestamp_match.group(1))
        text = _clean(' '.join(text_lines))
        if text:
            cues.append((start, text))

    return _dedupe_repeated_cues(cues)


def group_cues(
    cues: list[tuple[float, str]], chunk_seconds: int = 30
) -> list[tuple[float, str]]:
    """Merge cues into approximately chunk_seconds-long paragraphs."""
    if not cues:
        return []

    groups: list[tuple[float, str]] = []
    group_start = cues[0][0]
    bucket: list[str] = []

    for start, text in cues:
        if start - group_start >= chunk_seconds and bucket:
            groups.append((group_start, ' '.join(bucket)))
            group_start = start
            bucket = [text]
        else:
            bucket.append(text)

    if bucket:
        groups.append((group_start, ' '.join(bucket)))

    return groups


def _subtitle_stem(path: Path) -> str:
    return _SUBTITLE_SUFFIX_PATTERN.sub('', path.name)


def _parse_filename(path: Path) -> tuple[str, str | None, str | None]:
    """
    Extract (title, iso_date, video_id) from filenames like:
      20240315 - Some Title [abc123XYZ_AB].it.srt
    Falls back gracefully when parts are missing.
    """
    name = _subtitle_stem(path)

    video_id: str | None = None
    match = re.search(r'\[([A-Za-z0-9_-]{11})\]\s*$', name)
    if match:
        video_id = match.group(1)
        name = name[: match.start()].strip(' -').strip()

    iso_date: str | None = None
    match = re.match(r'^(\d{8})\s*[-–]\s*(.*)', name)
    if match:
        raw_date, name = match.group(1), match.group(2).strip()
        try:
            iso_date = datetime.strptime(raw_date, '%Y%m%d').strftime('%Y-%m-%d')
        except ValueError:
            pass

    return name or path.stem, iso_date, video_id


def _fmt_ts(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


def srt_to_md(
    subtitle_path: Path,
    output_path: Path | None = None,
    chunk_seconds: int = 30,
    channel: str | None = None,
) -> Path:
    title, iso_date, video_id = _parse_filename(subtitle_path)

    if channel is None:
        channel = subtitle_path.parent.name

    yt_url = f'https://youtu.be/{video_id}' if video_id else None

    content = subtitle_path.read_text(encoding='utf-8', errors='replace')
    cues = parse_srt(content)
    groups = group_cues(cues, chunk_seconds)

    lines: list[str] = []
    lines += ['---']
    lines += [f'title: "{title}"']
    if channel:
        lines += [f'channel: "{channel}"']
    if iso_date:
        lines += [f'date: {iso_date}']
    if yt_url:
        lines += [f'url: {yt_url}']
    lines += ['tags:\n  - youtube\n  - transcript']
    lines += ['---', '']

    lines += [f'# {title}', '']
    if channel:
        lines += [f'**Channel:** {channel}  ']
    if iso_date:
        lines += [f'**Date:** {iso_date}  ']
    if yt_url:
        lines += [f'**Video:** [{yt_url}]({yt_url})  ']
    lines += ['', '---', '']

    if not groups:
        lines += ['*(No subtitles found in this file.)*', '']
    else:
        for start_sec, text in groups:
            ts_str = _fmt_ts(start_sec)
            t_int = int(start_sec)
            if yt_url:
                anchor = f'[{ts_str}]({yt_url}?t={t_int})'
            else:
                anchor = f'**[{ts_str}]**'
            lines += [f'{anchor} {text}', '']

    md = '\n'.join(lines)

    if output_path is None:
        output_path = subtitle_path.parent / (_subtitle_stem(subtitle_path) + '.md')

    output_path.write_text(md, encoding='utf-8')
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Convert SRT subtitle files to Obsidian Markdown with clickable timestamps.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'input', nargs='+',
        help='SRT file(s) or directory/directories containing SRT files',
    )
    parser.add_argument(
        '-o', '--output-dir', metavar='DIR',
        help='Write all output files to this directory (default: same as each input file)',
    )
    parser.add_argument(
        '-r', '--recursive', action='store_true',
        help='Recurse into subdirectories when given a directory',
    )
    parser.add_argument(
        '-c', '--channel', metavar='NAME',
        help='Override the channel name (default: inferred from parent directory)',
    )
    parser.add_argument(
        '--chunk', type=int, default=30, metavar='SECONDS',
        help='Group subtitle cues into paragraphs of approximately N seconds (default: 30)',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Print what would be converted without writing any files',
    )
    args = parser.parse_args()

    subtitle_files: list[Path] = []
    for raw in args.input:
        path = Path(raw)
        if path.is_dir():
            pattern = '**/*.srt' if args.recursive else '*.srt'
            subtitle_files.extend(sorted(path.glob(pattern)))
        elif path.suffix.lower() == '.srt':
            subtitle_files.append(path)
        else:
            print(f'Warning: skipping {raw} (not a .srt file or directory)', file=sys.stderr)

    if not subtitle_files:
        print('No SRT files found.', file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    converted = 0
    for subtitle_path in subtitle_files:
        if output_dir:
            output_path = output_dir / (_subtitle_stem(subtitle_path) + '.md')
        else:
            output_path = None

        if args.dry_run:
            destination = output_path or (subtitle_path.parent / (_subtitle_stem(subtitle_path) + '.md'))
            print(f'  {subtitle_path}  ->  {destination}')
        else:
            result = srt_to_md(
                subtitle_path,
                output_path=output_path,
                chunk_seconds=args.chunk,
                channel=args.channel,
            )
            print(f'  {subtitle_path.name}  ->  {result.name}')

        converted += 1

    if not args.dry_run:
        print(f'\nConverted {converted} file(s).')


if __name__ == '__main__':
    main()
