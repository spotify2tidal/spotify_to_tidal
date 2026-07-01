#!/usr/bin/env python3

""" Consolidated logging of items that could not be found on Tidal during a sync.

Items are accumulated in a single in-memory list over the course of a run and
flushed to one log file at the end. Call clear_not_found_log() at the start of a
sync and write_not_found_log() once it finishes. """

# Global list to track all items not found during sync
_not_found_items = []

def add_not_found_item(item_type: str, item_info: str, context: str = None):
    """Add an item that couldn't be found to the global not found list"""
    _not_found_items.append({
        'type': item_type,
        'info': item_info,
        'context': context
    })

def write_not_found_log():
    """Write all not found items to a single consolidated log file"""
    if not _not_found_items:
        return

    filename = "items not found.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("==========================\n")
        f.write("Spotify to Tidal Sync Log\n")
        f.write("Items Not Found on Tidal\n")
        f.write("==========================\n\n")

        # Group items by type
        songs = [item for item in _not_found_items if item['type'] == 'track']
        albums = [item for item in _not_found_items if item['type'] == 'album']
        artists = [item for item in _not_found_items if item['type'] == 'artist']

        if songs:
            f.write("TRACKS/SONGS:\n")
            f.write("-" * 40 + "\n")
            for item in songs:
                context_str = f" (from {item['context']})" if item['context'] else ""
                f.write(f"{item['info']}{context_str}\n")
            f.write("\n")

        if albums:
            f.write("ALBUMS:\n")
            f.write("-" * 40 + "\n")
            for item in albums:
                f.write(f"{item['info']}\n")
            f.write("\n")

        if artists:
            f.write("ARTISTS:\n")
            f.write("-" * 40 + "\n")
            for item in artists:
                f.write(f"{item['info']}\n")
            f.write("\n")

        f.write(f"Total items not found: {len(_not_found_items)}\n")

    print(f"Wrote {len(_not_found_items)} items not found to '{filename}'")

def clear_not_found_log():
    """Clear the not found items list (called at start of sync)"""
    _not_found_items.clear()
