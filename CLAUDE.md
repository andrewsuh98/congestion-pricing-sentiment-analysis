# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Research pipeline for analyzing YouTube discourse on NYC congestion pricing:

1. **Data Collection**: Fetch videos and comments via YouTube Data API v3
2. **Transcript Extraction**: Download video transcripts using youtube-transcript-api
3. **Video Summarization**: Generate structured summaries using OpenAI with stance classification
4. **Comment Labeling**: Classify comments by sentiment and stance using OpenAI structured outputs
5. **User Profile Collection**: Fetch commenter channel data (profile images, descriptions, metadata)
6. **Demographic Analysis**: Infer user demographics using OpenAI Vision API from profile images and usernames

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Create `.env` file with API keys:
   ```
   YOUTUBE_API_KEY=your_youtube_key_here
   OPENAI_API_KEY=your_openai_key_here
   ```
3. Get YouTube API key: https://console.cloud.google.com/apis/credentials
4. Get OpenAI API key: https://platform.openai.com/api-keys

## Usage

**Basic scraping:**
```bash
python youtube.py                           # Default: 10 videos, "NYC congestion pricing"
python youtube.py -n 50                     # Scrape 50 videos
python youtube.py -q "your query" -n 20     # Custom query and count
python youtube.py -o custom.csv             # Custom output file
```

**Analysis:**
```bash
python youtube.py -a data/youtube_comments_20250930_1445.csv
```

**In Python:**
```python
from youtube import load_comments

df = load_comments()                        # Auto-loads latest CSV from data/
df = load_comments('path/to/file.csv')      # Load specific file
```

**Transcript extraction:**
```bash
python fetch_transcripts.py                 # Fetch all video transcripts
python fetch_transcripts.py -n 5            # Fetch first 5 videos only
python fetch_transcripts.py -i data/youtube_comments_20250930_1445.csv
python fetch_transcripts.py -o output.csv   # Resume capability (reuse same filename)
```

**Video summarization (requires OpenAI API):**
```bash
python summarize_videos.py                  # Summarize all videos
python summarize_videos.py -i data/transcripts_20251008_1430.csv
```

**Comment labeling (requires OpenAI API):**
```bash
python label_comments.py -n 10              # Test with 10 comments
python label_comments.py -n 100             # Test with 100 comments
python label_comments.py                    # Label all comments
python label_comments.py -o output.csv      # Resume capability (reuse same filename)
```

**User profile collection:**
```bash
python fetch_user_profiles.py               # Fetch all unique users
python fetch_user_profiles.py -n 10         # Test with 10 users
```

**Demographic inference (requires OpenAI Vision API):**
```bash
python infer_demographics.py                # Analyze all profiles
python infer_demographics.py -n 10          # Test with 10 profiles (RECOMMENDED)
python infer_demographics.py -i data/user_profiles_20251029_1549.csv
```

## Architecture

**Six-stage pipeline (stages 5 and 6 now use separate scripts):**

### 1. Data Collection (`youtube.py`)
- **Search phase:** `search_videos()` → `get_video_details()`
  - Searches by query, returns video IDs ranked by YouTube's relevance
  - Enriches with statistics (views, likes, duration, description)
  - Duration converted from ISO 8601 to seconds via `parse_duration()`
- **Collection phase:** `get_video_comments()` per video
  - Fetches all top-level comments with pagination (100/request)
  - **NEW**: Captures author metadata: `author_channel_id`, `author_channel_url`, `author_profile_image_url`
  - Handles disabled comments gracefully
  - Does NOT fetch replies (would require separate API calls)
- **Export:** Saves to `data/youtube_comments_YYYYMMDD_HHMM.csv`

### 2. Transcript Extraction (`fetch_transcripts.py`)
- Uses `youtube-transcript-api` (no OAuth required)
- Fetches transcripts for all videos in comments CSV
- Cleans escaped characters (`\xa0`, `\n`) and normalizes whitespace
- Checkpointing: saves after each successful fetch, resume with same filename
- Outputs: `data/transcripts_YYYYMMDD_HHMM.csv`
- Fields: `video_id`, `is_generated`, `language`, `language_code`, `transcript`

### 3. Video Summarization (`summarize_videos.py`)
- Uses OpenAI structured outputs (gpt-4o-mini)
- Pydantic model: `VideoSummary` with 5 structured fields
- Loads video metadata from comments CSV + transcripts
- Outputs: `data/video_summaries_YYYYMMDD_HHMM.csv`
- Fields: `video_id`, `summary_text`, `stance_congestion_pricing`, `stance_confidence`, `key_arguments` (JSON), `tone`

### 4. Comment Labeling (`label_comments.py`)
- Uses OpenAI structured outputs (gpt-4o-mini)
- Pydantic model: `CommentSentiment` with 4 structured fields
- Passes full video context (title, channel, date, stance, summary) to LLM
- Rate limiting: 50 requests/minute (~1.2s delay)
- Checkpointing: saves every 100 comments, resume with same filename
- Outputs: `data/labeled_comments_YYYYMMDD_HHMM.csv`
- New fields: `sentiment`, `stance_congestion_pricing_comment`, `stance_confidence_comment`, `tone`

### 5. User Profile Collection (`fetch_user_profiles.py`)
- Extracts unique users from comments CSV (`author` + `author_channel_id`)
- Batches channel IDs (50 per request) for YouTube API efficiency
- Calls `channels().list()` with parts: `snippet`, `statistics`
- Fetches: profile images (800x800px), channel descriptions, country, subscriber/view counts
- Checkpointing: saves after each batch, resume with same filename
- Outputs: `data/user_profiles_YYYYMMDD_HHMM.csv`
- Fields: `channel_id`, `channel_title`, `channel_description`, `channel_country`, `thumbnail_url`, `subscriber_count`, `view_count`, `video_count`

### 6. Demographic Analysis (`infer_demographics.py`)
- Uses OpenAI gpt-4o (vision-capable model)
- Pydantic model: `UserDemographics` with 5 structured fields
- Analyzes profile image + username + description + country
- Infers demographics from textual cues even without human faces (gendered names, birth years, cultural names)
- Rate limiting: 50 requests/minute (~1.2s delay)
- Checkpointing: saves every 50 users, resume with same filename
- Outputs: `data/user_demographics_YYYYMMDD_HHMM.csv`
- Fields: `inferred_age_range`, `inferred_gender`, `inferred_race_ethnicity`, `confidence_level`, `reasoning`
- **Note**: Separated from profile collection for better modularity and cost management

## CSV Schemas

### Comments CSV (`youtube_comments_*.csv`)
**Video metadata (repeated per comment):**
- `video_id`, `relevance_rank`, `video_title`, `video_channel`
- `video_published_at`, `video_view_count`, `video_like_count`, `video_comment_count`
- `video_duration` (seconds), `video_description`

**Comment data:**
- `author`, `comment_text`, `comment_like_count`, `comment_published_at`

**Author metadata:**
- `author_channel_id`, `author_channel_url`, `author_profile_image_url`

Note: Two separate date columns distinguish when video was uploaded vs when comment was posted.

### Transcripts CSV (`transcripts_*.csv`)
- `video_id`: YouTube video ID
- `is_generated`: Boolean, true if auto-generated captions
- `language`: Full language name
- `language_code`: ISO language code
- `transcript`: Full cleaned transcript text (one entry per video)

### Video Summaries CSV (`video_summaries_*.csv`)
- `video_id`: YouTube video ID
- `summary_text`: 150-300 word summary
- `stance_congestion_pricing`: strongly_supportive | supportive | neutral_or_mixed | skeptical | strongly_oppose | unclear
- `stance_confidence`: Float 0-1
- `key_arguments`: JSON array of 3-10 key arguments
- `tone`: objective | persuasive | critical | humorous | emotional | mixed
- `is_generated`: From transcript metadata
- `language_code`: From transcript metadata

### Labeled Comments CSV (`labeled_comments_*.csv`)
**All original comment columns, plus:**
- `summary_text`: Video summary (joined from summaries CSV)
- `stance_congestion_pricing`: Video's stance (joined from summaries CSV)
- `stance_confidence`: Video's stance confidence (joined from summaries CSV)
- `sentiment`: very_negative | negative | neutral | positive | very_positive
- `stance_congestion_pricing_comment`: Comment's stance (strongly_oppose | skeptical | neutral_or_unclear | supportive | strongly_supportive)
- `stance_confidence_comment`: Comment's stance confidence (float 0-1)
- `tone`: sarcastic | angry | frustrated | supportive | informative | humorous | neutral | mixed

### User Profiles CSV (`user_profiles_*.csv`)
- `channel_id`: YouTube channel ID
- `channel_title`: Channel/username
- `channel_description`: Channel "About" section
- `channel_country`: Country code (if set by user)
- `channel_custom_url`: Custom channel URL
- `thumbnail_url`: Profile image URL (800x800px)
- `subscriber_count`: Number of subscribers
- `view_count`: Total channel views
- `video_count`: Number of videos uploaded

### User Demographics CSV (`user_demographics_*.csv`)
- `channel_id`: YouTube channel ID
- `channel_title`: Channel/username
- `thumbnail_url`: Profile image URL
- `channel_description`: Channel "About" section
- `channel_country`: Country code
- `inferred_age_range`: under_18 | 18-24 | 25-34 | 35-44 | 45-54 | 55-64 | 65_plus | unclear
- `inferred_gender`: male | female | non_binary | unclear
- `inferred_race_ethnicity`: white | black_african_american | hispanic_latino | asian | middle_eastern_north_african | native_american_indigenous | pacific_islander | multiracial | unclear
- `confidence_level`: Float 0-1 indicating inference confidence
- `reasoning`: Brief explanation of demographic inference (2-3 sentences)

## API Quota Management

### YouTube Data API v3
- Free tier: 10,000 units/day
- Search: 100 units per query
- Comments: 1 unit per page (100 comments)
- Video details: 1 unit per batch (up to 50 IDs)
- Channels: 1 unit per batch (up to 50 IDs)
- Roughly ~100 videos + comments/day within quota

### OpenAI API
- Video summarization (gpt-4o-mini): ~50 videos can be processed
- Comment labeling (gpt-4o-mini): ~8,676 comments requires significant API credits
- Demographic analysis (gpt-4o with vision): ~7,500 users with profile images (most expensive)
- Rate limiting: 50 requests/minute built into scripts
- Checkpointing: prevents re-processing on failures
- Recommendation: Test with `-n 10` flag first, especially for demographic analysis

## Code Conventions

- Use tabs, not spaces
- No emojis
- Straight quotes only (never curly)
- Keep descriptions concise
- Never commit `.env`, CSV files, or Jupyter notebooks (gitignored)

## Prompts

LLM prompts are stored in `prompts/` directory:
- `prompts/summarize_video.md`: Video summarization system prompt
- `prompts/label_sentiment.md`: Comment sentiment labeling system prompt
- `prompts/infer_demographics.md`: Demographic inference system prompt (emphasizes inference from usernames, birth years, and cultural names)
