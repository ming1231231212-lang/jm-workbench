const token = document.querySelector('meta[name="jm-connector-token"]').content;
const message = document.querySelector('#message');
let stream;
async function request(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'X-JM-Connector-Token': token, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok || data.code !== 200) throw new Error(data.msg || data.error || '操作失败，请刷新后重试');
  return data.data;
}
async function refresh() {
  const accounts = await request('/getAccounts');
  const target = document.querySelector('#accounts');
  target.replaceChildren();
  if (!accounts.length) { target.textContent = '还没有账号。选择平台并打开登录后，账号会保存在这台电脑。'; return; }
  for (const account of accounts) {
    const row = document.createElement('div'); row.className = 'account row';
    const name = document.createElement('span'); name.textContent = `${account[3]} · ${{1:'小红书',2:'视频号',3:'抖音',4:'快手'}[account[1]]} · ${account[4] === 1 ? '已记录，发布前将检查' : '需要登录'}`;
    const remove = document.createElement('button'); remove.textContent = '删除'; remove.type = 'button';
    const rename = document.createElement('button'); rename.textContent = '修改备注'; rename.type = 'button';
    rename.onclick = async () => { const value = prompt('账号备注（最多60字）', account[3]); if (value === null) return; if (!value.trim() || value.trim().length > 60) { message.textContent = '请填写1–60字的账号备注'; return; } try { await request('/updateUserinfo', {id:account[0],type:account[1],userName:value.trim()}); await refresh(); } catch (e) { message.textContent = e.message; } };
    remove.onclick = async () => { if (!confirm(`删除账号“${account[3]}”？将移除此电脑上的登录资料。`)) return; try { await request('/deleteAccount?id=' + account[0]); await refresh(); } catch (e) { message.textContent = e.message; } };
    const actions = document.createElement('div'); actions.className = 'row'; actions.append(rename, remove);
    row.append(name, actions); target.append(row);
  }
}
document.querySelector('#refresh').onclick = () => refresh().catch(e => message.textContent = e.message);
document.querySelector('#login').onsubmit = event => {
  event.preventDefault();
  if (stream) stream.close();
  const form = new FormData(event.target);
  const query = new URLSearchParams({type: form.get('platform'), id: form.get('name'), token});
  stream = new EventSource('/login?' + query);
  message.textContent = '正在打开专用浏览器，请在平台完成登录；不要把验证码发给其他人。';
  stream.onmessage = async event => {
    if (event.data === '200') { stream.close(); message.textContent = '登录完成。返回工作台刷新账号列表。'; document.querySelector('#qr').hidden = true; await refresh(); }
    else if (event.data === '500') { stream.close(); message.textContent = '此次登录未完成，请检查浏览器页面后重试。'; }
    else if (event.data.startsWith('data:image/') || event.data.startsWith('https://')) { const qr = document.querySelector('#qr'); qr.src = event.data; qr.hidden = false; }
  };
  stream.onerror = () => { stream.close(); message.textContent = '登录连接已结束。可刷新列表查看结果，未完成时重新打开登录。'; };
};
window.addEventListener('beforeunload', () => stream?.close());
refresh().catch(e => message.textContent = e.message);
