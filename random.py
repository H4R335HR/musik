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

    # ==================================================================
    # SINGLE-SONG PUBLIC API
    # ==================================================================
    def get_random_song(self, min_year, genre=None, year_explicit=False,
                        keyword=None, artist_search=None,
                        any_year=False, any_type=False):
        """Dispatcher for single-song mode."""
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
            year_field = "date" if any_year else "firstreleasedate"
            query_parts.append(f"{year_field}:[{min_year} TO 2024]")
            mode_label = "any release year" if any_year else "original release year"
            self._log(f"[*] Year filter: {min_year} to 2024 ({mode_label})")

        if not query_parts:
            selected_year = random.randint(min_year, 2024)
            query_parts.append(f"date:{selected_year}")
            self._log(f"[*] Selected random year: {selected_year}")

        query = " AND ".join(query_parts)
        self._log("[*] Asking MusicBrainz how many tracks exist for this query...")

        data = self._make_request("recording",
                                  {"query": query, "limit": 1, "fmt": "json"})
        if not data:
            return None
        total_tracks = data.get("count", 0)
        if total_tracks == 0:
            self._log("No tracks found for this query. Try running the script again.")
            return None
        self._log(f"[*] MusicBrainz has {total_tracks:,} matching tracks.")

        max_offset = min(total_tracks - 1, 9999)
        random_offset = random.randint(0, max_offset)
        self._log(f"[*] Fetching track number {random_offset + 1}...")

        track_data = self._make_request("recording", {
            "query": query, "limit": 1, "offset": random_offset, "fmt": "json"
        })
        if not track_data or not track_data.get("recordings"):
            return None

        return self._recording_to_song(
            track_data["recordings"][0], selected_year, keyword, artist_search
        )

    # ------------------------------------------------------------------
    # PATH 2: release-group pivot (genre filter present)
    # ------------------------------------------------------------------
    def _random_via_release_group(self, genre, min_year, year_explicit,
                                   keyword, artist_search, any_type):
        """Search release-groups by tag, pick one at random, then pull a recording from it."""
        rg_query = self._build_rg_query(genre, min_year, year_explicit, artist_search, any_type)
        scope = "all release types" if any_type else "albums only"
        self._log(f"[*] Genre filter: '{genre}' ({scope}, searching release-groups)")
        if keyword:
            self._log(f"[*] Keyword filter (applied client-side): '{keyword}'")
        if artist_search:
            self._log(f"[*] Artist filter: '{artist_search}'")
        if year_explicit:
            self._log(f"[*] Year filter: {min_year} to 2024 (original release year)")

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

        MAX_ATTEMPTS = 3 if keyword else 1

        for attempt in range(MAX_ATTEMPTS):
            max_offset = min(total_rgs - 1, 9999)
            random_offset = random.randint(0, max_offset)
            suffix = f" (attempt {attempt + 1})" if MAX_ATTEMPTS > 1 else ""
            self._log(f"[*] Picking release-group #{random_offset + 1}{suffix}...")

            song = self._pick_song_from_random_rg(
                rg_query, random_offset, genre, keyword, artist_search, verbose=True
            )
            if song:
                return song

        self._log("[!] Could not satisfy all filters after several attempts.")
        return None

    # ==================================================================
    # PLAYLIST PUBLIC API
    # ==================================================================
    def get_random_playlist(self, n, min_year, genre=None, year_explicit=False,
                            keyword=None, artist_search=None,
                            any_year=False, any_type=False):
        """Dispatcher for playlist (mixtape) mode. Returns a list of up to n songs."""
        if genre:
            return self._playlist_via_release_group(
                n, genre, min_year, year_explicit, keyword, artist_search, any_type
            )
        return self._playlist_via_recording(
            n, min_year, year_explicit, keyword, artist_search, any_year
        )

    # ------------------------------------------------------------------
    # PLAYLIST PATH 1: recording search (no genre filter)
    # 2 API calls regardless of n — we just bump limit= to n.
    # ------------------------------------------------------------------
    def _playlist_via_recording(self, n, min_year, year_explicit, keyword,
                                artist_search, any_year):
        query_parts = []
        selected_year = None

        if keyword:
            query_parts.append(f"recording:{keyword}")
        if artist_search:
            query_parts.append(f"artist:\"{artist_search}\"")
        if year_explicit:
            year_field = "date" if any_year else "firstreleasedate"
            query_parts.append(f"{year_field}:[{min_year} TO 2024]")
        if not query_parts:
            selected_year = random.randint(min_year, 2024)
            query_parts.append(f"date:{selected_year}")

        query = " AND ".join(query_parts)

        data = self._make_request("recording",
                                  {"query": query, "limit": 1, "fmt": "json"})
        if not data:
            return []
        total = data.get("count", 0)
        if total == 0:
            return []

        # Pick a random offset that still leaves room for n results
        max_offset = max(0, min(total - n, 9999))
        random_offset = random.randint(0, max_offset) if max_offset > 0 else 0

        track_data = self._make_request("recording", {
            "query": query, "limit": n, "offset": random_offset, "fmt": "json"
        })
        if not track_data or not track_data.get("recordings"):
            return []

        return [
            self._recording_to_song(r, selected_year, keyword, artist_search)
            for r in track_data["recordings"]
        ]

    # ------------------------------------------------------------------
    # PLAYLIST PATH 2: release-group pivot (mixtape)
    # 1 + 2n API calls — each slot gets its own random release-group.
    # Progress is printed to stderr so stdout stays pipeable.
    # ------------------------------------------------------------------
    def _playlist_via_release_group(self, n, genre, min_year, year_explicit,
                                     keyword, artist_search, any_type):
        rg_query = self._build_rg_query(genre, min_year, year_explicit, artist_search, any_type)

        data = self._make_request("release-group",
                                  {"query": rg_query, "limit": 1, "fmt": "json"})
        if not data:
            return []
        total_rgs = data.get("count", 0)
        if total_rgs == 0:
            return []

        results = []
        for i in range(n):
            max_offset = min(total_rgs - 1, 9999)
            random_offset = random.randint(0, max_offset)

            song = self._pick_song_from_random_rg(
                rg_query, random_offset, genre, keyword, artist_search, verbose=False
            )
            if song:
                results.append(song)
                print(f"[{i + 1}/{n}] {song['artist']} - {song['title']}",
                      file=sys.stderr, flush=True)
            else:
                print(f"[{i + 1}/{n}] (skipped — no matching track)",
                      file=sys.stderr, flush=True)

        return results

    # ==================================================================
    # INTERNAL HELPERS
    # ==================================================================
    def _build_rg_query(self, genre, min_year, year_explicit, artist_search, any_type):
        parts = [f"tag:{genre}"]
        if not any_type:
            parts.append("primarytype:album")
        if artist_search:
            parts.append(f"artist:\"{artist_search}\"")
        if year_explicit:
            parts.append(f"firstreleasedate:[{min_year} TO 2024]")
        return " AND ".join(parts)

    def _pick_song_from_random_rg(self, rg_query, offset, genre, keyword,
                                   artist_search, verbose):
        """Fetch one release-group at `offset`, pick a release, pick a recording.
        Returns None if any step fails or keyword filter rejects everything.
        """
        rg_data = self._make_request("release-group", {
            "query": rg_query, "limit": 1, "offset": offset, "fmt": "json"
        })
        if not rg_data or not rg_data.get("release-groups"):
            return None

        rg = rg_data["release-groups"][0]
        rg_title = rg.get("title", "Unknown Album")
        rg_first_date = rg.get("first-release-date", "") or ""
        rg_artist_credit = rg.get("artist-credit", [])
        rg_artist = (
            rg_artist_credit[0].get("name", "Unknown Artist")
            if rg_artist_credit else "Unknown Artist"
        )

        releases = rg.get("releases", [])
        if not releases:
            if verbose:
                self._log("[!] Release-group has no listed releases, trying another...")
            return None
        release_id = random.choice(releases).get("id")
        if not release_id:
            return None

        if verbose:
            self._log(f"[*] Fetching tracks from '{rg_title}'...")

        rec_data = self._make_request("recording", {
            "release": release_id, "limit": 100, "fmt": "json"
        })
        if not rec_data or not rec_data.get("recordings"):
            return None

        recordings = rec_data["recordings"]
        if keyword:
            kw = keyword.lower()
            recordings = [r for r in recordings if kw in r.get("title", "").lower()]
            if not recordings:
                if verbose:
                    self._log("[!] No track matched keyword on this release, trying another...")
                return None

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

    def _recording_to_song(self, recording, selected_year, keyword, artist_search):
        title = recording.get("title", "Unknown Title")
        artist_credit = recording.get("artist-credit", [])
        artist = (
            artist_credit[0].get("name", "Unknown Artist")
            if artist_credit else "Unknown Artist"
        )
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


def _format_song_line(song):
    tags = " ".join(f"[{song[k]}]" for k in ('genre', 'keyword', 'artist_search') if song.get(k))
    suffix = f" {tags}" if tags else ""
    return f"{song['artist']} - {song['title']} ({song['year']}){suffix}"


def _filter_label(keyword, genre, any_type, artist_search, year_explicit, any_year, min_year):
    parts = []
    if keyword:
        parts.append(f"containing '{keyword}'")
    if genre:
        g = f"in genre '{genre}'"
        if any_type:
            g += " (all types)"
        parts.append(g)
    if artist_search:
        parts.append(f"by '{artist_search}'")
    if year_explicit:
        year_mode = "any release" if any_year else "originally"
        parts.append(f"{year_mode} from {min_year} onwards")
    return " ".join(parts) if parts else f"from {min_year} onwards"


def main():
    parser = argparse.ArgumentParser(description='Get a truly random song (or playlist) from MusicBrainz')
    parser.add_argument('-d', '--detail', action='store_true', help='Show detailed song information (single-song mode only)')
    parser.add_argument('-n', '--count', type=int, default=1, help='Number of songs to fetch. 1 (default) uses cache/prefetch; >1 enters playlist/mixtape mode.')
    parser.add_argument('-y', '--year', type=int, default=None, help='Lower limit for the random year (e.g. 1990). By default this matches ORIGINAL release year (firstreleasedate).')
    parser.add_argument('-g', '--genre', type=str, default=None, help='Filter by genre tag (e.g. rock, jazz, pop)')
    parser.add_argument('-k', '--keyword', type=str, default=None, help='Filter by keyword in track title (e.g. dream, love, night)')
    parser.add_argument('-a', '--artist', type=str, default=None, help='Filter by artist name (e.g. coldplay, madonna)')
    parser.add_argument('--any-year', action='store_true', help='Use the broader `date` field for -y (matches any release, including reissues). Pre-firstreleasedate behaviour.')
    parser.add_argument('--any-type', action='store_true', help='With -g, include singles, EPs and other release types (default is albums only).')
    # Hidden argument exclusively used for spawning background workers
    parser.add_argument('--prefetch', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".song_cache.json")

    year_explicit = args.year is not None
    min_year = min(args.year if args.year is not None else 1920, 2024)

    genre = args.genre.lower().strip() if args.genre else None
    keyword = args.keyword.lower().strip() if args.keyword else None
    artist_search = args.artist.lower().strip() if args.artist else None
    any_year = args.any_year
    any_type = args.any_type

    # Normalise count (treat non-positive as 1, cap at 100 so we don't hammer the API)
    count = max(1, min(args.count, 100))

    # ==================================================================
    # PLAYLIST MODE  (n > 1)  — skips cache and prefetch entirely.
    # ==================================================================
    if count > 1:
        label = _filter_label(keyword, genre, any_type, artist_search, year_explicit, any_year, min_year)
        print(f"🎵 Fetching {count} random songs {label}...", file=sys.stderr)

        # Quiet MB instance — the playlist path prints its own progress to stderr.
        mb = MusicBrainzAPI(quiet=True)
        songs = mb.get_random_playlist(
            count, min_year, genre, year_explicit, keyword,
            artist_search, any_year, any_type
        )

        if not songs:
            print("\nFailed to fetch any songs.", file=sys.stderr)
            sys.exit(1)

        # Final list goes to stdout — plain, unnumbered, newline-separated.
        print("", file=sys.stderr)  # visual break between progress and list
        for song in songs:
            print(_format_song_line(song))

        if len(songs) < count:
            print(f"\n(Got {len(songs)} of {count} — some fetches didn't pan out)",
                  file=sys.stderr)

        # No prefetch in playlist mode.
        sys.exit(0)

    # ==================================================================
    # SINGLE-SONG MODE  (n == 1)  — cache + foreground fetch + prefetch.
    # ==================================================================

    # ------ BACKGROUND PREFETCH ------
    if args.prefetch:
        mb = MusicBrainzAPI(quiet=True)
        song = mb.get_random_song(min_year, genre, year_explicit, keyword,
                                  artist_search, any_year, any_type)
        if song:
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

    # ------ FOREGROUND ------
    song = None
    cache_valid = False

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                song = json.load(f)

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

    if not cache_valid:
        label = _filter_label(keyword, genre, any_type, artist_search, year_explicit, any_year, min_year)
        print(f"🎵 Fetching a fresh random song {label}...")
        mb = MusicBrainzAPI(quiet=False)
        song = mb.get_random_song(min_year, genre, year_explicit, keyword,
                                  artist_search, any_year, any_type)

        if not song:
            print("\nFailed to fetch a random song.")
            sys.exit(1)

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
        print(f"\nResult: {_format_song_line(song)}")

    # Spawn background prefetch for the NEXT single-song run.
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
