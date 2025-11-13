#!/usr/bin/env python3
"""
Fetch YouTube user profile data from YouTube API.
Collects user channel data including profile images, descriptions, and metadata.
Includes checkpointing, batching, and resume capability.
"""

import os
import csv
import argparse
import time
from datetime import datetime
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd

# Load environment variables
load_dotenv()

# API Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# Rate limiting configuration
REQUESTS_PER_MINUTE = 50
DELAY_BETWEEN_REQUESTS = 60.0 / REQUESTS_PER_MINUTE  # ~1.2 seconds


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
            part="snippet,statistics", id=",".join(channel_ids), maxResults=50
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

            channels.append(
                {
                    "channel_id": item["id"],
                    "channel_title": snippet.get("title", ""),
                    "channel_description": snippet.get("description", ""),
                    "channel_country": snippet.get("country", ""),
                    "channel_custom_url": snippet.get("customUrl", ""),
                    "thumbnail_url": thumbnail_url,
                    "subscriber_count": statistics.get("subscriberCount", ""),
                    "view_count": statistics.get("viewCount", ""),
                    "video_count": statistics.get("videoCount", ""),
                }
            )

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
    Fetch user profile data from YouTube API.

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
    users_to_process = unique_users[
        ~unique_users["author_channel_id"].isin(processed_ids)
    ]
    print(
        f"Processing {len(users_to_process)} users (out of {len(unique_users)} total)"
    )

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
        batch_ids = channel_ids[i : i + batch_size]
        batch_num = (i // batch_size) + 1

        print(
            f"\n[Batch {batch_num}/{total_batches}] Fetching {len(batch_ids)} channels..."
        )

        # Fetch channel details
        channels = fetch_channel_details(youtube, batch_ids)

        if channels:
            all_results.extend(channels)
            print(f"  → Fetched {len(channels)} channel details")

            # Save checkpoint after each batch
            fieldnames = [
                "channel_id",
                "channel_title",
                "channel_description",
                "channel_country",
                "channel_custom_url",
                "thumbnail_url",
                "subscriber_count",
                "view_count",
                "video_count",
            ]
            save_checkpoint(output_file, all_results, fieldnames)
            print(f"  → Checkpoint saved ({len(all_results)} total users)")

        # Rate limiting
        if i + batch_size < len(channel_ids):
            time.sleep(DELAY_BETWEEN_REQUESTS)

    print(f"\nProfile collection complete! Saved to: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Fetch YouTube user profile data from YouTube API"
    )
    parser.add_argument(
        "-i", "--input", help="Input comments CSV file (default: latest in data/)"
    )
    parser.add_argument("-o", "--output", help="Output CSV file (default: timestamped)")
    parser.add_argument(
        "-n",
        "--num-users",
        type=int,
        help="Maximum number of users to process (default: all)",
    )

    args = parser.parse_args()

    fetch_user_profiles(
        input_file=args.input, output_file=args.output, max_users=args.num_users
    )


if __name__ == "__main__":
    main()
