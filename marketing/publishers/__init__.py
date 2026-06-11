# Platform publishers for the marketing video pipeline.
# Each module exposes: async publish(video_path, metadata) -> str | None
# (the published video URL, or a platform reference when no URL exists).
