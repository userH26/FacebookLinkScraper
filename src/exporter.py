"""
File export utilities for collected post URLs and metadata.
"""

import csv
import json
import os
import shutil
from typing import Any, Dict, List, Optional, Union


def create_backup(filepath: str) -> Optional[str]:
    """
    Creates a backup copy of the target file if it exists and has content.
    For example: 'post_urls.csv' -> 'post_urls_backup.csv'.
    Returns the backup filepath if created, else None.
    """
    if not filepath or not os.path.exists(filepath):
        return None
    try:
        if os.path.getsize(filepath) > 0:
            base, ext = os.path.splitext(filepath)
            backup_path = f"{base}_backup{ext}"
            shutil.copy2(filepath, backup_path)
            return backup_path
    except Exception:
        pass
    return None


def save_to_csv(
    data: List[Union[str, Dict[str, Any]]],
    filepath: str,
    field_name: str = "posturl",
) -> None:
    """
    Saves a list of URLs or dictionary records to a CSV file.

    :param data: List of URL strings or dict records
    :param filepath: Destination CSV file path
    :param field_name: Column header if data is a list of plain strings (default: 'posturl')
    """
    if not filepath:
        return

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        if not data:
            writer = csv.writer(f)
            writer.writerow([field_name])
            return

        first = data[0]
        if isinstance(first, dict):
            fieldnames = list(first.keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                writer.writerow(row)
        else:
            writer = csv.writer(f)
            writer.writerow([field_name])
            for url in data:
                writer.writerow([url])


def save_to_json(data: Any, filepath: str, indent: int = 2) -> None:
    """
    Saves data to a JSON file.

    :param data: Data to serialize
    :param filepath: Destination JSON file path
    :param indent: Indentation level for readability
    """
    if not filepath:
        return

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    with open(filepath, mode="w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def save_to_txt(urls: List[str], filepath: str) -> None:
    """
    Saves a list of URLs to a plain text file, one per line.

    :param urls: List of URL strings
    :param filepath: Destination TXT file path
    """
    if not filepath:
        return

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    with open(filepath, mode="w", encoding="utf-8") as f:
        for url in urls:
            f.write(f"{url}\n")
