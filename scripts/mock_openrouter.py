"""
Mock OpenRouter server for keyless integration testing.

Serves canned-but-plausible responses for every LLM call the pipeline
makes (signal analysis, trend analysis, mechanic mapping, gap analysis,
concept generation, template theming, SEO descriptions, FLUX images),
dispatching on the request's system prompt. Lets scripts/dry_run.py
exercise the full cycle without an OpenRouter key or spend.

Usage:
    python scripts/mock_openrouter.py [port]      # default 8901
Then point the pipeline at it:
    OPENROUTER_BASE_URL=http://127.0.0.1:8901/api/v1
    OPENROUTER_API_KEY=mock

All generated text is TOS-clean (AutoValidator scans concept.json).
"""
import base64
import io
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8901

USAGE = {"prompt_tokens": 50, "completion_tokens": 120, "cost": 0.0001}

SIGNALS = {
    "signals": [
        {
            "genre": "cozy island tycoon",
            "mechanic_tag": "idle_tycoon",
            "signal_strength": 0.85,
            "source": "roblox_games",
            "sustained_ccu_indicator": True,
        },
        {
            "genre": "creature collecting",
            "mechanic_tag": "pet_collect",
            "signal_strength": 0.75,
            "source": "youtube",
            "sustained_ccu_indicator": True,
        },
    ]
}

TRENDS = {
    "pre_arrival_trends": [
        {
            "trend_name": "axolotl aquarium craze",
            "platform_origin": "tiktok",
            "velocity_score": 0.8,
            "estimated_days_to_roblox": 7,
            "suggested_mechanic": "pet_collect",
        }
    ]
}

GAP = {
    "similarity_score": 0.45,
    "closest_existing_game": "Mega Tycoon World",
    "differentiation_suggestions": [
        "add a seasonal island theme",
        "weave in a creature companion system",
    ],
}

THEME_WORDS = [
    "Sunny Harbor", "Crystal Meadow", "Star Grove", "Maple Falls",
    "Coral Bay", "Breezy Peak", "Golden Orchard", "Misty Hollow",
]

CONCEPT_TITLES = {
    "idle_tycoon": "Sunny Harbor Tycoon",
    "pet_collect": "Axolotl Aquarium Adventure",
    "survival_horror": "Midnight Maze Escape",
    "incremental_sim": "Giant Garden Grower",
    "obby": "Cloud Hop Challenge",
    "rpg_dungeon": "Crystal Cavern Quest",
}


def make_concept(mechanic: str) -> dict:
    title = CONCEPT_TITLES.get(mechanic, "Sunny Harbor Tycoon")
    return {
        "game_title": title,
        "tagline": "Build, collect, and grow your dream world!",
        "mechanic_tag": mechanic,
        "core_loop": (
            "Earn coins from your plots, buy upgrades, unlock new areas, "
            "and prestige for permanent boosts."
        ),
        "systems": ["plots", "upgrades", "shop", "prestige", "daily rewards"],
        "monetization": {
            "game_passes": [
                {"name": "Double Coins", "price_robux": 199, "benefit": "2x coin income"},
                {"name": "Auto Collect", "price_robux": 299, "benefit": "hands-free collection"},
            ],
            "currency_name": "Coins",
            "shop_items": [
                {"name": "Sparkle Trail", "price": 500, "type": "cosmetic"},
                {"name": "Speed Boost", "price": 250, "type": "boost"},
            ],
            "vip_server": True,
        },
        "toolbox_keywords": ["low poly tree", "wooden pier", "treasure chest"],
        "target_genre_account": "idle",
    }


def make_png_data_url() -> str:
    """1280x720 two-tone PNG via Pillow (already in requirements)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1280, 720), (70, 130, 180))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 480, 1280, 720], fill=(34, 139, 84))
    draw.ellipse([1020, 60, 1200, 240], fill=(255, 215, 70))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def chat_response(content: str, images: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if images:
        message["images"] = images
    return {
        "id": "mock-completion",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": dict(USAGE),
    }


def build_response(body: dict) -> dict:
    # FLUX image generation (AssetGenerator)
    if "image" in (body.get("modalities") or []):
        return chat_response(
            "", images=[{"type": "image_url", "image_url": {"url": make_png_data_url()}}]
        )

    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m.get("role") == "system"), "")
    user = next((m["content"] for m in messages if m.get("role") == "user"), "")

    # MetaScout signal extraction
    if "game market analyst" in system:
        return chat_response(json.dumps(SIGNALS))

    # TrendPredictor pre-arrival trends
    if "gaming trend analyst" in system:
        return chat_response(json.dumps(TRENDS))

    # MechanicMapper — echo back every input id with its hint mechanic
    if "Map each incoming trend" in system:
        ids = re.findall(r"'id': (\d+)", user)
        hints = re.findall(r"'hint_mechanic': '(\w+)'", user)
        mappings = [
            {"id": int(i), "mechanic_tag": h, "confidence": 0.9}
            for i, h in zip(ids, hints)
        ]
        return chat_response(json.dumps({"mappings": mappings}))

    # GapAnalyzer differentiation scoring
    if "similarity_score" in system:
        return chat_response(json.dumps(GAP))

    # ConceptGenerator — full concept for the seed's mechanic
    if "Expand the seed opportunity" in system or "Expand the seed" in system:
        match = re.search(r"mechanic_tag: (\w+)", user)
        mechanic = match.group(1) if match else "idle_tycoon"
        return chat_response(json.dumps(make_concept(mechanic)))

    # LuauAgent template theming — fill every requested placeholder
    if "theming a Roblox game template" in system:
        placeholders = re.findall(r"\{\{[A-Z0-9_]+\}\}", user)
        values = {
            p: THEME_WORDS[i % len(THEME_WORDS)]
            for i, p in enumerate(dict.fromkeys(placeholders))
        }
        return chat_response(json.dumps(values))

    # AssetGenerator / marketer description writing
    if "SEO-optimized" in system or "Rewrite this Roblox game description" in system:
        return chat_response(
            "Build your dream harbor, collect adorable creatures, and unlock "
            "amazing upgrades! 🌟 Prestige for permanent boosts and climb the "
            "leaderboards with friends. New content every week! 🏝️"
        )

    # Unknown prompt — return empty JSON object so chat_json parses
    return chat_response("{}")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            payload = json.dumps(build_response(body)).encode()
            status = 200
        except Exception as exc:  # malformed request — surface as 500
            payload = json.dumps({"error": str(exc)}).encode()
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):  # quiet
        sys.stderr.write("mock_openrouter: %s\n" % (fmt % args))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock OpenRouter listening on http://127.0.0.1:{port}/api/v1")
    server.serve_forever()


if __name__ == "__main__":
    main()
