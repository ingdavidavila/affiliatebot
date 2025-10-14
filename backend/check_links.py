import os
import re
import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import sys

API_KEY = os.getenv('YOUTUBE_API_KEY')

def get_youtube_service():
    if not API_KEY:
        raise ValueError("Please set the YOUTUBE_API_KEY environment variable.")
    return build('youtube', 'v3', developerKey=API_KEY)

def get_uploads_playlist_id(youtube, channel_id):
    request = youtube.channels().list(part='contentDetails', id=channel_id)
    response = request.execute()
    if not response.get('items'):
        raise ValueError(f"Channel ID '{channel_id}' not found.")
    return response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

def get_video_ids(youtube, playlist_id, max_videos):
    video_ids = []
    next_page_token = None
    while len(video_ids) < max_videos:
        request = youtube.playlistItems().list(
            part='contentDetails',
            playlistId=playlist_id,
            maxResults=min(50, max_videos - len(video_ids)),
            pageToken=next_page_token
        )
        response = request.execute()
        for item in response.get('items', []):
            video_ids.append(item['contentDetails']['videoId'])
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
    return video_ids

def get_video_description(youtube, video_id):
    request = youtube.videos().list(part='snippet', id=video_id)
    response = request.execute()
    if response.get('items'):
        return response['items'][0]['snippet']['description']
    return ''

def extract_affiliate_links(description):
    url_pattern = re.compile(r'https?://[^\s]+')
    urls = url_pattern.findall(description)
    affiliate_urls = [url for url in urls if any(param in url.lower() for param in ['tag=', 'aff=', 'ref=', 'affiliate', 'partner'])]
    return affiliate_urls if affiliate_urls else urls

def check_link_status(url):
    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

def main(channel_id, max_videos):
    youtube = get_youtube_service()
    try:
        playlist_id = get_uploads_playlist_id(youtube, channel_id)
        video_ids = get_video_ids(youtube, playlist_id, max_videos)
        
        for video_id in video_ids:
            description = get_video_description(youtube, video_id)
            links = extract_affiliate_links(description)
            for link in links:
                if not check_link_status(link):
                    print(f"Video: https://www.youtube.com/watch?v={video_id}")
                    print(f"Broken link: {link}")
    except (HttpError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python check_links.py <channel_id> <max_videos>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], int(sys.argv[2]))