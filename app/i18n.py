"""Central translation table + lookup helpers.

Every user-facing string in the app lives here, keyed by a dotted id, with
one entry per supported language. No gettext/Babel/build step -- consistent
with the rest of the project (vanilla JS, no bundler, no compiled catalogs).

`t()` is used both server-side (Jinja global, Python message-building) and to
seed a small `js.*` subset embedded as JSON for static/app.js (see
templates/base.html).
"""

LANGS = ("de", "en")
DEFAULT_LANG = "de"

SKINS = ("colors", "numbers")
DEFAULT_SKIN = "colors"

# Channel colors double as their own name (see config.CHANNELS) -- the
# `channel.color` column value (violet/red/darkblue/...) is the stable,
# language-independent lookup key here.
CHANNEL_COLOR_NAMES = {
    "violet": {"de": "Violett", "en": "Purple"},
    "red": {"de": "Rot", "en": "Red"},
    "darkblue": {"de": "Dunkelblau", "en": "Dark Blue"},
    "green": {"de": "Grün", "en": "Green"},
    "yellow": {"de": "Gelb", "en": "Yellow"},
    "cyan": {"de": "Türkis", "en": "Turquoise"},
    "lightblue": {"de": "Hellblau", "en": "Light Blue"},
    "orange": {"de": "Orange", "en": "Orange"},
    "darkgreen": {"de": "Dunkelgrün", "en": "Dark Green"},
}

# Neutral gray used for every channel color swatch when skin == "numbers"
# (reuses --muted from static/style.css instead of inventing a new tone).
NEUTRAL_SKIN_HEX = "#667080"

STRINGS = {
    # --- Nav / chrome --------------------------------------------------------
    "nav.start": {"de": "Start", "en": "Home"},
    "nav.belegung": {"de": "Belegung", "en": "Storage"},
    "nav.bearbeiten": {"de": "Bearbeiten", "en": "Edit"},
    "nav.bibliothek": {"de": "Bibliothek", "en": "Library"},
    "nav.setup": {"de": "Setup", "en": "Setup"},
    "nav.logs": {"de": "Logs", "en": "Logs"},

    "legal_notice": {
        "de": "Downloads können AGB und Urheberrecht verletzen. Empfohlen für "
              "Podcasts mit offenem Feed, gemeinfreie Inhalte und eigenes Material.",
        "en": "Downloads may violate terms of service and/or copyright. "
              "Recommended for podcasts with an open feed, public-domain "
              "content, and your own material.",
    },

    # --- Channel display (skin) ----------------------------------------------
    "channel.numbered_button": {"de": "Taste {n}", "en": "Button {n}"},

    # --- Shared / cross-page --------------------------------------------------
    "common.back": {"de": "← Zurück", "en": "← Back"},
    "common.move": {"de": "Verschieben", "en": "Move"},
    "common.delete": {"de": "Löschen", "en": "Delete"},
    "common.cancel": {"de": "Abbrechen", "en": "Cancel"},
    "common.play": {"de": "Abspielen", "en": "Play"},
    "common.to_library": {"de": "→ Bibliothek", "en": "→ Library"},
    "common.other_channel": {"de": "→ anderer Kanal…", "en": "→ other button…"},
    "common.pick_channel": {"de": "Auf Kanal legen…", "en": "Assign to button…"},
    "common.inactive": {"de": "inaktiv", "en": "inactive"},
    "common.episodes": {"de": "{n} Folgen", "en": "{n} episodes"},
    "common.save": {"de": "Speichern", "en": "Save"},

    # --- base.html / index.html -----------------------------------------------
    "index.title": {"de": "Etwas hinzufügen", "en": "Add something"},
    "index.h1": {"de": "Etwas hinzufügen", "en": "Add something"},
    "index.url_label": {"de": "Link einfügen", "en": "Paste a link"},
    "index.url_placeholder": {
        "de": "Link einfügen – z.B. von YouTube, Spotify oder einem Podcast",
        "en": "Paste a link – e.g. from YouTube, Spotify, or a podcast",
    },
    "index.paste_title": {"de": "Aus Zwischenablage einfügen", "en": "Paste from clipboard"},
    "index.clear_title": {"de": "Eingabe löschen", "en": "Clear input"},
    "index.channel_label": {"de": "Auf welchen Knopf?", "en": "Which button?"},
    "index.add_btn": {"de": "Hinzufügen", "en": "Add"},
    "index.cancel_btn": {"de": "Abbrechen", "en": "Cancel"},
    "index.retry_btn": {"de": "Nochmal versuchen", "en": "Try again"},
    "index.delete_btn": {"de": "Löschen", "en": "Delete"},
    "index.hide_title": {"de": "Ausblenden", "en": "Dismiss"},
    "index.notice_needs_attention_one": {
        "de": "„{title}“ braucht Aufmerksamkeit{hint}.",
        "en": "“{title}” needs attention{hint}.",
    },
    "index.notice_needs_attention_many": {
        "de": "{count} Titel brauchen Aufmerksamkeit.",
        "en": "{count} titles need attention.",
    },
    "index.retry_now": {"de": "Nochmal versuchen", "en": "Try again"},
    "index.retry_all": {"de": "Alle nochmal versuchen", "en": "Retry all"},
    "index.find_alt": {"de": "Andere Quelle suchen", "en": "Find another source"},
    "index.find_alt_all": {"de": "Für alle andere Quelle suchen", "en": "Find another source for all"},
    "index.delete_one": {"de": "Löschen", "en": "Delete"},
    "index.delete_all": {"de": "Alle löschen", "en": "Delete all"},
    "index.edit_individually": {
        "de": "Einzeln bearbeiten unter <a href=\"/bearbeiten\">Bearbeiten</a>.",
        "en": "Handle individually under <a href=\"/bearbeiten\">Edit</a>.",
    },
    "index.unreviewed_one": {
        "de": "„{title}“ wurde automatisch über eine Ersatzsuche gefunden und "
              "sollte geprüft werden.",
        "en": "“{title}” was found automatically via a replacement search and "
              "should be reviewed.",
    },
    "index.unreviewed_many": {
        "de": "{count} Titel wurden automatisch über eine Ersatzsuche gefunden "
              "und sollten geprüft werden.",
        "en": "{count} titles were found automatically via a replacement "
              "search and should be reviewed.",
    },
    "index.review_individually": {
        "de": "Einzeln prüfen unter <a href=\"/bearbeiten\">Bearbeiten</a>.",
        "en": "Review individually under <a href=\"/bearbeiten\">Edit</a>.",
    },
    "index.evict_move": {"de": "In Bibliothek verschieben", "en": "Move to library"},
    "index.evict_delete": {"de": "Endgültig löschen", "en": "Delete permanently"},

    # --- channel.html -----------------------------------------------------------
    "channel.playtime_total": {"de": "Gesamte Spielzeit:", "en": "Total playtime:"},
    "channel.abo_toggle": {
        "de": "Neue Folgen automatisch holen",
        "en": "Fetch new episodes automatically",
    },
    "channel.park_all": {
        "de": "Alle in Bibliothek verschieben",
        "en": "Move all to library",
    },
    "channel.delete_all": {"de": "Alle Titel löschen", "en": "Delete all titles"},
    "channel.empty": {
        "de": "Hier ist noch nichts. Füge auf der Startseite etwas hinzu.",
        "en": "Nothing here yet. Add something on the home page.",
    },
    "playtime.hours_minutes": {"de": "{h} Std. {m} Min.", "en": "{h} hr {m} min"},
    "playtime.minutes_only": {"de": "{m} Min.", "en": "{m} min"},

    # --- _item_row.html -----------------------------------------------------------
    "item.handle_title": {"de": "Verschieben", "en": "Drag to reorder"},
    "item.alt_review_chip": {
        "de": "⟳ andere Quelle – bitte prüfen",
        "en": "⟳ alternate source – please check",
    },
    "item.alt_review_title": {
        "de": "Wurde automatisch über eine Ersatzsuche gefunden, noch nicht geprüft",
        "en": "Was found automatically via a replacement search, not reviewed yet",
    },
    "item.search_self": {"de": "Selbst suchen", "en": "Search myself"},
    "item.confirm_alt": {"de": "✓ passt", "en": "✓ looks good"},
    "item.confirm_alt_title": {
        "de": "Inhalt passt, Hinweis entfernen",
        "en": "Content is fine, remove the hint",
    },
    "item.next_try": {
        "de": "nächster Versuch automatisch um {time} Uhr",
        "en": "next automatic attempt at {time}",
    },
    "item.retry_now": {"de": "Jetzt nochmal versuchen", "en": "Try again now"},
    "item.find_alt": {"de": "Andere Quelle suchen", "en": "Find another source"},
    "item.loading": {"de": "wird geladen …", "en": "loading …"},
    "item.delete_title": {"de": "Löschen", "en": "Delete"},
    "item.search_placeholder_title": {"de": "Suchen", "en": "Search"},

    # --- bearbeiten.html -----------------------------------------------------------
    "bearbeiten.title": {"de": "Bearbeiten", "en": "Edit"},
    "bearbeiten.h1": {"de": "Bearbeiten", "en": "Edit"},
    "bearbeiten.hint": {
        "de": "Welchen Knopf möchtest du bearbeiten?",
        "en": "Which button would you like to edit?",
    },
    "bearbeiten.unreviewed_title": {
        "de": "Automatisch ersetzte Titel, noch nicht geprüft",
        "en": "Automatically replaced titles, not reviewed yet",
    },

    # --- belegung.html -----------------------------------------------------------
    "belegung.title": {"de": "Belegung", "en": "Storage"},
    "belegung.h1": {"de": "Belegung der Knöpfe", "en": "Button storage"},
    "belegung.hint": {
        "de": "Übersicht über alle gespeicherten Dateien",
        "en": "Overview of all stored files",
    },
    "belegung.disk_label": {
        "de": "{used} MB von {total} GB belegt ({free} MB frei)",
        "en": "{used} MB of {total} GB used ({free} MB free)",
    },
    "belegung.sd_export": {
        "de": "⬇ Für SD-Karte herunterladen",
        "en": "⬇ Download for SD card",
    },
    "belegung.sd_export_hint": {
        "de": "Lädt alle {count} Titel als ZIP-Datei herunter, sortiert in "
              "Ordner 0–8. Entpacken und den Inhalt auf die Speicherkarte kopieren.",
        "en": "Downloads all {count} titles as a ZIP file, sorted into "
              "folders 0–8. Unzip and copy the contents onto the memory card.",
    },
    "belegung.delete_title": {"de": "Löschen", "en": "Delete"},
    "belegung.delete_all_named": {
        "de": "Alle löschen ({name})",
        "en": "Delete all ({name})",
    },
    "belegung.no_files": {"de": "Keine Dateien", "en": "No files"},

    # --- bibliothek.html -----------------------------------------------------------
    "bibliothek.title": {"de": "Bibliothek", "en": "Library"},
    "bibliothek.h1": {"de": "Bibliothek", "en": "Library"},
    "bibliothek.hint": {
        "de": "Geparkte Titel und Playlists – liegen bereit, ohne einen "
              "Kanalplatz zu belegen.",
        "en": "Parked titles and playlists – ready to go, without taking up "
              "a button slot.",
    },
    "bibliothek.empty": {"de": "Die Bibliothek ist leer.", "en": "The library is empty."},

    # --- setup.html -----------------------------------------------------------
    "setup.title": {"de": "Setup", "en": "Setup"},
    "setup.h1": {"de": "Setup", "en": "Setup"},
    "setup.hint_top": {
        "de": "Diese Adressen einmalig im Gerät eintragen. Danach musst du "
              "hier nichts mehr tun – neue Inhalte erscheinen von selbst.",
        "en": "Enter these addresses in the device once. After that you "
              "won't need to do anything here – new content appears "
              "automatically.",
    },
    "setup.cookie_ok": {"de": "✓ YouTube-Zugang aktiv", "en": "✓ YouTube access active"},
    "setup.cookie_renew": {"de": "Erneuern", "en": "Renew"},
    "setup.cookie_warn": {
        "de": "ℹ YouTube-Zugang ist nicht eingerichtet – normalerweise nicht "
              "nötig. Nur falls YouTube-Downloads blockiert werden, hier "
              "einrichten:",
        "en": "ℹ YouTube access isn't set up – usually not necessary. Only "
              "set this up if YouTube downloads get blocked:",
    },
    "setup.cookie_setup": {"de": "Einrichten", "en": "Set up"},
    "setup.cookie_step1": {
        "de": "Browser-Erweiterung installieren:",
        "en": "Install the browser extension:",
    },
    "setup.cookie_step1_hint": {
        "de": "Dann auf youtube.com gehen, Erweiterung anklicken, „Export“ drücken.",
        "en": "Then go to youtube.com, click the extension, press \"Export\".",
    },
    "setup.cookie_step2": {
        "de": "Exportierte Datei hier hochladen:",
        "en": "Upload the exported file here:",
    },
    "setup.cookie_choose_file": {"de": "Datei auswählen …", "en": "Choose file …"},
    "setup.cookie_upload_btn": {"de": "Hochladen", "en": "Upload"},
    "setup.max_items_h2": {"de": "Maximale Downloads", "en": "Maximum downloads"},
    "setup.max_items_hint": {
        "de": "Wie viele Folgen soll eine Playlist oder ein Podcast höchstens "
              "auf einmal laden? Der Rest kommt automatisch nach und nach nach.",
        "en": "How many episodes should a playlist or podcast load at most "
              "at once? The rest follows automatically over time.",
    },
    "setup.max_length_h2": {"de": "Maximale Playlistlänge", "en": "Maximum playlist length"},
    "setup.max_length_hint": {
        "de": "Wie viele Folgen sollen pro Kanal höchstens aufgehoben werden? "
              "Kommen neue dazu, werden die ältesten darüber hinaus "
              "automatisch gelöscht.",
        "en": "How many episodes should be kept per button at most? As new "
              "ones arrive, the oldest ones beyond that limit are deleted "
              "automatically.",
    },
    "setup.audio_h2": {"de": "Audioausgabe", "en": "Audio output"},
    "setup.audio_mono": {"de": "Mono", "en": "Mono"},
    "setup.audio_stereo": {"de": "Stereo", "en": "Stereo"},
    "setup.language_h2": {"de": "Sprache", "en": "Language"},
    "setup.language_de": {"de": "Deutsch", "en": "German"},
    "setup.language_en": {"de": "English", "en": "English"},
    "setup.skin_h2": {"de": "Kanal-Anzeige", "en": "Button display"},
    "setup.skin_colors": {"de": "Bunte Knöpfe", "en": "Colored buttons"},
    "setup.skin_numbers": {
        "de": "Kanaltasten (nummeriert)",
        "en": "Numbered buttons",
    },
    "setup.addresses_h2": {"de": "Podcast-URLs", "en": "Podcast URLs"},
    "setup.addresses_hint": {
        "de": "Diese Adressen einmalig im Hörspieler als Podcast hinzufügen – "
              "für jeden Knopf eine.",
        "en": "Add these addresses to the player as a podcast once – one per "
              "button.",
    },
    "setup.deactivate_callout": {
        "de": "💡 Läuft auf einem Knopf externer Content (z. B. von einer "
              "SD-Karte)? Dann kannst Du ihn hier <strong>deaktivieren</strong>, "
              "indem Du auf den jeweiligen QR-Code klickst. Der Feeder lässt "
              "ihn dann in Ruhe, damit nichts durcheinanderkommt.",
        "en": "Is a button already playing external content (e.g. from an "
              "SD card)? You can <strong>deactivate</strong> it here by "
              "clicking its QR code. The feeder then leaves it alone so "
              "nothing gets mixed up.",
    },
    "setup.qr_alt": {"de": "QR-Code {name}", "en": "QR code {name}"},
    "setup.inactive_hint": {"de": "deaktiviert", "en": "deactivated"},
    "setup.cookie_uploading": {"de": "Wird hochgeladen …", "en": "Uploading …"},
    "setup.cookie_upload_error": {"de": "Fehler beim Hochladen.", "en": "Upload failed."},
    "setup.no_connection": {"de": "Keine Verbindung.", "en": "No connection."},

    # --- logs.html -----------------------------------------------------------
    "logs.title": {"de": "Logs", "en": "Logs"},
    "logs.h1": {"de": "Logs", "en": "Logs"},
    "logs.hint": {
        "de": "Die letzten {lines} Zeilen. Für Fehlersuche gedacht — keine "
              "Nutzerdaten, nur technische Meldungen.",
        "en": "The last {lines} lines. Meant for troubleshooting — no user "
              "data, just technical messages.",
    },
    "logs.refresh": {"de": "↻ Aktualisieren", "en": "↻ Refresh"},
    "logs.empty": {"de": "Noch keine Log-Einträge.", "en": "No log entries yet."},
    "logs.back_to_setup": {"de": "← Zurück zu Setup", "en": "← Back to Setup"},

    # --- title.* (persisted item titles) --------------------------------------
    "title.untitled": {"de": "Ohne Titel", "en": "Untitled"},

    # --- api.py messages -----------------------------------------------------------
    "api.channel_not_found": {"de": "Diesen Knopf gibt es nicht.", "en": "This button doesn't exist."},
    "api.channel_inactive": {"de": "Dieser Knopf ist deaktiviert.", "en": "This button is deactivated."},
    "api.paste_link_first": {"de": "Bitte zuerst einen Link einfügen.", "en": "Please paste a link first."},
    "api.paste_link_action": {"de": "Link einfügen", "en": "Paste link"},
    "api.no_space": {
        "de": "Kein Platz mehr. Räume den Kanal „{name}“ auf.",
        "en": "No space left. Clean up the “{name}” button.",
    },
    "api.tidy_up_action": {"de": "Aufräumen", "en": "Clean up"},
    "api.link_failed": {"de": "Der Link ließ sich nicht öffnen.", "en": "The link couldn't be opened."},
    "api.try_again_action": {"de": "Nochmal versuchen", "en": "Try again"},
    "api.eviction_needed": {
        "de": "Um Platz zu machen, ist kein Platz mehr für: {names}.",
        "en": "To make room, there's no space left for: {names}.",
    },
    "api.already_exists": {
        "de": "Das ist auf diesem Knopf schon vorhanden.",
        "en": "This is already on this button.",
    },
    "api.preparing": {"de": "Wird vorbereitet …", "en": "Preparing …"},
    "api.series_over_limit": {
        "de": "{label} hat {total} Folgen – die neuesten {created} werden "
              "jetzt geladen. Neue Folgen kommen automatisch.",
        "en": "{label} has {total} episodes – the newest {created} are "
              "loading now. New episodes arrive automatically.",
    },
    "api.series_all_loading": {
        "de": "{label}: {created} Folgen werden jetzt geladen. Neue Folgen "
              "kommen automatisch.",
        "en": "{label}: {created} episodes are loading now. New episodes "
              "arrive automatically.",
    },
    "api.the_list": {"de": "Die Liste", "en": "The list"},
    "api.job_not_found": {"de": "Auftrag nicht gefunden.", "en": "Job not found."},
    "api.queue_position": {
        "de": "Wird geladen (aktuell in Warteposition {pos})",
        "en": "Loading (currently at queue position {pos})",
    },
    "api.converting": {"de": "Umwandlung zu Audio …", "en": "Converting to audio …"},
    "api.loading_percent": {"de": "Wird geladen … {pct} %", "en": "Loading … {pct}%"},
    "api.on_player_tomorrow": {
        "de": "Ab morgen früh auf dem Hörspieler 🎵",
        "en": "On the player from tomorrow morning 🎵",
    },
    "api.cancelled": {"de": "Wurde abgebrochen", "en": "Was cancelled"},
    "api.cancelled_short": {"de": "Abgebrochen", "en": "Cancelled"},
    "api.unknown_reason": {"de": "Unbekannter Grund", "en": "Unknown reason"},
    "api.job_cannot_cancel": {
        "de": "Der Auftrag kann nicht mehr abgebrochen werden.",
        "en": "This job can no longer be cancelled.",
    },
    "api.job_was_cancelled": {"de": "Auftrag wurde abgebrochen.", "en": "Job was cancelled."},
    "api.item_not_found": {"de": "Eintrag nicht gefunden.", "en": "Entry not found."},
    "api.no_current_problem": {
        "de": "Dieser Eintrag hat gerade kein Problem.",
        "en": "This entry currently has no problem.",
    },
    "api.will_retry": {"de": "Wird erneut versucht.", "en": "Will be retried."},
    "api.no_title_search_self": {
        "de": "Kein Titel bekannt – bitte selbst nach einem Ersatz suchen.",
        "en": "No title known – please search for a replacement yourself.",
    },
    "api.searching_alt_source": {
        "de": "Suche nach anderer Quelle gestartet …",
        "en": "Searching for another source …",
    },
    "api.enter_search_term": {"de": "Bitte einen Suchbegriff eingeben.", "en": "Please enter a search term."},
    "api.search_failed": {"de": "Suche ist fehlgeschlagen.", "en": "Search failed."},
    "api.no_source_selected": {"de": "Keine Quelle ausgewählt.", "en": "No source selected."},
    "api.loading_with_picked_source": {
        "de": "Wird mit der ausgewählten Quelle geladen …",
        "en": "Loading with the selected source …",
    },
    "api.confirmed": {"de": "Bestätigt.", "en": "Confirmed."},
    "api.retry_count": {
        "de": "{count} Titel {verb} erneut versucht.",
        "en": "{count} title{s} being retried.",
    },
    "api.find_alt_count": {
        "de": "Suche nach anderen Quellen für {count} Titel gestartet …",
        "en": "Searching for alternative sources for {count} title{s} …",
    },
    "api.subscription_not_found": {"de": "Abo nicht gefunden.", "en": "Subscription not found."},
    "api.order_saved": {"de": "Reihenfolge gespeichert.", "en": "Order saved."},
    "api.entry_deleted": {"de": "Eintrag gelöscht.", "en": "Entry deleted."},
    "api.count_deleted": {"de": "{count} Titel gelöscht.", "en": "{count} title{s} deleted."},
    "api.episodes_deleted": {"de": "{count} Folgen gelöscht.", "en": "{count} episode{s} deleted."},
    "api.moved_to_library": {
        "de": "In die Bibliothek verschoben.",
        "en": "Moved to the library.",
    },
    "api.moved_to_channel": {
        "de": "Auf „{name}“ verschoben.",
        "en": "Moved to “{name}”.",
    },
    "api.episodes_moved_to_library": {
        "de": "{count} Folgen in die Bibliothek verschoben.",
        "en": "{count} episode{s} moved to the library.",
    },
    "api.episodes_moved_to_channel": {
        "de": "{count} Folgen auf „{name}“ verschoben.",
        "en": "{count} episode{s} moved to “{name}”.",
    },
    "api.abo_state": {
        "de": "Automatisches Holen ist jetzt {state}.",
        "en": "Automatic fetching is now {state}.",
    },
    "api.abo_on": {"de": "an", "en": "on"},
    "api.abo_off": {"de": "aus", "en": "off"},
    "api.channel_active_again": {
        "de": "„{name}“ ist wieder aktiv.",
        "en": "“{name}” is active again.",
    },
    "api.channel_has_content": {
        "de": "„{name}“ hat noch Inhalte. In Bibliothek verschieben oder abbrechen?",
        "en": "“{name}” still has content. Move to library or cancel?",
    },
    "api.channel_now_inactive": {
        "de": "„{name}“ ist jetzt inaktiv.",
        "en": "“{name}” is now inactive.",
    },
    "api.number_range_error": {
        "de": "Bitte eine Zahl zwischen 1 und 500 eingeben.",
        "en": "Please enter a number between 1 and 500.",
    },
    "api.max_items_saved": {
        "de": "bis zu {n} Folgen pro Liste werden geladen",
        "en": "up to {n} episodes per list will be loaded",
    },
    "api.max_length_saved": {
        "de": "max. {n} Folgen werden je Kanal behalten",
        "en": "up to {n} episodes are kept per button",
    },
    "api.choose_mono_stereo": {"de": "Bitte Mono oder Stereo wählen.", "en": "Please choose Mono or Stereo."},
    "api.audio_channels_saved": {
        "de": "neue Downloads werden ab jetzt in {label} umgewandelt",
        "en": "new downloads will now be converted to {label}",
    },
    "api.choose_language": {
        "de": "Bitte eine gültige Sprache wählen.",
        "en": "Please choose a valid language.",
    },
    "api.language_saved": {
        "de": "Sprache umgestellt auf {label}",
        "en": "language switched to {label}",
    },
    "api.choose_skin": {
        "de": "Bitte eine gültige Kanal-Anzeige wählen.",
        "en": "Please choose a valid button display.",
    },
    "api.skin_saved_colors": {
        "de": "Kanal-Anzeige auf bunte Knöpfe umgestellt",
        "en": "button display switched to colored buttons",
    },
    "api.skin_saved_numbers": {
        "de": "Kanal-Anzeige auf Kanaltasten (nummeriert) umgestellt",
        "en": "button display switched to numbered buttons",
    },
    "api.nothing_to_save": {"de": "Nichts zu speichern.", "en": "Nothing to save."},
    "api.saved_prefix": {"de": "Gespeichert – {details}.", "en": "Saved – {details}."},
    "api.sd_write_failed": {
        "de": "Das Schreiben auf die Karte ging nicht. → Karte neu einstecken "
              "und erneut tippen.",
        "en": "Writing to the card failed. → Reinsert the card and tap again.",
    },
    "api.zip_failed": {
        "de": "Die ZIP-Datei konnte nicht erstellt werden.",
        "en": "The ZIP file could not be created.",
    },
    "api.channel_not_found_short": {"de": "Kanal nicht gefunden.", "en": "Button not found."},
    "api.invalid_filename": {"de": "Ungültiger Dateiname.", "en": "Invalid filename."},
    "api.file_not_found": {"de": "Datei nicht gefunden.", "en": "File not found."},
    "api.file_deleted": {"de": "Datei gelöscht.", "en": "File deleted."},
    "api.delete_failed": {"de": "Löschen fehlgeschlagen.", "en": "Delete failed."},
    "api.no_file_uploaded": {"de": "Keine Datei übermittelt.", "en": "No file submitted."},
    "api.not_a_cookies_file": {"de": "Das ist keine Cookies-Datei.", "en": "This isn't a cookies file."},
    "api.save_failed": {"de": "Speichern fehlgeschlagen.", "en": "Save failed."},
    "api.youtube_access_saved": {
        "de": "YouTube-Zugang gespeichert ✓",
        "en": "YouTube access saved ✓",
    },
    "api.files_deleted": {"de": "{count} Dateien gelöscht.", "en": "{count} file{s} deleted."},

    # --- library.py -----------------------------------------------------------
    "library.item_downloading": {
        "de": "Dieser Titel wird gerade geladen – bitte kurz warten.",
        "en": "This title is currently downloading – please wait a moment.",
    },

    # --- worker.py / downloader.py -----------------------------------------------------------
    "worker.no_space": {
        "de": "Kein Platz mehr. → Räume den Kanal „{name}“ auf.",
        "en": "No space left. → Clean up the “{name}” button.",
    },
    "worker.entry_missing": {"de": "Eintrag fehlt", "en": "Entry missing"},
    "worker.failed_prefix": {"de": "Ging nicht: {error}", "en": "Failed: {error}"},
    "worker.no_title_use_search": {
        "de": " Kein Titel bekannt – bitte „Selbst suchen“ verwenden.",
        "en": " No title known – please use \"Search myself\".",
    },
    "worker.did_not_respond": {
        "de": "Hat zu lange nicht reagiert.",
        "en": "Did not respond in time.",
    },
    "downloader.content_unavailable": {
        "de": "Der Inhalt ist nicht verfügbar.",
        "en": "The content isn't available.",
    },
    "downloader.spotdl_missing": {
        "de": "spotdl ist nicht installiert. Bitte 'pip install spotdl' ausführen.",
        "en": "spotdl is not installed. Please run 'pip install spotdl'.",
    },
    "downloader.spotify_query_failed": {
        "de": "Spotify konnte nicht gelesen werden: {error}",
        "en": "Could not read from Spotify: {error}",
    },
    "downloader.spotify_no_match": {
        "de": "Kein passender Inhalt auf Spotify gefunden.",
        "en": "No matching content found on Spotify.",
    },
    "downloader.address_unreadable": {
        "de": "Die Adresse konnte nicht gelesen werden.",
        "en": "The address could not be read.",
    },
    "downloader.file_not_loaded": {
        "de": "Die Datei konnte nicht geladen werden.",
        "en": "The file could not be loaded.",
    },

    # --- sd_export.py -----------------------------------------------------------
    "sdexport.no_card": {
        "de": "Es ist keine Karte eingesteckt. → Karte einstecken und erneut tippen.",
        "en": "No card is inserted. → Insert the card and tap again.",
    },
    "sdexport.bad_path": {
        "de": "Der Kartenpfad stimmt nicht. → Karte neu einstecken und erneut tippen.",
        "en": "The card path is wrong. → Reinsert the card and tap again.",
    },
    "sdexport.not_writable": {
        "de": "Auf die Karte kann nicht geschrieben werden. → Schreibschutz prüfen.",
        "en": "Can't write to the card. → Check the write-protect switch.",
    },
    "sdexport.done": {
        "de": "{count} Titel auf die Karte geschrieben. → Karte jetzt sicher "
              "entnehmen und ins Gerät stecken.",
        "en": "{count} titles written to the card. → Now safely eject the "
              "card and insert it into the device.",
    },

    # --- feed.py -----------------------------------------------------------
    "feed.channel_title": {"de": "hoerbox-feeder – {name}", "en": "hoerbox-feeder – {name}"},
    "feed.channel_description": {
        "de": "hoerbox-feeder Kanal {id}",
        "en": "hoerbox-feeder button {id}",
    },

    # --- js.* (embedded for static/app.js) --------------------------------------
    "js.confirm.cancel_job": {"de": "Wirklich abbrechen?", "en": "Really cancel?"},
    "js.confirm.delete_entry": {
        "de": "Diesen Eintrag wirklich löschen?",
        "en": "Really delete this entry?",
    },
    "js.confirm.delete_all_problems": {
        "de": "Wirklich ALLE betroffenen Titel löschen?",
        "en": "Really delete ALL affected titles?",
    },
    "js.confirm.park_item": {
        "de": "Diesen Titel in die Bibliothek verschieben?",
        "en": "Move this title to the library?",
    },
    "js.confirm.park_block": {
        "de": "Diese ganze Playlist in die Bibliothek verschieben?",
        "en": "Move this whole playlist to the library?",
    },
    "js.confirm.delete_block": {
        "de": "Diese ganze Playlist wirklich endgültig löschen? Das kann "
              "nicht rückgängig gemacht werden.",
        "en": "Really permanently delete this whole playlist? This cannot "
              "be undone.",
    },
    "js.confirm.delete_forever": {
        "de": "Wirklich endgültig löschen? Das kann nicht rückgängig gemacht werden.",
        "en": "Really delete permanently? This cannot be undone.",
    },
    "js.confirm.delete_file": {
        "de": "\"{filename}\" wirklich löschen?",
        "en": "Really delete \"{filename}\"?",
    },
    "js.confirm.park_all_channel": {
        "de": "Alle Titel dieses Kanals in die Bibliothek verschieben?",
        "en": "Move all titles of this button to the library?",
    },
    "js.confirm.delete_all_files": {
        "de": "Wirklich ALLE Dateien dieses Kanals löschen?",
        "en": "Really delete ALL files of this button?",
    },
    "js.status.preparing": {"de": "Wird vorbereitet …", "en": "Preparing …"},
    "js.status.no_connection": {"de": "Keine Verbindung.", "en": "No connection."},
    "js.status.failed": {"de": "Ging nicht.", "en": "Failed."},
    "js.status.series_label_fallback": {"de": "Serie", "en": "Series"},
    "js.status.batch_progress": {
        "de": "{label}: {done} von {total} Folgen fertig",
        "en": "{label}: {done} of {total} episodes done",
    },
    "js.status.waiting_retry": {
        "de": "{n} warten auf erneuten Versuch",
        "en": "{n} waiting to retry",
    },
    "js.status.finally_unavailable": {
        "de": "{n} endgültig nicht verfügbar",
        "en": "{n} permanently unavailable",
    },
    "js.status.current_label": {"de": "Aktuell:", "en": "Currently:"},
    "js.status.cancelled": {"de": "Wurde abgebrochen", "en": "Was cancelled"},
    "js.status.batch_done_with_failures": {
        "de": "{label}: {done} von {total} geladen, {failedText} – Details "
              "unter „Bearbeiten“.",
        "en": "{label}: {done} of {total} loaded, {failedText} – details "
              "under \"Edit\".",
    },
    "js.status.failed_episode_one": {"de": "{n} Folge nicht verfügbar", "en": "{n} episode unavailable"},
    "js.status.failed_episode_many": {"de": "{n} Folgen nicht verfügbar", "en": "{n} episodes unavailable"},
    "js.status.on_player_tomorrow": {
        "de": "Ab morgen früh auf dem Hörspieler 🎵",
        "en": "On the player from tomorrow morning 🎵",
    },
    "js.status.failed_with_reason": {"de": "Ging nicht: {text}", "en": "Failed: {text}"},
    "js.status.entry_deleted": {"de": "Eintrag gelöscht.", "en": "Entry deleted."},
    "js.status.file_deleted": {"de": "Datei gelöscht.", "en": "File deleted."},
    "js.status.order_saved": {"de": "Reihenfolge gespeichert.", "en": "Order saved."},
    "js.toast.could_not_save": {"de": "Konnte nicht gespeichert werden.", "en": "Could not save."},
    "js.toast.could_not_retry": {"de": "Konnte nicht erneut versucht werden.", "en": "Could not retry."},
    "js.toast.could_not_find_alt": {
        "de": "Konnte keine andere Quelle suchen.",
        "en": "Could not search for another source.",
    },
    "js.toast.could_not_play": {"de": "Konnte nicht abspielen.", "en": "Could not play."},
    "js.toast.search_running": {"de": "Suche …", "en": "Searching …"},
    "js.toast.search_failed": {"de": "Suche fehlgeschlagen.", "en": "Search failed."},
    "js.toast.no_results": {
        "de": "Keine Treffer – anderen Suchbegriff probieren.",
        "en": "No results – try a different search term.",
    },
    "js.toast.could_not_apply": {"de": "Konnte nicht übernommen werden.", "en": "Could not apply."},
    "js.toast.could_not_confirm": {"de": "Konnte nicht bestätigt werden.", "en": "Could not confirm."},
    "js.toast.could_not_delete": {"de": "Konnte nicht gelöscht werden.", "en": "Could not delete."},
    "js.toast.could_not_move": {"de": "Konnte nicht verschoben werden.", "en": "Could not move."},
    "js.toast.pick_channel_first": {
        "de": "Bitte zuerst einen Kanal auswählen.",
        "en": "Please choose a button first.",
    },
    "js.toast.could_not_change": {"de": "Konnte nicht geändert werden.", "en": "Could not change."},
    "js.candidate.pick": {"de": "Diesen nehmen", "en": "Use this one"},
    "js.candidate.minutes": {"de": "Min.", "en": "min"},
}


def t(key: str, lang: str, **kwargs) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def channel_color_name(color: str, lang: str) -> str:
    entry = CHANNEL_COLOR_NAMES.get(color)
    if entry is None:
        return color
    return entry.get(lang) or entry.get(DEFAULT_LANG) or color


def channel_label(channel, lang: str, skin: str) -> str:
    """User-facing name for a channel: translated color name (default skin),
    or a plain "Taste N"/"Button N" label (skin == "numbers", N = id + 1)."""
    if skin == "numbers":
        return t("channel.numbered_button", lang, n=channel.id + 1)
    return channel_color_name(channel.color, lang)


def channel_color_hex(channel, skin: str) -> str:
    if skin == "numbers":
        return NEUTRAL_SKIN_HEX
    return channel.color_hex


def quote(text: str, lang: str) -> str:
    """Wrap a title/name in the language-appropriate quotation marks --
    German „low-high", English "curly" -- for messages that interpolate
    user/DB content rather than going through a STRINGS template."""
    if lang == "en":
        return f"“{text}”"
    return f"„{text}“"
