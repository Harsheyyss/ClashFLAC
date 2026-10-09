
import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="ClashFLAC BitChord Add-on")

CLASHFLAC_URL = os.getenv(
    "CLASHFLAC_URL",
    "https://clashflac.onrender.com"
).rstrip("/")

TIMEOUT = httpx.Timeout(25.0, connect=10.0)


@app.get("/")
@app.get("/manifest.json")
async def manifest():
    return {
        "id": "harsh.clashflac.bitchord",
        "name": "ClashFLAC Lossless",
        "version": "0.1.0",
        "resources": ["search", "stream"],
        "allowDownloads": 0,
        "checkValidLossless": 0,
        "settings": [
            {
                "key": "quality",
                "type": "select",
                "default": "LOSSLESS",
                "options": [
                    {"label": "Lossless", "value": "LOSSLESS"},
                    {"label": "High", "value": "HIGH"},
                    {"label": "Low", "value": "LOW"}
                ]
            }
        ]
    }


@app.get("/health")
async def health():
    return {"status": "ok", "backend": CLASHFLAC_URL}


@app.get("/search")
async def search(q: str, quality: str = "LOSSLESS"):
    if not q.strip():
        return {"tracks": []}

    results = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True
    ) as client:
        # Amazon Music
        try:
            response = await client.get(
                f"{CLASHFLAC_URL}/api/search",
                params={"q": q}
            )
            if response.is_success:
                data = response.json()
                items = data if isinstance(data, list) else (
                    data.get("tracks", data.get("results", []))
                    if isinstance(data, dict) else []
                )

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    track_id = item.get("track_id") or item.get("asin") or item.get("id")
                    title = item.get("title") or item.get("name")
                    if track_id and title:
                        results.append({
                            "id": f"amazon:{track_id}",
                            "title": title,
                            "artist": item.get("artist") or item.get("artists") or "Unknown Artist",
                            "album": item.get("album") or "",
                            "duration": item.get("duration_sec") or item.get("duration") or 0,
                            "artworkURL": item.get("thumbnail_url") or item.get("thumbnail") or item.get("image"),
                            "format": "flac",
                            "audioQuality": "LOSSLESS"
                        })
        except (httpx.HTTPError, ValueError):
            pass

        # Tidal
        try:
            response = await client.get(
                f"{CLASHFLAC_URL}/api/tidal/search",
                params={"q": q, "limit": 10}
            )
            if response.is_success:
                data = response.json()
                items = data if isinstance(data, list) else (
                    data.get("tracks", data.get("results", []))
                    if isinstance(data, dict) else []
                )

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    track_id = item.get("asin") or item.get("id") or item.get("track_id")
                    title = item.get("title")
                    if track_id and title:
                        results.append({
                            "id": f"tidal:{track_id}",
                            "title": title,
                            "artist": item.get("artist") or "Unknown Artist",
                            "album": item.get("album") or "",
                            "duration": item.get("duration_sec") or 0,
                            "artworkURL": item.get("thumbnail_url"),
                            "format": "flac",
                            "audioQuality": "LOSSLESS"
                        })
        except (httpx.HTTPError, ValueError):
            pass

    return {"tracks": results[:30]}


@app.get("/stream/{track_id:path}")
async def stream(track_id: str, quality: str = "LOSSLESS"):
    if ":" not in track_id:
        raise HTTPException(status_code=404, detail="Unknown track source")

    engine, native_id = track_id.split(":", 1)
    selected_quality = (
        "HI_RES_LOSSLESS" if quality.upper() == "LOSSLESS"
        else "HIGH" if quality.upper() == "HIGH"
        else "LOW"
    )

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True
    ) as client:
        try:
            if engine == "tidal":
                response = await client.post(
                    f"{CLASHFLAC_URL}/api/tidal/resolve",
                    json={"input": native_id, "quality": selected_quality}
                )
            elif engine == "amazon":
                response = await client.post(
                    f"{CLASHFLAC_URL}/api/resolve",
                    json={"track_id": native_id, "quality": selected_quality}
                )
            else:
                raise HTTPException(status_code=404, detail="Unknown engine")

            if not response.is_success:
                raise HTTPException(
                    status_code=502,
                    detail=f"{engine} stream resolution failed"
                )

            data = response.json()
            media_url = (
                data.get("url")
                or data.get("stream_url")
                or data.get("streamUrl")
                or data.get("download_url")
            )
            if not media_url:
                raise HTTPException(
                    status_code=502,
                    detail="Backend returned no playable URL"
                )

            return JSONResponse({
                "url": media_url,
                "format": "flac",
                "codec": "flac",
                "container": "flac",
                "manifest": "none",
                "encrypted": False,
                "quality": data.get("quality", "Lossless")
            })

        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not contact ClashFLAC"
            ) from exc
