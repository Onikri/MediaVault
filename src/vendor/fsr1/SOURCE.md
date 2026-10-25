AMD FidelityFX FSR 1.0.2, MIT. mpv luma port by agyild.
https://gist.github.com/agyild/82219c545228d70c5604f865ce0b0ce5
Original SHA256: 56d8597fc6b7bf6d13f8c3b2bdf1cdc43b06175d51746aab44cf1dca16929b9e
WebGL2 adapter in fsr-shaders.js: RGBA video → EASU luma → RCAS → original interpolated chroma. No HDR/PQ conversion; SDR only.
