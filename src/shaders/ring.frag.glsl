// Ring fragment shader - linhas finas brilhantes com gradiente
uniform float uTime;
uniform vec3 uColor;
uniform float uOpacity;

varying vec2 vUv;

void main() {
  // Distancia radial do centro (UV 0.5, 0.5)
  vec2 centered = vUv - 0.5;
  float dist = length(centered);

  // Cria um anel: alpha alto perto de raio 0.5, baixa nas bordas
  float ringInner = smoothstep(0.42, 0.45, dist);
  float ringOuter = 1.0 - smoothstep(0.49, 0.50, dist);
  float ring = ringInner * ringOuter;

  // Energia rotacionando (segmentos)
  float angle = atan(centered.y, centered.x);
  float segments = sin(angle * 16.0 + uTime * 2.0) * 0.5 + 0.5;
  ring *= mix(0.6, 1.0, segments);

  // Cor com glow
  vec3 color = uColor * (1.5 + sin(uTime * 3.0) * 0.3);

  gl_FragColor = vec4(color, ring * uOpacity);
}
