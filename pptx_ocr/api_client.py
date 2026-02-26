"""
PaddleOCR Layout Parsing API client.

API: POST /layout-parsing
  - fileType=0 for PDF
  - fileType=1 for image
Response: result.layoutParsingResults[].markdown.{text, images}
"""
import base64
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests


@dataclass
class ParseResult:
    """One page/slide worth of parsing output."""
    markdown_text: str
    # rel_path -> raw bytes of the image
    images: dict[str, bytes] = field(default_factory=dict)


class LayoutParsingClient:
    def __init__(self, api_url: str, token: str, timeout: int = 120):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
        }

    def parse_file(
        self,
        file_path: Path,
        file_type: int,
        use_chart_recognition: bool = False,
        max_retries: int = 3,
        retry_delay: float = 10.0,
    ) -> list[ParseResult]:
        """
        Send a file to the layout parsing API, with retry on 5xx/timeout errors.

        Args:
            file_path: Path to PDF (file_type=0) or image (file_type=1)
            file_type: 0=PDF, 1=image
            use_chart_recognition: enable chart analysis (slower)
            max_retries: number of retry attempts on server/network errors
            retry_delay: base wait time in seconds between retries (multiplied by attempt#)

        Returns:
            List of ParseResult, one per page/document unit.
        """
        file_path = Path(file_path)
        with open(file_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode("ascii")

        payload = {
            "file": file_data,
            "fileType": file_type,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useTextlineOrientation": False,
            "useChartRecognition": use_chart_recognition,
        }

        last_exc: Exception = RuntimeError("No attempts made")
        resp = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    self.api_url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                break  # success — exit retry loop
            except requests.HTTPError as e:
                last_exc = e
                if resp is not None and resp.status_code < 500:
                    raise  # 4xx: not retryable
                if attempt < max_retries:
                    wait = retry_delay * attempt
                    print(
                        f"\n    [WARN] HTTP {resp.status_code if resp else '?'}, "
                        f"retrying in {wait:.0f}s (attempt {attempt}/{max_retries})...",
                        end=" ", flush=True,
                    )
                    time.sleep(wait)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if attempt < max_retries:
                    wait = retry_delay * attempt
                    print(
                        f"\n    [WARN] {type(e).__name__}, "
                        f"retrying in {wait:.0f}s (attempt {attempt}/{max_retries})...",
                        end=" ", flush=True,
                    )
                    time.sleep(wait)
        else:
            raise last_exc

        data = resp.json()
        results: list[ParseResult] = []

        for item in data.get("result", {}).get("layoutParsingResults", []):
            md_text = item.get("markdown", {}).get("text", "")
            image_urls: dict[str, str] = item.get("markdown", {}).get("images", {})

            images: dict[str, bytes] = {}
            for rel_path, url in image_urls.items():
                try:
                    img_resp = requests.get(url, timeout=30)
                    if img_resp.status_code == 200:
                        images[rel_path] = img_resp.content
                except Exception as e:
                    print(f"  [WARN] Failed to download image {rel_path}: {e}")

            results.append(ParseResult(markdown_text=md_text, images=images))

        return results

    def health_check(self) -> bool:
        """Check if the service is reachable with current credentials."""
        if not self.token:
            return False
        try:
            resp = requests.post(
                self.api_url,
                json={},
                headers=self._headers,
                timeout=10,
            )
            return resp.status_code < 500
        except Exception:
            return False
