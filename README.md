# cc-archive

Small toolkit for archiving YouTube channel subtitles and turning them into Obsidian-friendly Markdown notes.

## What It Does

- `download.sh` uses `yt-dlp` to download manual and auto-generated subtitles as SRT.
- Videos are never downloaded.
- `srt2md.py` converts downloaded `.srt` files into Markdown with YAML frontmatter and clickable YouTube timestamp links.

## Requirements

- `yt-dlp`
- `python3`

## Usage

Download subtitles from a channel:

```bash
./download.sh https://www.youtube.com/@SomeChannel
```

Download only recent non-Shorts videos:

```bash
./download.sh --no-shorts --since last-month https://www.youtube.com/@SomeChannel
```

Convert downloaded SRT files into Markdown:

```bash
python3 srt2md.py subtitles/ --recursive
```

Write Markdown files somewhere else, such as an Obsidian vault:

```bash
python3 srt2md.py subtitles/ --recursive -o ~/Documents/Obsidian/Vault/Transcripts
```

## Output Layout

Downloaded subtitles are stored like this:

```text
subtitles/Channel Name/20260414 - Video Title [video_id].it.srt
```

Converted notes are stored as Markdown files with the same base name:

```text
subtitles/Channel Name/20260414 - Video Title [video_id].md
```

## Notes

- `--metadata` also saves yt-dlp `.info.json` files if you want extra citation context.