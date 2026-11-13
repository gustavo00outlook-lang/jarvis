uniform float uSize;
uniform float uTime;
attribute float aRandom;
void main() {
  vec3 pos = position;
  // Pequena oscilacao orbital
  float t = uTime * 0.5 + aRandom * 6.28;
  pos.x += sin(t) * 0.05;
  pos.y += cos(t * 1.3) * 0.05;

  vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
  gl_PointSize = uSize * (300.0 / -mvPosition.z) * (0.5 + aRandom * 0.5);
  gl_Position = projectionMatrix * mvPosition;
}
