from googleapiclient.discovery import build
from config.api_keys import YOUTUBE_API_KEY

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

def search_youtube(query):
    try:
        request = youtube.search().list(
            part="snippet",
            maxResults=5,
            q=query,
            type="video"  # Only return videos, not channels/playlists
        )
        response = request.execute()
        if response['items']:
            for item in response['items']:
                if 'id' in item and 'videoId' in item['id']:
                    video_url = f"https://www.youtube.com/watch?v={item['id']['videoId']}"
                    return video_url
            return None
        else:
            return None
    except Exception as e:
        print(f"Error with YouTube API: {e}")
        return None
