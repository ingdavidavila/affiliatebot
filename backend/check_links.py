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
    return 50

def get_uploads_playlist_id(youtube, channel_id):
    response = youtube.channels().list(part='contentDetails', id=channel_id).execute()
    if not response.get('items'):
        raise ValueError(f"Channel ID '{channel_id}' not found.")
    return response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

def get_video_ids(youtube, playlist_id, max_videos):
    video_ids, next_page_token = [], None
    while len(video_ids) < max_videos:
        response = youtube.playlistItems().list(
            part='contentDetails',
            playlistId=playlist_id,
            maxResults=min(50, max_videos - len(video_ids)),
            pageToken=next_page_token
        ).execute()
        for item in response.get('items', []):
            video_ids.append(item['contentDetails']['videoId'])
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
    return video_ids[:max_videos]

def get_video_description(youtube, video_id):
    response = youtube.videos().list(part='snippet', id=video_id).execute()
    if response.get('items'):
        return response['items'][0]['snippet']['description']
    return ''

def is_affiliate_link(url):
    return any(domain in url.lower() for domain in AFFILIATE_DOMAINS) or \
           any(param in url.lower() for param in ['tag=', 'ref=', 'aff=', 'affiliate', 'partner'])

def extract_affiliate_links(description):
    urls = re.findall(r'https?://[^\s\)\]]+', description)
    affiliate_urls = [u for u in urls if is_affiliate_link(u)]
    return affiliate_urls or urls

def check_link_status(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LinkChecker/1.1)"}
    timeout = 5 if is_affiliate_link(url) else 2  # faster for normal links
    try:
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=timeout, stream=True)
        return resp.status_code in (200, 301, 302), resp.status_code
    except requests.Timeout:
        return False, 408
    except requests.RequestException:
        return False, None

def check_all_links(links):
    broken = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(check_link_status, link): link for link in links}
        for future in as_completed(future_map):
            link = future_map[future]
            valid, status = future.result()
            if not valid:
                broken.append({'videoId': None, 'link': link, 'status': status})
    return broken

def main(channel_id, max_videos):
    youtube = get_youtube_service()
    broken_links = []
    playlist_id = get_uploads_playlist_id(youtube, channel_id)
    video_ids = get_video_ids(youtube, playlist_id, max_videos)

    for video_id in video_ids:
        description = get_video_description(youtube, video_id)
        links = extract_affiliate_links(description)
        if not links:
            continue
        bad_links = check_all_links(links)
        for link in bad_links:
            link['videoId'] = video_id
            broken_links.append(link)

    # write CSV for debugging
    with open("broken_links.csv", "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Video URL", "Broken Link", "Status"])
        for item in broken_links:
            writer.writerow([
                f"https://www.youtube.com/watch?v={item['videoId']}",
                item['link'],
                item['status']
            ])

    return broken_links

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python check_links.py <channel_id> <max_videos>"}))
        sys.exit(1)
    channel_id, max_videos = sys.argv[1], int(sys.argv[2])
    try:
        broken_links = main(channel_id, max_videos)
        print(json.dumps({"brokenLinks": broken_links}))  # <-- Only one JSON print
    except Exception as e:
        print(json.dumps({"error": str(e)}))
    sys.exit(0)
