# Changelog

*[Deutsche Version](CHANGELOG.md)*

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Internationalization: the entire interface in German or English,
  switchable on the Setup page (the "Language" setting), with the default
  controllable via the new `LANG` environment variable.
- Button display as "channel buttons": as an alternative to colored
  buttons, all nine buttons can be shown neutral/gray with a running
  number (1–9) instead of a color name, switchable on the Setup page (the
  "Button display" setting) – for hörbert variants/replicas without
  colored keys.
- Global audio-channel setting (mono/stereo) on the Setup page. Applies to
  new downloads; already-loaded titles keep their existing audio channels.

## [0.1.0] - 2026-08-27

First public release.

### Added
- Paste a link (YouTube, Spotify, podcast, ...) in the browser, assign it
  to one of nine buttons; automatic download and conversion to MP3.
- Automatic volume normalization, mono conversion, cover-art embedding.
- Podcast RSS feed per button – works with any podcast-capable device.
- Automatic subscription for playlists/podcast feeds including retention
  (oldest episodes are parked as a whole playlist, not individually).
- Overview of storage usage per button, SD-card export as a ZIP.
- Library for parking content outside the active buttons.
- Buttons can be individually deactivated (for externally/manually
  provisioned content).
- Docker Compose deployment, setup/update scripts for manual installation.
