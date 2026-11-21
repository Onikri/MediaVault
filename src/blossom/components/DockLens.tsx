import {useEffect, useId, useRef, useState} from 'react';

// Encode the lateral ray offset through a rounded glass rim in red and green.
// A flat centre has a vertical normal and therefore zero displacement.
function lensMap(width: number, height: number) {
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(width / 2);
  canvas.height = Math.ceil(height / 2);
  const ctx = canvas.getContext('2d');
  if (!ctx) return '';
  const pixels = ctx.createImageData(canvas.width, canvas.height);
  const radius = height / 2;
  const bevel = Math.min(radius, 6);
  for (let y = 0; y < canvas.height; y++) {
    for (let x = 0; x < canvas.width; x++) {
      const px = (x + .5) * width / canvas.width;
      const dx = px - Math.max(radius, Math.min(width - radius, px));
      const dy = (y + .5) * height / canvas.height - radius;
      const distance = Math.hypot(dx, dy);
      const slope = Math.min(1, Math.max(0, 1 - (radius - distance) / bevel));
      const incidence = Math.asin(slope);
      const refracted = Math.asin(slope / 1.5);
      const shift = Math.sin(incidence - refracted) / (distance || 1);
      const i = (y * canvas.width + x) * 4;
      pixels.data[i] = 128 - 127 * dx * shift;
      pixels.data[i + 1] = 128 - 127 * dy * shift;
      pixels.data[i + 3] = 255;
    }
  }
  ctx.putImageData(pixels, 0, 0);
  return canvas.toDataURL();
}

export default function DockLens() {
  const id = 'dock-lens-' + useId().replace(/[^a-z0-9-]/gi, '');
  const ref = useRef<SVGSVGElement>(null);
  const [map, setMap] = useState('');
  useEffect(() => {
    const dock = ref.current?.parentElement;
    // Chromium composites SVG displacement filters against the live DOM backdrop.
    if (!dock || !('chrome' in window) || !CSS.supports('backdrop-filter', 'url(#lens)')) return;
    let timer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (dock.offsetWidth && dock.offsetHeight) setMap(lensMap(dock.offsetWidth, dock.offsetHeight));
      }, 80);
    });
    observer.observe(dock);
    return () => { observer.disconnect(); clearTimeout(timer); };
  }, []);
  useEffect(() => {
    const dock = ref.current?.parentElement;
    if (!dock || !map) return;
    dock.style.setProperty('--dock-refraction', 'url("#' + id + '")');
    return () => { dock.style.removeProperty('--dock-refraction'); };
  }, [id, map]);
  return <svg ref={ref} width="0" height="0" style={{position:'absolute',pointerEvents:'none'}} aria-hidden="true" focusable="false">
    <defs><filter id={id} x="0%" y="0%" width="100%" height="100%" colorInterpolationFilters="sRGB">
      {map && <feImage href={map} width="100%" height="100%" preserveAspectRatio="none" result="lens"/>}
      <feDisplacementMap in="SourceGraphic" in2="lens" xChannelSelector="R" yChannelSelector="G" scale="8"/>
    </filter></defs>
  </svg>;
}
