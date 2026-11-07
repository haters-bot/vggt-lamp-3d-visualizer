// Local rendering helpers. Three.js r160; EDL shader written for this project.
import * as THREE from './vendor/three.module.js';

export function createCameraFrustum(position, forward, up, color, size, options = {}) {
  const emphasized = options.emphasized ?? false;
  const opacity = options.opacity ?? (emphasized ? 1 : 0.14);
  const direction = forward.clone().normalize();
  let vertical = up.clone().addScaledVector(direction, -up.dot(direction));
  if (vertical.lengthSq() < 1e-10) {
    vertical = Math.abs(direction.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
    vertical.addScaledVector(direction, -vertical.dot(direction));
  }
  vertical.normalize();
  const right = direction.clone().cross(vertical).normalize();
  vertical = right.clone().cross(direction).normalize();
  const center = position.clone().addScaledVector(direction, size);
  const halfHeight = size * 0.38;
  const halfWidth = halfHeight * 4 / 3;
  const corners = [
    center.clone().addScaledVector(right, -halfWidth).addScaledVector(vertical, halfHeight),
    center.clone().addScaledVector(right, halfWidth).addScaledVector(vertical, halfHeight),
    center.clone().addScaledVector(right, halfWidth).addScaledVector(vertical, -halfHeight),
    center.clone().addScaledVector(right, -halfWidth).addScaledVector(vertical, -halfHeight),
  ];
  const segmentPoints = [];
  for (const corner of corners) segmentPoints.push(position, corner);
  for (let i = 0; i < 4; i++) segmentPoints.push(corners[i], corners[(i + 1) % 4]);
  segmentPoints.push(position, center);
  const line = new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints(segmentPoints),
    new THREE.LineBasicMaterial({
      color, transparent: opacity < 1, opacity,
      depthTest: !emphasized, depthWrite: false,
    }),
  );
  line.renderOrder = emphasized ? 22 : 4;
  const group = new THREE.Group();
  group.add(line);
  if (emphasized) {
    const face = new THREE.BufferGeometry().setFromPoints(corners);
    face.setIndex([0, 1, 2, 0, 2, 3]);
    face.computeVertexNormals();
    const plane = new THREE.Mesh(face, new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: options.faceOpacity ?? 0.16,
      side: THREE.DoubleSide, depthTest: false, depthWrite: false,
    }));
    plane.renderOrder = 21;
    group.add(plane);
  }
  group.userData.frustumRole = options.role || 'ordinary';
  return group;
}

export function createTaperedTubeGeometry(curve, tubularSegments, radialSegments, startRadius, endRadius, startColor = null, endColor = null) {
  const segments = Math.max(8, Math.floor(tubularSegments));
  const sides = Math.max(3, Math.floor(radialSegments));
  const frames = curve.computeFrenetFrames(segments, false);
  const positions = [], normals = [], uvs = [], colors = [], indices = [];
  const colorA = startColor === null ? null : new THREE.Color(startColor);
  const colorB = endColor === null ? colorA : new THREE.Color(endColor);
  for (let i = 0; i <= segments; i++) {
    const u = i / segments;
    const center = curve.getPointAt(u);
    const radius = THREE.MathUtils.lerp(startRadius, endRadius, u);
    const color = colorA?.clone().lerp(colorB, u);
    for (let j = 0; j < sides; j++) {
      const angle = j / sides * Math.PI * 2;
      const normal = frames.normals[i].clone().multiplyScalar(Math.cos(angle))
        .addScaledVector(frames.binormals[i], Math.sin(angle)).normalize();
      positions.push(center.x + normal.x * radius, center.y + normal.y * radius, center.z + normal.z * radius);
      normals.push(normal.x, normal.y, normal.z);
      uvs.push(u, j / sides);
      if (color) colors.push(color.r, color.g, color.b);
    }
  }
  for (let i = 0; i < segments; i++) {
    for (let j = 0; j < sides; j++) {
      const next = (j + 1) % sides;
      const a = i * sides + j, b = (i + 1) * sides + j;
      const c = (i + 1) * sides + next, d = i * sides + next;
      indices.push(a, b, d, b, c, d);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  if (colors.length) geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex(indices);
  geometry.computeBoundingSphere();
  return geometry;
}

export function configureSplat(material) {
  const round = {value: true};
  material.userData.roundSplat = round;
  material.onBeforeCompile = shader => {
    shader.uniforms.roundSplat = round;
    shader.fragmentShader = 'uniform bool roundSplat;\n' + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <clipping_planes_fragment>',
      '#include <clipping_planes_fragment>\nif(roundSplat && length(gl_PointCoord-vec2(0.5))>0.5) discard;'
    );
  };
  material.customProgramCacheKey = () => 'circular-splat-v1';
  material.sizeAttenuation = true;
  material.transparent = false;
  material.depthWrite = true;
  material.needsUpdate = true;
}

export class EyeDomeRenderer {
  constructor(renderer) {
    this.renderer = renderer;
    this.target = new THREE.WebGLRenderTarget(1, 1, {
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter,
      depthBuffer: true, stencilBuffer: false,
    });
    this.target.depthTexture = new THREE.DepthTexture(1, 1, THREE.UnsignedIntType);
    this.uniforms = {
      colorMap: {value: this.target.texture}, depthMap: {value: this.target.depthTexture},
      texel: {value: new THREE.Vector2()}, nearClip: {value: 0.01}, farClip: {value: 10000},
    };
    const material = new THREE.ShaderMaterial({
      uniforms: this.uniforms, depthTest: false, depthWrite: false,
      vertexShader: 'varying vec2 uvScreen; void main(){uvScreen=uv;gl_Position=vec4(position.xy,0.,1.);}',
      fragmentShader: `
        uniform sampler2D colorMap, depthMap;
        uniform vec2 texel;
        uniform float nearClip, farClip;
        varying vec2 uvScreen;
        float eyeDepth(float d) {
          return (2.0*nearClip*farClip)/(farClip+nearClip-(2.0*d-1.0)*(farClip-nearClip));
        }
        void main() {
          vec4 color=texture2D(colorMap,uvScreen);
          float depth=texture2D(depthMap,uvScreen).r;
          float response=0.0;
          if(depth<0.999999) {
            float center=log2(max(eyeDepth(depth),nearClip));
            for(int i=0;i<8;i++) {
              float angle=float(i)*0.78539816339;
              vec2 sampleUV=uvScreen+vec2(cos(angle),sin(angle))*texel*2.0;
              float other=texture2D(depthMap,clamp(sampleUV,vec2(0.0),vec2(1.0))).r;
              if(other<0.999999) response+=max(0.0,center-log2(max(eyeDepth(other),nearClip)));
            }
          }
          gl_FragColor=vec4(color.rgb*exp(-response*3.0),color.a);
          #include <colorspace_fragment>
        }`,
    });
    this.scene = new THREE.Scene();
    this.scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.size = new THREE.Vector2();
  }
  render(scene, camera, enabled) {
    if (!enabled) { this.renderer.render(scene, camera); return; }
    this.renderer.getDrawingBufferSize(this.size);
    if (this.target.width !== this.size.x || this.target.height !== this.size.y)
      this.target.setSize(this.size.x, this.size.y);
    this.uniforms.texel.value.set(1 / this.size.x, 1 / this.size.y);
    this.uniforms.nearClip.value = camera.near;
    this.uniforms.farClip.value = camera.far;
    this.renderer.setRenderTarget(this.target);
    this.renderer.render(scene, camera);
    this.renderer.setRenderTarget(null);
    this.renderer.render(this.scene, this.camera);
  }
}
