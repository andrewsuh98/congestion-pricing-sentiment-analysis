#!/usr/bin/env python3
"""
Fetch YouTube user profile data and infer demographics using OpenAI Vision API.
Two-phase process:
1. Collect user channel data from YouTube API (profile images, descriptions, metadata)
2. Analyze demographics using OpenAI with profile images and contextual data
Includes checkpointing, rate limiting, and resume capability.
"""

import os
import csv
import argparse
import time
from datetime import datetime
from typing import Literal
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from openai import OpenAI
from pydantic import BaseModel
import pandas as pd

# Load environment variables
load_dotenv()

# API Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Rate limiting configuration
REQUESTS_PER_MINUTE = 50
DELAY_BETWEEN_REQUESTS = 60.0 / REQUESTS_PER_MINUTE  # ~1.2 seconds

# Checkpoint configuration
CHECKPOINT_INTERVAL = 50  # Save progress every N users


class UserDemographics(BaseModel):
	"""Pydantic model for structured demographic inference output"""
	model_config = {"extra": "forbid"}

	inferred_age_range: Literal["under_18", "18-24", "25-34", "35-44", "45-54", "55-64", "65_plus", "unclear"]
	inferred_gender: Literal["male", "female", "non_binary", "unclear"]
	inferred_race_ethnicity: Literal[
		"white",
		"black_african_american",
		"hispanic_latino",
		"asian",
		"middle_eastern_north_african",
		"native_american_indigenous",
		"pacific_islander",
		"multiracial",
		"unclear"
	]
	confidence_level: float
	reasoning: str


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


def load_comments(csv_file=None):
	"""
	Load comments CSV to extract unique users.

	Args:
		csv_file: Path to comments CSV (default: latest in data/)

	Returns:
		DataFrame with comment data
	"""
	try:
		if csv_file is None:
			import glob
			csv_files = glob.glob("data/youtube_comments_*.csv")
			if not csv_files:
				print("Error: No comments CSV files found in data/ directory")
				return None
			csv_file = max(csv_files, key=os.path.getmtime)
			print(f"Loading comments from: {csv_file}")

		df = pd.read_csv(csv_file)
		return df

	except Exception as e:
		print(f"Error loading comments: {e}")
		return None


def get_unique_users(df):
	"""
	Extract unique users from comments DataFrame.

	Args:
		df: Comments DataFrame

	Returns:
		DataFrame with unique users (author, author_channel_id)
	"""
	# Check if author_channel_id column exists
	if "author_channel_id" not in df.columns:
		print("\nError: The comments CSV does not contain 'author_channel_id' column.")
		print("This column is required to fetch user profile data from YouTube API.")
		print("\nTo fix this:")
		print("1. The youtube.py script has been updated to capture author_channel_id")
		print("2. Please re-run youtube.py to scrape fresh comments with this field:")
		print("   python youtube.py -n 50  # or your desired number of videos")
		print("3. Then run this script again on the new CSV file")
		return None

	# Get unique author + channel_id combinations
	unique_users = df[["author", "author_channel_id"]].drop_duplicates()

	# Filter out users without channel IDs
	unique_users = unique_users[unique_users["author_channel_id"].notna()]
	unique_users = unique_users[unique_users["author_channel_id"] != ""]

	print(f"Found {len(unique_users)} unique users with channel IDs")

	return unique_users


def fetch_channel_details(youtube, channel_ids):
	"""
	Fetch channel details from YouTube API for a batch of channel IDs.

	Args:
		youtube: YouTube API service object
		channel_ids: List of channel IDs (max 50)

	Returns:
		List of channel detail dictionaries
	"""
	try:
		request = youtube.channels().list(
			part="snippet,statistics",
			id=",".join(channel_ids),
			maxResults=50
		)
		response = request.execute()

		channels = []
		for item in response.get("items", []):
			snippet = item["snippet"]
			statistics = item.get("statistics", {})
			thumbnails = snippet.get("thumbnails", {})

			# Get highest quality thumbnail available
			thumbnail_url = ""
			if "high" in thumbnails:
				thumbnail_url = thumbnails["high"]["url"]
			elif "medium" in thumbnails:
				thumbnail_url = thumbnails["medium"]["url"]
			elif "default" in thumbnails:
				thumbnail_url = thumbnails["default"]["url"]

			channels.append({
				"channel_id": item["id"],
				"channel_title": snippet.get("title", ""),
				"channel_description": snippet.get("description", ""),
				"channel_country": snippet.get("country", ""),
				"channel_custom_url": snippet.get("customUrl", ""),
				"thumbnail_url": thumbnail_url,
				"subscriber_count": statistics.get("subscriberCount", ""),
				"view_count": statistics.get("viewCount", ""),
				"video_count": statistics.get("videoCount", ""),
			})

		return channels

	except HttpError as e:
		print(f"An HTTP error occurred: {e}")
		return []


def load_checkpoint(output_file):
	"""
	Load existing results to determine which users have been processed.

	Args:
		output_file: Path to output CSV

	Returns:
		Set of processed channel IDs
	"""
	if not os.path.exists(output_file):
		return set()

	try:
		df = pd.read_csv(output_file)
		processed_ids = set(df["channel_id"].unique())
		print(f"Resuming: {len(processed_ids)} users already processed")
		return processed_ids
	except Exception as e:
		print(f"Error loading checkpoint: {e}")
		return set()


def save_checkpoint(output_file, results, fieldnames):
	"""
	Save current results to CSV.

	Args:
		output_file: Path to output CSV
		results: List of result dictionaries
		fieldnames: List of CSV column names
	"""
	with open(output_file, "w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(results)


def fetch_user_profiles(input_file=None, output_file=None, max_users=None):
	"""
	Phase 1: Fetch user profile data from YouTube API.

	Args:
		input_file: Path to comments CSV (default: latest)
		output_file: Path to save user profiles (default: timestamped)
		max_users: Maximum number of users to process (default: all)

	Returns:
		Path to output file
	"""
	# Load comments and extract unique users
	df = load_comments(input_file)
	if df is None:
		return None

	unique_users = get_unique_users(df)
	if unique_users is None or len(unique_users) == 0:
		if unique_users is not None:
			print("Error: No users with channel IDs found")
		return None

	# Limit number of users if specified
	if max_users:
		unique_users = unique_users.head(max_users)
		print(f"Processing first {len(unique_users)} users")

	# Create output file if not specified
	if output_file is None:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M")
		output_file = f"data/user_profiles_{timestamp}.csv"
		os.makedirs("data", exist_ok=True)

	# Load checkpoint (users already processed)
	processed_ids = load_checkpoint(output_file)

	# Filter out already-processed users
	users_to_process = unique_users[~unique_users["author_channel_id"].isin(processed_ids)]
	print(f"Processing {len(users_to_process)} users (out of {len(unique_users)} total)")

	if len(users_to_process) == 0:
		print("All users already processed!")
		return output_file

	# Initialize YouTube API
	youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

	# Collect channel IDs to batch
	channel_ids = users_to_process["author_channel_id"].tolist()

	# Process in batches of 50 (YouTube API limit)
	all_results = []
	if processed_ids:
		# Load existing results
		existing_df = pd.read_csv(output_file)
		all_results = existing_df.to_dict("records")

	batch_size = 50
	total_batches = (len(channel_ids) + batch_size - 1) // batch_size

	for i in range(0, len(channel_ids), batch_size):
		batch_ids = channel_ids[i:i + batch_size]
		batch_num = (i // batch_size) + 1

		print(f"\n[Batch {batch_num}/{total_batches}] Fetching {len(batch_ids)} channels...")

		# Fetch channel details
		channels = fetch_channel_details(youtube, batch_ids)

		if channels:
			all_results.extend(channels)
			print(f"  → Fetched {len(channels)} channel details")

			# Save checkpoint after each batch
			fieldnames = [
				"channel_id", "channel_title", "channel_description",
				"channel_country", "channel_custom_url", "thumbnail_url",
				"subscriber_count", "view_count", "video_count"
			]
			save_checkpoint(output_file, all_results, fieldnames)
			print(f"  → Checkpoint saved ({len(all_results)} total users)")

		# Rate limiting
		if i + batch_size < len(channel_ids):
			time.sleep(DELAY_BETWEEN_REQUESTS)

	print(f"\nProfile collection complete! Saved to: {output_file}")
	return output_file


def infer_demographics(client, prompt, channel_data):
	"""
	Infer demographics for a single user using OpenAI Vision API.

	Args:
		client: OpenAI client
		prompt: System prompt
		channel_data: Dictionary with channel information

	Returns:
		UserDemographics object or None on error
	"""
	try:
		# Prepare user message with channel context
		user_message = f"""Username: {channel_data['channel_title']}
Channel Description: {channel_data['channel_description'] or 'Not available'}
Country: {channel_data['channel_country'] or 'Not available'}
Profile Image URL: {channel_data['thumbnail_url']}

Please analyze the profile image and available information to infer demographic characteristics."""

		# Build messages - check if we have an image
		if channel_data['thumbnail_url']:
			# Multimodal message with image
			messages = [
				{"role": "system", "content": prompt},
				{
					"role": "user",
					"content": [
						{"type": "text", "text": user_message},
						{
							"type": "image_url",
							"image_url": {"url": channel_data['thumbnail_url']}
						}
					]
				}
			]
		else:
			# Text-only message
			messages = [
				{"role": "system", "content": prompt},
				{"role": "user", "content": user_message}
			]

		# Call OpenAI API with vision model
		response = client.chat.completions.create(
			model="gpt-4o",
			messages=messages,
			response_format={"type": "json_schema", "json_schema": {
				"name": "user_demographics",
				"schema": UserDemographics.model_json_schema(),
				"strict": True
			}}
		)

		# Parse the JSON response
		import json
		result_dict = json.loads(response.choices[0].message.content)
		return UserDemographics(**result_dict)

	except Exception as e:
		print(f"Error inferring demographics: {e}")
		return None


def analyze_demographics(profiles_file=None, output_file=None, max_users=None):
	"""
	Phase 2: Analyze demographics using OpenAI Vision API.

	Args:
		profiles_file: Path to user profiles CSV (default: latest)
		output_file: Path to save demographics (default: timestamped)
		max_users: Maximum number of users to process (default: all)
	"""
	# Load user profiles
	if profiles_file is None:
		import glob
		csv_files = glob.glob("data/user_profiles_*.csv")
		if not csv_files:
			print("Error: No user profiles CSV files found in data/ directory")
			print("Please run fetch_user_profiles.py first (without -a flag)")
			return
		profiles_file = max(csv_files, key=os.path.getmtime)
		print(f"Loading profiles from: {profiles_file}")

	profiles_df = pd.read_csv(profiles_file)

	# Limit number of users if specified
	if max_users:
		profiles_df = profiles_df.head(max_users)
		print(f"Processing first {len(profiles_df)} users")

	# Create output file if not specified
	if output_file is None:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M")
		output_file = f"data/user_demographics_{timestamp}.csv"
		os.makedirs("data", exist_ok=True)

	# Load checkpoint
	processed_ids = load_checkpoint(output_file)
	profiles_to_process = profiles_df[~profiles_df["channel_id"].isin(processed_ids)]

	print(f"Processing {len(profiles_to_process)} users (out of {len(profiles_df)} total)")

	if len(profiles_to_process) == 0:
		print("All users already processed!")
		return

	# Initialize OpenAI client
	client = OpenAI(api_key=OPENAI_API_KEY)

	# Load prompt
	prompt = load_prompt("prompts/infer_demographics.md")

	# Load existing results if any
	all_results = []
	if processed_ids:
		existing_df = pd.read_csv(output_file)
		all_results = existing_df.to_dict("records")

	# Process each user
	total_users = len(profiles_to_process)
	for idx, (_, row) in enumerate(profiles_to_process.iterrows(), 1):
		print(f"\n[{idx}/{total_users}] Analyzing: {row['channel_title']}")

		# Infer demographics
		demographics = infer_demographics(client, prompt, row.to_dict())

		if demographics:
			result = {
				"channel_id": row["channel_id"],
				"channel_title": row["channel_title"],
				"thumbnail_url": row["thumbnail_url"],
				"channel_description": row["channel_description"],
				"channel_country": row["channel_country"],
				"inferred_age_range": demographics.inferred_age_range,
				"inferred_gender": demographics.inferred_gender,
				"inferred_race_ethnicity": demographics.inferred_race_ethnicity,
				"confidence_level": demographics.confidence_level,
				"reasoning": demographics.reasoning,
			}
			all_results.append(result)

			print(f"  → Age: {demographics.inferred_age_range}, Gender: {demographics.inferred_gender}")
			print(f"  → Race/Ethnicity: {demographics.inferred_race_ethnicity} (confidence: {demographics.confidence_level:.2f})")

		# Save checkpoint periodically
		if idx % CHECKPOINT_INTERVAL == 0 or idx == total_users:
			fieldnames = [
				"channel_id", "channel_title", "thumbnail_url",
				"channel_description", "channel_country",
				"inferred_age_range", "inferred_gender", "inferred_race_ethnicity",
				"confidence_level", "reasoning"
			]
			save_checkpoint(output_file, all_results, fieldnames)
			print(f"  → Checkpoint saved ({len(all_results)} total users)")

		# Rate limiting
		if idx < total_users:
			time.sleep(DELAY_BETWEEN_REQUESTS)

	print(f"\nDemographic analysis complete! Saved to: {output_file}")


def main():
	parser = argparse.ArgumentParser(
		description="Fetch YouTube user profiles and analyze demographics"
	)
	parser.add_argument(
		"-i",
		"--input",
		help="Input comments CSV file (default: latest in data/)"
	)
	parser.add_argument(
		"-o",
		"--output",
		help="Output CSV file (default: timestamped)"
	)
	parser.add_argument(
		"-n",
		"--num-users",
		type=int,
		help="Maximum number of users to process (default: all)"
	)
	parser.add_argument(
		"-a",
		"--analyze",
		action="store_true",
		help="Run demographic analysis phase (requires user_profiles CSV)"
	)
	parser.add_argument(
		"-p",
		"--profiles",
		help="User profiles CSV file for analysis phase (default: latest in data/)"
	)

	args = parser.parse_args()

	if args.analyze:
		# Phase 2: Analyze demographics
		analyze_demographics(
			profiles_file=args.profiles,
			output_file=args.output,
			max_users=args.num_users
		)
	else:
		# Phase 1: Fetch user profiles
		fetch_user_profiles(
			input_file=args.input,
			output_file=args.output,
			max_users=args.num_users
		)


if __name__ == "__main__":
	main()
