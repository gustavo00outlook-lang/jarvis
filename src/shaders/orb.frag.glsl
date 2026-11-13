// JARVIS Orb fragment shader
// Fresnel edge + holographic rainbow shift + chromatic aberration in-shader + subtle scanlines for cinematic holo
// Cores reagem ao estado e audio (stronger chromatic/pulse on speaking; red on confirm via uniform)

varying vec3 vNormal;
varying vec3 vPosition;
varying vec2 vUv;

uniform vec3 uSphereColor;
uniform float uOpacity;
uniform float uTime;
uniform float uChromaticAberration;
uniform float uAudioLevel; // used for extra shimmer/scan on voice

// === HSV conversion helpers ===
vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    // === Fresnel: borda brilha mais que centro ===
    vec3 viewDir = normalize(cameraPosition - vPosition);
    float fresnel = pow(1.0 - abs(dot(viewDir, normalize(vNormal))), 2.0);

    // === Holographic rainbow shift ===
    vec3 nW = normalize(vNormal);
    float shift = nW.x * 0.5 + nW.y * 0.2 + nW.z * 0.1;
    shift += sin(vPosition.x * 5.0 + uTime * 0.5) * 0.012;
    shift += cos(vPosition.y * 4.0 - uTime * 0.3) * 0.012;
    shift = fract(shift);

    // Para JARVIS: rainbow eh dominantemente cyan (saturation reduzida) - clean futuristic
    vec3 rainbow = hsv2rgb(vec3(shift * 0.22 + 0.52, 0.58, 1.0));

    // === Chromatic aberration in-shader (sem post-processing) - stronger on high uChromatic (speaking) ===
    vec3 hsv = rgb2hsv(uSphereColor);
    float aberrationAmount = uChromaticAberration * fresnel * (0.9 + uAudioLevel * 0.35);

    vec3 hsvR = hsv; hsvR.x = fract(hsv.x + aberrationAmount * 0.16);
    vec3 colorR = hsv2rgb(hsvR);
    vec3 colorG = uSphereColor;
    vec3 hsvB = hsv; hsvB.x = fract(hsv.x - aberrationAmount * 0.16);
    vec3 colorB = hsv2rgb(hsvB);

    vec3 color = vec3(colorR.r, colorG.g, colorB.b);

    // Mistura holografica nas bordas (fresnel) - richer for 3D layered depth
    float holoIntensity = fresnel * 0.68 + 0.18;
    color = mix(color, rainbow, holoIntensity * 0.42);

    // Boost de borda + audio reactive rim
    color += fresnel * uChromaticAberration * 0.17;
    color += uAudioLevel * fresnel * 0.09;

    // Variacao sutil de brilho + shimmer (more alive)
    float brightness = 1.0 + sin(vPosition.x * 3.0 + uTime) * 0.11;
    brightness += sin(vPosition.y * 2.5 - uTime * 0.8) * 0.11;
    float shimmer = sin(vPosition.x * 8.0 + vPosition.y * 6.0 + uTime * 2.0) * 0.045 + 0.955;
    brightness *= shimmer;

    color *= brightness;

    // === Subtle scanlines inside orb layers (for holographic monitor/CRT Insta feel, stronger with audio) ===
    float scan = sin(vPosition.y * 38.0 + uTime * 6.5) * 0.5 + 0.5;
    float scan2 = sin(vPosition.x * 29.0 - uTime * 4.2) * 0.5 + 0.5;
    float scanMix = mix(scan, scan2, 0.4) * (0.04 + uAudioLevel * 0.065);
    color = mix(color, color * 0.82, scanMix * fresnel * 0.7);

    gl_FragColor = vec4(color, uOpacity);
}
