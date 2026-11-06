"""Photo storage: size cap, real MIME check, sanitized names, uuid paths."""

import logging
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import settings

logger = logging.getLogger("taskflow.uploads")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str | None) -> str:
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = base.replace("\x00", "")
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    return (cleaned[:80] or "archivo")


async def read_limited(upload: UploadFile, *, org_id: int, user_id: int) -> bytes:
    safe_name = sanitize_filename(upload.filename)
    limit = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await upload.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                logger.error(
                    "Upload rejected: file exceeds %s bytes org_id=%s user_id=%s filename=%s",
                    limit,
                    org_id,
                    user_id,
                    safe_name,
                )
                raise HTTPException(status_code=413, detail="La imagen supera el límite de 5 MB")
            chunks.append(chunk)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Upload failed while reading the stream org_id=%s user_id=%s filename=%s",
            org_id,
            user_id,
            safe_name,
        )
        raise HTTPException(status_code=400, detail="No se pudo leer la imagen") from None
    data = b"".join(chunks)
    if not data:
        logger.error(
            "Upload rejected: empty file org_id=%s user_id=%s filename=%s",
            org_id,
            user_id,
            safe_name,
        )
        raise HTTPException(status_code=422, detail="La foto es obligatoria")
    return data


def validate_image(data: bytes, original_name: str | None, *, org_id: int, user_id: int) -> str:
    """Return 'jpg' or 'png' after checking magic bytes and decoding with Pillow."""

    safe_name = sanitize_filename(original_name)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        magic = "PNG"
    elif data.startswith(b"\xff\xd8\xff"):
        magic = "JPEG"
    else:
        logger.error(
            "Upload rejected: magic bytes are not JPG or PNG org_id=%s user_id=%s filename=%s",
            org_id,
            user_id,
            safe_name,
        )
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes JPG o PNG")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            fmt = (image.format or "").upper()
            image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        logger.exception(
            "Upload rejected: Pillow could not decode the file org_id=%s user_id=%s filename=%s magic=%s",
            org_id,
            user_id,
            safe_name,
            magic,
        )
        raise HTTPException(status_code=400, detail="El archivo no es una imagen JPG o PNG válida") from None
    if fmt not in {"JPEG", "PNG"} or fmt != magic:
        logger.error(
            "Upload rejected: detected format %s does not match magic %s org_id=%s user_id=%s filename=%s",
            fmt,
            magic,
            org_id,
            user_id,
            safe_name,
        )
        raise HTTPException(status_code=400, detail="El archivo no es una imagen JPG o PNG válida")
    return "jpg" if fmt == "JPEG" else "png"


def store_image(org_id: int, user_id: int, data: bytes, ext: str, original_name: str | None) -> str:
    safe_name = sanitize_filename(original_name)
    root = settings.upload_path.resolve()
    folder = (root / str(org_id)).resolve()
    try:
        folder.relative_to(root)
    except ValueError:
        logger.error("Upload rejected: unsafe organization folder org_id=%s", org_id)
        raise HTTPException(status_code=400, detail="No se pudo guardar la imagen") from None
    filename = f"{uuid4().hex}.{ext}"
    destination = (folder / filename).resolve()
    try:
        destination.relative_to(folder)
        folder.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Upload failed while writing file org_id=%s user_id=%s filename=%s",
            org_id,
            user_id,
            safe_name,
        )
        raise HTTPException(status_code=500, detail="No se pudo guardar la imagen") from None
    relative = f"{org_id}/{filename}"
    logger.info(
        "Stored upload org_id=%s user_id=%s path=%s bytes=%s original=%s",
        org_id,
        user_id,
        relative,
        len(data),
        safe_name,
    )
    return relative


def resolve_photo(photo_path: str, org_id: int) -> Path:
    if not photo_path or photo_path.startswith(("/", "\\")) or ".." in photo_path.replace("\\", "/"):
        logger.error("Evidence path rejected org_id=%s path=%s", org_id, photo_path)
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    root = settings.upload_path.resolve()
    full = (root / photo_path).resolve()
    try:
        full.relative_to(root / str(org_id))
    except ValueError:
        logger.error("Evidence path escaped the organization folder org_id=%s path=%s", org_id, photo_path)
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from None
    if full.parent.name != str(org_id) or not full.is_file():
        logger.error("Evidence file missing org_id=%s path=%s", org_id, photo_path)
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return full


def delete_photo(photo_path: str, org_id: int) -> None:
    try:
        path = resolve_photo(photo_path, org_id)
    except HTTPException:
        logger.error("Could not resolve evidence file for deletion org_id=%s path=%s", org_id, photo_path)
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not delete evidence file org_id=%s path=%s", org_id, photo_path)
