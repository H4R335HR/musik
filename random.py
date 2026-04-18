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

    def get_random_song(self, min_year, genre=None, year_explicit=False, keyword=None):
        """Gets a random song, with optional genre, year, and keyword filters.

        - Year mode   (-y only):           query = date:<random_year>
        - Genre mode  (-g only):           query = tag:<genre>
        - Keyword mode (-k only):          query = recording:<keyword>
        - Any combination works, e.g.:     query = tag:<genre> AND recording:<keyword> AND date:[y TO 2024]
        """
        query_parts = []

        if genre:
            query_parts.append(f"tag:{genre}")
            self._log(f"[*] Genre filter: '{genre}'")

        if keyword:
            query_parts.append(f"recording:{keyword}")
            self._log(f"[*] Keyword filter: '{keyword}'")

        if year_explicit:
            query_parts.append(f"date:[{min_year} TO 2024]")
            self._log(f"[*] Year filter: {min_year} to 2024")

        if not query_parts:
            # ------ YEAR-PRIMARY MODE (default, no filters given) ------
            year = random.randint(min_year, 2024)
            query_parts.append(f"date:{year}")
            self._log(f"[*] Selected random year: {year}")

        query = " AND ".join(query_parts)
        self._log("[*] Asking MusicBrainz how many tracks exist for this query...")

        # 1. Get the total count of matching recordings
        params = {"query": query, "limit": 1, "fmt": "json"}
        data = self._make_request(params)
        if not data:
            return None

        total_tracks = data.get("count", 0)
        if total_tracks == 0:
            self._log("No tracks found for this query. Try running the script again.")
            return None

        self._log(f"[*] MusicBrainz has {total_tracks:,} matching tracks.")

        # 2. Pick a random offset and fetch that track
        max_offset = min(total_tracks - 1, 9999)
        random_offset = random.randint(0, max_offset)
        self._log(f"[*] Fetching track number {random_offset + 1}...")

        params = {"query": query, "limit": 1, "offset": random_offset, "fmt": "json"}
        track_data = self._make_request(params)
        if not track_data or not track_data.get("recordings"):
            return None

        recording = track_data["recordings"][0]

        # 3. Extract metadata
        title = recording.get("title", "Unknown Title")

        artist_credit = recording.get("artist-credit", [])
        artist = artist_credit[0].get("name", "Unknown Artist") if artist_credit else "Unknown Artist"

        releases = recording.get("releases", [])
        album = releases[0].get("title", "Unknown Album") if releases else "Unknown/Single"

        # Extract actual release year from recording metadata
        # In default year-primary mode, use the randomly selected query year (more reliable)
        release_year = recording.get("first-release-date", "") or ""
        if not release_year and releases:
            release_year = releases[0].get("date", "") or ""
        if not genre and not keyword and not year_explicit:
            result_year = year  # default mode: use the random year we searched for
        else:
            result_year = int(release_year[:4]) if len(release_year) >= 4 and release_year[:4].isdigit() else "Unknown"

        return {
            "artist": artist,
            "title": title,
            "album": album,
            "year": result_year,
            "genre": genre or "",
            "keyword": keyword or ""
        }

def main():
    parser = argparse.ArgumentParser(description='Get a truly random song from MusicBrainz')
    parser.add_argument('-d', '--detail', action='store_true', help='Show detailed song information')
    parser.add_argument('-y', '--year', type=int, default=None, help='Lower limit for the random year (e.g. 1990)')
    parser.add_argument('-g', '--genre', type=str, default=None, help='Filter by genre tag (e.g. rock, jazz, pop)')
    parser.add_argument('-k', '--keyword', type=str, default=None, help='Filter by keyword in track title (e.g. dream, love, night)')
    # Hidden argument exclusively used for spawning background workers
    parser.add_argument('--prefetch', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".song_cache.json")

    # Detect whether -y was explicitly passed
    year_explicit = args.year is not None
    min_year = min(args.year if args.year is not None else 1920, 2024)

    genre = args.genre.lower().strip() if args.genre else None
    keyword = args.keyword.lower().strip() if args.keyword else None

    # ------ BACKGROUND PREFETCH MODE ------
    if args.prefetch:
        # We run silently in the background
        mb = MusicBrainzAPI(quiet=True)
        song = mb.get_random_song(min_year, genre, year_explicit, keyword)
        if song:
            # Overwrite the cache file with the new random song
            # Add exactly what was requested for the next retrieval
            song['_requested_min_year'] = min_year if year_explicit else 0
            song['_requested_genre'] = genre or ""
            song['_requested_keyword'] = keyword or ""
            song['_year_explicit'] = year_explicit
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

            # All filters must match exactly
            cached_genre   = (song.get('_requested_genre',   "") or "").lower()
            cached_keyword = (song.get('_requested_keyword', "") or "").lower()
            genre_ok   = cached_genre   == (genre   or "").lower()
            keyword_ok = cached_keyword == (keyword or "").lower()

            # Year check only matters when -y was explicitly requested
            if year_explicit:
                year_ok = (
                    song.get('_requested_min_year', 0) >= min_year
                    or (isinstance(song.get('year'), int) and song.get('year', 0) >= min_year)
                )
            else:
                year_ok = True

            if genre_ok and keyword_ok and year_ok:
                cache_valid = True
            else:
                cache_valid = False
                song = None
        except Exception:
            pass

    # If cache is missing (first run) or invalid for our requested criteria
    if not cache_valid:
        label_parts = []
        if keyword:
            label_parts.append(f"containing '{keyword}'")
        if genre:
            label_parts.append(f"in genre '{genre}'")
        if year_explicit:
            label_parts.append(f"from {min_year} onwards")
        label = " ".join(label_parts) if label_parts else f"from {min_year} onwards"
        print(f"🎵 Fetching a fresh random song {label}...")
        mb = MusicBrainzAPI(quiet=False)
        song = mb.get_random_song(min_year, genre, year_explicit, keyword)

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
        if song.get('genre'):
            print(f"Genre  : {song['genre']}")
        if song.get('keyword'):
            print(f"Keyword: {song['keyword']}")
        print("="*40)
    else:
        tags = " ".join(f"[{song[k]}]" for k in ('genre', 'keyword') if song.get(k))
        suffix = f" {tags}" if tags else ""
        print(f"\nResult: {song['artist']} - {song['title']} ({song['year']}){suffix}")

    # Command the script to independently launch itself in the background
    prefetch_cmd = [sys.executable, os.path.abspath(__file__), "--prefetch"]
    if year_explicit:
        prefetch_cmd += ["-y", str(min_year)]
    if genre:
        prefetch_cmd += ["-g", genre]
    if keyword:
        prefetch_cmd += ["-k", keyword]
    subprocess.Popen(
        prefetch_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProcess canceled by user.")
        sys.exit(0)
