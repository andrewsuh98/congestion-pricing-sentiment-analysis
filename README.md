# NYC Congestion Pricing Sentiment Analysis

Research pipeline for analyzing YouTube discourse on NYC congestion pricing through automated video and comment analysis.

## Overview

This project implements a six-stage pipeline to collect, transcribe, summarize, and analyze YouTube discourse on NYC congestion pricing:

1. **Data Collection** - Scrape videos and comments via YouTube Data API
2. **Transcript Extraction** - Download video transcripts
3. **Video Summarization** - Generate structured summaries with stance classification
4. **Comment Labeling** - Classify comments by sentiment and stance
5. **User Profile Collection** - Fetch commenter channel data from YouTube API
6. **Demographic Analysis** - Infer user demographics using OpenAI vision API

## Features

- Automated YouTube video and comment scraping with author metadata
- Transcript extraction without OAuth requirements
- AI-powered video summarization with structured outputs (OpenAI)
- Sentiment and stance analysis for comments
- User profile collection (channel data, profile images, descriptions)
- Demographic inference from profile images and usernames (OpenAI Vision)
- Structured data outputs with confidence scores
- Rate limiting and checkpointing for reliability
- Resume capability for long-running processes

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file with your API keys:
   ```
   YOUTUBE_API_KEY=your_youtube_api_key
   OPENAI_API_KEY=your_openai_api_key
   ```

4. Get API keys:
   - YouTube Data API: https://console.cloud.google.com/apis/credentials
   - OpenAI API: https://platform.openai.com/api-keys

## Usage

### 1. Scrape YouTube Videos and Comments

```bash
# Default: scrape 10 videos about "NYC congestion pricing"
python youtube.py

# Scrape 50 videos
python youtube.py -n 50

# Custom query
python youtube.py -q "your search query" -n 20
```

**Output:** `data/youtube_comments_YYYYMMDD_HHMM.csv`

### 2. Extract Video Transcripts

```bash
# Fetch all video transcripts
python fetch_transcripts.py

# Fetch first 5 videos only (for testing)
python fetch_transcripts.py -n 5
```

**Output:** `data/transcripts_YYYYMMDD_HHMM.csv`

### 3. Summarize Videos

```bash
# Summarize all videos
python summarize_videos.py

# Use specific transcript file
python summarize_videos.py -i data/transcripts_20251008_1430.csv
```

**Output:** `data/video_summaries_YYYYMMDD_HHMM.csv`

### 4. Label Comments

```bash
# Test with 10 comments first
python label_comments.py -n 10

# Test with 100 comments
python label_comments.py -n 100

# Label all comments
python label_comments.py

# Resume from checkpoint (use same filename)
python label_comments.py -o data/my_labels.csv
```

**Output:** `data/labeled_comments_YYYYMMDD_HHMM.csv`

### 5. Fetch User Profiles

```bash
# Fetch profile data for all unique users
python fetch_user_profiles.py

# Test with 10 users first
python fetch_user_profiles.py -n 10

# Use specific comments file
python fetch_user_profiles.py -i data/youtube_comments_20251029_1549.csv
```

**Output:** `data/user_profiles_YYYYMMDD_HHMM.csv`

### 6. Analyze User Demographics

```bash
# Analyze demographics for all users (requires user_profiles CSV from step 5)
python infer_demographics.py

# Test with 10 users first (RECOMMENDED - uses OpenAI Vision API)
python infer_demographics.py -n 10

# Use specific profiles file
python infer_demographics.py -i data/user_profiles_20251029_1549.csv
```

**Output:** `data/user_demographics_YYYYMMDD_HHMM.csv`

## Data Pipeline

```
YouTube Videos
     ↓
[youtube.py] → youtube_comments_YYYYMMDD_HHMM.csv
     ↓                           ↓
     ↓                    [fetch_user_profiles.py]
     ↓                           ↓
     ↓                    user_profiles_YYYYMMDD_HHMM.csv
     ↓                           ↓
     ↓                    [infer_demographics.py]
     ↓                           ↓
     ↓                    user_demographics_YYYYMMDD_HHMM.csv
     ↓
[fetch_transcripts.py] → transcripts_YYYYMMDD_HHMM.csv
     ↓
[summarize_videos.py] → video_summaries_YYYYMMDD_HHMM.csv
     ↓
[label_comments.py] → labeled_comments_YYYYMMDD_HHMM.csv
```

## Output Schemas

### Comments CSV
- Video metadata: `video_id`, `video_title`, `video_channel`, `video_published_at`, `video_view_count`, etc.
- Comment data: `author`, `comment_text`, `comment_like_count`, `comment_published_at`
- Author metadata: `author_channel_id`, `author_channel_url`, `author_profile_image_url`

### User Profiles CSV
- `channel_id`, `channel_title`, `channel_description`
- `channel_country`, `channel_custom_url`, `thumbnail_url`
- `subscriber_count`, `view_count`, `video_count`

### User Demographics CSV
- `channel_id`, `channel_title`, `thumbnail_url`
- `channel_description`, `channel_country`
- `inferred_age_range`: under_18 | 18-24 | 25-34 | 35-44 | 45-54 | 55-64 | 65_plus | unclear
- `inferred_gender`: male | female | non_binary | unclear
- `inferred_race_ethnicity`: white | black_african_american | hispanic_latino | asian | middle_eastern_north_african | native_american_indigenous | pacific_islander | multiracial | unclear
- `confidence_level`: 0-1 float
- `reasoning`: Brief explanation of inference

### Transcripts CSV
- `video_id`, `is_generated`, `language`, `language_code`, `transcript`

### Video Summaries CSV
- `video_id`, `summary_text` (150-300 words)
- `stance_congestion_pricing`: strongly_supportive | supportive | neutral_or_mixed | skeptical | strongly_oppose | unclear
- `stance_confidence`: 0-1 float
- `key_arguments`: JSON array of 3-10 key points
- `tone`: objective | persuasive | critical | humorous | emotional | mixed

### Labeled Comments CSV
- All original comment columns
- `sentiment`: very_negative | negative | neutral | positive | very_positive
- `stance_congestion_pricing_comment`: strongly_oppose | skeptical | neutral_or_unclear | supportive | strongly_supportive
- `stance_confidence_comment`: 0-1 float
- `tone`: sarcastic | angry | frustrated | supportive | informative | humorous | neutral | mixed

## API Quota Considerations

**YouTube Data API v3 (Free tier: 10,000 units/day)**
- Search: 100 units per query
- Comments: 1 unit per 100 comments
- Video details: 1 unit per batch (up to 50 IDs)
- Channels: 1 unit per batch (up to 50 IDs)
- Approximately 100 videos + comments per day

**OpenAI API**
- Video summarization (gpt-4o-mini): ~50 videos
- Comment labeling (gpt-4o-mini): 8,676+ comments requires significant API credits
- Demographic analysis (gpt-4o with vision): ~7,500 users with profile image analysis
- Built-in rate limiting: 50 requests/minute
- **Recommendation**: Test with `-n 10` first, especially for demographic analysis (most expensive)

## Key Features

### Structured Outputs
Uses OpenAI's structured outputs feature with Pydantic models for guaranteed JSON schema compliance.

### Rate Limiting
Automatic delays between API calls (50 requests/minute for OpenAI) to stay within rate limits.

### Checkpointing
Saves progress every 100 comments. If script crashes, re-run with the same output filename to resume.

### Error Handling
Gracefully handles missing data, disabled comments, and API errors.

## Project Structure

```
.
├── youtube.py                    # Video and comment scraping
├── fetch_transcripts.py          # Transcript extraction
├── summarize_videos.py           # Video summarization (OpenAI)
├── label_comments.py             # Comment sentiment labeling (OpenAI)
├── fetch_user_profiles.py        # User profile collection (YouTube API)
├── infer_demographics.py         # Demographic analysis (OpenAI Vision)
├── prompts/
│   ├── summarize_video.md        # Video summarization prompt
│   ├── label_sentiment.md        # Comment labeling prompt
│   └── infer_demographics.md     # Demographic inference prompt
├── data/                          # Output CSVs (gitignored)
├── requirements.txt
├── .env                           # API keys (gitignored)
└── README.md
```

## License

MIT
