// Particle fragment - dots circulares brilhantes
uniform vec3 uColor;

void main() {
  // gl_PointCoord vai de 0..1 dentro do ponto
  vec2 center = gl_PointCoord - 0.5;
  float dist = length(center);

  // Soft circle: opaco no centro, fade ate borda
  if (dist > 0.5) discard;
  float alpha = 1.0 - smoothstep(0.2, 0.5, dist);

  gl_FragColor = vec4(uColor, alpha);
}
