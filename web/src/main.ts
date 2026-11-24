import './style.css';

type Room = {id:string;name:string;color:string;state:string;backend:string|null;viewers:number;current_prompt:string;frame_seq:number;source_frames:number;source_fps:number;first_frame_ms:number|null;error:string|null;prompt_seq:number};
type Prompt = {id:string;seq:number;nickname:string;text:string;status:string;accepted_at:string;sent_at:string|null};
type FrameMeta = {room_id:string;frame_seq:number;source_frames:number;source_fps:number;width:number;height:number};
const el = <T extends HTMLElement=HTMLElement>(id:string) => document.getElementById(id) as T;
const stateLabels:Record<string,string> = {LIVE:'直播中',STARTING:'准备画面中',STOPPED:'未开播',CLOSING:'正在结束',FAILED:'连接异常'};
const statusLabels:Record<string,string> = {accepted:'已提交',superseded:'已被更新的想法替代',sent:'已投递',expired:'已过期',failed:'投递失败'};
const clientId = localStorage.getItem('longlive.client') || crypto.randomUUID();
localStorage.setItem('longlive.client',clientId);
let nickname = localStorage.getItem('longlive.nickname') || `观众 ${clientId.slice(0,4)}`;
let rooms:Room[] = [], activeRoom:string|null = null, socket:WebSocket|null = null;
let heartbeat:ReturnType<typeof setInterval>|null = null, reconnect:ReturnType<typeof setTimeout>|null = null;
let streamGeneration = 0, connectedAt = 0, firstFrameMs:number|null = null, renderedFrames = 0;
let latestFrame:ArrayBuffer|null = null, decoding = false, danmakuEnabled = true, danmakuLane = 0;
let availableSlots = 0, submitting = false, toastTimer:ReturnType<typeof setTimeout>;
let pendingRequest:{roomId:string;payload:{client_id:string;message_id:string;nickname:string;text:string}}|null = null;
const messages = new Map<string,HTMLElement>();
const canvas = el<HTMLCanvasElement>('video-canvas'), context = canvas.getContext('2d')!;
const input = el<HTMLTextAreaElement>('prompt-input');
el('nickname-label').textContent = nickname;

function toast(message:string){el('toast').textContent=message;el('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el('toast').hidden=true,4500);}
async function api<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await fetch(path,{...init,headers:{'Content-Type':'application/json',...init?.headers}});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error?.message||`请求失败 (${response.status})`);
  return data as T;
}
function renderRooms(){
  const list=el('room-list'); list.replaceChildren();
  for(const room of rooms){
    const button=document.createElement('button');button.className=`room-item${room.id===activeRoom?' active':''}`;button.dataset.roomId=room.id;button.setAttribute('aria-current',room.id===activeRoom?'true':'false');
    const thumb=document.createElement('span');thumb.className='room-thumb';thumb.style.setProperty('--room-color',room.color);thumb.textContent='✧';
    const detail=document.createElement('span'),name=document.createElement('strong'),meta=document.createElement('span'),dot=document.createElement('i');
    name.textContent=room.name;meta.className='room-meta';dot.className=`live-dot${room.state==='LIVE'?' on':''}`;meta.append(dot,document.createTextNode(stateLabels[room.state]||room.state));detail.append(name,meta);button.append(thumb,detail);button.onclick=()=>selectRoom(room.id);list.append(button);
  }
  el('room-total').textContent=String(rooms.length);
}
function updateRoom(room:Room){
  const at=rooms.findIndex(r=>r.id===room.id);if(at>=0)rooms[at]=room;else rooms.push(room);
  renderRooms();if(room.id!==activeRoom)return;
  el('room-title').textContent=room.name;
  el('current-prompt').textContent=room.current_prompt||'等待第一条提示词';
  el('viewer-count').textContent=`${room.viewers} 人正在观看`;
  el('message-count').textContent=`${room.prompt_seq} 条弹幕`;
  el('live-badge').textContent=stateLabels[room.state]||room.state;
  el('live-badge').classList.toggle('is-live',room.state==='LIVE');
  el('model-badge').textContent=room.backend==='mock'?'MOCK 测试画面':room.backend==='scope'?'AI LIVE':'';
  const toggle=el<HTMLButtonElement>('room-toggle');toggle.disabled=room.state==='CLOSING'||room.state==='STARTING';toggle.textContent=room.state==='LIVE'?'停止直播':'开始直播';
  el<HTMLButtonElement>('send-prompt').disabled=room.state!=='LIVE'||submitting;
  if(room.state!=='LIVE' && room.state!=='STARTING'){
    el('stage-placeholder').hidden=false;el('placeholder-title').textContent=room.state==='FAILED'?'画面暂时中断':'这个世界正在休息';
    el('placeholder-detail').textContent=room.error?'生成服务暂不可用，可稍后重试。':'点击“开始直播”，让想象继续。';
    el('stream-status').textContent=stateLabels[room.state]||room.state;
  }else if(renderedFrames===0){
    el('stage-placeholder').hidden=false;el('placeholder-title').textContent='正在唤醒画面';el('placeholder-detail').textContent='首次加载可能需要一点时间，直播准备好后会自动出现。';
  }
}
async function refresh(){
  try{
    const [listing,cap]=await Promise.all([api<{items:Room[]}>('/api/v1/rooms?limit=100'),api<{available_slots:number;effective_limit:number;active_sessions:number;reserved_sessions:number}>('/api/v1/capacity')]);
    rooms=listing.items;availableSlots=cap.available_slots;renderRooms();
    el('capacity-text').textContent=`${cap.active_sessions+cap.reserved_sessions} / ${cap.effective_limit} 路生成中`;
    el('capacity-fill').style.width=`${cap.effective_limit?Math.min(100,100*(cap.active_sessions+cap.reserved_sessions)/cap.effective_limit):0}%`;
    el<HTMLButtonElement>('new-room').disabled=availableSlots===0;
    if(activeRoom){const room=rooms.find(r=>r.id===activeRoom);if(room)updateRoom(room);}
    else if(rooms.length){const saved=localStorage.getItem('longlive.room');selectRoom(rooms.some(r=>r.id===saved)?saved!:rooms[0].id);}
  }catch{el('capacity-text').textContent='服务连接暂时中断';}
}
function clearConnection(){
  if(heartbeat)clearInterval(heartbeat);if(reconnect)clearTimeout(reconnect);
  if(socket){socket.onclose=null;socket.close();socket=null;}
  heartbeat=null;reconnect=null;latestFrame=null;
}
function selectRoom(id:string){
  if(id===activeRoom)return;
  clearConnection();streamGeneration++;activeRoom=id;localStorage.setItem('longlive.room',id);
  firstFrameMs=null;renderedFrames=0;messages.clear();el('messages').replaceChildren();el('danmaku-layer').replaceChildren();
  context.clearRect(0,0,canvas.width,canvas.height);el('stage-placeholder').hidden=false;el('stream-fps').textContent='— fps';el('stream-latency').textContent='共享实时画面';
  const room=rooms.find(r=>r.id===id);if(room)updateRoom(room);connectStream(id,streamGeneration);
}
function connectStream(id:string,generation:number){
  if(generation!==streamGeneration)return;
  connectedAt=performance.now();
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/v1/rooms/${encodeURIComponent(id)}/stream`);
  socket=ws;ws.binaryType='arraybuffer';
  const ping=()=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'ping',client_time:performance.now(),rendered_frames:renderedFrames,first_frame_ms:firstFrameMs}));};
  ws.onopen=()=>{el('stream-status').textContent='已连接，等待画面';ping();heartbeat=setInterval(ping,5000);};
  ws.onmessage=(event)=>{
    if(generation!==streamGeneration)return;
    if(event.data instanceof ArrayBuffer){latestFrame=event.data;void drawLatest(generation);return;}
    const data=JSON.parse(event.data);
    if(data.type==='snapshot'){
      messages.clear();el('messages').replaceChildren();updateRoom(data.room);for(const item of data.history)appendMessage(item,false);if(!data.history.length)showEmpty();
    }else if(data.type==='prompt'){appendMessage(data.prompt,true);el('message-count').textContent=`${data.prompt.seq} 条弹幕`;}
    else if(data.type==='prompt_status'){appendMessage(data.prompt,false);if(data.prompt.status==='sent')el('current-prompt').textContent=data.prompt.text;}
    else if(data.type==='room_state'){updateRoom(data.room);if(data.room.state==='STARTING'){renderedFrames=0;firstFrameMs=null;connectedAt=performance.now();}}
    else if(data.type==='viewers'){el('viewer-count').textContent=`${data.count} 人正在观看`;}
    else if(data.type==='pong'){if(data.room)updateRoom(data.room);}
    else if(data.type==='error'){toast(data.message);}
  };
  ws.onclose=()=>{
    if(generation!==streamGeneration)return;
    if(heartbeat)clearInterval(heartbeat);el('stream-status').textContent='连接断开，正在重连';
    reconnect=setTimeout(()=>connectStream(id,generation),1800);
  };
  ws.onerror=()=>{el('stream-status').textContent='正在恢复连接';};
}
async function drawLatest(generation:number){
  if(decoding)return;
  decoding=true;
  try{
    while(latestFrame && generation===streamGeneration){
      const packet=latestFrame;latestFrame=null;
      const size=new DataView(packet).getUint32(0);
      const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(packet,4,size))) as FrameMeta;
      if(meta.room_id!==activeRoom)continue;
      const bitmap=await createImageBitmap(new Blob([packet.slice(4+size)],{type:'image/jpeg'}));
      if(generation!==streamGeneration){bitmap.close();break;}
      if(canvas.width!==bitmap.width||canvas.height!==bitmap.height){canvas.width=bitmap.width;canvas.height=bitmap.height;}
      context.drawImage(bitmap,0,0);bitmap.close();renderedFrames++;
      canvas.dataset.frameSeq=String(meta.frame_seq);canvas.dataset.roomId=meta.room_id;canvas.dataset.renderedFrames=String(renderedFrames);
      if(firstFrameMs===null){firstFrameMs=Math.round(performance.now()-connectedAt);el('stream-latency').textContent=`首帧 ${(firstFrameMs/1000).toFixed(1)}s`;}
      el('stage-placeholder').hidden=true;el('stream-status').textContent='正在接收画面';el('stream-fps').textContent=`${meta.source_fps.toFixed(1)} fps · 源收帧`;
    }
  }catch{el('stream-status').textContent='正在等待下一帧';}
  finally{decoding=false;if(latestFrame)void drawLatest(streamGeneration);}
}
function showEmpty(){const empty=document.createElement('div');empty.className='chat-empty';empty.innerHTML='<span>✧</span><p>灵感从你开始</p><small>发送第一条提示词</small>';el('messages').append(empty);}
function appendMessage(prompt:Prompt,animate:boolean){
  let item=messages.get(prompt.id);
  if(!item){
    el('messages').querySelector('.chat-empty')?.remove();
    item=document.createElement('article');item.className='chat-message';item.dataset.messageId=prompt.id;
    const top=document.createElement('div');top.className='message-top';
    const avatar=document.createElement('span');avatar.className='message-avatar';avatar.textContent=prompt.nickname.slice(0,1);
    const name=document.createElement('span');name.className='message-name';name.textContent=prompt.nickname;
    const time=document.createElement('span');time.className='message-time';time.textContent=new Date(prompt.accepted_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
    top.append(avatar,name,time);
    const text=document.createElement('p');text.textContent=prompt.text;
    const status=document.createElement('span');status.className='message-status';item.append(top,text,status);messages.set(prompt.id,item);el('messages').append(item);
    if(messages.size>150){const key=messages.keys().next().value!;messages.get(key)?.remove();messages.delete(key);}
    el('messages').scrollTop=el('messages').scrollHeight;
    if(animate&&danmakuEnabled){
      const line=document.createElement('span');line.className=`danmaku${prompt.nickname===nickname?' own':''}`;line.textContent=prompt.text.slice(0,90);
      line.style.top=`${(danmakuLane++%5)*22}px`;line.style.setProperty('--stage-width',`${el('stage').clientWidth}px`);
      const layer=el('danmaku-layer');while(layer.children.length>=30)layer.firstChild?.remove();layer.append(line);line.onanimationend=()=>line.remove();
    }
  }
  const status=item.querySelector('.message-status')!;status.textContent=statusLabels[prompt.status]||prompt.status;status.className=`message-status ${prompt.status}`;
}
input.oninput=()=>{el('char-count').textContent=`${input.value.length} / 1500`;};
input.onkeydown=(event)=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();el<HTMLFormElement>('prompt-form').requestSubmit();}};
el<HTMLFormElement>('prompt-form').onsubmit=async(event)=>{
  event.preventDefault();const text=input.value.trim(),roomId=activeRoom;if(!text||!roomId||submitting)return;
  if(!pendingRequest||pendingRequest.roomId!==roomId||pendingRequest.payload.text!==text)pendingRequest={roomId,payload:{client_id:clientId,message_id:crypto.randomUUID(),nickname,text}};
  const request=pendingRequest;submitting=true;el<HTMLButtonElement>('send-prompt').disabled=true;
  try{
    const prompt=await api<Prompt>(`/api/v1/rooms/${encodeURIComponent(roomId)}/prompts`,{method:'POST',body:JSON.stringify(request.payload)});
    if(activeRoom===roomId){appendMessage(prompt,false);if(input.value.trim()===text){input.value='';el('char-count').textContent='0 / 1500';}}
    pendingRequest=null;
  }catch(error){toast((error as Error).message+'，可再次发送重试');}
  finally{submitting=false;el<HTMLButtonElement>('send-prompt').disabled=rooms.find(r=>r.id===activeRoom)?.state!=='LIVE';}
};
el('toggle-danmaku').onclick=()=>{danmakuEnabled=!danmakuEnabled;el('toggle-danmaku').textContent=`弹幕 ${danmakuEnabled?'开':'关'}`;el('toggle-danmaku').setAttribute('aria-pressed',String(danmakuEnabled));if(!danmakuEnabled)el('danmaku-layer').replaceChildren();};
el('fullscreen').onclick=()=>{if(document.fullscreenElement)void document.exitFullscreen();else void el('stage').requestFullscreen();};
el('edit-name').onclick=()=>{const value=window.prompt('你的昵称（最多 24 个字）',nickname)?.trim();if(value){nickname=value.slice(0,24);localStorage.setItem('longlive.nickname',nickname);el('nickname-label').textContent=nickname;}};
document.querySelectorAll<HTMLButtonElement>('[data-prompt]').forEach(button=>button.onclick=()=>{input.value=button.dataset.prompt!;input.dispatchEvent(new Event('input'));input.focus();});
el('room-toggle').onclick=async()=>{if(!activeRoom)return;const room=rooms.find(r=>r.id===activeRoom);try{await api(`/api/v1/rooms/${activeRoom}/${room?.state==='LIVE'?'stop':'start'}`,{method:'POST'});await refresh();}catch(error){toast((error as Error).message);}};
const dialog=el<HTMLDialogElement>('create-dialog');
el('new-room').onclick=()=>{if(availableSlots)dialog.showModal();else toast('当前生成资源已满，你仍然可以加入已有直播间。');};
el('close-dialog').onclick=()=>dialog.close();
el<HTMLFormElement>('create-form').onsubmit=async(event)=>{
  event.preventDefault();const form=event.currentTarget as HTMLFormElement;const button=form.querySelector<HTMLButtonElement>('[type=submit]')!;button.disabled=true;
  try{const values=Object.fromEntries(new FormData(form));const room=await api<Room>('/api/v1/rooms',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(values)});rooms.push(room);dialog.close();form.reset();selectRoom(room.id);await refresh();}
  catch(error){toast((error as Error).message);}finally{button.disabled=false;}
};
window.addEventListener('pagehide',clearConnection);
void refresh();setInterval(()=>void refresh(),5000);
