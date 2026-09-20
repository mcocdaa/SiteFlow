import hashlib


def generate_svg_cover(slug: str, title: str, project_type: str = "html") -> str:
    """Generates a procedural, minimalist vector grid SVG placeholder for project covers.
    
    Aesthetic: Clean tech-restrained engineering grid with subtle coordinates,
    deterministic accent hue based on slug hash, and elegant monogram centerpiece.
    """
    raw_hash = hashlib.sha256(slug.encode()).hexdigest()
    hue = sum(slug.encode()) % 360
    accent_hsl = f"hsl({hue}, 70%, 55%)"
    accent_soft = f"hsl({hue}, 65%, 45%)"
    
    char = (title[:1] if title else "S").upper()
    type_label = {
        "html": "HTML5 APP",
        "zip": "ZIP BUNDLE",
        "link": "EXTERNAL",
        "space": "WORKSPACE",
        "resume": "RESUME",
        "blog": "PUBLICATION",
    }.get(project_type.lower(), project_type.upper())

    # Build subtle intersection cross markers
    crosses = []
    for x in (160, 320, 480, 640):
        for y in (100, 200, 300, 400):
            crosses.append(
                f'<path d="M {x-4} {y} H {x+4} M {x} {y-4} V {y+4}" stroke="{accent_hsl}" stroke-opacity="0.3" stroke-width="1" />'
            )
    crosses_svg = "\n    ".join(crosses)

    svg = f"""<svg class="cover-svg" viewBox="0 0 800 500" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="glow-{slug}" cx="50%" cy="45%" r="65%">
      <stop offset="0%" stop-color="{accent_hsl}" stop-opacity="0.16" />
      <stop offset="60%" stop-color="{accent_soft}" stop-opacity="0.04" />
      <stop offset="100%" stop-color="#090b10" stop-opacity="0" />
    </radialGradient>
    <pattern id="grid-{slug}" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="currentColor" stroke-opacity="0.06" stroke-width="1" />
      <circle cx="40" cy="40" r="1" fill="currentColor" fill-opacity="0.12" />
    </pattern>
    <linearGradient id="frame-grad-{slug}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{accent_hsl}" stop-opacity="0.6" />
      <stop offset="100%" stop-color="{accent_hsl}" stop-opacity="0.1" />
    </linearGradient>
  </defs>

  <!-- Dark Atmospheric Background -->
  <rect width="800" height="500" fill="#0d1117" />
  <!-- Radial Accent Glow -->
  <rect width="800" height="500" fill="url(#glow-{slug})" />
  <!-- Precision Vector Grid Pattern -->
  <rect width="800" height="500" fill="url(#grid-{slug})" style="color: #ffffff;" />

  <!-- Grid Intersection Markers -->
  <g>
    {crosses_svg}
  </g>

  <!-- Technical Diagonal Guide Lines (Subtle) -->
  <line x1="0" y1="0" x2="800" y2="500" stroke="{accent_hsl}" stroke-opacity="0.04" stroke-width="1" stroke-dasharray="6 6" />
  <line x1="800" y1="0" x2="0" y2="500" stroke="{accent_hsl}" stroke-opacity="0.04" stroke-width="1" stroke-dasharray="6 6" />

  <!-- Frame Corners / Technical Brackets -->
  <path d="M 28 44 L 28 28 L 44 28" fill="none" stroke="{accent_hsl}" stroke-opacity="0.45" stroke-width="1.5" />
  <path d="M 772 44 L 772 28 L 756 28" fill="none" stroke="{accent_hsl}" stroke-opacity="0.45" stroke-width="1.5" />
  <path d="M 28 456 L 28 472 L 44 472" fill="none" stroke="{accent_hsl}" stroke-opacity="0.45" stroke-width="1.5" />
  <path d="M 772 456 L 772 472 L 756 472" fill="none" stroke="{accent_hsl}" stroke-opacity="0.45" stroke-width="1.5" />

  <!-- Technical Header Meta -->
  <text x="48" y="42" fill="#8b949e" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="11" font-weight="500" letter-spacing="1.5">SITEFLOW // ARTIFACT #{raw_hash[:6].upper()}</text>
  <text x="752" y="42" text-anchor="end" fill="{accent_hsl}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="11" font-weight="600" letter-spacing="1">● READY</text>

  <!-- Centerpiece Monogram & Typography -->
  <g transform="translate(400, 240)">
    <!-- Outer Geometric Frame -->
    <rect x="-60" y="-60" width="120" height="120" rx="20" fill="#161b22" stroke="url(#frame-grad-{slug})" stroke-width="1.5" />
    <!-- Subtle Inner Glow Border -->
    <rect x="-52" y="-52" width="104" height="104" rx="14" fill="none" stroke="{accent_hsl}" stroke-opacity="0.15" stroke-width="1" stroke-dasharray="4 4" />
    <!-- Monogram Character -->
    <text x="0" y="16" text-anchor="middle" fill="#f0f6fc" font-family="-apple-system, 'SF Pro Display', 'PingFang SC', sans-serif" font-size="52" font-weight="700">{char}</text>
  </g>

  <!-- Centerpiece Type Label -->
  <g transform="translate(400, 340)">
    <rect x="-65" y="-12" width="130" height="24" rx="12" fill="#21262d" stroke="{accent_hsl}" stroke-opacity="0.3" stroke-width="1" />
    <text x="0" y="4" text-anchor="middle" fill="{accent_hsl}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="10" font-weight="600" letter-spacing="1.5">{type_label}</text>
  </g>

  <!-- Technical Footer Meta -->
  <text x="48" y="468" fill="#484f58" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="10" letter-spacing="1">SLUG: {slug[:24]}</text>
  <text x="752" y="468" text-anchor="end" fill="#484f58" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="10" letter-spacing="1">SAFE ORIGIN // SANDBOXED</text>
</svg>"""
    return svg
