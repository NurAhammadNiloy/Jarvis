from googleapiclient.discovery import build
from config.api_keys import YOUTUBE_API_KEY

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

def search_youtube(query):
    try:
        request = youtube.search().list(
            part="snippet",
            maxResults=1,
            q=query
        )
        response = request.execute()
        if response['items']:
            video_url = f"https://www.youtube.com/watch?v={response['items'][0]['id']['videoId']}"
            return video_url
        else:
            return None
    except Exception as e:
        print(f"Error with YouTube API: {e}")
        return None
