import os
import re
import sys
import csv
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

API_KEY = os.getenv('YOUTUBE_API_KEY')

AFFILIATE_DOMAINS = [
    "amzn.to", "amazon.com", "bit.ly", "shareasale.com",
    "impact.com", "rakuten.com", "cj.com", "shopstyle.com",
    "rewardstyle.com", "clickbank.net", "linksynergy.com",
    "pepperjam.com", "awin1.com"
]

def get_youtube_service():
    if not API_KEY:
        raise ValueError("Please set the YOUTUBE_API_KEY environment variable.")
    return build('youtube', 'v3', developerKey=API_KEY)

def get_total_video_count(youtube, channel_id):
    request = youtube.channels().list(part='statistics', id=channel_id)
    response = request.execute()
    if response.get('items'):
        return int(response['items'][0]['statistics']['videoCount'])
    return 50  # Fallback if channel not found or no videos

def get_uploads_playlist_id(youtube, channel_id):
    request = youtube.channels().list(part='contentDetails', id=channel_id)
    response = request.execute()
    if not response.get('items'):
        print(f"Debug: Channel ID '{channel_id}' not found in API response.", file=sys.stderr)
        raise ValueError(f"Channel ID '{channel_id}' not found.")
    return response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

def get_video_ids(youtube, playlist_id, max_videos):
    video_ids = []
    next_page_token = None
    while len(video_ids) < max_videos if max_videos >= 0 else True:
        request = youtube.playlistItems().list(
            part='contentDetails',
            playlistId=playlist_id,
            maxResults=min(50, max_videos - len(video_ids) if max_videos >= 0 else 50),
            pageToken=next_page_token
        )
        response = request.execute()
        for item in response.get('items', []):
            video_ids.append(item['contentDetails']['videoId'])
        next_page_token = response.get('nextPageToken')
        if not next_page_token and (max_videos < 0 or len(video_ids) >= max_videos):
            break
    return video_ids[:max_videos] if max_videos >= 0 else video_ids

def get_video_description(youtube, video_id):
    request = youtube.videos().list(part='snippet', id=video_id)
    response = request.execute()
    if response.get('items'):
        return response['items'][0]['snippet']['description']
    return ''

def is_affiliate_link(url):
    return any(domain in url.lower() for domain in AFFILIATE_DOMAINS) or \
           any(param in url.lower() for param in ['tag=', 'ref=', 'aff=', 'affiliate', 'partner'])

def extract_affiliate_links(description):
    url_pattern = re.compile(r'https?://[^\s\)\]]+')
    urls = url_pattern.findall(description)
    affiliate_urls = [url for url in urls if is_affiliate_link(url)]
    return affiliate_urls if affiliate_urls else urls

def check_link_status(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LinkChecker/1.0)"}
    try:
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=10, stream=True)
        return response.status_code in [200, 301, 302], response.status_code
    except requests.RequestException as e:
        print(f"Error checking {url}: {e}", file=sys.stderr)
        return False, None

def check_all_links(links):
    broken = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_link_status, link): link for link in links}
        for future in as_completed(futures):
            link = futures[future]
            is_valid, status_code = future.result()
            if not is_valid:
                broken.append({'videoId': None, 'link': link, 'status': status_code})
    return broken

def main(channel_id, max_videos):
    youtube = get_youtube_service()
    broken_links = []
    try:
        effective_max_videos = max_videos if max_videos >= 0 else get_total_video_count(youtube, channel_id)
        playlist_id = get_uploads_playlist_id(youtube, channel_id)
        video_ids = get_video_ids(youtube, playlist_id, effective_max_videos)

        for video_id in video_ids:
            print(f"[INFO] Checking video: {video_id}", file=sys.stderr)
            description = get_video_description(youtube, video_id)
            links = extract_affiliate_links(description)
            if not links:
                continue
            bad_links = check_all_links(links)
            for link in bad_links:
                link['videoId'] = video_id
                broken_links.append(link)

        if broken_links:
            print("\nBroken affiliate (or general) links found:\n", file=sys.stderr)
            for item in broken_links:
                print(f"Video: https://www.youtube.com/watch?v={item['videoId']}", file=sys.stderr)
                print(f"Broken link: {item['link']} (Status: {item['status']})\n", file=sys.stderr)

            with open("broken_links.csv", "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Video URL", "Broken Link", "Status"])
                for item in broken_links:
                    writer.writerow([f"https://www.youtube.com/watch?v={item['videoId']}", item['link'], item['status']])
            print("[INFO] CSV saved with {len(broken_links)} broken links.", file=sys.stderr)
        else:
            print("✅ No broken links found in the checked videos.", file=sys.stderr)

        # Output JSON to stdout
        print(json.dumps({'brokenLinks': broken_links}))
    except HttpError as e:
        print(f"YouTube API error: {e}", file=sys.stderr)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python check_links.py <channel_id> <max_videos>", file=sys.stderr)
        sys.exit(1)
    broken_links = main(sys.argv[1], int(sys.argv[2]))
    print(json.dumps({'brokenLinks': broken_links}))  # Only JSON to stdout
