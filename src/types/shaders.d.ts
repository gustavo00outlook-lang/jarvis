// Allows importing .glsl / .vert / .frag files as raw strings (handled by webpack asset/source in next.config.js)
declare module "*.glsl" {
  const content: string;
  export default content;
}

declare module "*.vert" {
  const content: string;
  export default content;
}

declare module "*.frag" {
  const content: string;
  export default content;
}
