import requests
import random
import time
import argparse
import sys
import os
import json
import subprocess

class MusicBrainzAPI:
    def __init__(self, quiet=False):
        self.BASE_URL = "https://musicbrainz.org/ws/2/recording"
        # MusicBrainz requires a descriptive User-Agent
        self.headers = {"User-Agent": "RandomUsikPlayer/1.0 ( test@example.com )"}
        # Respecting MusicBrainz API rate limiting (1 request per second)
        self.DELAY = 1.2 
        self.quiet = quiet

    def _log(self, msg):
        """Only print if we are not safely logging in the background."""
        if not self.quiet:
            print(msg)

    def _make_request(self, params):
        """Helper method to make requests and handle rate limiting."""
        time.sleep(self.DELAY)
        try:
            response = requests.get(self.BASE_URL, headers=self.headers, params=params, timeout=10)
        except requests.exceptions.RequestException:
            return None
            
        if response.status_code != 200:
            self._log(f"Error connecting to MusicBrainz: HTTP {response.status_code}")
            return None
            
        return response.json()

    def get_random_song(self, min_year):
        """Gets a random song from min_year to 2026."""
        # 1. Pick a random year (from min_year to roughly now)
        year = random.randint(min_year, 2026)
        query = f"date:{year}"
        
        self._log(f"[*] Selected random year: {year}")
        self._log("[*] Asking MusicBrainz how many tracks exist for this year...")
        
        # 2. Ask MusicBrainz for the total count of recordings in that year
        params = {
            "query": query,
            "limit": 1,
            "fmt": "json"
        }
        
        data = self._make_request(params)
        if not data:
            return None

        total_tracks = data.get("count", 0)
        
        if total_tracks == 0:
            self._log(f"No tracks found for the year {year}. Try running the script again.")
            return None
            
        self._log(f"[*] MusicBrainz has {total_tracks:,} tracks recorded in {year}.")
        
        # 3. Pick a random track number
        max_offset = min(total_tracks - 1, 9999)
        random_offset = random.randint(0, max_offset)
        
        self._log(f"[*] Fetching track number {random_offset + 1}...")
        
        # 4. Fetch that exact random track
        params = {
            "query": query,
            "limit": 1,
            "offset": random_offset,
            "fmt": "json"
        }
        
        track_data = self._make_request(params)
        if not track_data or not track_data.get("recordings"):
            return None
            
        recording = track_data["recordings"][0]
        
        # Extract metadata
        title = recording.get("title", "Unknown Title")
        
        artist_credit = recording.get("artist-credit", [])
        if artist_credit:
            artist = artist_credit[0].get("name", "Unknown Artist")
        else:
            artist = "Unknown Artist"
            
        releases = recording.get("releases", [])
        album = releases[0].get("title", "Unknown Album") if releases else "Unknown/Single"
            
        return {
            "artist": artist,
            "title": title,
            "album": album,
            "year": year
        }

def main():
    parser = argparse.ArgumentParser(description='Get a truly random song from MusicBrainz')
    parser.add_argument('-d', '--detail', action='store_true', help='Show detailed song information')
    parser.add_argument('-y', '--year', type=int, default=1920, help='Lower limit for the random year (e.g. 1990)')
    # Hidden argument exclusively used for spawning background workers
    parser.add_argument('--prefetch', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".song_cache.json")

    # Ensure the minimum year doesn't exceed 2024
    min_year = min(args.year, 2024)

    # ------ BACKGROUND PREFETCH MODE ------
    if args.prefetch:
        # We run silently in the background
        mb = MusicBrainzAPI(quiet=True)
        song = mb.get_random_song(min_year)
        if song:
            # Overwrite the cache file with the new random song
            # Add exactly what was requested for the next retrieval
            song['_requested_min_year'] = min_year
            with open(CACHE_FILE, "w") as f:
                json.dump(song, f)
        sys.exit(0)

    # ------ NORMAL FOREGROUND MODE ------
    song = None
    cache_valid = False
    
    # Attempt to load the pre-fetched song from the previous run
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                song = json.load(f)
                
            # It's only valid if the cache meets our newly requested criteria
            if song.get('_requested_min_year', 1920) >= min_year:
                cache_valid = True
            elif song.get('year', 0) >= min_year:
                # Cache was fetched with a lower requirement, but happens to still satisfy this req
                cache_valid = True
            else:
                cache_valid = False
                song = None
        except Exception:
            pass

    # If cache is missing (first run) or invalid for our requested year
    if not cache_valid:
        print(f"🎵 Fetching a fresh random song from {min_year} onwards...")
        mb = MusicBrainzAPI(quiet=False)
        song = mb.get_random_song(min_year)
        
        if not song:
            print("\nFailed to fetch a random song.")
            sys.exit(1)

    # Print the song results practically instantaneously
    if args.detail:
        print("\n" + "="*40)
        print(f"🎵 RANDOM SONG DISCOVERED 🎵")
        print("="*40)
        print(f"Artist : {song['artist']}")
        print(f"Title  : {song['title']}")
        print(f"Album  : {song['album']}")
        print(f"Year   : {song['year']}")
        print("="*40)
    else:
        print(f"\nResult: {song['artist']} - {song['title']} ({song['year']})")

    # Command the script to independently launch itself in the background
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--prefetch", "-y", str(min_year)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProcess canceled by user.")
        sys.exit(0)
