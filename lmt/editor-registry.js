// SPDX-License-Identifier: AGPL-3.0-or-later
// MediaVault owns its page queue; upstream editor publishes its normal events.
export function markDone(src){document.dispatchEvent(new CustomEvent('lmt:translation-status',{detail:{src,status:'done'}}));}
export function markIdle(src){document.dispatchEvent(new CustomEvent('lmt:translation-status',{detail:{src,status:'idle'}}));}
