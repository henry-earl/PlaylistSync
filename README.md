# Apple-to-Spotify Playlist Sync Engine

An automated, end-to-end data pipeline that bridges closed-ecosystem music platforms. This project seamlessly reconciles a master Apple Music library with a target Spotify playlist using a custom browser bookmarklet, a serverless encryption webhook, GitHub Actions, and an algorithmic Python matching engine.

---

## The Problem & Solution

While Apple Music hosts a preferred master playlist, managing cross-platform listening without manual curation is a bottleneck. Standard third-party sync tools often lack granular state management, fall short on edge-case matching (like regional track variations or remixes), or require storing plaintext API credentials insecurely.

**The Solution:** An automated integration pipeline built with product-grade security and robust data reconciliation logic. It abstracts away session token maintenance, securely pipes credentials via asymmetric encryption, and runs deterministic-to-probabilistic matching algorithms to ensure zero broken links.

---

## System Architecture & Data Flow

```text
[ Apple Music Web ] 
       │ (Bookmarklet: Extracts Developer JWT & User Token)
       ▼
[ Pipedream Webhook ] 
       │ (Libsodium Public-Key Crypto / Box Seal)
       ▼
[ GitHub Secrets ] 
       │ (Securely Stored as Encrypted JSON)
       ▼
[ GitHub Actions (Cron / Dispatch) ] 
       │ (Runs Python Reconciler Script)
       ▼
[ Spotify API & State Tracking ]
'''

## End-to-End Workflow:
Client-Side Extraction: A custom JavaScript bookmarklet taps into Apple Music's underlying MusicKit instance to extract the active Developer JWT (developerToken) and session user token (musicUserToken).
Serverless Secure Tunnel: The tokens are securely POSTed to a Pipedream webhook, which encrypts them on-the-fly using Libsodium (Crypto Box Seal) against the GitHub repository's public key.
Zero-Trust Storage: The encrypted payload is automatically pushed via GitHub's API into a single secure repository secret (APPLE_MUSIC_WEBHOOK_TOKEN), preventing credential leakage.
Algorithmic Sync Pipeline: A scheduled GitHub Action runs a Python engine that unpacks the tokens, enforces Apple's required dual-header API authentication, reconciles state (state.json), and updates Spotify.
Core Engineering & Algorithmic Highlights
Dual-Header API Authentication: Custom handling of Apple Music’s strict API requirements, simultaneously passing Bearer tokens (Authorization) and session headers (Music-User-Token).
Multi-Tier Matching Waterfall: To handle cross-platform metadata discrepancies (e.g., slight title variations, capitalization, or remix tags), the engine uses a cascading waterfall:
Manual Override Database (track_overrides.json): Hardcoded deterministic mappings for stubborn edge cases.
ISRC Match: Exact international standard recording code lookup.
Fuzzy String Matching + Duration Tolerance: Uses rapidfuzz for normalized string distance scoring combined with a strict \pm 3,000\text{ms} duration tolerance window to filter out false-positive remixes.
Catalog Fallback Search: Queries the Spotify Search API dynamically if no local match is found.
State Tracking & Deletion Propagation: Tracks historical states (state.json) to detect when a song is removed from the Apple Master playlist, automatically propagating the deletion to the Spotify target.
Tech Stack
Languages: Python, JavaScript
Orchestration & CI/CD: GitHub Actions (Automated Cron / Dispatch)
Serverless & Security: Pipedream, Libsodium (libsodium-wrappers), GitHub REST API (Secrets Management)
APIs & Libraries: Apple Music API, Spotify Web API, rapidfuzz, requests
Quick Start / Setup
1. Configure the Bookmarklet
Create a new bookmark in your browser and set the URL to the extraction script:

javascript:(function(){
    if (!window.location.hostname.includes('music.apple.com')) {
        window.location.href = '[https://music.apple.com](https://music.apple.com)';
        return;
    }
    const music = MusicKit.getInstance();
    const token = music.developerToken;
    const userToken = music.musicUserToken;
    fetch('YOUR_PIPEDREAM_WEBHOOK_URL', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userToken: userToken, developerToken: token })
    }).then(() => alert('Apple Music Tokens Synced to GitHub!'));
})();

2. Environment Variables & Secrets
Configure the following secrets in your GitHub Repository settings:
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
APPLE_MUSIC_WEBHOOK_TOKEN (Automatically populated and updated by your Pipedream webhook)
GITHUB_PERSONAL_ACCESS_TOKEN (Configured inside Pipedream for automated secret rotation)
