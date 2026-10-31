# Original placeholder artwork

Generated with the built-in image-generation tool, two independent new-image
generations. No external API key, reference photograph, title poster or character
was used. The owner requested mature painted anime atmosphere, without chibi,
kawaii mascots or text. This is fallback art only; real covers take priority.

Prompt set / art direction:

- **Screen media:** a quiet coastal railway station at dusk, a distant train,
  painted clouds and sea, detailed hand-painted anime background, warm lights,
  restrained cinematic atmosphere, portrait cover composition, no lettering,
  no logo and no characters. Output: `src/blossom/placeholders/screen.webp`.
- **Printed media:** a sunlit reading room with bookshelves and a view through
  the window, painterly hand-drawn anime background, paper and wood textures,
  soft natural light, restrained mature atmosphere, portrait cover composition,
  no lettering, no logo and no characters. Output:
  `src/blossom/placeholders/print.webp`.

Generation originals and task files are stored in `.codex-local/` in the project.
The published copies are resized to 480 × 640 and encoded as WebP using ffmpeg;
this conversion does not redraw or edit their content. Together they are about
132 KiB. No full generation originals are shipped in the application bundle.
