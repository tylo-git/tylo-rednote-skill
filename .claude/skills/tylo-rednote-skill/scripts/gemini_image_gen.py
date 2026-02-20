"""
Gemini Image Generation Script
Calls Gemini gemini-3-pro-image-preview to generate images for Xiaohongshu posts.
Compatible with Google Gemini API and third-party proxies.

Usage:
    python gemini_image_gen.py \
        --prompt "your image prompt" \
        --reference path/to/reference_image.png \
        --output output/2026-02-19_102600/2026-02-19-figure-1.png

Environment Variables (required):
    GEMINI_API_URL  - Gemini API endpoint URL
    GEMINI_API_KEY  - Your Gemini API key
"""

import argparse
import base64
import json
import os
import requests
from pathlib import Path


# ==================== Config ====================
# Set these via environment variables or --api-url / --api-key flags
DEFAULT_API_URL = os.environ.get("GEMINI_API_URL", "__YOUR_API_URL__")
DEFAULT_API_KEY = os.environ.get("GEMINI_API_KEY", "__YOUR_API_KEY__")
DEFAULT_MODEL = "gemini-3-pro-image-preview"
# =================================================


def encode_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_image_mime_type(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mime_map.get(ext, "image/png")


def generate_image(
    prompt: str,
    reference_path: str | None,
    output_path: str,
    api_url: str = DEFAULT_API_URL,
    api_key: str = DEFAULT_API_KEY,
    model: str = DEFAULT_MODEL,
) -> str:
    # Build URL with API key as query param (required by some proxies)
    url = f"{api_url.rstrip('/')}/v1beta/models/{model}:generateContent?key={api_key}"

    headers = {
        "Content-Type": "application/json",
    }

    # Build request parts
    parts = []

    # Add reference image if provided
    if reference_path and os.path.exists(reference_path):
        print(f"[INFO] Using reference image: {reference_path}")
        image_base64 = encode_image_to_base64(reference_path)
        mime_type = get_image_mime_type(reference_path)

        parts.append({
            "text": "Please use the following image as a style reference. Generate a new image matching this style:"
        })
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": image_base64,
            }
        })

    # Add text prompt
    parts.append({"text": prompt})

    request_body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["image", "text"],
            "temperature": 0.7,
        },
    }

    print(f"[INFO] Calling Gemini API...")
    print(f"[INFO] Model: {model}")
    print(f"[INFO] API URL: {url.split('?')[0]}")

    response = requests.post(url, headers=headers, json=request_body, timeout=180)
    response.raise_for_status()

    result = response.json()

    # Extract image from response
    candidates = result.get("candidates", [])
    if not candidates:
        print(f"[DEBUG] API Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        raise ValueError("Gemini API returned no results")

    content = candidates[0].get("content", {})
    resp_parts = content.get("parts", [])

    image_saved = False
    for part in resp_parts:
        if "inlineData" in part:  # Gemini API uses camelCase
            image_data = part["inlineData"].get("data", "")
            if image_data:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                with open(output_path, "wb") as f:
                    f.write(base64.b64decode(image_data))

                image_saved = True
                print(f"[SUCCESS] Image saved to: {output_path}")
                break

    if not image_saved:
        print(f"[DEBUG] API Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        raise ValueError("Failed to extract image data from Gemini API response")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Gemini Image Generation for Rednote Skill")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--reference", default=None, help="Reference image path")
    parser.add_argument("--output", required=True, help="Output image path")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Gemini API proxy URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Gemini API key")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name")
    args = parser.parse_args()

    try:
        result_path = generate_image(
            prompt=args.prompt,
            reference_path=args.reference,
            output_path=args.output,
            api_url=args.api_url,
            api_key=args.api_key,
            model=args.model,
        )
        print(f"\n[DONE] Image generation complete: {result_path}")
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] API request failed (HTTP {e.response.status_code}): {e}")
        print(f"[ERROR] Response: {e.response.text[:500]}")
        raise
    except Exception as e:
        print(f"[ERROR] Image generation failed: {e}")
        raise


if __name__ == "__main__":
    main()
