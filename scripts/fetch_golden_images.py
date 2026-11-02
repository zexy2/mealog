#!/usr/bin/env python3
"""Fetch and verify the human-gated golden-set input images.

Images stay in ``data/golden-images/`` (gitignored). The manifest stores the
source URL, licence and expected SHA-256, so a source change fails loudly
instead of silently changing the input behind a recorded provider fixture.

The source adapters are deliberately small and standard-library-only:

* direct HTTP images (Nutrition5k, Open Food Facts, Wikimedia Commons),
* Hugging Face row APIs, whose signed image URL is resolved at fetch time, and
* the official UEC-Food ZIP, fetched with HTTP ranges so two images do not
  require downloading the 4.2 GB archive in full.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "eval/golden/manifest.jsonl"
DEFAULT_OUTPUT = ROOT / "data/golden-images"
MAX_IMAGE_BYTES = 25 * 1024 * 1024
ZIP_TAIL_BYTES = 131_072
MAX_ZIP_DIRECTORY_BYTES = 8 * 1024 * 1024
HTTP_TIMEOUT = 90
USER_AGENT = "mealog-golden-images/1.0"


def _request(url: str, *, headers: dict[str, str] | None = None) -> urllib.request.Request:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    return urllib.request.Request(url, headers=request_headers)


def _read_limited(response: Any, limit: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > limit:
        raise RuntimeError(f"download exceeds {limit} bytes: {content_length}")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 1024, limit - total + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise RuntimeError(f"download exceeds {limit} bytes")
        chunks.append(chunk)


def _fetch_http(url: str, *, limit: int = MAX_IMAGE_BYTES) -> bytes:
    try:
        with urllib.request.urlopen(_request(url), timeout=HTTP_TIMEOUT) as response:
            return _read_limited(response, limit)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"download failed with HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"download failed: {url}: {exc.reason}") from exc


def _fetch_range(url: str, start: int, end: int, *, limit: int) -> bytes:
    expected = end - start + 1
    try:
        with urllib.request.urlopen(
            _request(url, headers={"Range": f"bytes={start}-{end}"}),
            timeout=HTTP_TIMEOUT,
        ) as response:
            data = _read_limited(response, limit)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"range download failed with HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"range download failed: {url}: {exc.reason}") from exc
    if len(data) != expected:
        raise RuntimeError(
            f"server did not honour byte range {start}-{end}: received {len(data)} bytes"
        )
    return data


class RemoteZip:
    """Read deflated ZIP members using HTTP range requests."""

    def __init__(self, url: str):
        self.url = url
        self.entries: dict[str, tuple[int, int, int, int]] = {}
        self._load_central_directory()

    def _content_length(self) -> int:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    self.url,
                    headers={"User-Agent": USER_AGENT},
                    method="HEAD",
                ),
                timeout=HTTP_TIMEOUT,
            ) as response:
                length = response.headers.get("Content-Length")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"could not inspect ZIP source: HTTP {exc.code}: {self.url}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"could not inspect ZIP source: {self.url}: {exc.reason}") from exc
        if not length:
            raise RuntimeError(f"ZIP source has no Content-Length: {self.url}")
        return int(length)

    def _load_central_directory(self) -> None:
        size = self._content_length()
        tail_start = max(0, size - ZIP_TAIL_BYTES)
        tail = _fetch_range(self.url, tail_start, size - 1, limit=ZIP_TAIL_BYTES)
        end = tail.rfind(b"PK\x05\x06")
        if end < 0:
            raise RuntimeError(f"ZIP end record not found: {self.url}")
        _, _, _, _, total, directory_size, directory_offset, _ = struct.unpack_from(
            "<4s4H2LH", tail, end
        )
        if directory_size > MAX_ZIP_DIRECTORY_BYTES:
            raise RuntimeError(f"ZIP central directory is unexpectedly large: {directory_size}")
        directory = _fetch_range(
            self.url,
            directory_offset,
            directory_offset + directory_size - 1,
            limit=MAX_ZIP_DIRECTORY_BYTES,
        )

        position = 0
        for _ in range(total):
            fields = struct.unpack_from("<4s6H3L5H2L", directory, position)
            signature, method = fields[0], fields[4]
            compressed, uncompressed = fields[8], fields[9]
            name_length, extra_length, comment_length = fields[10:13]
            local_offset = fields[16]
            if signature != b"PK\x01\x02":
                raise RuntimeError(f"invalid ZIP central directory: {self.url}")
            name_start = position + 46
            name = directory[name_start:name_start + name_length].decode("utf-8")
            self.entries[name] = (method, compressed, uncompressed, local_offset)
            position += 46 + name_length + extra_length + comment_length

    def read_member(self, name: str) -> bytes:
        try:
            method, compressed, uncompressed, local_offset = self.entries[name]
        except KeyError as exc:
            raise RuntimeError(f"ZIP member not found: {name}") from exc
        if uncompressed > MAX_IMAGE_BYTES or compressed > MAX_IMAGE_BYTES:
            raise RuntimeError(f"ZIP member exceeds {MAX_IMAGE_BYTES} bytes: {name}")

        local = _fetch_range(self.url, local_offset, local_offset + 29, limit=30)
        _, _, _, _, _, _, _, _, _, name_length, extra_length = struct.unpack_from(
            "<4s5H3L2H", local
        )
        payload_start = local_offset + 30 + name_length + extra_length
        payload = _fetch_range(
            self.url,
            payload_start,
            payload_start + compressed - 1,
            limit=MAX_IMAGE_BYTES,
        )
        if method == 0:
            data = payload
        elif method == 8:
            data = zlib.decompress(payload, -15)
        else:
            raise RuntimeError(f"unsupported ZIP compression method {method}: {name}")
        if len(data) != uncompressed:
            raise RuntimeError(f"ZIP member length mismatch: {name}")
        return data


def _fetch_huggingface_row(url: str) -> bytes:
    try:
        payload = json.loads(_fetch_http(url, limit=2 * 1024 * 1024))
        image_url = payload["rows"][0]["row"]["image"]["src"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Hugging Face row response has no image URL: {url}") from exc
    return _fetch_http(image_url)


def _fetch_entry(entry: dict[str, Any], zip_cache: dict[str, RemoteZip]) -> bytes:
    source_type = entry.get("image_source_type", "direct")
    source_url = entry["image_source_url"]
    if source_type == "direct":
        return _fetch_http(source_url)
    if source_type == "huggingface_row":
        return _fetch_huggingface_row(source_url)
    if source_type == "zip_member":
        remote_zip = zip_cache.setdefault(source_url, RemoteZip(source_url))
        return remote_zip.read_member(entry["image_source_member"])
    raise RuntimeError(f"unsupported image_source_type for {entry['sample_id']}: {source_type}")


def _manifest_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid manifest JSON on line {line_number}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("sample_id"), str):
            raise TypeError(f"manifest line {line_number} is not a sample object")
        if row["sample_id"] in seen:
            raise RuntimeError(f"duplicate sample_id in manifest: {row['sample_id']}")
        seen.add(row["sample_id"])
        rows.append(row)
    return rows


def _output_path(output_dir: Path, filename: str) -> Path:
    root = output_dir.resolve()
    target = (output_dir / filename).resolve()
    if target.parent != root or target == root:
        raise RuntimeError(f"image_filename must be a plain filename: {filename}")
    return target


def _write_verified(target: Path, data: bytes, expected_sha256: str) -> None:
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"sha256 mismatch for {target.name}: expected {expected_sha256}, "
            f"received {actual_sha256}"
        )
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as tmp:
        temporary = Path(tmp.name)
        tmp.write(data)
    os.replace(temporary, target)


def fetch_manifest(manifest: Path, output_dir: Path) -> tuple[int, list[str]]:
    """Fetch every non-text input, isolating per-row failures.

    One dead source must not stop the 75 images that do resolve. The previous
    all-or-nothing loop aborted on the first HTTP 403, before most of the
    manifest had been attempted, which made the live path look missing rather
    than partially unavailable.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _manifest_rows(manifest)
    zip_cache: dict[str, RemoteZip] = {}
    fetched = 0
    failures: list[str] = []
    for row in rows:
        if row.get("input_type") == "text":
            continue
        sample_id = row.get("sample_id", "<unknown>")
        try:
            for field in ("image_source_url", "image_license", "image_sha256", "image_filename"):
                if not row.get(field):
                    raise RuntimeError(f"missing {field}")
            target = _output_path(output_dir, row["image_filename"])
            data = _fetch_entry(row, zip_cache)
            _write_verified(target, data, row["image_sha256"])
            try:
                display_target = target.relative_to(ROOT)
            except ValueError:
                display_target = target
            print(f"fetched {sample_id} -> {display_target}")
            fetched += 1
        except (RuntimeError, OSError, ValueError) as error:
            failures.append(f"{sample_id}: {error}")
            print(f"failed {sample_id}: {error}", file=sys.stderr)
    return fetched, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    manifest = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    count, failures = fetch_manifest(manifest, output_dir)
    print(f"fetched {count} non-text golden input(s)")
    if failures:
        print(f"{len(failures)} input(s) could not be fetched:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
