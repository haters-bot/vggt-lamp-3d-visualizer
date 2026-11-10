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
    for(const name of ['range_m','seconds'])if(!Number.isFinite(value?.[name]))throw new Error(`${key}.${name} 必须是有限数值`);
    if(value.seconds<0)throw new Error(`无效推理耗时：${key}`);
    if(!value.decoded||!Number.isFinite(value.decoded.heading_deg)||!Number.isFinite(value.decoded.range_m)||!Number.isInteger(value.decoded.label_index)||value.decoded.label_index<0)throw new Error(`无效 decoded：${key}`);
  }
  return cache;
}

export function universitySpiralStep(frameIndex) {
  if(!Number.isFinite(frameIndex))throw new Error('frameIndex 必须是有限数值');
  return frameIndex<=1?4*frameIndex:4+5*(frameIndex-1);
}

export function universitySpiralPoint(step,winding=1) {
  const range=256-.5*step,angle=winding*step*4*Math.PI/180,horizontal=range*Math.SQRT1_2;
  return[horizontal*Math.sin(angle),range*Math.SQRT1_2,horizontal*Math.cos(angle)];
}

function median(values) {
  if(!values.length)return 0;
  const sorted=values.slice().sort((a,b)=>a-b),middle=Math.floor(sorted.length/2);
  return sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])*.5;
}

function rotateByQuaternion(point,q) {
  const[w,x,y,z]=q,[px,py,pz]=point,tx=2*(y*pz-z*py),ty=2*(z*px-x*pz),tz=2*(x*py-y*px);
  return[px+w*tx+(y*tz-z*ty),py+w*ty+(z*tx-x*tz),pz+w*tz+(x*ty-y*tx)];
}

function weightedSimilarity(source,target,weights) {
  const count=source.length,total=weights.reduce((sum,value)=>sum+value,0);
  if(count!==target.length||count<3||total<=0)throw new Error('相似变换至少需要三个有效对应点');
  const sourceCenter=[0,0,0],targetCenter=[0,0,0];
  for(let i=0;i<count;i++)for(let axis=0;axis<3;axis++){sourceCenter[axis]+=weights[i]*source[i][axis]/total;targetCenter[axis]+=weights[i]*target[i][axis]/total;}
  const h=Array.from({length:3},()=>[0,0,0]);let sourceEnergy=0;
  for(let i=0;i<count;i++){
    const a=source[i].map((value,axis)=>value-sourceCenter[axis]),b=target[i].map((value,axis)=>value-targetCenter[axis]),weight=weights[i];
    sourceEnergy+=weight*(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);
    for(let row=0;row<3;row++)for(let column=0;column<3;column++)h[row][column]+=weight*a[row]*b[column];
  }
  if(sourceEnergy<=1e-12)throw new Error('标准螺旋退化，无法估计尺度');
  const[[sxx,sxy,sxz],[syx,syy,syz],[szx,szy,szz]]=h,trace=sxx+syy+szz;
  const n=[
    [trace,syz-szy,szx-sxz,sxy-syx],
    [syz-szy,sxx-syy-szz,sxy+syx,szx+sxz],
    [szx-sxz,sxy+syx,-sxx+syy-szz,syz+szy],
    [sxy-syx,szx+sxz,syz+szy,-sxx-syy+szz],
  ];
  const shift=Math.max(...n.map(row=>row.reduce((sum,value)=>sum+Math.abs(value),0)))+1e-12;
  let quaternion=[1,0,0,0];
  for(let iteration=0;iteration<80;iteration++){
    const next=n.map((row,index)=>row.reduce((sum,value,column)=>sum+value*quaternion[column],shift*quaternion[index])),length=Math.hypot(...next)||1;
    quaternion=next.map(value=>value/length);
  }
  let numerator=0;
  for(let i=0;i<count;i++){
    const a=source[i].map((value,axis)=>value-sourceCenter[axis]),b=target[i].map((value,axis)=>value-targetCenter[axis]),rotated=rotateByQuaternion(a,quaternion);
    numerator+=weights[i]*(rotated[0]*b[0]+rotated[1]*b[1]+rotated[2]*b[2]);
  }
  const scale=numerator/sourceEnergy,rotatedCenter=rotateByQuaternion(sourceCenter,quaternion),translation=targetCenter.map((value,axis)=>value-scale*rotatedCenter[axis]);
  const transform=point=>{const rotated=rotateByQuaternion(point,quaternion);return rotated.map((value,axis)=>scale*value+translation[axis]);};
  return{scale,quaternion,translation,transform};
}

export function fitUniversitySpiral(cameraPoints) {
  if(!Array.isArray(cameraPoints)||cameraPoints.length<3||cameraPoints.some(point=>!Array.isArray(point)||point.length!==3||point.some(value=>!Number.isFinite(value))))throw new Error('VGGT 相机点格式无效');
  const target=cameraPoints.map(point=>point.slice()),candidates=[];
  for(const winding of[1,-1]){
    const source=target.map((_,index)=>universitySpiralPoint(universitySpiralStep(index),winding));let weights=source.map(()=>1),fit;
    for(let iteration=0;iteration<7;iteration++){
      fit=weightedSimilarity(source,target,weights);
      const residuals=source.map((point,index)=>Math.hypot(...fit.transform(point).map((value,axis)=>value-target[index][axis]))),center=median(residuals),mad=median(residuals.map(value=>Math.abs(value-center))),threshold=Math.max(center+3*1.4826*mad,center*1.8,1e-9);
      weights=residuals.map(value=>value<=threshold?1:Math.max(.02,threshold/value));
    }
    const points=source.map(fit.transform),residuals=points.map((point,index)=>Math.hypot(...point.map((value,axis)=>value-target[index][axis]))),center=median(residuals),mad=median(residuals.map(value=>Math.abs(value-center))),threshold=Math.max(center+3*1.4826*mad,center*1.8,1e-9),outliers=residuals.map((value,index)=>value>threshold?index:-1).filter(index=>index>=0),rms=Math.sqrt(residuals.reduce((sum,value)=>sum+value*value,0)/residuals.length);
    candidates.push({...fit,winding,points,residuals,medianResidual:center,rms,outliers});
  }
  candidates.sort((a,b)=>a.medianResidual-b.medianResidual);
  return candidates[0];
}
