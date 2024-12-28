import sys
import os
import time
import ytmusicapi
import subprocess
import argparse
import yt_dlp
import configparser
import webbrowser
import hashlib
import urllib.parse
import urllib.request
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.ini')

# Check if config file exists
if not os.path.exists(CONFIG_PATH):
    print(f"Config file not found. Creating a new one at {CONFIG_PATH}")
    config = configparser.ConfigParser()
    config['lastfm'] = {
        'api_key': 'your_api_key_here',
        'api_secret': 'your_api_secret_here'
    }
    with open(CONFIG_PATH, 'w') as configfile:
        config.write(configfile)
    print("Please edit config.ini and add your Last.fm API credentials")
    exit(1)

# Load config
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

# Check if lastfm section exists
if 'lastfm' not in config:
    print(f"Error: 'lastfm' section missing in {CONFIG_PATH}")
    exit(1)



def scrobble_track(artist, title, timestamp, session_key, api_key, api_secret, album=None, duration=None):
    parameters = {
        'method': 'track.scrobble',
        'api_key': api_key,
        'sk': session_key,
        'artist': artist,
        'track': title,
        'timestamp': str(int(timestamp))
    }
    
    if album:
        parameters['album'] = album
    if duration:
        parameters['duration'] = str(int(duration))
    
    signature = generate_api_sig(parameters, api_secret)
    parameters['api_sig'] = signature
    
    data = urllib.parse.urlencode(parameters).encode('utf-8')
    url = "http://ws.audioscrobbler.com/2.0/"
    
    try:
        request = urllib.request.Request(url, data=data)
        response = urllib.request.urlopen(request)
        return True
    except Exception as e:
        print(f"Scrobbling failed: {e}")
        return False

def play_from_ytmusic(search_query, limit=1, show_lyrics=False, enable_scrobble=False):
    console = Console()
    yt = ytmusicapi.YTMusic()
    results = yt.search(query=search_query, filter="songs", limit=limit)
    if results:
        for i in range(limit):
            total_duration = int(results[i].get('duration_seconds', 0))
            video_id = results[i]["videoId"]
            title = results[i]["title"]
            artists = results[i].get("artists", [])
            artist_names = ", ".join([artist.get("name", "") for artist in artists])
            album = results[i].get("album", {})
            album_name = album.get("name", "Unknown Album")
            year = results[i].get("year", "N/A")
            url = f"https://music.youtube.com/watch?v={video_id}"

            # Print track info using Rich
            console.print(Panel(f"""
[cyan]Title:[/cyan] [bold]{title}[/bold]
[cyan]Artist:[/cyan] {artist_names}
[cyan]Album:[/cyan] {album_name}
[cyan]Year:[/cyan] {year}
[cyan]Duration:[/cyan] {total_duration}s
""", title="Track Information"))

            # Try to get lyrics
            if show_lyrics:
                try:
                    watch_playlist = yt.get_watch_playlist(videoId=video_id)
                    if watch_playlist and 'lyrics' in watch_playlist:
                        lyrics_browse_id = watch_playlist['lyrics']
                        lyrics_data = yt.get_lyrics(lyrics_browse_id)
                        if lyrics_data and 'lyrics' in lyrics_data:
                            console.print(Panel(
                                Text(lyrics_data['lyrics'],
                                    style="italic gold1",
                                    justify="center"),
                                title="[bold green]Lyrics[/bold green]",
                                border_style="green"
                            ))
                        else:
                            console.print(Panel(
                                "[yellow]Lyrics not available for this song[/yellow]",
                                border_style="yellow"
                            ))
                    else:
                        console.print(Panel(
                            "[yellow]Lyrics not available for this song[/yellow]",
                            border_style="yellow"
                        ))
                except Exception as e:
                    console.print(Panel(
                        f"[red]Couldn't fetch lyrics: {e}[/red]",
                        border_style="red"
                    ))

            start_time = time.time()
            try:
                subprocess.run(f"yt-dlp '{url}' -f bestaudio -o - | mpv -", shell=True)
            except subprocess.CalledProcessError as e:
                console.print(Panel(
                    f"[red]Error playing from YouTube Music: {e}[/red]",
                    border_style="red"
                ))

            played_duration = int(time.time() - start_time)
            # Cap the percentage at 100%
            percentage = min(100, (played_duration / total_duration) * 100 if total_duration > 0 else 0)

            # Add the scrobbling check
            if enable_scrobble:
                try:
                    timestamp = int(time.time())
                    success = scrobble_track(
                        artist=artist_names,
                        title=title,
                        timestamp=timestamp,
                        session_key=SESSION_KEY,
                        api_key=API_KEY,
                        api_secret=API_SECRET,
                        album=album_name,
                        duration=total_duration
                    )
                    
                    if success:
                        console.print(Panel(
                            "[bold green]Successfully scrobbled to Last.fm![/bold green]",
                            border_style="green"
                        ))
                    else:
                        console.print(Panel(
                            "[bold red]Failed to scrobble to Last.fm[/bold red]",
                            border_style="red"
                        ))
                except Exception as e:
                    console.print(Panel(
                        f"[bold red]Scrobbling error: {str(e)}[/bold red]",
                        border_style="red"
                    ))
            else:
                console.print(Panel(
                    "[yellow]Scrobbling is disabled. Use -s or --scrobble to enable.[/yellow]",
                    border_style="yellow"
                ))
            console.print(Panel(
                f"[green]Played {played_duration}s of {total_duration}s ({percentage:.1f}%)[/green]",
                border_style="green"
            ))
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
    
    # Record start time
    start_time = time.time()
    
    try:
        subprocess.run(f"yt-dlp '{video_url}' -f bestaudio -o - | mpv -", shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error playing from YouTube: {e}")
    
    # Calculate and display duration
    end_time = time.time()
    duration = end_time - start_time
    print(f"Played for: {int(duration)} seconds")


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

def get_session_key(api_key, api_secret):
    # Step 1: Get a token
    parameters = {
        'api_key': api_key,
        'method': "auth.getToken"
    }
    
    # Generate API signature
    auth_token = get_token(parameters, api_secret)
    
    # Step 2: Get user authorization
    auth_url = f"http://www.last.fm/api/auth/?api_key={api_key}&token={auth_token}"
    webbrowser.open(auth_url)
    
    print("Please authorize the application in your browser.")
    input("Press Enter after authorization...")
    
    # Step 3: Get session key
    parameters = {
        'api_key': api_key,
        'method': "auth.getSession",
        'token': auth_token
    }
    
    # Generate API signature
    signature = generate_api_sig(parameters, api_secret)
    parameters['api_sig'] = signature
    
    # Make API request
    url = f"http://ws.audioscrobbler.com/2.0/?{urllib.parse.urlencode(parameters)}"
    try:
        response = urllib.request.urlopen(url).read()
        
        # Extract session key from response
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response)
        session_key = root.find('.//key').text
        return session_key
    except Exception as e:
        print(f"Error getting session key: {e}")
        return None

def get_token(parameters, api_secret):
    # Generate API signature
    signature = generate_api_sig(parameters, api_secret)
    parameters['api_sig'] = signature
    
    # Make API request
    url = f"http://ws.audioscrobbler.com/2.0/?{urllib.parse.urlencode(parameters)}"
    response = urllib.request.urlopen(url).read()
    
    # Extract token from response
    import xml.etree.ElementTree as ET
    root = ET.fromstring(response)
    return root.find('token').text

def decode(s):
    mid_index = len(s) // 2
    swapped = s[mid_index:] + s[:mid_index]
    reversed_s = swapped[::-1]
    decoded = ''.join(chr((ord(c) - ord('a') + 3) % 26 + ord('a')) if c.isalpha() else c for c in reversed_s.lower())
    return decoded
    
def generate_api_sig(parameters, api_secret):
    # Sort parameters alphabetically
    sorted_params = sorted(parameters.items())
    
    # Concatenate parameters
    signature = ''.join([f"{k}{v}" for k, v in sorted_params])
    
    # Add API secret
    signature += api_secret
    
    # Generate MD5 hash
    return hashlib.md5(signature.encode('utf-8')).hexdigest()

# Getting session key file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_KEY_PATH = os.path.join(SCRIPT_DIR, '.session_key')


API_KEY = decode(config['lastfm']['api_key'])
API_SECRET = decode(config['lastfm']['api_secret'])

# Try to get existing session key or create new one
try:
    with open(SESSION_KEY_PATH, 'r') as f:
        SESSION_KEY = f.read().strip()
except FileNotFoundError:
    SESSION_KEY = get_session_key(API_KEY, API_SECRET)
    if SESSION_KEY:
        with open(SESSION_KEY_PATH, 'w') as f:
            f.write(SESSION_KEY)
    else:
        print("Failed to get session key")
        exit(1)

if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Search and play music from YouTube Music or YouTube.")
    
    # Create a mutually exclusive group for search_query and input file
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("search_query", nargs="?", help="The search query for the track")
    input_group.add_argument("-i", "--infile", type=argparse.FileType('r'), 
                            help="Input file containing newline-separated tracks")
    
    parser.add_argument("-n", "--num-results", type=int, default=1, 
                        help="Number of results to play (default is 1)")
    parser.add_argument("-a", "--audio", action="store_true", 
                        help="First play from YouTube Music, then fallback to YouTube video if available")
    parser.add_argument("-v", "--video", action="store_true", 
                        help="Search and play directly from YouTube video")
    parser.add_argument("-p", "--playlist", action="store_true", 
                        help="Play all videos from a YouTube playlist")
    parser.add_argument("-b", "--album", action="store_true", 
                        help="Search and play album from YouTube Music")
    parser.add_argument("-l", "--lyrics", action="store_true", 
                        help="Show lyrics if available")
    parser.add_argument("-s", "--scrobble", action="store_true",
                   help="Enable scrobbling to Last.fm")

    # Parse the arguments
    args = parser.parse_args()
    num_results = args.num_results
    playlist_url = None

    # Handle input file or search query
    if args.infile:
        # Read tracks from file
        tracks = [line.strip() for line in args.infile if line.strip()]
        args.infile.close()
        
        # Process each track
        for track in tracks:
            print(f"\nProcessing track: {track}")
            if args.video:
                search_from_youtube(track)
            elif args.audio:
                # Try playing from YouTube Music first, then fallback to YouTube
                if not play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble):
                    print("Falling back to YouTube video...")
                    search_from_youtube(track)
            else:
                # Default: play only from YouTube Music
                play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble)
    else:
        # Process single search query
        search_query = args.search_query
        
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
            play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble)
            print("Falling back to YouTube video...")
            search_from_youtube(args.search_query)
        else:
            # Default: play only from YouTube Music
            play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble)
