import {useEffect, useRef} from 'react';
import {gsap, useGSAP, reduced, PETAL, SMALL_PETAL, ROT} from './gsap-setup.js';
import './motion-icons.css';

// Every glyph lives inside the 192-unit tile of the site icon: the ring's inner
// edge is 58 units from the centre, so all shapes stay within that circle.
// intro(tl,q) adds the entrance to the icon's timeline; hover(q) returns a new
// timeline whose end state looks identical to its start, so it can loop.

const SmallBlossom = ({className, petalClass = 'mi-accent'}) => <g className={className}>
  {ROT.map(r => <g key={r} transform={`rotate(${r})`}><g transform="translate(0 -1.5)"><path className={petalClass} d={SMALL_PETAL}/></g></g>)}
</g>;

const LP = 'M96 70C86 62 70 59 54 62V128C70 126 86 128 96 136Z';
const RP = 'M96 70C106 62 122 59 138 62V128C122 126 106 128 96 136Z';

// A real page turn: the right page lifts, curls over the spine and settles on
// the left, darkening as its back faces us. Ends hidden so it can loop.
const TURN = [
  'M96 70C104 57 117 48 130 46V114C117 115 104 122 96 136Z',
  'M96 70C99 55 101 45 101 40V108C101 115 99 124 96 136Z',
  'M96 70C88 57 75 48 62 46V114C75 115 88 122 96 136Z',
  LP
];
const pageFlip = q => {
  // GSAP can't tween CSS variables inside fill, so read the resolved colours.
  const front = getComputedStyle(q('.ribbon')[0]).fill, back = getComputedStyle(q('.pl')[0]).fill;
  return gsap.timeline()
  .set(q('.flip'), {morphSVG: RP, opacity: 1, fill: front})
  .to(q('.flip'), {keyframes: TURN.map(d => ({morphSVG: d})), duration: .9, ease: 'power2.inOut'})
  .to(q('.flip'), {fill: back, duration: .45, ease: 'power1.in'}, .2)
  .to(q('.lines-r'), {opacity: .25, duration: .2, yoyo: true, repeat: 1}, .05)
  .to(q('.pl'), {scaleY: 1.03, transformOrigin: '50% 100%', duration: .12, yoyo: true, repeat: 1}, .85)
  .to(q('.flip'), {opacity: 0, duration: .25}, .95);
};

export const GLYPHS = [
  {
    id: 'site', label: 'Значок сайта',
    render: () => <g className="blossom">
      {ROT.map(r => <g key={r} transform={`rotate(${r} 96 96)`}><g transform="translate(96 92)"><path className="mi-ink petal" d={PETAL}/></g></g>)}
      <circle className="mi-accent hub" cx="96" cy="96" r="8"/>
    </g>,
    intro: (tl, q) => tl
      .from(q('.petal'), {scale: 0, rotation: -50, transformOrigin: '50% 100%', duration: .7, stagger: .07, ease: 'back.out(2)'}, .3)
      .from(q('.hub'), {scale: 0, transformOrigin: '50% 50%', duration: .45, ease: 'back.out(3)'}, .75),
    hover: q => gsap.timeline()
      .to(q('.blossom'), {rotation: 72, svgOrigin: '96 96', duration: .7, ease: 'back.out(2.2)'})
      .to(q('.hub'), {scale: 1.5, transformOrigin: '50% 50%', duration: .18, yoyo: true, repeat: 1, ease: 'power2.out'}, 0)
      .set(q('.blossom'), {rotation: 0})
  },
  {
    id: 'home', label: 'Главная',
    // A small Japanese house: upturned eaves, a blossom crest under the ridge
    // and a sliding doorway that lights up warm when you come home.
    render: () => <>
      <rect className="mi-ink body" x="62" y="97" width="68" height="39" rx="5"/>
      <path className="mi-cut doorway" d="M85 136V119Q85 110 96 110Q107 110 107 119V136Z"/>
      <g className="glow"><path className="mi-accent" d="M85 136V119Q85 110 96 110Q107 110 107 119V136Z"/></g>
      <rect className="mi-ink shoji" x="85" y="110" width="11" height="26"/>
      <path className="mi-ink roof" d="M42 95C60 92 78 80 96 55C114 80 132 92 150 95C147 101 141 102 134 101H58C51 102 45 101 42 95Z"/>
      <g transform="translate(96 85) scale(.85)"><SmallBlossom className="crest" petalClass="mi-cut"/></g>
    </>,
    intro: (tl, q) => tl
      .from(q('.body'), {scaleY: 0, transformOrigin: '50% 100%', duration: .5, ease: 'power3.out'}, .3)
      .from(q('.roof'), {y: -46, opacity: 0, duration: .75, ease: 'bounce.out'}, .42)
      .to(q('.roof'), {scaleX: 1.06, scaleY: .9, transformOrigin: '50% 100%', duration: .09, yoyo: true, repeat: 1, ease: 'power1.out'}, .78)
      .from(q('.doorway'), {scaleY: 0, transformOrigin: '50% 100%', duration: .4, ease: 'back.out(2)'}, .75)
      .from(q('.shoji'), {x: 11, opacity: 0, duration: .5, ease: 'power3.out'}, .9)
      .from(q('.crest'), {scale: 0, rotation: -144, transformOrigin: '50% 50%', duration: .7, ease: 'back.out(2)'}, 1)
      .set(q('.glow'), {opacity: 0}, 0),
    hover: q => gsap.timeline()
      .to(q('.shoji'), {x: 11, duration: .3, ease: 'power2.inOut'})
      .fromTo(q('.glow'), {opacity: 0, scaleY: 0, transformOrigin: '50% 100%'}, {opacity: 1, scaleY: 1, duration: .3, ease: 'power2.out', immediateRender: false}, .12)
      .to(q('.roof'), {y: -7, duration: .16, ease: 'power2.out'}, .1)
      .to(q('.roof'), {y: 0, duration: .55, ease: 'bounce.out'}, .26)
      .to(q('.crest'), {rotation: 72, transformOrigin: '50% 50%', duration: .7, ease: 'back.out(2.2)'}, .1)
      .to(q('.glow'), {opacity: 0, duration: .35, ease: 'power1.in'}, .85)
      .to(q('.shoji'), {x: 0, duration: .4, ease: 'power2.inOut'}, .85)
      .set(q('.crest'), {rotation: 0})
  },
  {
    id: 'library', label: 'Библиотека',
    render: () => <>
      <path className="mi-stroke shelf" d="M60 134H132" strokeWidth="8"/>
      <rect className="mi-ink book" x="60" y="62" width="16" height="66" rx="4"/>
      <g className="book">
        <rect className="mi-ink" x="80" y="50" width="18" height="78" rx="4"/>
        <g transform="translate(89 86)"><path className="mi-accent mark" d={SMALL_PETAL}/></g>
      </g>
      <rect className="mi-ink book" x="102" y="68" width="15" height="60" rx="4"/>
      <g transform="rotate(-14 132 128)"><rect className="mi-ink mi-sep lean" x="118" y="68" width="14" height="60" rx="4"/></g>
    </>,
    intro: (tl, q) => tl
      .fromTo(q('.shelf'), {drawSVG: '50% 50%'}, {drawSVG: '0% 100%', duration: .5, ease: 'power2.out'}, .3)
      .from(q('.book'), {y: -70, opacity: 0, duration: .75, stagger: .08, ease: 'bounce.out'}, .35)
      .from(q('.lean'), {rotation: 14, y: -70, opacity: 0, transformOrigin: '100% 100%', duration: .85, ease: 'bounce.out'}, .6)
      .from(q('.mark'), {scale: 0, transformOrigin: '50% 100%', duration: .4, ease: 'back.out(3)'}, 1.1),
    hover: q => gsap.timeline()
      .to(q('.lean'), {rotation: 14, transformOrigin: '100% 100%', duration: .28, ease: 'power2.out'})
      .to(q('.lean'), {rotation: 0, duration: .7, ease: 'bounce.out'})
      .to(q('.book'), {y: -6, stagger: .05, duration: .15, yoyo: true, repeat: 1, ease: 'power1.out'}, 0)
  },
  {
    id: 'collection', label: 'Коллекция',
    render: () => <>
      <path className="mi-stroke tray" d="M56 100V122Q56 134 68 134H124Q136 134 136 122V100" strokeWidth="12"/>
      <g transform="translate(101 50)"><g className="drop"><path className="mi-ink" d={PETAL} transform="rotate(200) scale(1.15)"/></g></g>
    </>,
    intro: (tl, q) => tl
      .fromTo(q('.tray'), {drawSVG: '50% 50%'}, {drawSVG: '0% 100%', duration: .6, ease: 'power2.out'}, .3)
      .from(q('.drop'), {y: -60, x: 14, rotation: -60, opacity: 0, transformOrigin: '50% 0%', duration: 1, ease: 'bounce.out'}, .45)
      .to(q('.tray'), {scaleY: .9, transformOrigin: '50% 100%', duration: .1, yoyo: true, repeat: 1}, .95),
    hover: q => gsap.timeline()
      .to(q('.drop'), {y: -16, rotation: 18, transformOrigin: '50% 0%', duration: .25, ease: 'power2.out'})
      .to(q('.drop'), {y: 0, rotation: 0, duration: .7, ease: 'bounce.out'})
      .to(q('.tray'), {scaleY: .92, transformOrigin: '50% 100%', duration: .1, yoyo: true, repeat: 1}, .45)
  },
  {
    id: 'history', label: 'История',
    render: () => <>
      <path className="mi-stroke arc" d="M56.5 81.6A42 42 0 1 1 56.5 110.4" strokeWidth="9"/>
      <path className="mi-ink mi-round arrow" d="M45 80H68L56.5 94Z"/>
      <g className="hands">
        <path className="mi-stroke" d="M96 96V68" strokeWidth="8"/>
        <path className="mi-stroke" d="M96 96L114 106" strokeWidth="8"/>
      </g>
      <circle className="mi-accent hub" cx="96" cy="96" r="6"/>
    </>,
    intro: (tl, q) => tl
      .fromTo(q('.arc'), {drawSVG: '100% 100%'}, {drawSVG: '0% 100%', duration: .8, ease: 'power2.inOut'}, .3)
      .from(q('.arrow'), {scale: 0, transformOrigin: '50% 0%', duration: .35, ease: 'back.out(3)'}, 1)
      .from(q('.hands'), {rotation: 300, svgOrigin: '96 96', duration: 1.1, ease: 'power3.out'}, .35)
      .from(q('.hub'), {scale: 0, transformOrigin: '50% 50%', duration: .3}, .4),
    hover: q => gsap.timeline()
      .to(q('.hands'), {rotation: -360, svgOrigin: '96 96', duration: .9, ease: 'power2.inOut'})
      .to(q('.arrow'), {y: 4, duration: .15, yoyo: true, repeat: 1}, 0)
      .set(q('.hands'), {rotation: 0})
  },
  {
    id: 'profile', label: 'Профиль',
    render: () => <>
      <path className="mi-ink body" d="M62 134C62 114 76 104 96 104C116 104 130 114 130 134Z"/>
      <circle className="mi-ink head" cx="96" cy="76" r="18"/>
      <g transform="translate(113 60)"><SmallBlossom className="pin"/></g>
    </>,
    intro: (tl, q) => tl
      .from(q('.body'), {y: 24, opacity: 0, duration: .55, ease: 'power3.out'}, .3)
      .from(q('.head'), {scale: 0, transformOrigin: '50% 50%', duration: .5, ease: 'back.out(2.5)'}, .45)
      .from(q('.pin'), {scale: 0, rotation: -144, transformOrigin: '50% 14px', duration: .7, ease: 'back.out(2)'}, .7),
    hover: q => gsap.timeline()
      .to(q('.head'), {y: -6, duration: .18, ease: 'power2.out', yoyo: true, repeat: 1})
      .to(q('.pin'), {rotation: 72, transformOrigin: '50% 14px', duration: .7, ease: 'back.out(2.5)'}, 0)
      .set(q('.pin'), {rotation: 0})
  },
  {
    id: 'anime', label: 'Аниме',
    render: () => <>
      <path className="mi-stroke line" d="M56 78H68" strokeWidth="8"/>
      <path className="mi-stroke line" d="M48 96H68" strokeWidth="8"/>
      <path className="mi-stroke line" d="M56 114H68" strokeWidth="8"/>
      <path className="mi-ink mi-round12 play" d="M84 64V128L136 96Z"/>
    </>,
    intro: (tl, q) => tl
      .from(q('.play'), {x: -36, opacity: 0, duration: .6, ease: 'power3.out'}, .35)
      .fromTo(q('.line'), {drawSVG: '100% 100%'}, {drawSVG: '0% 100%', duration: .35, stagger: .06, ease: 'power2.out'}, .55),
    hover: q => gsap.timeline()
      .to(q('.play'), {x: 10, duration: .16, ease: 'power2.in'})
      .to(q('.play'), {x: 0, duration: .6, ease: 'elastic.out(1,.35)'})
      .fromTo(q('.line'), {drawSVG: '100% 100%'}, {drawSVG: '0% 100%', duration: .35, stagger: .05, ease: 'power2.out', immediateRender: false}, .1)
  },
  {
    id: 'manga', label: 'Манга',
    render: () => <>
      <g className="bubble">
        <ellipse className="mi-ink" cx="96" cy="88" rx="46" ry="35"/>
        <path className="mi-ink mi-round" d="M72 114L62 136L102 120Z"/>
      </g>
      {[76, 96, 116].map(x => <circle key={x} className="mi-cut dot" cx={x} cy="88" r="6.5"/>)}
    </>,
    intro: (tl, q) => tl
      .from(q('.bubble'), {scale: 0, transformOrigin: '25% 100%', duration: .8, ease: 'elastic.out(1,.55)'}, .3)
      .from(q('.dot'), {scale: 0, transformOrigin: '50% 50%', stagger: .08, duration: .35, ease: 'back.out(3)'}, .7),
    hover: q => gsap.timeline()
      .to(q('.dot'), {y: -8, duration: .16, stagger: .09, ease: 'power2.out', yoyo: true, repeat: 1})
      .to(q('.bubble'), {scale: 1.05, transformOrigin: '25% 100%', duration: .16, yoyo: true, repeat: 1}, 0)
  },
  {
    id: 'ranobe', label: 'Ранобэ',
    render: () => <>
      <path className="mi-ink page pl" d={LP}/>
      <path className="mi-ink page pr" d={RP}/>
      <path className="mi-cut-s lines lines-l" d="M64 82C72 80 80 81 86 84M64 96C72 94 80 95 86 98M64 110C72 108 80 109 86 112" strokeWidth="4.5"/>
      <path className="mi-cut-s lines lines-r" d="M106 84C112 81 120 80 128 82M106 98C112 95 120 94 128 96M106 112C112 109 120 108 128 110" strokeWidth="4.5"/>
      <path className="mi-accent flip" d={RP} opacity="0"/>
      <path className="mi-accent ribbon" d="M110 124V143L116 137L122 143V122Z"/>
    </>,
    intro: (tl, q) => tl
      .from(q('.pl'), {scaleX: 0, transformOrigin: '100% 50%', duration: .6, ease: 'power3.out'}, .3)
      .from(q('.pr'), {scaleX: 0, transformOrigin: '0% 50%', duration: .6, ease: 'power3.out'}, .3)
      .fromTo(q('.lines'), {drawSVG: '0%'}, {drawSVG: '100%', duration: .5, stagger: .12, ease: 'power2.out'}, .7)
      .from(q('.ribbon'), {scaleY: 0, transformOrigin: '50% 0%', duration: .6, ease: 'elastic.out(1,.45)'}, .8)
      .add(pageFlip(q), 1.15),
    hover: q => gsap.timeline()
      .add(pageFlip(q))
      .to(q('.ribbon'), {rotation: 10, transformOrigin: '50% 0%', duration: .2, yoyo: true, repeat: 1, ease: 'sine.inOut'}, .55)
  },
  {
    id: 'book', label: 'Книги',
    render: () => <g className="bk">
      <rect className="mi-ink" x="64" y="54" width="64" height="84" rx="8"/>
      <path className="mi-cut-s" d="M76 60V132" strokeWidth="4"/>
      <path className="mi-cut-s" d="M86 104H116M86 116H106" strokeWidth="5"/>
      <path className="mi-accent mark" d="M100 50H116V88L108 81L100 88Z"/>
    </g>,
    intro: (tl, q) => tl
      .from(q('.bk'), {scaleX: 0, transformOrigin: '0% 50%', duration: .6, ease: 'power3.out'}, .3)
      .from(q('.mark'), {scaleY: 0, transformOrigin: '50% 0%', duration: .7, ease: 'elastic.out(1,.45)'}, .75),
    hover: q => gsap.timeline()
      .to(q('.mark'), {scaleY: 1.25, transformOrigin: '50% 0%', duration: .18, ease: 'power2.out'})
      .to(q('.mark'), {scaleY: 1, duration: .6, ease: 'elastic.out(1,.35)'})
      .to(q('.bk'), {rotation: -5, transformOrigin: '50% 100%', duration: .18, yoyo: true, repeat: 1, ease: 'power1.inOut'}, 0)
  },
  {
    id: 'music', label: 'Музыка',
    render: () => <g className="notes">
      <path className="mi-ink beam" d="M79 68L131 56V72L79 84Z"/>
      <g className="note"><path className="mi-stroke" d="M83 124V72" strokeWidth="8"/><ellipse className="mi-ink" cx="71" cy="126" rx="15" ry="11" transform="rotate(-20 71 126)"/></g>
      <g className="note"><path className="mi-stroke" d="M127 114V62" strokeWidth="8"/><ellipse className="mi-ink" cx="115" cy="116" rx="15" ry="11" transform="rotate(-20 115 116)"/></g>
    </g>,
    intro: (tl, q) => tl
      .from(q('.note'), {y: -50, opacity: 0, stagger: .14, duration: .8, ease: 'bounce.out'}, .3)
      .from(q('.beam'), {scaleX: 0, transformOrigin: '0% 50%', duration: .5, ease: 'power3.out'}, .75),
    hover: q => gsap.timeline()
      .to(q('.notes'), {y: -8, rotation: -7, svgOrigin: '96 130', duration: .18, ease: 'power2.out'})
      .to(q('.notes'), {y: 0, rotation: 0, duration: .75, ease: 'elastic.out(1,.32)'})
  },
  {
    id: 'bell', label: 'Уведомления',
    // A bell with a blossom clapper: it swings on hover and the clapper rings.
    render: () => <g className="bell">
      <path className="mi-ink dome" d="M96 50C76 50 64 66 64 86V108L54 122H138L128 108V86C128 66 116 50 96 50Z"/>
      <rect className="mi-ink" x="90" y="42" width="12" height="12" rx="6"/>
      <g transform="translate(96 132)"><g className="clapper"><circle className="mi-accent" r="10"/></g></g>
    </g>,
    intro: (tl, q) => tl
      .from(q('.dome'), {scaleY: 0, transformOrigin: '50% 100%', duration: .55, ease: 'back.out(2)'}, .3)
      .from(q('.clapper'), {scale: 0, duration: .4, ease: 'back.out(3)'}, .7),
    hover: q => gsap.timeline()
      .to(q('.bell'), {keyframes: [{rotation: 14}, {rotation: -11}, {rotation: 7}, {rotation: -4}, {rotation: 0}], svgOrigin: '96 44', duration: .9, ease: 'power1.inOut'})
      .to(q('.clapper'), {keyframes: [{x: -6}, {x: 6}, {x: -3}, {x: 0}], duration: .8, ease: 'power1.inOut'}, .05)
  },
  {
    id: 'rooms', label: 'Комнаты',
    render: () => <g transform="rotate(-45 96 96)">
      <g className="link l1"><rect className="mi-stroke" x="50" y="81" width="58" height="30" rx="15" strokeWidth="11"/></g>
      <g className="link l2">
        <rect className="mi-cut-s" x="84" y="81" width="58" height="30" rx="15" strokeWidth="19"/>
        <rect className="mi-stroke" x="84" y="81" width="58" height="30" rx="15" strokeWidth="11"/>
      </g>
      <g transform="translate(96 96) rotate(45)"><g className="spark" opacity="0"><SmallBlossom/></g></g>
    </g>,
    intro: (tl, q) => tl
      .from(q('.l1'), {x: -50, opacity: 0, duration: .7, ease: 'back.out(2)'}, .3)
      .from(q('.l2'), {x: 50, opacity: 0, duration: .7, ease: 'back.out(2)'}, .36)
      .fromTo(q('.spark'), {opacity: 1, scale: .3}, {opacity: 0, scale: 1.5, transformOrigin: '50% 50%', duration: .6, ease: 'power2.out', immediateRender: false}, .8),
    hover: q => gsap.timeline()
      .to(q('.l1'), {x: -8, duration: .18, ease: 'power2.out'})
      .to(q('.l2'), {x: 8, duration: .18, ease: 'power2.out'}, 0)
      .to(q('.link'), {x: 0, duration: .6, ease: 'elastic.out(1,.4)'}, .18)
      .fromTo(q('.spark'), {opacity: 1, scale: .3}, {opacity: 0, scale: 1.5, transformOrigin: '50% 50%', duration: .6, ease: 'power2.out', immediateRender: false}, .2)
  }
];

export const glyph = id => GLYPHS.find(g => g.id === id);

// variant: 'a' сейф (dark tile + ring), 'b' бутон (red tile), 'c' линия (bare glyph
// in the text colour, for navigation), 'r' кольцо (ring and glyph without a tile).
// The hover gesture plays when the pointer enters the surrounding button or link,
// so the whole control animates its icon. Decorative unless `label` is given.
export function MotionIcon({glyph: g, variant = 'c', size = 22, delay = 0, label, className = ''}) {
  const root = useRef(null), state = useRef({});
  const {contextSafe} = useGSAP(() => {
    const q = gsap.utils.selector(root);
    const intro = gsap.timeline({delay});
    if (variant === 'a' || variant === 'b') intro.from(q('.mi-tile'), {scale: .7, opacity: 0, transformOrigin: '50% 50%', duration: .5, ease: 'power3.out'}, 0);
    if (variant === 'a' || variant === 'r') intro.fromTo(q('.mi-ring'), {drawSVG: '0%'}, {drawSVG: '100%', duration: .9, ease: 'power2.inOut'}, .12);
    g.intro(intro, q);
    state.current = {intro, q, hover: null};
    if (reduced()) intro.progress(1);
  }, {scope: root, dependencies: [variant, g], revertOnUpdate: true});
  const play = contextSafe(() => {
    const s = state.current;
    if (reduced() || !s.intro || s.intro.isActive()) return;
    if (!s.hover) s.hover = g.hover(s.q);
    else if (!s.hover.isActive()) s.hover.restart();
  });
  useEffect(() => {
    const target = root.current?.closest('button,a,[role=button],[role=tab]') || root.current;
    target?.addEventListener('pointerenter', play);
    return () => target?.removeEventListener('pointerenter', play);
  }, [play]);
  const viewBox = variant === 'c' ? '34 34 124 124' : variant === 'r' ? '26 26 140 140' : '0 0 192 192';
  return <svg ref={root} className={`mi mi-${variant} ${className}`.trim()} viewBox={viewBox} width={size} height={size}
    {...(label ? {role: 'img', 'aria-label': label} : {'aria-hidden': true, focusable: 'false'})}>
    {(variant === 'a' || variant === 'b') && <rect className="mi-tile" width="192" height="192" rx="44"/>}
    {(variant === 'a' || variant === 'r') && <circle className="mi-ring" cx="96" cy="96" r="64" transform="rotate(-90 96 96)"/>}
    <g transform={variant === 'b' ? 'translate(96 96) scale(1.16) translate(-96 -96)' : undefined}>{g.render()}</g>
  </svg>;
}

/** Shorthand: <SiteIcon name="home"/> renders that glyph as a line icon. */
export function SiteIcon({name, ...props}) {
  const value = glyph(name);
  return value ? <MotionIcon glyph={value} {...props}/> : null;
}
