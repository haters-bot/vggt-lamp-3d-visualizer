// Local rendering helpers. Three.js r160; EDL shader written for this project.
import * as THREE from './vendor/three.module.js';

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
