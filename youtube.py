#!/usr/bin/env python3
"""
YouTube Comment Scraper
Scrapes comments from YouTube videos using the YouTube Data API v3
"""

import os
import csv
import argparse
import re
from datetime import datetime
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd

# Load environment variables
load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")


def parse_duration(duration):
    """
    Convert ISO 8601 duration (e.g., PT2M18S) to seconds.

    Args:
            duration: ISO 8601 duration string

    Returns:
            Total duration in seconds as integer
    """
    if not duration:
        return 0

    # Pattern matches PT1H30M5S format
    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    match = re.match(pattern, duration)

    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def get_video_details(youtube, video_ids):
    """
    Fetch detailed metadata for a list of video IDs.

    Args:
            youtube: YouTube API service object
            video_ids: List of video IDs

    Returns:
            Dictionary mapping video_id to metadata dict
    """
    if not video_ids:
        return {}

    try:
        request = youtube.videos().list(
            part="snippet,statistics,contentDetails", id=",".join(video_ids)
        )
        response = request.execute()

        video_details = {}
        for item in response.get("items", []):
            video_id = item["id"]
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            video_details[video_id] = {
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "duration": parse_duration(content.get("duration", "")),
                "description": item["snippet"].get("description", ""),
            }

        return video_details

    except HttpError as e:
        print(f"An HTTP error occurred fetching video details: {e}")
        return {}


def search_videos(youtube, query, max_results=10):
    """
    Search for videos matching the given query.

    Args:
            youtube: YouTube API service object
            query: Search query string
            max_results: Maximum number of videos to return (default: 10)

    Returns:
            List of video dictionaries with id, title, and channel info
    """
    try:
        request = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            maxResults=max_results,
            order="relevance",
        )
        response = request.execute()

        videos = []
        video_ids = []
        for rank, item in enumerate(response.get("items", []), start=1):
            video_id = item["id"]["videoId"]
            video_ids.append(video_id)
            video = {
                "video_id": video_id,
                "relevance_rank": rank,
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "video_published_at": item["snippet"]["publishedAt"],
            }
            videos.append(video)

        # Enrich with detailed metadata
        details = get_video_details(youtube, video_ids)
        for video in videos:
            vid_id = video["video_id"]
            if vid_id in details:
                video.update(details[vid_id])

        return videos

    except HttpError as e:
        print(f"An HTTP error occurred: {e}")
        return []


def get_video_comments(youtube, video_id):
    """
    Fetch all comments for a given video, handling pagination.

    Args:
            youtube: YouTube API service object
            video_id: YouTube video ID

    Returns:
            List of comment dictionaries
    """
    comments = []

    try:
        request = youtube.commentThreads().list(
            part="snippet", videoId=video_id, maxResults=100, textFormat="plainText"
        )

        while request:
            response = request.execute()

            for item in response.get("items", []):
                comment = item["snippet"]["topLevelComment"]["snippet"]
                comments.append(
                    {
                        "video_id": video_id,
                        "author": comment["authorDisplayName"],
                        "comment_text": comment["textDisplay"],
                        "comment_like_count": comment["likeCount"],
                        "comment_published_at": comment["publishedAt"],
                    }
                )

            # Get next page of comments
            request = youtube.commentThreads().list_next(request, response)

        return comments

    except HttpError as e:
        if "commentsDisabled" in str(e):
            print(f"Comments disabled for video: {video_id}")
        else:
            print(f"An HTTP error occurred for video {video_id}: {e}")
        return []


def load_comments(csv_file=None):
    """
    Load comments from CSV into a pandas DataFrame.

    Args:
            csv_file: Path to the CSV file (default: latest file in data/)

    Returns:
            pandas DataFrame with parsed dates and types
    """
    try:
        # If no file specified, find the latest CSV in data/
        if csv_file is None:
            import glob
            csv_files = glob.glob("data/youtube_comments_*.csv")
            if not csv_files:
                print("Error: No CSV files found in data/ directory")
                return None
            csv_file = max(csv_files, key=os.path.getmtime)
            print(f"Loading latest file: {csv_file}")

        df = pd.read_csv(csv_file)

        # Convert date columns to datetime
        if "video_published_at" in df.columns:
            df["video_published_at"] = pd.to_datetime(df["video_published_at"])
        if "comment_published_at" in df.columns:
            df["comment_published_at"] = pd.to_datetime(df["comment_published_at"])

        # Convert numeric columns to integers
        numeric_cols = [
            "relevance_rank",
            "video_view_count",
            "video_like_count",
            "video_comment_count",
            "video_duration",
            "comment_like_count",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(int)

        return df

    except FileNotFoundError:
        print(f"Error: File '{csv_file}' not found")
        return None
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return None


def scrape_comments(query, max_videos=10, output_file=None):
    """
    Main orchestrator function to search videos and scrape comments.

    Args:
            query: Search query string
            max_videos: Maximum number of videos to process
            output_file: Output CSV filename (default: data/youtube_comments_YYYYMMDD_HHMM.csv)
    """
    if not API_KEY or API_KEY == "your_api_key_here":
        print("Error: Please set your YouTube API key in the .env file")
        return

    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)

    # Generate default filename with timestamp if not provided
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = f"data/youtube_comments_{timestamp}.csv"

    # Build YouTube API service
    youtube = build("youtube", "v3", developerKey=API_KEY)

    print(f"Searching for videos matching: '{query}'...")
    videos = search_videos(youtube, query, max_videos)

    if not videos:
        print("No videos found.")
        return

    print(f"Found {len(videos)} videos. Fetching comments...")

    all_comments = []
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] Processing: {video['title']}")
        comments = get_video_comments(youtube, video["video_id"])

        # Add video metadata to each comment
        for comment in comments:
            comment["relevance_rank"] = video.get("relevance_rank", 0)
            comment["video_title"] = video["title"]
            comment["video_channel"] = video["channel"]
            comment["video_published_at"] = video.get("video_published_at", "")
            comment["video_view_count"] = video.get("view_count", 0)
            comment["video_like_count"] = video.get("like_count", 0)
            comment["video_comment_count"] = video.get("comment_count", 0)
            comment["video_duration"] = video.get("duration", "")
            comment["video_description"] = video.get("description", "")

        all_comments.extend(comments)
        print(f"  → Collected {len(comments)} comments")

    # Export to CSV
    if all_comments:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "video_id",
                "relevance_rank",
                "video_title",
                "video_channel",
                "video_published_at",
                "video_view_count",
                "video_like_count",
                "video_comment_count",
                "video_duration",
                "video_description",
                "author",
                "comment_text",
                "comment_like_count",
                "comment_published_at",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_comments)

        print(
            f"\n Successfully scraped {len(all_comments)} comments from {len(videos)} videos"
        )
        print(f" Saved to: {output_file}")
    else:
        print("No comments collected.")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape YouTube comments for videos matching a search query"
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        default="NYC congestion pricing",
        help='Search query (default: "NYC congestion pricing")',
    )
    parser.add_argument(
        "-n",
        "--max-videos",
        type=int,
        default=10,
        help="Maximum number of videos to process (default: 10)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output CSV filename (default: data/youtube_comments_YYYYMMDD_HHMM.csv)",
    )
    parser.add_argument(
        "-a",
        "--analyze",
        type=str,
        metavar="FILE",
        help="Load and display basic stats from existing CSV file",
    )

    args = parser.parse_args()

    if args.analyze:
        df = load_comments(args.analyze)
        if df is not None:
            print(f"\n=== Analysis of {args.analyze} ===\n")
            print(f"Total comments: {len(df)}")
            print(f"Unique videos: {df['video_id'].nunique()}")
            print(f"Unique authors: {df['author'].nunique()}")
            print(
                f"Date range: {df['published_at'].min()} to {df['published_at'].max()}"
            )
            print("\nTop 5 authors by comment count:")
            print(df["author"].value_counts().head())
            print("\nTop 5 most liked comments:")
            print(
                df.nlargest(5, "like_count")[["author", "like_count", "comment_text"]]
            )
    else:
        scrape_comments(args.query, args.max_videos, args.output)


if __name__ == "__main__":
    main()
