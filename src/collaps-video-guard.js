export const SLATE_WIDTH = 16;
export const SLATE_HEIGHT = 9;

// Quantized luminance from the slogan and QR areas of the observed slate.
// Both areas must match. Include the variant shown before the slogan appears.
const slogan = [
 'cddeffffefeeeeeffefdcbcccdd9cdddcdee769cefffe',
 'cddeffffeffffffffeffffffffeffffffffeceffffffe',
];
const qrArea = 'eeeffa9aefa89ef989ef';

export function isCollapsSlate(rgba) {
 function matches(pattern, x, y, width, tolerance) {
  let error = 0;
  for (let i = 0; i < pattern.length; i++) {
   const offset = ((y + Math.floor(i / width)) * SLATE_WIDTH + x + i % width) * 4;
   const gray = .213 * rgba[offset] + .715 * rgba[offset + 1] + .072 * rgba[offset + 2];
   error += Math.abs(gray - parseInt(pattern[i], 16) * 17);
  }
  return error <= pattern.length * tolerance;
 }
 return matches(qrArea, 11, 0, 5, 17) && slogan.some(pattern => matches(pattern, 2, 1, 9, 18));
}

export function watchCollapsFrames(video, onSlate) {
 if (!video) return;
 const canvas = video.ownerDocument.createElement('canvas');
 canvas.width = SLATE_WIDTH;
 canvas.height = SLATE_HEIGHT;
 const context = canvas.getContext('2d', {willReadFrequently:true});
 if (!context) return;
 context.imageSmoothingQuality = 'high';
 const events = ['loadeddata', 'playing', 'seeked', 'timeupdate'];
 let checkedAt = -Infinity;
 const stop = () => events.forEach(event => video.removeEventListener(event, check));
 function check(event) {
  if (video.readyState < 2 || video.seeking || !video.videoWidth) return;
  const now = performance.now();
  if (event?.type === 'timeupdate' && now - checkedAt < 300) return;
  checkedAt = now;
  let slate;
  try {
   context.drawImage(video, 0, 0, SLATE_WIDTH, SLATE_HEIGHT);
   slate = isCollapsSlate(context.getImageData(0, 0, SLATE_WIDTH, SLATE_HEIGHT).data);
  } catch (error) {
   if (error.name === 'SecurityError') stop();
   return;
  }
  if (slate) {
   stop();
   onSlate();
  }
 }
 events.forEach(event => video.addEventListener(event, check));
 return stop;
}
