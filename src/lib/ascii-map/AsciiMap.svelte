<script lang="ts">
  import { goto } from "$app/navigation";
  import { renderAsciiMap } from "./renderer";
  import { loadImage } from "./assets";
  import type { AsciiMapOptions } from "./types";
  import { CONTINENTS, type ContinentId } from "./continents";

  const BASE_W = 1000;
  const BASE_H = 520;

  let canvas: HTMLCanvasElement;
  let container: HTMLDivElement;

  let img = $state<HTMLImageElement | null>(null);
  let maskData = $state<ImageData | null>(null);

  let width = $state(BASE_W);
  let height = $state(BASE_H);

  let hovered = $state<ContinentId | null>(null);
  let debugOverlay = $state(false);

  let opts = $state<AsciiMapOptions>({
    step: 12,
    fontSize: 9,
    opacity: 0.75,
    chars: "loremipsumartgroup",
    background: "black",
    color: "white"
  });

  let autoStep = $derived.by((): number => {
    if (width >= 1200) return 10;
    if (width >= 900) return 12;
    if (width >= 600) return 14;
    return 16;
  });

  function rebuildMask() {
    if (!img) return;

    const off = document.createElement("canvas");
    off.width = width;
    off.height = height;

    const offCtx = off.getContext("2d");
    if (!offCtx) return;

    offCtx.clearRect(0, 0, width, height);
    offCtx.drawImage(img, 0, 0, width, height);

    maskData = offCtx.getImageData(0, 0, width, height);
  }

  function draw() {
    if (!canvas || !maskData) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    renderAsciiMap({
      ctx,
      mask: maskData,
      width,
      height,
      opts: { ...opts, step: autoStep }
    });
  }

  $effect(() => {
    if (img) return;

    (async () => {
      img = await loadImage("/world-mask.png");
      rebuildMask();
      draw();
    })();
  });

  $effect(() => {
    if (!container) return;

    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (!cr) return;

      const w = Math.max(320, Math.floor(cr.width));
      const h = Math.floor(w * (BASE_H / BASE_W));

      width = w;
      height = h;

      if (canvas) {
        canvas.width = w;
        canvas.height = h;
      }

      rebuildMask();
      draw();
    });

    ro.observe(container);
    return () => ro.disconnect();
  });

  $effect(() => {
    if (!maskData) return;
    draw();
  });

  function onContinentClick(id: ContinentId) {
    goto(`/explore/continent/${id}`);
  }

  function onKeyActivate(e: KeyboardEvent, id: ContinentId) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onContinentClick(id);
    }
  }

  function toggleDebug() {
    debugOverlay = !debugOverlay;
  }
</script>

<div
  bind:this={container}
  style="
    position: relative;
    width: 100%;
    max-width: 1200px;
    aspect-ratio: 1000 / 520;
    overflow: hidden;
  "
>
  <canvas
    bind:this={canvas}
    style="
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      pointer-events: none;
      image-rendering: pixelated;
    "
  ></canvas>
  
<!-- The SVG overlay is used for continent hit-testing and interactivity... -->
  <svg
    viewBox={`0 0 ${BASE_W} ${BASE_H}`}
    preserveAspectRatio="none"
    aria-label="Continent overlay"
    style="
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      z-index: 10;
    "
  >
    {#if debugOverlay}
      <image
        href="/world-map.png"
        x="0"
        y="0"
        width={BASE_W}
        height={BASE_H}
        opacity="0.25"
        preserveAspectRatio="none"
        pointer-events="none"
      />
    {/if}

    {#each Object.entries(CONTINENTS) as [id, c]}
      <path
        d={c.path}
        fill="transparent"
        stroke={debugOverlay ? "rgba(0,255,255,0.65)" : "transparent"}
        stroke-width={debugOverlay ? "2" : "0"}
        pointer-events="all"
        tabindex="0"
        role="link"
        aria-label={c.label}
        style="cursor: pointer;"
        onmouseenter={() => (hovered = id as ContinentId)}
        onmouseleave={() => (hovered = null)}
        onclick={() => onContinentClick(id as ContinentId)}
        onfocus={() => (hovered = id as ContinentId)}
        onblur={() => (hovered = null)}
        onkeydown={(e) => onKeyActivate(e as KeyboardEvent, id as ContinentId)}
      />
    {/each}

  </svg>

  {#if hovered}
    <div
      style="
        position: absolute;
        left: 12px;
        top: 12px;
        z-index: 20;
        font-size: 12px;
        padding: 4px 8px;
        border-radius: 6px;
        background: rgba(0,0,0,0.55);
        border: 1px solid rgba(255,255,255,0.15);
        color: white;
      "
    >
      {CONTINENTS[hovered].label}
    </div>
  {/if}

  <button
    type="button"
    onclick={toggleDebug}
    style="
      position: absolute;
      right: 12px;
      top: 12px;
      z-index: 20;
      font-size: 12px;
      padding: 4px 8px;
      border-radius: 6px;
      background: rgba(0,0,0,0.55);
      border: 1px solid rgba(255,255,255,0.15);
      color: white;
    "
  >
    {debugOverlay ? "Hide debug" : "Show debug"}
  </button>
</div>