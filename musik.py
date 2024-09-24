import sys
import ytmusicapi
import subprocess
import argparse
import yt_dlp

def play_from_ytmusic(search_query, limit=1):
    """Search and play from YouTube Music."""
    yt = ytmusicapi.YTMusic()
    
    # Search for the song on YouTube Music
    results = yt.search(query=search_query, filter="songs", limit=limit)
    
    if results:
        for i in range(limit):
            video_id = results[i]["videoId"]
            url = f"https://music.youtube.com/watch?v={video_id}"
            title = results[i]["title"]  # Get the title of the result

            # Print the title and URL
            print(f"Now playing: \033[1m{title}\033[0m")
            
            # Try playing the song from YouTube Music
            try:
                subprocess.run(f"yt-dlp '{url}' -f bestaudio -o - | mpv -", shell=True)
            except subprocess.CalledProcessError as e:
                print(f"Error playing from YouTube Music: {e}")
    else:
        print("No results found on YouTube Music.")
        return False

def search_from_youtube(search_query):
    """Search and play from YouTube (video)."""
    print(f"Searching on YouTube for: {search_query}")

    result = subprocess.check_output(f"yt-dlp --get-title --get-id 'ytsearch1:{search_query}'", shell=True)
    result = result.decode('utf-8').splitlines()
    title = result[0]  # Extract the title
    video_id = result[1]  # Extract the video ID
    play_from_youtube(video_id, title)

def play_from_youtube(video_url, title):
    """Play a video from YouTube using the provided URL and title."""
    print(f"Now playing: \033[1m{title}\033[0m")

    try:
        # Use the video URL to play directly
        subprocess.run(f"yt-dlp '{video_url}' -f bestaudio -o - | mpv -", shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error playing from YouTube: {e}")


def get_album_playlist_url(search_query):
    """Search for an album on YouTube Music and return its playlist URL."""
    yt = ytmusicapi.YTMusic()
    
    # Search for the album on YouTube Music
    results = yt.search(query=search_query, filter="albums", limit=1)
    
    if results:
        album_id = results[0]["playlistId"]
        url = f"https://music.youtube.com/playlist?list={album_id}"
        print(f"Found album on YouTube Music: {url}")
        return url
    else:
        print("No results found on YouTube Music.")
        return None

def extract_video_urls_from_playlist(playlist_url):
    """Extract video URLs and titles from a YouTube playlist URL."""
    ydl_opts = {'quiet': True, 'extract_flat': True}
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist_info = ydl.extract_info(playlist_url, download=False)
        video_info = [
            {
                'url': f"https://www.youtube.com/watch?v={entry['id']}",
                'title': entry['title']
            }
            for entry in playlist_info['entries']
        ]
    
    return video_info

if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Search and play music from YouTube Music or YouTube.")
    parser.add_argument("search_query", help="The search query for the track")
    parser.add_argument("-n", "--num-results", type=int, default=1, help="Number of results to play (default is 1)")
    parser.add_argument("-a", "--audio", action="store_true", help="First play from YouTube Music, then fallback to YouTube video if available")
    parser.add_argument("-v", "--video", action="store_true", help="Search and play directly from YouTube video")
    parser.add_argument("-p", "--playlist", action="store_true", help="Play all videos from a YouTube playlist")
    parser.add_argument("-b", "--album", action="store_true", help="Search and play album from YouTube Music")

    # Parse the arguments
    args = parser.parse_args()
    search_query = args.search_query
    num_results = args.num_results
    playlist_url = None

    # Determine the source based on provided options
    if args.album:
        print(f"Searching for album: {search_query}")
        playlist_url = get_album_playlist_url(search_query)
        args.playlist = True

    if args.playlist:
        if not playlist_url:
            playlist_url =  search_query
        print(f"Extracting videos from playlist: {playlist_url}")
        video_links = extract_video_urls_from_playlist(playlist_url)
        
        # Play each video one by one
        for video_info in video_links:
            play_from_youtube(video_info['url'], video_info['title'])

    if args.video:
        search_from_youtube(args.search_query)
    elif args.audio:
        # Try playing from YouTube Music first, then fallback to YouTube if available
        play_from_ytmusic(args.search_query, limit=num_results)
        print("Falling back to YouTube video...")
        search_from_youtube(args.search_query)
    else:
        # Default: play only from YouTube Music
        play_from_ytmusic(args.search_query, limit=num_results)
