# MuxDeck landing page

The static site in `dist/` contains all its assets and needs no Node dependencies or build step.

![MuxDeck landing page with the Windows download and desktop app preview](../docs/landing.png)

From this directory, start a loopback preview:

```powershell
python -m http.server 8530 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:8530. The Windows button links to the public MuxDeck preview. To offer a local build instead, serve a copy of `dist/` with the executable at `downloads/MuxDeck-Setup-x64.exe` in that copy. The loopback page detects that file and uses it as the download. The demo copy and installer can stay outside Git. [MuxDeck Windows preview](https://github.com/Sanjeeth-Prakash/MuxDeck/releases/tag/v0.2.0)

The screenshot tabs show the installed app. The PowerShell example uses the local gateway on port 8520 and needs a gateway key from your own running instance. The landing page itself can be served by any static host.

The [backdrop](dist/assets/night-crossing.webp) was made with built-in image generation and compressed to WebP.

<details>
<summary>Backdrop prompt</summary>

> Create a 16:9 widescreen cinematic maritime background for a desktop AI app landing page. Photorealistic low-key film still of a weathered black three-masted sailing ship from the age of sail, under outstretched dark tattered canvas, cutting through moody North Atlantic waves at night. Ship is small to medium and entirely within the right two-fifths of the frame, with a warm, muted copper glow breaking through heavy clouds in the right sky behind the rigging. The left 55 percent is very dark mostly empty blue-black mist with faint cloud and water texture, usable behind large white website copy. Black slate sea, subtle film grain, soft depth, elegant gritty pirate atmosphere. Horizon below center. Palette is charcoal navy, desaturated steel blue and a hint of warm amber on the right. Dark overall, preserve readably silhouetted rigging on the right. No text, no logos, no visible symbols, no people, no typography, no borders, no interface. This is background art, not a website mockup.

</details>

The [MuxDeck octopus logo](../assets/muxdeck-mark.png) uses the same white pixel artwork on the landing page and in the dashboard. Its [Windows icon](../assets/muxdeck.ico) includes sizes for the shortcut, taskbar, and installer. The artwork was created with built-in image generation.

<details>
<summary>Logo prompt</summary>

> One original square logo icon for MuxDeck, inspired by small retro nautical octopus emblems. A clearly recognizable white OCTOPUS, not a skull: a smooth stepped bulbous octopus mantle, two small dark eyes, and eight short curling tentacles fanned symmetrically to either side and below. Negative space between arms is bold and clean. Tentacle ends curl back in simple square hooks, with two tips ending in small blocky squares like data connectors. Head is about a third of the height, limbs fill the lower two thirds. Use a single compact silhouette centered within a solid pure black square, comfortable even padding about 11 percent. White graphic only plus black background and black cutouts. Hard square stair steps on a coarse 32 by 32 conceptual pixel grid. Looks hand-pixeled using nearest-neighbor, no anti-aliasing, no gradients, no shading, no texture, no outline, no extra decorations. Highly legible 24px software logo. No text, no lettering, no border, no tricorn hat, no skull, no crossbones, no other icon, no mockup.

</details>
