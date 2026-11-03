// No dependencies beyond the bundled Three.js. All inputs are GLB-local points.
import * as THREE from './vendor/three.module.js';

export function solve3(matrix, values) {
  const rows = matrix.map((row, i) => [...row, values[i]]);
  for (let col=0; col<3; col++) {
    let pivot=col;
    for(let i=col+1;i<3;i++) if(Math.abs(rows[i][col])>Math.abs(rows[pivot][col]))pivot=i;
    if(Math.abs(rows[pivot][col])<1e-12)throw new Error('相机轨迹退化，无法拟合环绕中心');
    [rows[col],rows[pivot]]=[rows[pivot],rows[col]];
    const scale=rows[col][col];for(let k=col;k<4;k++)rows[col][k]/=scale;
    for(let i=0;i<3;i++)if(i!==col){const factor=rows[i][col];for(let k=col;k<4;k++)rows[i][k]-=factor*rows[col][k];}
  }
  return rows.map(row=>row[3]);
}

export function fitOrbit(points, smallestEigenvector) {
  if(points.length<3)throw new Error(`角度放置至少需要 3 个相机，实际 ${points.length}`);
  const mean=points.reduce((a,p)=>a.add(p),new THREE.Vector3()).divideScalar(points.length);
  const covariance=[[0,0,0],[0,0,0],[0,0,0]];
  for(const p of points){const d=p.clone().sub(mean).toArray();for(let i=0;i<3;i++)for(let j=0;j<3;j++)covariance[i][j]+=d[i]*d[j];}
  const normal=smallestEigenvector(covariance),u=points[0].clone().sub(mean);
  u.addScaledVector(normal,-u.dot(normal)).normalize();
  const v=normal.clone().cross(u).normalize(),matrix=[[0,0,0],[0,0,0],[0,0,0]],rhs=[0,0,0];
  for(const p of points){const d=p.clone().sub(mean),x=d.dot(u),y=d.dot(v),row=[2*x,2*y,1],r2=x*x+y*y;
    for(let i=0;i<3;i++){rhs[i]+=row[i]*r2;for(let j=0;j<3;j++)matrix[i][j]+=row[i]*row[j];}}
  const [cx,cy,c]=solve3(matrix,rhs),radius=Math.sqrt(c+cx*cx+cy*cy);
  if(!Number.isFinite(radius)||radius<=0)throw new Error(`无效拟合半径：${radius}`);
  return {center:mean.addScaledVector(u,cx).addScaledVector(v,cy),normal,u,v,radius};
}

export function relativeBearing(point, source, orbit) {
  const project=p=>{const d=p.clone().sub(orbit.center);return d.addScaledVector(orbit.normal,-d.dot(orbit.normal)).normalize();};
  return Math.acos(THREE.MathUtils.clamp(project(point).dot(project(source)),-1,1))*180/Math.PI;
}

// Geodesic rotation has no direction. Choose the FIRST crossing while advancing
// in input order; never use the selected target to choose a more favorable branch.
export function pointAtAngle(spline, points, sourceIndex, degrees, orbit) {
  if(!Number.isFinite(degrees)||degrees<0||degrees>180)throw new Error(`rotation_angle_deg 应在 [0,180]，实际 ${degrees}`);
  const start=sourceIndex/(points.length-1),source=points[sourceIndex];
  let previous=start,previousValue=0,best=start,bestError=degrees;
  const steps=8192;
  for(let i=0;i<=steps;i++){
    const t=start+(1-start)*i/steps,value=relativeBearing(spline.getPoint(t),source,orbit);
    if(Math.abs(value-degrees)<bestError){best=t;bestError=Math.abs(value-degrees);}
    if(value>=degrees && previousValue<=degrees){
      let lo=previous,hi=t;
      for(let k=0;k<30;k++){const mid=(lo+hi)/2;if(relativeBearing(spline.getPoint(mid),source,orbit)<degrees)lo=mid;else hi=mid;}
      const found=(lo+hi)/2;return {t:found,point:spline.getPoint(found),outside:false};
    }
    previous=t;previousValue=value;
  }
  return {t:best,point:spline.getPoint(best),outside:true};
}

export function validateCache(cache) {
  if(!cache||!Array.isArray(cache.images)||cache.images.length<2)throw new Error('缓存 images 必须含至少两张图片');
  if(new Set(cache.images).size!==cache.images.length||cache.images.some(x=>typeof x!=='string'||!x||/[\\/]/.test(x)))throw new Error('缓存图片名重复或含路径');
  if(cache.index_base!==undefined&&cache.index_base!==0)throw new Error('缓存必须使用从 0 开始的输入序号');
  if(!cache.pairs||typeof cache.pairs!=='object'||Array.isArray(cache.pairs))throw new Error('缓存缺少 pairs 对象');
  const entries=Object.entries(cache.pairs);if(!entries.length)throw new Error('缓存 pairs 为空');
  for(const [key,value] of entries){
    if(!/^(0|[1-9]\d*)->(0|[1-9]\d*)$/.test(key))throw new Error(`无效 pair 键：${key}`);
    const [a,b]=key.split('->').map(Number);
    if(a===b||a>=cache.images.length||b>=cache.images.length)throw new Error(`pair 超出图片范围或为自身：${key}`);
    for(const name of ['heading_deg','yaw_deg','rotation_angle_deg','range_m','seconds'])if(!Number.isFinite(value?.[name]))throw new Error(`${key}.${name} 必须是有限数值`);
    if(value.rotation_angle_deg<0||value.rotation_angle_deg>180||value.seconds<0)throw new Error(`无效角度或耗时：${key}`);
    if(!value.decoded||!Number.isFinite(value.decoded.heading_deg)||!Number.isFinite(value.decoded.range_m)||!Number.isInteger(value.decoded.label_index)||value.decoded.label_index<0)throw new Error(`无效 decoded：${key}`);
  }
  return cache;
}
