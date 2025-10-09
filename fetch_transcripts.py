#!/usr/bin/env python3
"""
Fetch transcripts for all videos from the YouTube comments CSV.
Uses youtube-transcript-api to retrieve transcripts without OAuth.
"""

import os
import csv
import re
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi
from youtube import load_comments


def clean_text(text):
	"""
	Clean transcript text by removing escaped characters and normalizing whitespace.

	Args:
		text: Raw transcript text

	Returns:
		Cleaned text string
	"""
	# Replace non-breaking spaces with regular spaces
	text = text.replace("\xa0", " ")

	# Replace newlines with spaces
	text = text.replace("\n", " ")

	# Collapse multiple spaces into single space
	text = re.sub(r"\s+", " ", text)

	# Strip leading/trailing whitespace
	text = text.strip()

	return text


def fetch_transcripts(csv_file=None, output_file=None, max_videos=None):
	"""
	Load comments CSV and fetch transcripts for all unique videos.

	Args:
		csv_file: Path to comments CSV (default: latest file in data/)
		output_file: Output CSV filename (default: data/transcripts_YYYYMMDD_HHMM.csv)
		max_videos: Maximum number of videos to process (default: all)
	"""
	# Load comments to get video IDs
	print("Loading comments CSV...")
	df = load_comments(csv_file)

	if df is None:
		print("Error: Could not load comments CSV")
		return

	# Get unique video IDs
	video_ids = df["video_id"].unique()

	# Limit number of videos if specified
	if max_videos is not None and max_videos > 0:
		video_ids = video_ids[:max_videos]
		print(f"Processing {len(video_ids)} of {len(df['video_id'].unique())} unique videos")
	else:
		print(f"Found {len(video_ids)} unique videos")

	# Create data directory if it doesn't exist
	os.makedirs("data", exist_ok=True)

	# Generate default filename with timestamp if not provided
	if output_file is None:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M")
		output_file = f"data/transcripts_{timestamp}.csv"

	# Fetch transcripts for each video
	all_transcript_entries = []
	ytt_api = YouTubeTranscriptApi()

	for i, video_id in enumerate(video_ids, 1):
		print(f"[{i}/{len(video_ids)}] Fetching transcript for video: {video_id}")

		try:
			transcript = ytt_api.fetch(video_id)

			# Get transcript metadata (is_generated, language, etc.)
			is_generated = transcript.is_generated
			language = transcript.language
			language_code = transcript.language_code

			# Combine all segments into one full transcript with cleaning
			full_text = " ".join(clean_text(segment.text) for segment in transcript)

			all_transcript_entries.append({
				"video_id": video_id,
				"is_generated": is_generated,
				"language": language,
				"language_code": language_code,
				"transcript": full_text,
			})

			print(f"  → Collected transcript with {len(transcript)} segments")

		except Exception as e:
			print(f"  → Error fetching transcript: {e}")
			continue

	# Save to CSV
	if all_transcript_entries:
		with open(output_file, "w", newline="", encoding="utf-8") as f:
			fieldnames = [
				"video_id",
				"is_generated",
				"language",
				"language_code",
				"transcript",
			]
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(all_transcript_entries)

		print(f"\n Successfully fetched transcripts from {len(all_transcript_entries)} videos")
		print(f" Saved to: {output_file}")
	else:
		print("No transcripts collected.")


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(
		description="Fetch transcripts for videos from YouTube comments CSV"
	)
	parser.add_argument(
		"-i",
		"--input",
		type=str,
		default=None,
		help="Input comments CSV file (default: latest file in data/)",
	)
	parser.add_argument(
		"-o",
		"--output",
		type=str,
		default=None,
		help="Output CSV filename (default: data/transcripts_YYYYMMDD_HHMM.csv)",
	)
	parser.add_argument(
		"-n",
		"--max-videos",
		type=int,
		default=None,
		help="Maximum number of videos to process (default: all)",
	)

	args = parser.parse_args()
	fetch_transcripts(args.input, args.output, args.max_videos)
