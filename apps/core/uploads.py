"""Shared upload checks and private (non-public) file storage.

Public uploads live under MEDIA_ROOT and are served by URL. Student answer files are personal data, so they
are written under PRIVATE_MEDIA_ROOT, which is never mapped to a URL; views stream them after an access check.
"""
import uuid
from pathlib import Path

from django.conf import settings

CONTENT_TYPES = {
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp',
    'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg', 'm4a': 'audio/mp4',
    'mp4': 'video/mp4', 'webm': 'video/webm',
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def file_extension(name: str) -> str:
    return (name.rsplit('.', 1)[-1] if '.' in (name or '') else '').lower()


def signature_ok(uploaded, extension: str) -> bool:
    """Reject files whose leading bytes contradict their extension (e.g. a script renamed to .pdf)."""
    head = uploaded.read(16)
    uploaded.seek(0)
    if extension == 'pdf':
        return head.startswith(b'%PDF')
    if extension == 'png':
        return head.startswith(b'\x89PNG')
    if extension in {'jpg', 'jpeg'}:
        return head.startswith(b'\xff\xd8\xff')
    if extension == 'webp':
        return head[:4] == b'RIFF' and head[8:12] == b'WEBP'
    if extension == 'gif':
        return head.startswith((b'GIF87a', b'GIF89a'))
    if extension == 'wav':
        return head[:4] == b'RIFF' and head[8:12] == b'WAVE'
    if extension in {'mp4', 'm4a'}:
        return head[4:8] == b'ftyp'
    if extension == 'webm':
        return head.startswith(b'\x1a\x45\xdf\xa3')
    if extension == 'ogg':
        return head.startswith(b'OggS')
    if extension == 'mp3':
        return head.startswith(b'ID3') or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if extension == 'docx':
        return head.startswith(b'PK\x03\x04')
    if extension == 'vtt':
        return head.removeprefix(b'\xef\xbb\xbf').startswith(b'WEBVTT')
    return False


IMAGE_FORMATS = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP', 'gif': 'GIF'}
IMAGE_MAX_PIXELS = 4096 * 4096


def image_ok(uploaded, extension: str) -> bool:
    """Decode the upload with Pillow: it must be a real image in the format its extension claims, and not oversized."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(uploaded) as image:
            width, height = image.size
            ok = image.format == IMAGE_FORMATS.get(extension) and width * height <= IMAGE_MAX_PIXELS
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        ok = False
    uploaded.seek(0)
    return ok


def private_root() -> Path:
    return Path(settings.PRIVATE_MEDIA_ROOT)


def store_private(uploaded, subfolder: str, extension: str) -> str:
    """Write an already-validated upload under PRIVATE_MEDIA_ROOT; returns its path relative to that root."""
    relative = Path(subfolder) / f'{uuid.uuid4().hex}.{extension}'
    target = private_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as handle:
        for chunk in uploaded.chunks():
            handle.write(chunk)
    return relative.as_posix()


def private_path(relative: str) -> Path | None:
    """Resolve a stored relative path, refusing anything that escapes PRIVATE_MEDIA_ROOT."""
    root = private_root().resolve()
    target = (root / relative).resolve()
    return target if root in target.parents and target.is_file() else None


def delete_private(relative: str) -> None:
    target = private_path(relative)
    if target:
        target.unlink(missing_ok=True)
