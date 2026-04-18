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
        # Base URL for the MusicBrainz v2 web service. Endpoint appended per-call.
        self.BASE = "https://musicbrainz.org/ws/2"
        # MusicBrainz requires a descriptive User-Agent with REAL contact info.
        # TODO: replace the email/URL below with your real contact — MB throttles
        # placeholder/"anonymous" UAs more aggressively than identified ones.
        self.headers = {"User-Agent": "RandomUsikPlayer/1.0 ( test@example.com )"}
        # Respecting MusicBrainz API rate limiting (1 request per second per IP).
        self.DELAY = 1.2
        self.quiet = quiet

    def _log(self, msg):
        """Only print if we are not safely logging in the background."""
        if not self.quiet:
            print(msg)

    def _make_request(self, endpoint, params):
        """GET a MusicBrainz endpoint with rate limiting and 503 backoff."""
        url = f"{self.BASE}/{endpoint}"
        time.sleep(self.DELAY)
        for attempt in range(3):
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
            except requests.exceptions.RequestException as e:
                self._log(f"Network error: {e}")
                return None

            if response.status_code == 503:
                # Rate limited or server busy — respect Retry-After if present.
                wait = 3
                try:
                    wait = int(response.headers.get("Retry-After", "3"))
                except ValueError:
                    pass
                self._log(f"[!] Throttled (503). Backing off {wait}s...")
                time.sleep(wait)
                continue

            if response.status_code != 200:
                self._log(f"Error connecting to MusicBrainz: HTTP {response.status_code}")
                return None

            return response.json()

        self._log("[!] Giving up after repeated 503s.")
        return None

    # ------------------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ------------------------------------------------------------------
    def get_random_song(self, min_year, genre=None, year_explicit=False,
                        keyword=None, artist_search=None,
                        any_year=False, any_type=False):
        """Dispatcher.

        When a genre filter is requested we pivot through release-group search
        because recording-level tags in MusicBrainz are very sparse — most genre
        tagging happens at the artist / release-group level. Without a genre
        filter the existing recording search path works fine.

        Flags:
        - any_year:  when -y is set, use `date:` (matches ANY release year,
                     including reissues) instead of the stricter `firstreleasedate:`
                     (which only matches songs originally released that year).
        - any_type:  when -g is set, DON'T restrict to primarytype:album — allow
                     singles, EPs, compilations, etc. in the genre search.
        """
        if genre:
            return self._random_via_release_group(
                genre, min_year, year_explicit, keyword, artist_search, any_type
            )
        return self._random_via_recording(
            min_year, year_explicit, keyword, artist_search, any_year
        )

    # ------------------------------------------------------------------
    # PATH 1: direct recording search (no genre filter)
    # ------------------------------------------------------------------
    def _random_via_recording(self, min_year, year_explicit, keyword,
                              artist_search, any_year):
        query_parts = []
        selected_year = None

        if keyword:
            query_parts.append(f"recording:{keyword}")
            self._log(f"[*] Keyword filter: '{keyword}'")

        if artist_search:
            query_parts.append(f"artist:\"{artist_search}\"")
            self._log(f"[*] Artist filter: '{artist_search}'")

        if year_explicit:
            # Default: `firstreleasedate` — songs ORIGINALLY from min_year onwards.
            # --any-year: `date` — old behavior, matches any release year (incl. reissues).
            year_field = "date" if any_year else "firstreleasedate"
            query_parts.append(f"{year_field}:[{min_year} TO 2024]")
            mode_label = "any release year" if any_year else "original release year"
            self._log(f"[*] Year filter: {min_year} to 2024 ({mode_label})")

        if not query_parts:
            # Default mode: pick a random year and search by it.
            # Kept on `date:` (old behavior) so random-year mode gets broad results.
            selected_year = random.randint(min_year, 2024)
            query_parts.append(f"date:{selected_year}")
            self._log(f"[*] Selected random year: {selected_year}")

        query = " AND ".join(query_parts)
        self._log("[*] Asking MusicBrainz how many tracks exist for this query...")

        # 1. Count
        data = self._make_request("recording",
                                  {"query": query, "limit": 1, "fmt": "json"})
        if not data:
            return None
        total_tracks = data.get("count", 0)
        if total_tracks == 0:
            self._log("No tracks found for this query. Try running the script again.")
            return None
        self._log(f"[*] MusicBrainz has {total_tracks:,} matching tracks.")

        # 2. Fetch one at a random offset
        max_offset = min(total_tracks - 1, 9999)
        random_offset = random.randint(0, max_offset)
        self._log(f"[*] Fetching track number {random_offset + 1}...")

        track_data = self._make_request("recording", {
            "query": query, "limit": 1, "offset": random_offset, "fmt": "json"
        })
        if not track_data or not track_data.get("recordings"):
            return None

        recording = track_data["recordings"][0]

        # 3. Extract metadata
        title = recording.get("title", "Unknown Title")
        artist_credit = recording.get("artist-credit", [])
        artist = artist_credit[0].get("name", "Unknown Artist") if artist_credit else "Unknown Artist"
        releases = recording.get("releases", [])
        album = releases[0].get("title", "Unknown Album") if releases else "Unknown/Single"

        release_year = recording.get("first-release-date", "") or ""
        if not release_year and releases:
            release_year = releases[0].get("date", "") or ""

        if selected_year is not None:
            result_year = selected_year
        else:
            result_year = (
                int(release_year[:4])
                if len(release_year) >= 4 and release_year[:4].isdigit()
                else "Unknown"
            )

        return {
            "artist": artist,
            "title": title,
            "album": album,
            "year": result_year,
            "genre": "",
            "keyword": keyword or "",
            "artist_search": artist_search or "",
        }

    # ------------------------------------------------------------------
    # PATH 2: release-group pivot (genre filter present)
    # ------------------------------------------------------------------
    def _random_via_release_group(self, genre, min_year, year_explicit,
                                   keyword, artist_search, any_type):
        """Search release-groups by tag, pick one at random, then pull a recording from it.

        Recording-level tags are sparse in MusicBrainz; release-group tags are
        densely applied, giving dramatically better coverage for genre queries.

        By default we restrict to `primarytype:album` (full-length albums, which
        also includes compilation albums). Pass any_type=True to lift the
        restriction so singles, EPs and other release types are included.

        Note: the year filter here always uses `firstreleasedate` — the release-
        group index has no clean equivalent of recording's broad `date:` field.
        """
        rg_query_parts = [f"tag:{genre}"]
        if not any_type:
            # Albums only. Compilations (primarytype=album + secondarytype=compilation)
            # are still included — add `AND -secondarytype:compilation` here if you
            # want to also exclude those.
            rg_query_parts.append("primarytype:album")
        if artist_search:
            rg_query_parts.append(f"artist:\"{artist_search}\"")
        if year_explicit:
            rg_query_parts.append(f"firstreleasedate:[{min_year} TO 2024]")

        rg_query = " AND ".join(rg_query_parts)
        scope = "all release types" if any_type else "albums only"
        self._log(f"[*] Genre filter: '{genre}' ({scope}, searching release-groups)")
        if keyword:
            self._log(f"[*] Keyword filter (applied client-side): '{keyword}'")
        if artist_search:
            self._log(f"[*] Artist filter: '{artist_search}'")
        if year_explicit:
            self._log(f"[*] Year filter: {min_year} to 2024 (original release year)")

        # 1. Count matching release-groups
        self._log("[*] Asking MusicBrainz how many release-groups match...")
        data = self._make_request("release-group",
                                  {"query": rg_query, "limit": 1, "fmt": "json"})
        if not data:
            return None
        total_rgs = data.get("count", 0)
        if total_rgs == 0:
            self._log(f"No release-groups found for genre '{genre}'.")
            return None
        self._log(f"[*] MusicBrainz has {total_rgs:,} matching release-groups.")

        # If keyword filtering is active we may need to try a few different
        # release-groups before one of them contains a matching track.
        MAX_ATTEMPTS = 3 if keyword else 1

        for attempt in range(MAX_ATTEMPTS):
            # 2. Pick a random release-group
            max_offset = min(total_rgs - 1, 9999)
            random_offset = random.randint(0, max_offset)
            suffix = f" (attempt {attempt + 1})" if MAX_ATTEMPTS > 1 else ""
            self._log(f"[*] Picking release-group #{random_offset + 1}{suffix}...")

            rg_data = self._make_request("release-group", {
                "query": rg_query, "limit": 1, "offset": random_offset, "fmt": "json"
            })
            if not rg_data or not rg_data.get("release-groups"):
                continue

            rg = rg_data["release-groups"][0]
            rg_title = rg.get("title", "Unknown Album")
            rg_first_date = rg.get("first-release-date", "") or ""
            rg_artist_credit = rg.get("artist-credit", [])
            rg_artist = (
                rg_artist_credit[0].get("name", "Unknown Artist")
                if rg_artist_credit else "Unknown Artist"
            )

            # Release-group search results include a `releases` array.
            releases = rg.get("releases", [])
            if not releases:
                self._log("[!] Release-group has no listed releases, trying another...")
                continue
            release_id = random.choice(releases).get("id")
            if not release_id:
                continue

            # 3. Browse recordings of the chosen release (up to 100 tracks)
            self._log(f"[*] Fetching tracks from '{rg_title}'...")
            rec_data = self._make_request("recording", {
                "release": release_id, "limit": 100, "fmt": "json"
            })
            if not rec_data or not rec_data.get("recordings"):
                continue

            recordings = rec_data["recordings"]
            if keyword:
                kw = keyword.lower()
                recordings = [r for r in recordings
                              if kw in r.get("title", "").lower()]
                if not recordings:
                    self._log("[!] No track matched keyword on this release, trying another...")
                    continue

            recording = random.choice(recordings)
            title = recording.get("title", "Unknown Title")

            result_year = (
                int(rg_first_date[:4])
                if len(rg_first_date) >= 4 and rg_first_date[:4].isdigit()
                else "Unknown"
            )

            return {
                "artist": rg_artist,
                "title": title,
                "album": rg_title,
                "year": result_year,
                "genre": genre,
                "keyword": keyword or "",
                "artist_search": artist_search or "",
            }

        self._log("[!] Could not satisfy all filters after several attempts.")
        return None


def main():
    parser = argparse.ArgumentParser(description='Get a truly random song from MusicBrainz')
    parser.add_argument('-d', '--detail', action='store_true', help='Show detailed song information')
    parser.add_argument('-y', '--year', type=int, default=None, help='Lower limit for the random year (e.g. 1990). By default this matches ORIGINAL release year (firstreleasedate).')
    parser.add_argument('-g', '--genre', type=str, default=None, help='Filter by genre tag (e.g. rock, jazz, pop)')
    parser.add_argument('-k', '--keyword', type=str, default=None, help='Filter by keyword in track title (e.g. dream, love, night)')
    parser.add_argument('-a', '--artist', type=str, default=None, help='Filter by artist name (e.g. coldplay, madonna)')
    parser.add_argument('--any-year', action='store_true', help='Use the broader `date` field for -y (matches any release, including reissues). This is the old pre-firstreleasedate behavior.')
    parser.add_argument('--any-type', action='store_true', help='With -g, include singles, EPs and other release types (default is albums only).')
    # Hidden argument exclusively used for spawning background workers
    parser.add_argument('--prefetch', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".song_cache.json")

    # Detect whether -y was explicitly passed
    year_explicit = args.year is not None
    min_year = min(args.year if args.year is not None else 1920, 2024)

    genre = args.genre.lower().strip() if args.genre else None
    keyword = args.keyword.lower().strip() if args.keyword else None
    artist_search = args.artist.lower().strip() if args.artist else None
    any_year = args.any_year
    any_type = args.any_type

    # ------ BACKGROUND PREFETCH MODE ------
    if args.prefetch:
        # We run silently in the background
        mb = MusicBrainzAPI(quiet=True)
        song = mb.get_random_song(min_year, genre, year_explicit, keyword,
                                  artist_search, any_year, any_type)
        if song:
            # Overwrite the cache file with the new random song
            # Add exactly what was requested for the next retrieval
            song['_requested_min_year'] = min_year if year_explicit else 0
            song['_requested_genre'] = genre or ""
            song['_requested_keyword'] = keyword or ""
            song['_requested_artist'] = artist_search or ""
            song['_requested_any_year'] = any_year
            song['_requested_any_type'] = any_type
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
            cached_genre    = (song.get('_requested_genre',   "") or "").lower()
            cached_keyword  = (song.get('_requested_keyword', "") or "").lower()
            cached_artist   = (song.get('_requested_artist',  "") or "").lower()
            cached_any_year = bool(song.get('_requested_any_year', False))
            cached_any_type = bool(song.get('_requested_any_type', False))
            genre_ok    = cached_genre    == (genre   or "").lower()
            keyword_ok  = cached_keyword  == (keyword or "").lower()
            artist_ok   = cached_artist   == (artist_search or "").lower()
            any_year_ok = cached_any_year == any_year
            any_type_ok = cached_any_type == any_type

            # Year check only matters when -y was explicitly requested
            if year_explicit:
                year_ok = (
                    song.get('_requested_min_year', 0) >= min_year
                    or (isinstance(song.get('year'), int) and song.get('year', 0) >= min_year)
                )
            else:
                year_ok = True

            if (genre_ok and keyword_ok and artist_ok and year_ok
                    and any_year_ok and any_type_ok):
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
            genre_label = f"in genre '{genre}'"
            if any_type:
                genre_label += " (all types)"
            label_parts.append(genre_label)
        if artist_search:
            label_parts.append(f"by '{artist_search}'")
        if year_explicit:
            year_mode = "any release" if any_year else "originally"
            label_parts.append(f"{year_mode} from {min_year} onwards")
        label = " ".join(label_parts) if label_parts else f"from {min_year} onwards"
        print(f"🎵 Fetching a fresh random song {label}...")
        mb = MusicBrainzAPI(quiet=False)
        song = mb.get_random_song(min_year, genre, year_explicit, keyword,
                                  artist_search, any_year, any_type)

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
        if song.get('artist_search'):
            print(f"Artist Search: {song['artist_search']}")
        print("="*40)
    else:
        tags = " ".join(f"[{song[k]}]" for k in ('genre', 'keyword', 'artist_search') if song.get(k))
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
    if artist_search:
        prefetch_cmd += ["-a", artist_search]
    if any_year:
        prefetch_cmd += ["--any-year"]
    if any_type:
        prefetch_cmd += ["--any-type"]
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
