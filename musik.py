import sys
import time
import ytmusicapi
import subprocess
import argparse
import yt_dlp
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

def play_from_ytmusic(search_query, limit=1, show_lyrics=False):
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
            percentage = (played_duration / total_duration) * 100 if total_duration > 0 else 0
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

if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Search and play music from YouTube Music or YouTube.")
    parser.add_argument("search_query", help="The search query for the track")
    parser.add_argument("-n", "--num-results", type=int, default=1, help="Number of results to play (default is 1)")
    parser.add_argument("-a", "--audio", action="store_true", help="First play from YouTube Music, then fallback to YouTube video if available")
    parser.add_argument("-v", "--video", action="store_true", help="Search and play directly from YouTube video")
    parser.add_argument("-p", "--playlist", action="store_true", help="Play all videos from a YouTube playlist")
    parser.add_argument("-b", "--album", action="store_true", help="Search and play album from YouTube Music")
    parser.add_argument("-l", "--lyrics", action="store_true", help="Show lyrics if available")

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
        play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics)
        print("Falling back to YouTube video...")
        search_from_youtube(args.search_query)
    else:
        # Default: play only from YouTube Music
        play_from_ytmusic(args.search_query, limit=num_results, show_lyrics=args.lyrics)
