#!/usr/bin/env python3
"""
Infer user demographics using OpenAI Vision API.
Analyzes YouTube user profile images, usernames, descriptions, and metadata
to estimate age range, gender, and race/ethnicity.
Includes checkpointing, rate limiting, and resume capability.
"""

import os
import csv
import argparse
import time
from datetime import datetime
from typing import Literal
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
import pandas as pd
import json

# Load environment variables
load_dotenv()

# API Configuration
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
		result_dict = json.loads(response.choices[0].message.content)
		return UserDemographics(**result_dict)

	except Exception as e:
		print(f"Error inferring demographics: {e}")
		return None


def analyze_demographics(profiles_file=None, output_file=None, max_users=None):
	"""
	Analyze demographics using OpenAI Vision API.

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
			print("Please run fetch_user_profiles.py first to collect user profiles")
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
		description="Infer user demographics from YouTube profiles using OpenAI Vision API"
	)
	parser.add_argument(
		"-i",
		"--input",
		help="Input user profiles CSV file (default: latest in data/)"
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

	args = parser.parse_args()

	analyze_demographics(
		profiles_file=args.input,
		output_file=args.output,
		max_users=args.num_users
	)


if __name__ == "__main__":
	main()
