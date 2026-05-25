# Image Generation

Generate images using the built-in `image_gen` tool (gpt-image-2).

## Instructions

1. Use the `image_gen` tool to generate images based on the user's description.
2. Save generated images to the working directory with timestamped filenames: `codex-image-YYYYMMDD-HHMMSS.png` (use `-1.png`, `-2.png` suffixes for multiple).
3. Never overwrite existing files.
4. After generation, report the saved file path(s) and dimensions.

## Parameters from user prompt

Extract these if specified, otherwise use defaults:
- **Size**: 1024x1024(default), 1024x1536(portrait), 1536x1024(landscape)
- **Quality**: auto, low, medium, high(default)
- **Count**: 1(default), up to 10

## Notes

- The sandbox must be `workspace-write` for file saving.
- Generated images initially land in `~/.codex/generated_images/` — copy them to the specified output directory.
