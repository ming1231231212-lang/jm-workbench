export async function fetchWithDeadline(path, options = {}, fetcher = fetch, milliseconds) {
  const writing = Boolean(options.method && options.method !== 'GET');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), milliseconds ?? (writing ? 350000 : 20000));
  try {
    return await fetcher(path, {...options, signal:controller.signal});
  } catch (error) {
    if(controller.signal.aborted) throw Error(writing
      ? '操作尚未确认，请先查看内容与运行记录，不要重复提交。'
      : '读取状态超时，请检查本机服务后刷新。');
    throw error;
  } finally {clearTimeout(timer);}
}
