import { Geometry, Mesh, RenderTexture, Shader, type Renderer } from "pixi.js";

/** Deferred 2D lighting: the colour world and a parallel normal-map world are
 *  rendered to two screen-sized textures; one full-screen quad combines them
 *  with a sun (directional), ambient light and up to MAX_LIGHTS point lights. */
export const MAX_LIGHTS = 16;
export type LightMode = "off" | "tint" | "lit";

const vertex = `
in vec2 aPosition;
in vec2 aUV;
out vec2 vUV;
uniform mat3 uProjectionMatrix;
uniform mat3 uWorldTransformMatrix;
uniform mat3 uTransformMatrix;
void main() {
  mat3 mvp = uProjectionMatrix * uWorldTransformMatrix * uTransformMatrix;
  gl_Position = vec4((mvp * vec3(aPosition, 1.0)).xy, 0.0, 1.0);
  vUV = aUV;
}`;

const fragment = `
in vec2 vUV;
out vec4 finalColor;
uniform sampler2D uColorTex;
uniform sampler2D uNormalTex;
uniform vec2 uResolution;
uniform float uMode;
uniform vec3 uTint;
uniform vec3 uAmbient;
uniform vec3 uSunDir;
uniform vec3 uSunColor;
uniform float uBands;
uniform float uLightCount;
uniform vec4 uLights[${MAX_LIGHTS}];
uniform vec4 uLightColors[${MAX_LIGHTS}];

float band(float v) { return uBands > 0.0 ? floor(v * uBands + 0.5) / uBands : v; }

void main() {
  vec4 c = texture(uColorTex, vUV);
  if (c.a <= 0.0) { finalColor = vec4(0.0); return; }
  if (uMode < 0.5) { finalColor = c; return; }
  if (uMode < 1.5) { finalColor = vec4(c.rgb * uTint, c.a); return; }
  vec3 n = normalize(texture(uNormalTex, vUV).rgb * 2.0 - 1.0);
  vec3 light = uAmbient + uSunColor * band(max(dot(n, uSunDir), 0.0));
  vec2 p = vUV * uResolution;
  for (int i = 0; i < ${MAX_LIGHTS}; i++) {
    if (float(i) >= uLightCount) break;
    vec4 L = uLights[i];
    vec2 dv = L.xy - p;
    float dist = length(dv);
    if (dist > L.z) continue;
    vec3 ld = normalize(vec3(dv.x, -dv.y, L.w));
    float att = 1.0 - dist / L.z;
    att *= att;
    light += uLightColors[i].rgb * uLightColors[i].a * att * (0.3 + 0.7 * band(max(dot(n, ld), 0.0)));
  }
  finalColor = vec4(min(c.rgb * light, vec3(c.a)), c.a);
}`;

export class Lighting {
  colorRT: RenderTexture;
  normalRT: RenderTexture;
  quad: Mesh<Geometry, Shader>;
  private shader: Shader;
  lights: { x: number; y: number; radius: number; height: number; color: [number, number, number]; intensity: number }[] = [];

  constructor(private renderer: Renderer, w: number, h: number) {
    this.colorRT = RenderTexture.create({ width: w, height: h, resolution: renderer.resolution });
    this.normalRT = RenderTexture.create({ width: w, height: h, resolution: renderer.resolution });
    const geometry = new Geometry({
      attributes: { aPosition: [0, 0, 1, 0, 1, 1, 0, 1], aUV: [0, 0, 1, 0, 1, 1, 0, 1] },
      indexBuffer: [0, 1, 2, 0, 2, 3],
    });
    this.shader = Shader.from({
      gl: { vertex, fragment },
      resources: {
        uColorTex: this.colorRT.source,
        uNormalTex: this.normalRT.source,
        lightUniforms: {
          uResolution: { value: [w, h], type: "vec2<f32>" },
          uMode: { value: 2, type: "f32" },
          uTint: { value: [1, 1, 1], type: "vec3<f32>" },
          uAmbient: { value: [0.6, 0.6, 0.65], type: "vec3<f32>" },
          uSunDir: { value: [0.3, 0.5, 0.8], type: "vec3<f32>" },
          uSunColor: { value: [0.6, 0.6, 0.55], type: "vec3<f32>" },
          uBands: { value: 0, type: "f32" },
          uLightCount: { value: 0, type: "f32" },
          uLights: { value: new Float32Array(MAX_LIGHTS * 4), type: "vec4<f32>", size: MAX_LIGHTS },
          uLightColors: { value: new Float32Array(MAX_LIGHTS * 4), type: "vec4<f32>", size: MAX_LIGHTS },
        },
      },
    });
    this.quad = new Mesh({ geometry, shader: this.shader });
    this.quad.scale.set(w, h);
  }

  resize(w: number, h: number) {
    this.colorRT.resize(w, h);
    this.normalRT.resize(w, h);
    this.quad.scale.set(w, h);
    this.u.uResolution = [w, h];
  }

  private get u() {
    return (this.shader.resources.lightUniforms as { uniforms: Record<string, unknown> }).uniforms as Record<string, any>;
  }

  set(params: { mode: LightMode; tint: number[]; ambient: number[]; sunDir: number[]; sunColor: number[]; bands: number }) {
    const u = this.u;
    u.uMode = params.mode === "off" ? 0 : params.mode === "tint" ? 1 : 2;
    u.uTint = params.tint;
    u.uAmbient = params.ambient;
    const [x, y, z] = params.sunDir;
    const l = Math.hypot(x, y, z) || 1;
    u.uSunDir = [x / l, y / l, z / l];
    u.uSunColor = params.sunColor;
    u.uBands = params.bands;
    const pos = u.uLights as Float32Array, col = u.uLightColors as Float32Array;
    const n = Math.min(MAX_LIGHTS, this.lights.length);
    for (let i = 0; i < n; i++) {
      const L = this.lights[i];
      pos.set([L.x, L.y, L.radius, L.height], i * 4);
      col.set([L.color[0], L.color[1], L.color[2], L.intensity], i * 4);
    }
    u.uLightCount = n;
  }

  /** Render both worlds into their textures (call once per frame before the stage renders). */
  render(colorWorld: import("pixi.js").Container, normalWorld: import("pixi.js").Container) {
    this.renderer.render({ container: normalWorld, target: this.normalRT, clear: true, clearColor: [0.5, 0.5, 1, 1] });
    this.renderer.render({ container: colorWorld, target: this.colorRT, clear: true, clearColor: [0, 0, 0, 0] });
  }

  destroy() {
    this.colorRT.destroy(true);
    this.normalRT.destroy(true);
  }
}

// ---------------------------------------------------------------- sky model
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const mix3 = (a: number[], b: number[], t: number) => a.map((v, i) => lerp(v, b[i], t));
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
export type Weather = "clear" | "snow" | "blizzard" | "fog";
export const WEATHER_LABEL: Record<Weather, string> = { clear: "晴", snow: "小雪", blizzard: "暴风雪", fog: "雾" };

/** Sun/moon direction (x right, y up on screen, z toward viewer), colours and the
 *  old multiply tint, from the hour (0-24) and the weather. */
export function sky(h: number, weather: Weather) {
  const dayT = (h - 6) / 12; // 0 at 6:00, 1 at 18:00
  const isDay = dayT > 0 && dayT < 1;
  const a = dayT * Math.PI;
  let sunDir: number[], sunColor: number[], ambient: number[];
  if (isDay) {
    const elev = Math.sin(a);
    // keep a low sun from going flat: games light dawn/dusk for readability, not physics
    sunDir = [Math.cos(a), 0.45, Math.max(0.35, elev)];
    const warm = clamp01(1 - elev * 1.6);
    sunColor = mix3([0.6, 0.58, 0.53], [0.98, 0.58, 0.32], warm).map((v) => v * (0.62 + 0.38 * clamp01(elev * 2.5)));
    ambient = mix3([0.5, 0.52, 0.58], [0.56, 0.42, 0.42], warm);
  } else {
    sunDir = [-0.35, 0.55, 0.75];
    sunColor = [0.22, 0.27, 0.46];
    ambient = [0.2, 0.24, 0.38];
  }
  // twilight blend so dawn/dusk do not snap
  const tw = h < 6 ? clamp01((h - 5) / 1) : h > 18 ? clamp01((19 - h) / 1) : 1;
  if (!isDay) {
    ambient = mix3(ambient, [0.5, 0.38, 0.42], tw);
    sunColor = mix3(sunColor, [0.6, 0.32, 0.22], tw);
  }
  const k = weather === "blizzard" ? 0.35 : weather === "fog" ? 0.5 : weather === "snow" ? 0.72 : 1;
  sunColor = sunColor.map((v) => v * k);
  if (weather !== "clear") {
    const grey = weather === "blizzard" ? 0.16 : weather === "fog" ? 0.1 : 0.05;
    ambient = ambient.map((v) => v + grey * (isDay ? 1 : 0.4));
  }
  // legacy multiply tint (the previous lab look), for comparison
  const DAY = [1, 1, 1], DUSK = [1, 0.77, 0.56], NIGHT = [0.34, 0.39, 0.65];
  let tint = DAY;
  if (h >= 17 && h < 19) tint = mix3(DAY, DUSK, (h - 17) / 2);
  else if (h >= 19 && h < 20) tint = mix3(DUSK, NIGHT, h - 19);
  else if (h >= 5 && h < 7) tint = mix3(NIGHT, DAY, (h - 5) / 2);
  else if (h >= 20 || h < 5) tint = NIGHT;
  const night = !isDay && tw < 0.6;
  return { sunDir, sunColor, ambient, tint, night };
}
