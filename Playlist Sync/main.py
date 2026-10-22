import os
import json
from datetime import timedelta
import requests
from rapidfuzz import process

# Constants
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
APPLE_MUSIC_API_KEY = os.getenv("APPLE_MUSIC_API_KEY")

def load_state():
    """Load state from state.json"""
    try:
        with open('state.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_state(state):
    """Save state to state.json"""
    with open('state.json', 'w') as f:
        json.dump(state, f)

def load_track_overrides():
    """Load track overrides from track_overrides.json"""
    try:
        with open('track_overrides.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def push_to_git(repo_path, branch='main'):
    """Push the current state to the specified Git repo"""
    # Assuming we're pushing to a local git repo, modify accordingly for remote
    os.system(f'cd {repo_path} && git add .')
    os.system(f'cd {repo_path} && git commit -m "Sync update" --allow-empty')
    os.system(f'cd {repo_path} && git push origin {branch}')

def get_playlist_data(playlist_uri):
    """Fetch data from Spotify/Apple Music API"""
    headers = {'Authorization': f'Bearer {os.environ["SPOTIFY_ACCESS_TOKEN"]}'}
    
    spotify_response = requests.get(f'{playlist_uri}', headers=headers)
    apple_music_response = requests.get(f'{playlist_uri}?type=tracks', headers=headers)
    
    if spotify_response.status_code == 200:
        return spotify_response.json()
    elif apple_music_response.status_code == 200:
        return apple_music_response.json()
    else:
        print(f"Failed to retrieve playlist data: {spotify_response.status_code}")
        raise Exception("API Request Failed")

def handle_deletions(state, current_platform):
    """Handle deletions based on state and current platform"""
    tracked_tracks = state.get('tracked_tracks', [])
    current_tracks = current_platform.get('tracks', [])

    for track in current_tracks:
        if track['id'] in [t['id'] for t in tracked_tracks]:
            continue
        
        # Remove from both platforms
        del current_platform['tracks'][current_tracks.index(track)]
        del state['tracked_tracks'][tracked_tracks.index(track)]

def reconcile_additions(current_platform, target_platform):
    """Reconcile additions and matches"""
    additions = []
    conflicts = []

    for track in current_platform['tracks']:
        if track['id'] in [p['id'] for p in target_platform['tracks']]:
            continue

        # Exact ISRC match
        if track.get('isrc') and track['isrc'].upper() in [p.get('isrc').upper() for p in target_platform['tracks']]:
            additions.append(track)
            continue

        # Normalized fuzzy string match
        suggestions = process.extractOne(track['name'], [p['name'] for p in target_platform['tracks']])
        if suggestions[1] >= 80:
            additions.append(suggestions[0])
            continue

        # Duration check
        if abs(timedelta(milliseconds=(track['duration_ms'] // 1000)) - timedelta(milliseconds=(target_platform['tracks'][i]['duration_ms'] // 1000))) <= timedelta(seconds=3):
            additions.append(track)
        else:
            conflicts.append((track, target_platform['tracks'][i]))

    for conflict in conflicts:
        # Propagate deletion to target platform
        target_platform['tracks'].append(conflict[0])

    return additions

def main():
    # Initialize states
    state = load_state()

    # Track overrides loaded from disk
    track_overrides = load_track_overrides()

    # Fetch playlists
    master_playlist = get_playlist_data('master_playlist_uri')
    target_playlist = get_playlist_data('target_playlist_uri')

    # Handle deletions
    handle_deletions(state, target_playlist)

    # Merge current and target platforms
    merged_platforms = {**target_playlist, **master_playlist}

    # Sort tracks alphabetically by artist + title
    sorted_tracks = sorted(merged_platforms['tracks'], key=lambda k: (k['artist'], k['title']))

    # Step through tracks, handling each individually
    for i, track in enumerate(sorted_tracks):
        # Manual override check
        if track['id'] in track_overrides:
            state['tracked_tracks'].remove(track)
            merge_target = True
            break
        else:
            merge_target = False

        # Process remaining steps
        if merge_target:
            state['tracked_tracks'].append(track)
            target_playlist['tracks'].insert(i, track)

    # Save state
    save_state(state)

    # Commit updates to Git
    push_to_git('/path/to/sync_repo')

if __name__ == "__main__":
    main()