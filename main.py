import json
import os
import requests
from rapidfuzz import process

# Constants & Credentials from GitHub Repository Secrets
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
RAW_APPLE_SECRET = os.getenv("APPLE_MUSIC_WEBHOOK_TOKEN")

# Unpack the combined Apple Music tokens from the GitHub secret
APPLE_DEVELOPER_TOKEN = None
APPLE_USER_TOKEN = None

if RAW_APPLE_SECRET:
    try:
        token_data = json.loads(RAW_APPLE_SECRET)
        APPLE_DEVELOPER_TOKEN = token_data.get("developerToken")
        APPLE_USER_TOKEN = token_data.get("userToken")
    except json.JSONDecodeError:
        # Fallback if someone accidentally stored just a raw token string previously
        APPLE_USER_TOKEN = RAW_APPLE_SECRET

# Playlist IDs (Hardcoded constants since they are public/non-sensitive)
APPLE_MASTER_PLAYLIST_ID = "pl.u-JPAZE6GTLB9Zy0I"
SPOTIFY_TARGET_PLAYLIST_ID = "7gTN8X6AHEJ98T8uFT8P7Q"


def get_spotify_token():
  """Generate a Spotify access token using client credentials"""
  auth_url = "https://accounts.spotify.com/api/token"
  auth_data = {
      "grant_type": "client_credentials",
      "client_id": SPOTIFY_CLIENT_ID,
      "client_secret": SPOTIFY_CLIENT_SECRET,
  }
  response = requests.post(auth_url, data=auth_data)
  if response.status_code == 200:
    return response.json().get("access_token")
  else:
    raise Exception(
        f"Failed to authenticate with Spotify: {response.status_code}"
    )


def load_json_file(filename, default_data):
  """Safely load JSON files or initialize them if missing"""
  if not os.path.exists(filename):
    with open(filename, "w") as f:
      json.dump(default_data, f, indent=4)
  with open(filename, "r") as f:
    return json.load(f)


def save_json_file(filename, data):
  """Save data to JSON file"""
  with open(filename, "w") as f:
    json.dump(data, f, indent=4)


def fetch_apple_master_tracks():
  """Fetch tracks from Apple Music master playlist using both required tokens"""
  if not APPLE_DEVELOPER_TOKEN or not APPLE_USER_TOKEN:
    raise Exception(
        "Missing Apple Music developerToken or userToken in environment variables."
    )

  url = f"https://api.music.apple.com/v1/me/library/playlists/{APPLE_MASTER_PLAYLIST_ID}/tracks"

  # Apple requires BOTH a Bearer Developer JWT AND a Music-User-Token header
  headers = {
      "Authorization": f"Bearer {APPLE_DEVELOPER_TOKEN}",
      "Music-User-Token": APPLE_USER_TOKEN,
  }

  response = requests.get(url, headers=headers)

  if response.status_code == 401:
    raise Exception(
        "401 Unauthorized: Apple Music session token or developer JWT has"
        " expired. Bookmarklet refresh needed!"
    )
  elif response.status_code != 200:
    raise Exception(
        f"Failed to fetch Apple Music playlist: {response.status_code} -"
        f" {response.text}"
    )

  data = response.json().get("data", [])
  formatted_tracks = []

  for item in data:
    attrs = item.get("attributes", {})
    isrc = attrs.get("isrc")
    formatted_tracks.append({
        "id": item["id"],
        "name": attrs.get("name"),
        "artist": attrs.get("artistName", "Unknown"),
        "isrc": isrc,
        "duration_ms": attrs.get("durationInMillis", 0),
    })
  return formatted_tracks


def fetch_spotify_target_tracks(token):
  """Fetch tracks from target Spotify playlist"""
  url = f"https://api.spotify.com/v1/playlists/{SPOTIFY_TARGET_PLAYLIST_ID}/tracks"
  headers = {"Authorization": f"Bearer {token}"}

  response = requests.get(url, headers=headers)
  if response.status_code != 200:
    raise Exception(
        f"Failed to fetch Spotify target playlist: {response.status_code}"
    )

  data = response.json().get("items", [])
  formatted_tracks = []

  for item in data:
    track = item.get("track")
    if not track:
      continue
    formatted_tracks.append({
        "id": track["id"],
        "name": track["name"],
        "artist": track["artists"][0]["name"] if track["artists"] else "Unknown",
        "isrc": track.get("external_ids", {}).get("isrc"),
        "duration_ms": track["duration_ms"],
        "uri": track["uri"],
    })
  return formatted_tracks


def search_spotify_catalog(track_name, artist_name, token):
  """Search Spotify catalog for a matching track URI using metadata"""
  query = f"track:{track_name} artist:{artist_name}"
  url = (
      "https://api.spotify.com/v1/search?q="
      f"{requests.utils.quote(query)}&type=track&limit=1"
  )
  headers = {"Authorization": f"Bearer {token}"}

  response = requests.get(url, headers=headers)
  if response.status_code == 200:
    items = response.json().get("tracks", {}).get("items", [])
    if items:
      return items[0]["uri"]
  return None


def update_spotify_playlist(spotify_uris, token):
  """Overwrite/Update Spotify target playlist tracks"""
  url = f"https://api.spotify.com/v1/playlists/{SPOTIFY_TARGET_PLAYLIST_ID}/tracks"
  headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

  payload = {"uris": spotify_uris}
  response = requests.put(url, headers=headers, json=payload)
  if response.status_code not in [200, 201]:
    raise Exception(
        f"Failed to update Spotify playlist: {response.status_code}"
    )


def push_to_git(branch="main"):
  """Commit and push state.json back to GitHub repository"""
  os.system('git config --global user.name "Playlist Sync Bot"')
  os.system('git config --global user.email "bot@users.noreply.github.com"')
  os.system("git add state.json")
  os.system(
      'git commit -m "Auto-update state.json baseline [skip ci]" --allow-empty'
  )
  os.system(f"origin {branch}")


def main():
  # 1. Authenticate with Spotify
  spotify_token = get_spotify_token()

  # 2. Load state and manual override databases
  state = load_json_file("state.json", {"tracked_tracks": []})
  overrides_data = load_json_file("track_overrides.json", {"overrides": []})
  overrides_map = {
      item["apple_id"]: item["spotify_uri"]
      for item in overrides_data.get("overrides", [])
  }

  # 3. Fetch current platforms (Apple Music as Master, Spotify as Target)
  master_tracks = fetch_apple_master_tracks()
  target_tracks = fetch_spotify_target_tracks(spotify_token)

  # 4. Handle Deletions (State Reconciliation)
  previous_tracked_ids = {t["id"] for t in state.get("tracked_tracks", [])}
  current_master_ids = {t["id"] for t in master_tracks}

  deleted_ids = previous_tracked_ids - current_master_ids
  if deleted_ids:
    print(
        f"Propagation: {len(deleted_ids)} deletion(s) detected. Removing from"
        " target."
    )

  # 5. Matching Waterfall & Build Final Ordered URI List for Spotify Target
  final_spotify_uris = []

  for track in master_tracks:
    apple_id = track["id"]

    # Step A: Check Manual Override Database First
    if apple_id in overrides_map:
      final_spotify_uris.append(overrides_map[apple_id])
      continue

    # Step B: Try finding existing track on Spotify Target via ISRC match
    matched_uri = None
    track_isrc = track.get("isrc")
    if track_isrc:
      for st in target_tracks:
        if st.get("isrc") and st["isrc"].upper() == track_isrc.upper():
          matched_uri = st["uri"]
          break

    # Step C: Fallback to Normalized Fuzzy String Match + Duration Check
    if not matched_uri:
      target_names = [st["name"] for st in target_tracks]
      if target_names:
        match_result = process.extractOne(track["name"], target_names)
        if match_result and match_result[1] >= 80:
          matched_index = match_result[2]
          matched_target_track = target_tracks[matched_index]

          # Step D: Duration Tolerance Check (within 3 seconds / 3000ms)
          if (
              abs(track["duration_ms"] - matched_target_track["duration_ms"])
              <= 3000
          ):
            matched_uri = matched_target_track["uri"]

    # Step E: If still not found anywhere on Spotify, search Spotify catalog
    if not matched_uri:
      matched_uri = search_spotify_catalog(
          track["name"], track["artist"], spotify_token
      )

    if matched_uri:
      final_spotify_uris.append(matched_uri)

  # 6. Push Synchronized Order to Spotify Target
  update_spotify_playlist(final_spotify_uris, spotify_token)

  # 7. Save New State Baseline & Commit back to GitHub Repo
  new_state = {"tracked_tracks": master_tracks}
  save_json_file("state.json", new_state)
  push_to_git()

  print("Production playlist sync completed successfully!")


if __name__ == "__main__":
  main()
