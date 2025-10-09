#!/usr/bin/env python3
"""
Summarize video transcripts using OpenAI API.
Generates concise summaries for each video to provide context for comment analysis.
"""

import os
import csv
import argparse
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd

# Load environment variables
load_dotenv()

def load_prompt(prompt_file):
	"""
	Load prompt text from markdown file.

	Args:
		prompt_file: Path to prompt file

	Returns:
		Prompt text as string
	"""
	with open(prompt_file, "r", encoding="utf-8") as f:
		return f.read()


def load_transcripts(csv_file=None):
	"""
	Load transcripts from CSV file.

	Args:
		csv_file: Path to transcripts CSV (default: latest file in data/)

	Returns:
		pandas DataFrame with transcripts
	"""
	try:
		# If no file specified, find the latest transcripts CSV in data/
		if csv_file is None:
			import glob
			csv_files = glob.glob("data/transcripts_*.csv")
			if not csv_files:
				print("Error: No transcripts CSV files found in data/ directory")
				return None
			csv_file = max(csv_files, key=os.path.getmtime)
			print(f"Loading latest file: {csv_file}")

		df = pd.read_csv(csv_file)
		return df

	except FileNotFoundError:
		print(f"Error: File '{csv_file}' not found")
		return None
	except Exception as e:
		print(f"Error loading CSV: {e}")
		return None


def summarize_video(client, prompt, transcript):
	"""
	Generate summary for a video transcript using OpenAI API.

	Args:
		client: OpenAI client instance
		prompt: System prompt for summarization
		transcript: Video transcript text

	Returns:
		Summary text or None if error
	"""
	try:
		response = client.chat.completions.create(
			model="gpt-4o-mini",
			messages=[
				{"role": "system", "content": prompt},
				{"role": "user", "content": f"Transcript:\n\n{transcript}"}
			],
			temperature=0.3,
			max_tokens=500
		)
		return response.choices[0].message.content.strip()

	except Exception as e:
		print(f"  Error calling OpenAI API: {e}")
		return None


def summarize_videos(transcripts_file=None, output_file=None):
	"""
	Generate summaries for all videos in the transcripts CSV.

	Args:
		transcripts_file: Path to transcripts CSV (default: latest in data/)
		output_file: Output CSV filename (default: data/video_summaries_YYYYMMDD_HHMM.csv)
	"""
	# Check for API key
	api_key = os.getenv("OPENAI_API_KEY")
	if not api_key:
		print("Error: OPENAI_API_KEY not found in environment variables")
		print("Please add it to your .env file")
		return

	# Initialize OpenAI client
	client = OpenAI(api_key=api_key)

	# Load prompt
	prompt_file = "prompts/summarize_video.md"
	if not os.path.exists(prompt_file):
		print(f"Error: Prompt file '{prompt_file}' not found")
		return

	print("Loading prompt...")
	prompt = load_prompt(prompt_file)

	# Load transcripts
	print("Loading transcripts...")
	df = load_transcripts(transcripts_file)
	if df is None:
		return

	# Create data directory if it doesn't exist
	os.makedirs("data", exist_ok=True)

	# Generate default filename with timestamp if not provided
	if output_file is None:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M")
		output_file = f"data/video_summaries_{timestamp}.csv"

	print(f"Processing {len(df)} videos...")

	# Generate summaries
	summaries = []
	for i, row in df.iterrows():
		video_id = row["video_id"]
		transcript = row["transcript"]

		print(f"[{i+1}/{len(df)}] Summarizing video: {video_id}")

		summary = summarize_video(client, prompt, transcript)

		if summary:
			summaries.append({
				"video_id": video_id,
				"summary": summary,
				"is_generated": row.get("is_generated", ""),
				"language": row.get("language", ""),
				"language_code": row.get("language_code", "")
			})
			print(f"  → Summary generated ({len(summary)} chars)")
		else:
			print(f"  → Failed to generate summary")

	# Save to CSV
	if summaries:
		with open(output_file, "w", newline="", encoding="utf-8") as f:
			fieldnames = ["video_id", "summary", "is_generated", "language", "language_code"]
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(summaries)

		print(f"\n Successfully generated {len(summaries)} summaries")
		print(f" Saved to: {output_file}")
	else:
		print("No summaries generated.")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(
		description="Generate video summaries from transcripts using OpenAI API"
	)
	parser.add_argument(
		"-i",
		"--input",
		type=str,
		default=None,
		help="Input transcripts CSV file (default: latest file in data/)",
	)
	parser.add_argument(
		"-o",
		"--output",
		type=str,
		default=None,
		help="Output CSV filename (default: data/video_summaries_YYYYMMDD_HHMM.csv)",
	)

	args = parser.parse_args()
	summarize_videos(args.input, args.output)
