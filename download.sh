#!/usr/bin/env bash
# download.sh — Archive YouTube channel subtitles for later citation

set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
Usage: ./download.sh [OPTIONS] <channel_url>

Download CC subtitles (manual + auto-generated) from a YouTube channel.
Videos are never downloaded. An archive file tracks which video IDs have
already been processed so subsequent runs only fetch new content.

OPTIONS
  -l, --lang LANG       Subtitle language(s), comma-separated (default: en)
                        Examples: en  |  en,it  |  en.*  (all English variants)
  -o, --output DIR      Output directory (default: ./subtitles)
  -a, --archive FILE    Archive file to track downloaded IDs (default: ./archive.txt)
      --since DATE      Only fetch videos on/after DATE. Accepts YYYYMMDD or
                        shorthand: last-month, last-week, last-year.
                        NOTE: videos already in the archive are always skipped.
                        Use --force --since DATE to re-check archived videos.
      --no-shorts       Exclude Shorts and Live streams (uses /videos tab + duration filter)
      --force           Ignore archive and re-check every video on the channel
      --metadata        Also save a JSON metadata file per video (useful for citations)
  -h, --help            Show this help

Environment variable overrides (lower priority than flags):
  SUBTITLE_LANG, SUBTITLE_FORMAT, OUTPUT_DIR, ARCHIVE_FILE

EXAMPLES
  ./download.sh https://www.youtube.com/@SomeChannel
  ./download.sh --no-shorts --since last-month https://www.youtube.com/@SomeChannel
  ./download.sh --lang en,es https://www.youtube.com/@SomeChannel
  ./download.sh --since 20240101 https://www.youtube.com/@SomeChannel
  ./download.sh --force --since last-month https://www.youtube.com/@SomeChannel
EOF
  exit "${1:-0}"
}

# ── Defaults ──────────────────────────────────────────────────────────────────
LANG="${SUBTITLE_LANG:-en}"
OUTPUT_DIR="${OUTPUT_DIR:-./subtitles}"
ARCHIVE_FILE="${ARCHIVE_FILE:-./archive.txt}"
DATE_AFTER=""
FORCE=false
NO_SHORTS=false
WRITE_METADATA=false
CHANNEL_URL=""

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -l|--lang)     LANG="$2";            shift 2 ;;
    -o|--output)   OUTPUT_DIR="$2";      shift 2 ;;
    -a|--archive)  ARCHIVE_FILE="$2";    shift 2 ;;
    --since)       DATE_AFTER="$2";      shift 2 ;;
    --no-shorts)   NO_SHORTS=true;        shift   ;;
    --force)       FORCE=true;            shift   ;;
    --metadata)    WRITE_METADATA=true;   shift   ;;
    -h|--help)     usage 0 ;;
    -*)            echo "Error: unknown option '$1'" >&2; usage 1 ;;
    *)             CHANNEL_URL="$1";     shift   ;;
  esac
done

[[ -z "$CHANNEL_URL" ]] && { echo "Error: channel URL is required." >&2; usage 1; }

# ── Resolve friendly --since shorthands ───────────────────────────────────────
if [[ -n "$DATE_AFTER" ]]; then
  case "$DATE_AFTER" in
    last-week)  DATE_AFTER=$(date -v-7d  +%Y%m%d 2>/dev/null || date -d '7 days ago'   +%Y%m%d) ;;
    last-month) DATE_AFTER=$(date -v-1m  +%Y%m%d 2>/dev/null || date -d '1 month ago'  +%Y%m%d) ;;
    last-year)  DATE_AFTER=$(date -v-1y  +%Y%m%d 2>/dev/null || date -d '1 year ago'   +%Y%m%d) ;;
  esac
fi

# ── Apply --no-shorts: point at the /videos tab (excludes Shorts and Lives) ───
if [[ "$NO_SHORTS" == true ]]; then
  CHANNEL_URL="${CHANNEL_URL%/}"          # strip trailing slash
  # Strip any existing tab suffix (/shorts, /streams, /videos, etc.) then add /videos
  CHANNEL_URL="${CHANNEL_URL%/shorts}"
  CHANNEL_URL="${CHANNEL_URL%/streams}"
  CHANNEL_URL="${CHANNEL_URL%/videos}"
  CHANNEL_URL="${CHANNEL_URL%/live}"
  CHANNEL_URL="$CHANNEL_URL/videos"
fi

# ── Dependency check ──────────────────────────────────────────────────────────
if ! command -v yt-dlp &>/dev/null; then
  echo "Error: yt-dlp is not installed." >&2
  echo "  pip install yt-dlp   or   brew install yt-dlp" >&2
  exit 1
fi

# ── Setup ─────────────────────────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"

# Subtitle files are saved as:
#   <OUTPUT_DIR>/<channel>/<YYYYMMDD> - <title> [<video_id>].<lang>.<format>
OUTPUT_TEMPLATE="$OUTPUT_DIR/%(channel)s/%(upload_date)s - %(title)s [%(id)s]"

# ── Build yt-dlp argument list ────────────────────────────────────────────────
YTDLP_ARGS=(
  --skip-download                # never download video streams

  # Subtitles — fetch both manual and auto-generated.
  # When manual subs exist for a language, yt-dlp prefers them over auto-gen;
  # auto-gen is used for videos that have no manual track.
  --write-subs
  --write-auto-subs
  --sub-langs "$LANG"
  --convert-subs srt             # convert everything to SRT

  --output "$OUTPUT_TEMPLATE"
  --ignore-errors                # skip private/deleted/geo-blocked videos
  --retries 5
)

# Shorts guard: the /videos tab is the primary filter; duration>60s catches
# any that slip through (YouTube Shorts are capped at 60s as of 2024).
[[ "$NO_SHORTS" == true ]] && YTDLP_ARGS+=(--match-filter "duration>60")

if [[ "$FORCE" == false ]]; then
  # Record processed video IDs so re-runs skip already-fetched content.
  # Delete or edit archive.txt to force a re-check of specific videos,
  # or use --force to bypass the archive entirely.
  YTDLP_ARGS+=(--download-archive "$ARCHIVE_FILE")
fi

if [[ -n "$DATE_AFTER" ]]; then
  YTDLP_ARGS+=(--dateafter "$DATE_AFTER")
  # YouTube channel playlists are ordered newest-first, so stop as soon as a
  # video is too old rather than crawling the entire channel history.
  YTDLP_ARGS+=(--break-on-reject)
fi
[[ "$WRITE_METADATA" == true ]] && YTDLP_ARGS+=(--write-info-json)

# ── Summary ───────────────────────────────────────────────────────────────────
divider="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$divider"
printf "  Channel:  %s\n" "$CHANNEL_URL"
printf "  Language: %s\n" "$LANG"

printf "  Output:   %s\n" "$OUTPUT_DIR"
if [[ "$FORCE" == true ]]; then
  printf "  Archive:  (disabled — re-checking all videos)\n"
else
  printf "  Archive:  %s\n" "$ARCHIVE_FILE"
fi
[[ -n "$DATE_AFTER"          ]] && printf "  Since:    %s\n" "$DATE_AFTER"
[[ "$NO_SHORTS" == true      ]] && printf "  Shorts:   excluded\n"
[[ "$WRITE_METADATA" == true ]] && printf "  Metadata: yes\n"
echo "$divider"
echo

# ── Execute ───────────────────────────────────────────────────────────────────
yt-dlp "${YTDLP_ARGS[@]}" "$CHANNEL_URL"

echo
echo "Done."
printf "  Subtitles saved to: %s\n" "$OUTPUT_DIR"
[[ "$FORCE" == false ]] && printf "  Archive updated:    %s\n" "$ARCHIVE_FILE"
