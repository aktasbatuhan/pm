"""
PM Image tools — generate cover images for briefs via fal.ai nano-banana-2.

The agent calls `brief_generate_cover` after producing a brief.
The image URL is stored in the briefs table.
"""

import json
import os
import time
import logging
import urllib.request
import urllib.error

from tools.registry import registry

logger = logging.getLogger(__name__)

FAL_QUEUE_URL = "https://queue.fal.run/fal-ai/nano-banana-2"
FAL_STATUS_URL = "https://queue.fal.run/fal-ai/nano-banana-2/requests"


def _fal_key() -> str:
    return os.environ.get("FAL_KEY", "")


def brief_generate_cover(prompt: str, brief_id: str = "", **kwargs) -> str:
    """Generate a cover image for a brief using fal.ai nano-banana-2."""
    key = _fal_key()
    if not key:
        return json.dumps({"error": "FAL_KEY not set. Add it to .env."})

    # Submit to queue
    req_data = json.dumps({
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": "16:9",
        "output_format": "png",
        "safety_tolerance": "4",
        "resolution": "1K",
        "limit_generations": True,
    }).encode()

    req = urllib.request.Request(
        FAL_QUEUE_URL,
        data=req_data,
        headers={
            "Authorization": f"Key {key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return json.dumps({"error": f"fal.ai queue submit failed: {e.code} {body[:200]}"})
    except Exception as e:
        return json.dumps({"error": f"fal.ai request failed: {e}"})

    request_id = result.get("request_id")
    if not request_id:
        return json.dumps({"error": "No request_id returned", "response": result})

    # Poll for completion
    poll_url = f"{FAL_STATUS_URL}/{request_id}"
    for _ in range(60):  # Max 60 seconds
        time.sleep(1)
        try:
            poll_req = urllib.request.Request(
                poll_url,
                headers={"Authorization": f"Key {key}"},
            )
            with urllib.request.urlopen(poll_req, timeout=10) as resp:
                status = json.loads(resp.read())
        except Exception:
            continue

        if status.get("status") == "COMPLETED":
            # Get the result
            result_url = f"{FAL_STATUS_URL}/{request_id}/result"
            result_req = urllib.request.Request(
                result_url,
                headers={"Authorization": f"Key {key}"},
            )
            try:
                with urllib.request.urlopen(result_req, timeout=10) as resp:
                    final = json.loads(resp.read())
            except Exception as e:
                return json.dumps({"error": f"Failed to fetch result: {e}"})

            images = final.get("images", final.get("output", []))
            if images and isinstance(images, list):
                image_url = images[0].get("url", "") if isinstance(images[0], dict) else str(images[0])
            else:
                image_url = ""

            # Store cover URL in brief if brief_id provided
            if brief_id and image_url:
                try:
                    from tools.pm_brief_tools import _get_db
                    db = _get_db()
                    # Add cover_url column if missing
                    try:
                        db.execute("SELECT cover_url FROM briefs LIMIT 0")
                    except Exception:
                        db.execute("ALTER TABLE briefs ADD COLUMN cover_url TEXT DEFAULT ''")
                    db.execute("UPDATE briefs SET cover_url = ? WHERE id = ?", (image_url, brief_id))
                    db.commit()
                except Exception as e:
                    logger.warning("Failed to store cover URL: %s", e)

            return json.dumps({
                "success": True,
                "image_url": image_url,
                "brief_id": brief_id,
                "request_id": request_id,
            })

        if status.get("status") == "FAILED":
            return json.dumps({"error": "Image generation failed", "details": status})

    return json.dumps({"error": "Timed out waiting for image generation", "request_id": request_id})


BRIEF_GENERATE_COVER_SCHEMA = {
    "name": "brief_generate_cover",
    "description": "Generate a cover image for a daily brief using AI image generation (fal.ai nano-banana-2). Call after storing a brief to create a visual header. Use a prompt that captures the brief's mood: sprint progress, risk level, team energy.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Image generation prompt. Should be evocative and visual, reflecting the brief's theme. E.g. 'A calm sunrise over a modern office, golden light streaming through floor-to-ceiling windows, a whiteboard with a sprint board visible, warm productive morning atmosphere'"
            },
            "brief_id": {
                "type": "string",
                "description": "The brief ID to attach the cover image to (from brief_store response)"
            }
        },
        "required": ["prompt"]
    }
}

registry.register(
    name="brief_generate_cover",
    toolset="pm-brief",
    schema=BRIEF_GENERATE_COVER_SCHEMA,
    handler=lambda args, **kw: brief_generate_cover(
        prompt=args.get("prompt", ""),
        brief_id=args.get("brief_id", "")),
)
