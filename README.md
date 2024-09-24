
# Musik 🎵

Musik is a simple command-line tool that allows you to search and play music directly from YT Music and YT. Whether you want to play individual tracks, albums, or playlists, Musik has got you covered. With support for both audio and video, it can handle flexible media playback using external tools like `yt-dlp` and `mpv`.

## Features

- Search and play songs from **YT Music**.
- Fallback to **YT** videos when a song isn't found on YT Music.
- Play albums and playlists from YT Music or YT.
- Choose the number of search results to play.
- Works with external tools like `yt-dlp` and `mpv` for seamless media playback.

## Requirements

Before you can use Musik, you'll need to have the following installed:

- [Python 3.x](https://www.python.org/downloads/)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [mpv](https://mpv.io/installation/)
- [ytmusicapi](https://ytmusicapi.readthedocs.io/en/latest/setup.html)

To install the required Python libraries, run:

```bash
pip install ytmusicapi yt-dlp
```

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/your-username/musik.git
   cd musik
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Make sure `yt-dlp` and `mpv` are installed on your system. You can use your package manager (e.g., `apt`, `brew`, etc.) to install them.

## Usage

### Basic Usage

To search and play music from YT Music:

```bash
python musik.py "search query"
```

For example:

```bash
python musik.py "dreams by Fleetwood Mac"
```

### Options

- `-n`, `--num-results`: Number of results to play (default is 1). This applies to both YT Music and YT searches.
  
  Example:
  ```bash
  python musik.py "nirvana" -n 3
  ```

- `-a`, `--audio`: First search on YT Music. If not found, fallback to YT.
  
  Example:
  ```bash
  python musik.py "Linkin Park" -a
  ```

- `-v`, `--video`: Search and play the first result directly from YT video.
  
  Example:
  ```bash
  python musik.py "classical music playlist" -v
  ```

- `-p`, `--playlist`: Play all videos from a YT playlist URL or search for a playlist.
  
  Example:
  ```bash
  python musik.py "https://YT.com/playlist?list=..." -p
  ```

- `-b`, `--album`: Search and play albums from YT Music as a playlist.
  
  Example:
  ```bash
  python musik.py "Abbey Road by The Beatles" -b
  ```

## Example Commands

- Search and play **Nirvana's** top 2 results from YT Music:
  ```bash
  python musik.py "nirvana" -n 2
  ```

- Search for an album and play it as a playlist:
  ```bash
  python musik.py "random access memories by daft punk" -b
  ```

- Play audio from a YT playlist:
  ```bash
  python musik.py "https://YT.com/playlist?list=..." -p
  ```

- Search and play audio belonging to a **video** from YT directly:
  ```bash
  python musik.py "lofi beats" -v
  ```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
