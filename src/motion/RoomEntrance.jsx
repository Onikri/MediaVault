import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {gsap, useGSAP, reduced} from '../motion-icons/gsap-setup.js';
import {VaultMark} from './splash.jsx';
import './motion.css';

/* «Дверь сейфа»: a guest who opens a room link meets closed vault doors. The
   dial clicks while the room loads; once the lobby (or the room itself) is on
   screen, two sparks cut the seam with light from the centre outwards, light
   spills through the gap and the doors slide fully off-screen onto the room. */

// The room is ready when the lobby has lit its key art, the joined room page
// is up, or the lobby reports a closed room or an error. Never longer than 9 s.
function useRoomReady() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const started = performance.now();
    const check = () => {
      const up = document.querySelector('.room-lobby.is-lit, .watch-room-page, .room-lobby [role="alert"]');
      if (up || performance.now() - started > 9000) { setReady(true); return true; }
      return false;
    };
    if (check()) return;
    const timer = setInterval(() => { if (check()) clearInterval(timer); }, 120);
    return () => clearInterval(timer);
  }, []);
  return ready;
}

const seenKey = identity => 'mv_room_door:' + identity;

export default function RoomEntrance({identity}) {
  const [on, setOn] = useState(() => {
    if (reduced()) return false;
    try { return !sessionStorage.getItem(seenKey(identity)); } catch { return true; }
  });
  const ready = useRoomReady();
  useEffect(() => { if (!on) return; try { sessionStorage.setItem(seenKey(identity), '1'); } catch {} }, [on, identity]);
  if (!on) return null;
  return createPortal(<VaultDoors ready={ready} onDone={() => setOn(false)}/>, document.body);
}

function VaultDoors({ready, onDone}) {
  const root = useRef(null), st = useRef(null);
  const {contextSafe} = useGSAP(() => {
    const q = gsap.utils.selector(root);
    const intro = gsap.timeline()
      .fromTo(q('.vm-ring'), {drawSVG: '0%'}, {drawSVG: '100%', duration: .8, ease: 'power2.inOut'})
      .from(q('.vm-petal'), {scale: 0, rotation: -50, transformOrigin: '50% 100%', stagger: .05, duration: .55, ease: 'back.out(2)'}, .2)
      .from(q('.vm-hub'), {scale: 0, transformOrigin: '50% 50%', duration: .35, ease: 'back.out(3)'}, .55)
      .from(q('.rv-hint'), {opacity: 0, y: 8, duration: .4}, .6);
    // The dial keeps clicking a fifth of a turn while the room loads.
    const dial = gsap.timeline({repeat: -1, delay: intro.duration() + .1})
      .to(q('.vm-blossom'), {rotation: '+=72', svgOrigin: '96 96', duration: .32, ease: 'back.out(3)'})
      .to(q('.vm-hub'), {scale: 1.4, transformOrigin: '50% 50%', duration: .12, yoyo: true, repeat: 1}, '<.08')
      .to({}, {duration: .3});
    st.current = {intro, dial, q};
  }, {scope: root});

  const open = contextSafe(() => {
    const {intro, dial, q} = st.current;
    gsap.timeline({delay: Math.max(0, intro.duration() - intro.time()), onComplete: onDone})
      .add(() => dial.pause())
      .to(q('.vm-blossom'), {rotation: '+=72', svgOrigin: '96 96', duration: .32, ease: 'back.out(3)'})
      .to(q('.rv-hint'), {opacity: 0, duration: .25}, '<')
      .addLabel('cut', '+=.05')
      .fromTo(q('.rv-seam'), {scaleY: 0, opacity: 1}, {scaleY: 1, duration: .55, ease: 'power2.inOut'}, 'cut')
      .fromTo(q('.rv-spark-up'), {opacity: 1}, {top: '-4%', duration: .55, ease: 'power2.inOut'}, 'cut')
      .fromTo(q('.rv-spark-down'), {opacity: 1}, {top: '104%', duration: .55, ease: 'power2.inOut'}, 'cut')
      // Until the seam is fully lit the doors sit under one solid face, so no hairline shows early.
      .set(q('.rv-solid'), {display: 'none'}, 'cut+=.56')
      .to(q('.rv-rim'), {opacity: 1, duration: .45, ease: 'power2.out'}, 'cut+=.56')
      .fromTo(q('.rv-flare'), {opacity: 0, scaleX: .15}, {opacity: 1, scaleX: 1, duration: .35, ease: 'power2.out'}, 'cut+=.45')
      .to(q('.rv-seam'), {boxShadow: '0 0 18px 4px rgba(255,140,120,.95), 0 0 70px 18px rgba(238,60,53,.7)', duration: .25, yoyo: true, repeat: 1}, 'cut+=.5')
      .addLabel('part', 'cut+=.95')
      .to(q('.rv-left'), {xPercent: -56, duration: 1.15, ease: 'power4.inOut'}, 'part')
      .to(q('.rv-right'), {xPercent: 56, duration: 1.15, ease: 'power4.inOut'}, 'part')
      .to(q('.rv-flare'), {scaleX: 9, opacity: 0, duration: 1, ease: 'power2.out'}, 'part+=.1')
      .to(q('.rv-seam'), {opacity: 0, duration: .35}, 'part+=.15');
  });
  useEffect(() => { if (ready && st.current) open(); }, [ready]);

  const face = <div className="rv-face"><VaultMark/><p className="rv-hint">Открываем комнату</p></div>;
  return <div ref={root} className="room-entrance" role="status" aria-label="Открываем комнату">
    <div className="rv-door rv-left">{face}<span className="rv-rim"/></div>
    <div className="rv-door rv-right">{face}<span className="rv-rim"/></div>
    <div className="rv-door rv-solid">{face}</div>
    <div className="rv-light" aria-hidden="true">
      <span className="rv-flare"/>
      <span className="rv-seam"/>
      <span className="rv-spark rv-spark-up"/>
      <span className="rv-spark rv-spark-down"/>
    </div>
  </div>;
}
