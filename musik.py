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
import xml.etree.ElementTree as ET
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Global debug flag (will be set by command line args)
DEBUG = False

def debug_print(*args, **kwargs):
    """Print debug information only when DEBUG mode is enabled"""
    if DEBUG:
        print("DEBUG:", *args, **kwargs)

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.ini')

# Config file will be loaded only when needed for scrobbling


def format_count(n):
    """Format a large number into a human-readable string (e.g. 1.2M, 340K)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "N/A"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def get_yt_view_count(yt, video_id):
    """Fetch YouTube view count via ytmusicapi's get_song()."""
    debug_print(f"Fetching YT view count for videoId: {video_id}")
    try:
        song_details = yt.get_song(video_id)
        view_count = song_details.get('videoDetails', {}).get('viewCount')
        debug_print(f"YT view count: {view_count}")
        return int(view_count) if view_count else None
    except Exception as e:
        debug_print(f"Failed to get YT view count: {e}")
        return None


def get_lastfm_track_info(artist, track, api_key):
    """Fetch track listeners and playcount from Last.fm's track.getInfo endpoint."""
    debug_print(f"Fetching Last.fm stats for: {track} by {artist}")
    params = {
        'method': 'track.getInfo',
        'api_key': api_key,
        'artist': artist,
        'track': track,
        'format': 'json',
    }
    url = f"http://ws.audioscrobbler.com/2.0/?{urllib.parse.urlencode(params)}"
    try:
        response = urllib.request.urlopen(url, timeout=5).read()
        import json
        data = json.loads(response)
        track_data = data.get('track', {})
        listeners = track_data.get('listeners')
        playcount = track_data.get('playcount')
        debug_print(f"Last.fm listeners: {listeners}, playcount: {playcount}")
        return {
            'listeners': int(listeners) if listeners else None,
            'playcount': int(playcount) if playcount else None,
        }
    except Exception as e:
        debug_print(f"Failed to get Last.fm track info: {e}")
        return {'listeners': None, 'playcount': None}


def scrobble_track(artist, title, timestamp, session_key, api_key, api_secret, album=None, duration=None):
    debug_print(f"Scrobbling track: {title} by {artist}")
    debug_print(f"  Album: {album}, Duration: {duration}s, Timestamp: {timestamp}")
    
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
    debug_print(f"Searching YouTube Music for: '{search_query}'")
    debug_print(f"  Limit: {limit}, Show lyrics: {show_lyrics}, Scrobble: {enable_scrobble}")
    
    console = Console()
    yt = ytmusicapi.YTMusic()
    
    debug_print("Executing YouTube Music search...")
    results = yt.search(query=search_query, filter="songs", limit=limit)
    debug_print(f"Found {len(results)} result(s)")
    if results:
        for i in range(limit):
            total_duration = int(results[i].get('duration_seconds', 0))
            video_id = results[i]["videoId"]
            title = results[i]["title"]
            artists = results[i].get("artists", [])
            artist_names = ", ".join([artist.get("name", "") for artist in artists])
            album = results[i].get("album", {})
            album_name = album.get("name", "Unknown Album")
            #year = results[i].get("year", "N/A")
            if album.get("id"):  # If no album_year was passed and we have an album ID
                try:
                    album_details = yt.get_album(album["id"])
                    year = album_details.get("year", "N/A")
                except:
                    year = "N/A"
            else:
                year = results[i].get("year", "N/A")

            url = f"https://music.youtube.com/watch?v={video_id}"

            # --- Popularity stats ---
            yt_views = get_yt_view_count(yt, video_id)

            lastfm_info = {'listeners': None, 'playcount': None}
            if enable_scrobble:
                global API_KEY, API_SECRET, SESSION_KEY
                # Ensure Last.fm credentials are ready before querying
                if API_KEY is None or API_SECRET is None or SESSION_KEY is None:
                    debug_print("Last.fm credentials not initialized, initializing now (for stats)")
                    if not init_lastfm():
                        console.print("[yellow]Last.fm init failed — skipping Last.fm stats[/yellow]")
                    # After init_lastfm(), API_KEY should be set even if SESSION_KEY failed
                if API_KEY:
                    lastfm_info = get_lastfm_track_info(artist_names, title, API_KEY)

            # Build the popularity line(s)
            popularity_lines = ""
            if yt_views is not None:
                popularity_lines += f"[cyan]YT Views:[/cyan] {format_count(yt_views)}\n"
            if lastfm_info['listeners'] is not None:
                popularity_lines += (
                    f"[cyan]Last.fm:[/cyan] {format_count(lastfm_info['listeners'])} listeners · "
                    f"{format_count(lastfm_info['playcount'])} plays\n"
                )

            # Print track info using Rich
            console.print(Panel(f"""
[cyan]Title:[/cyan] [bold]{title}[/bold]
[cyan]Artist:[/cyan] {artist_names}
[cyan]Album:[/cyan] {album_name}
[cyan]Year:[/cyan] {year}
[cyan]Duration:[/cyan] {total_duration}s
{popularity_lines}""", title="♫ Track Information ♫"))

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
                subprocess.run(f'yt-dlp "{url}" -f bestaudio -o - | mpv -', shell=True)
            except subprocess.CalledProcessError as e:
                console.print(Panel(
                    f"[red]Error playing from YouTube Music: {e}[/red]",
                    border_style="red"
                ))

            played_duration = int(time.time() - start_time)
            # Cap the percentage at 100%
            percentage = min(100, (played_duration / total_duration) * 100 if total_duration > 0 else 0)

            # Add the scrobbling check
            if enable_scrobble and (percentage > 50 or played_duration > 240):
                # Check if Last.fm credentials are initialized
                if API_KEY is None or API_SECRET is None or SESSION_KEY is None:
                    debug_print("Last.fm credentials not initialized, initializing now")
                    if not init_lastfm():
                        console.print(Panel(
                            "[bold red]Failed to initialize Last.fm credentials. Scrobbling disabled.[/bold red]",
                            border_style="red"
                        ))
                        return False
                
                try:
                    debug_print(f"Attempting to scrobble: {title} by {artist_names}")
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
                debug_print(f"Skipping scrobble: enable_scrobble={enable_scrobble}, percentage={percentage}%, played_duration={played_duration}s")
                if not enable_scrobble:
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
    debug_print(f"Executing YouTube search for: '{search_query}'")

    debug_print("Running yt-dlp to get video title and ID...")
    result = subprocess.check_output(f'yt-dlp --get-title --get-id "ytsearch1:{search_query}"', shell=True)
    result = result.decode('utf-8').splitlines()
    title = result[0]  # Extract the title
    video_id = result[1]  # Extract the video ID
    play_from_youtube(video_id, title)

def play_from_youtube(video_url, title):
    """Play a video from YouTube using the provided URL and title."""
    print(f"Now playing: \033[1m{title}\033[0m")
    debug_print(f"Playing YouTube video: {title}")
    debug_print(f"Video URL: {video_url}")
    
    # Record start time
    start_time = time.time()
    debug_print(f"Starting playback at: {time.strftime('%H:%M:%S', time.localtime(start_time))}")
    
    try:
        debug_print("Executing yt-dlp to stream audio to mpv...")
        subprocess.run(f'yt-dlp "{video_url}" -f bestaudio -o - | mpv -', shell=True)
    except subprocess.CalledProcessError as e:
        print(f"Error playing from YouTube: {e}")
    
    # Calculate and display duration
    end_time = time.time()
    duration = end_time - start_time
    print(f"Played for: {int(duration)} seconds")


def play_album_from_ytmusic(search_query, show_lyrics=False, enable_scrobble=False, offset=0):
    debug_print(f"Searching for album: '{search_query}'")
    debug_print(f"  Show lyrics: {show_lyrics}, Scrobble: {enable_scrobble}, Offset: {offset}")
    
    console = Console()
    yt = ytmusicapi.YTMusic()
    # Search for the album
    debug_print("Executing YouTube Music album search...")
    results = yt.search(query=search_query, filter="albums", limit=1)
    debug_print(f"Found {len(results)} album result(s)")
    
    if results:
        album = results[0]
        album_id = album["browseId"]
        
        # Get full album details including track list
        album_details = yt.get_album(album_id)
        
        console.print(Panel(f"""
        [bold magenta]╔══ ALBUM DETAILS ══╗[/bold magenta]
        
        [gold1]Album:[/gold1] [bold white]{album_details['title']}[/bold white]
        [gold1]Artist:[/gold1] [bold white]{album_details['artists'][0]['name']}[/bold white]
        [gold1]Year:[/gold1] [bold white]{album_details.get('year', 'N/A')}[/bold white]
        [gold1]Total Tracks:[/gold1] [bold white]{len(album_details['tracks'])}[/bold white]
        
        [bold magenta]╚═══════════════════╝[/bold magenta]
        """, 
        title="[bold magenta]♫ Now Playing Album ♫[/bold magenta]",
        border_style="magenta",
        padding=(0, 2)))

        # Add a separator between album info and tracks
        console.print("[magenta]═" * 50 + "[/magenta]\n")
        total_tracks = len(album_details['tracks'])
        if offset >= total_tracks:
            console.print(f"[red]Offset {offset} is larger than the number of tracks ({total_tracks})[/red]")
            return
        
        if offset > 0:
            console.print(f"[yellow]Starting from track {offset + 1} of {total_tracks}[/yellow]")
        # Play each track starting from offset
        for track in album_details['tracks'][offset:]:
            search_query = f"{track['title']} {track['artists'][0]['name']}"
            play_from_ytmusic(search_query, limit=1,
                            show_lyrics=show_lyrics,
                            enable_scrobble=enable_scrobble)
    else:
        print("Album not found on YouTube Music.")

def extract_video_urls_from_playlist(playlist_url):
    """Extract video URLs and titles from a YouTube playlist URL."""
    debug_print(f"Extracting videos from playlist: {playlist_url}")
    
    ydl_opts = {'quiet': True, 'extract_flat': True}
    debug_print("YDL options:", ydl_opts)
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        debug_print("Fetching playlist information...")
        playlist_info = ydl.extract_info(playlist_url, download=False)
        debug_print(f"Found {len(playlist_info.get('entries', []))} videos in playlist")
        video_info = [
            {
                'url': f"https://www.youtube.com/watch?v={entry['id']}",
                'title': entry['title']
            }
            for entry in playlist_info['entries']
        ]
    
    return video_info

def get_session_key(api_key, api_secret):
    debug_print("Getting Last.fm session key")
    debug_print("Step 1: Getting authentication token")
    
    # Step 1: Get a token
    parameters = {
        'api_key': api_key,
        'method': "auth.getToken"
    }
    
    # Generate API signature
    debug_print("Requesting auth token from Last.fm API...")
    auth_token = get_token(parameters, api_secret)
    debug_print(f"Received auth token: {auth_token[:4]}...{auth_token[-4:]}")
    
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

# Session key path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_KEY_PATH = os.path.join(SCRIPT_DIR, '.session_key')

# Last.fm credentials - will be initialized only when needed
API_KEY = None
API_SECRET = None
SESSION_KEY = None

def init_lastfm():
    """Initialize Last.fm credentials for scrobbling"""
    global API_KEY, API_SECRET, SESSION_KEY
    
    debug_print("Initializing Last.fm credentials for scrobbling")
    
    # Check if config file exists
    debug_print(f"Looking for config file at: {CONFIG_PATH}")
    if not os.path.exists(CONFIG_PATH):
        print(f"Config file not found at {CONFIG_PATH}. Scrobbling will be disabled.")
        debug_print("Config file not found, disabling scrobbling")
        return False
        
    # Load config
    debug_print("Config file found, loading contents")
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    debug_print(f"Config sections: {list(config.sections())}")
    
    # Check if lastfm section exists
    if 'lastfm' not in config:
        print(f"Error: 'lastfm' section missing in {CONFIG_PATH}. Scrobbling will be disabled.")
        debug_print("'lastfm' section missing in config, disabling scrobbling")
        return False
        
    debug_print("Config loaded successfully")
    
    # Decode API key and secret
    API_KEY = decode(config['lastfm']['api_key'])
    API_SECRET = decode(config['lastfm']['api_secret'])
    
    # Try to get existing session key or create new one
    debug_print(f"Checking for existing session key at: {SESSION_KEY_PATH}")
    try:
        with open(SESSION_KEY_PATH, 'r') as f:
            SESSION_KEY = f.read().strip()
            debug_print("Loaded existing session key")
    except FileNotFoundError:
        debug_print("No session key found, getting a new one")
        SESSION_KEY = get_session_key(API_KEY, API_SECRET)
        if SESSION_KEY:
            debug_print("Saving new session key")
            with open(SESSION_KEY_PATH, 'w') as f:
                f.write(SESSION_KEY)
        else:
            debug_print("Failed to get session key from Last.fm")
            print("Failed to get session key. Scrobbling will be disabled.")
            return False
    
    debug_print("Last.fm credentials initialized successfully")
    return True

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
    parser.add_argument("-o", "--offset", type=int, default=0,
                    help="Start playing from this track number (0-based index)")
    parser.add_argument("-d", "--debug", action="store_true",
                    help="Enable debug mode to show detailed execution information")

    # Parse the arguments
    args = parser.parse_args()
    
    # Set global debug flag
    DEBUG = args.debug
    
    debug_print("Command line arguments:", args)
    debug_print(f"Debug mode: {'Enabled' if DEBUG else 'Disabled'}")
    
    num_results = args.num_results
    playlist_url = None

    # Handle input file or search query
    if args.infile:
        debug_print(f"Reading tracks from file: {args.infile.name}")
        # Read tracks from file
        tracks = [line.strip() for line in args.infile if line.strip()]
        args.infile.close()
        debug_print(f"Read {len(tracks)} tracks from input file")
        
        # Check offset validity
        if args.offset >= len(tracks):
            print(f"Offset {args.offset} is larger than the number of tracks ({len(tracks)})")
            debug_print(f"Invalid offset value: {args.offset}, max allowed: {len(tracks)-1}")
            exit(1)
        
        if args.offset > 0:
            print(f"Starting from track {args.offset + 1} of {len(tracks)}")
        
        console = Console()
        # Process each track starting from offset
        for track in tracks[args.offset:]:
            console.print(f"\n[bold yellow]▶ INPUT RECEIVED:[/bold yellow] [bold white]{track}[/bold white]")
            if args.video:
                search_from_youtube(track)
            elif args.audio:
                if not play_from_ytmusic(track, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble):
                    print("Falling back to YouTube video...")
                    search_from_youtube(track)
            else:
                play_from_ytmusic(track, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble)
    else:
        # Process single search query
        search_query = args.search_query
        debug_print(f"Processing single search query: '{search_query}'")
        
        # Determine the source based on provided options
        if args.album:
            debug_print("Album mode selected")
            print(f"Searching for album: {search_query}")
            play_album_from_ytmusic(search_query,
                                show_lyrics=args.lyrics,
                                enable_scrobble=args.scrobble,
                                offset=args.offset)
        if args.playlist:
            debug_print("Playlist mode selected")
            if not playlist_url:
                playlist_url = search_query
                debug_print(f"Using search query as playlist URL: {playlist_url}")
            print(f"Extracting videos from playlist: {playlist_url}")
            video_links = extract_video_urls_from_playlist(playlist_url)
            debug_print(f"Extracted {len(video_links)} videos from playlist")
            
            # Check offset validity
            if args.offset >= len(video_links):
                print(f"Offset {args.offset} is larger than the number of videos ({len(video_links)})")
                debug_print(f"Invalid offset value: {args.offset}, max allowed: {len(video_links)-1}")
                exit(1)
            
            if args.offset > 0:
                print(f"Starting from video {args.offset + 1} of {len(video_links)}")
            
            # Play each video starting from offset
            for video_info in video_links[args.offset:]:
                play_from_youtube(video_info['url'], video_info['title'])

        if args.video:
            debug_print("Video mode selected, searching directly on YouTube")
            search_from_youtube(args.search_query)
        elif args.audio:
            debug_print("Audio mode selected, trying YouTube Music with fallback to YouTube video")
            # Try playing from YouTube Music first, then fallback to YouTube if available
            play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble)
            debug_print("YouTube Music playback completed, falling back to YouTube video")
            print("Falling back to YouTube video...")
            search_from_youtube(args.search_query)
        else:
            debug_print("Default mode: YouTube Music only")
            # Default: play only from YouTube Music
            play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics, enable_scrobble=args.scrobble)
