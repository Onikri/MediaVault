// The player sits in a plain card (the design's player card). The former
// scroll-driven SVG aperture is gone; the wrapper keeps its class for layout.
export default function PlaybackReveal({children}){
 return <div className="title-playback-reveal is-revealed">{children}</div>;
}
